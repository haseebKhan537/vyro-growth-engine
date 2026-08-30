from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Never
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings, get_settings
from vyro_growth.domain import (
    EnrollmentSkipReason,
    EnrollmentStatus,
    LeadStage,
    OutreachPlanRunStatus,
    PersonalizationReadiness,
)
from vyro_growth.models import (
    Activity,
    Campaign,
    CampaignEnrollment,
    Contact,
    Lead,
    LeadScore,
    Organization,
    OutreachPlanRun,
    PersonalizationDraft,
)
from vyro_growth.providers.decision_makers import clean_optional_text
from vyro_growth.providers.smartlead import (
    LiveSmartleadDisabledError,
    LiveSmartleadNotImplementedError,
    MalformedSmartleadOutput,
    RetryableSmartleadError,
    SmartleadLeadPayload,
    SmartleadPlanResult,
    SmartleadProvider,
    SmartleadProviderError,
    build_smartlead_provider,
    enrollment_idempotency_key,
    parse_smartlead_plan_result,
    split_stored_name,
    stored_custom_fields,
)
from vyro_growth.services.lead_scoring import ScoreBand
from vyro_growth.services.outbound_guard import (
    OutboundAction,
    OutboundBlockedError,
    OutboundGuard,
    domain_from_email,
    suppression_status,
)

logger = structlog.get_logger(__name__)

OUTREACH_PLAN_ACTOR = "outreach_enrollment"
DEFAULT_CAMPAIGN_NAME = "phase-6-dry-run"
BATCH_MAX = 200
ELIGIBLE_STAGES = frozenset({LeadStage.QUALIFIED, LeadStage.READY_FOR_OUTREACH})
ELIGIBLE_BANDS = frozenset({ScoreBand.HOT, ScoreBand.HIGH, ScoreBand.MEDIUM})


class OutreachEnrollmentError(ValueError):
    """Raised when a dry-run outreach plan cannot load the requested records."""


@dataclass(frozen=True)
class EnrollmentItemResult:
    enrollment_id: UUID
    lead_id: UUID
    organization_id: UUID
    status: EnrollmentStatus
    skip_reason: EnrollmentSkipReason | None
    reused: bool
    dry_run: bool
    live_send_attempted: bool
    provider_name: str


@dataclass(frozen=True)
class OutreachPlanResult:
    outreach_plan_run_id: UUID
    campaign_id: UUID
    planned_count: int
    skipped_count: int
    suppressed_count: int
    blocked_count: int
    reused_count: int
    status: OutreachPlanRunStatus
    items: tuple[EnrollmentItemResult, ...]


class OutreachEnrollmentService:
    """Plan dry-run Smartlead enrollments. Does not send email or enroll live campaigns."""

    def __init__(
        self,
        provider: SmartleadProvider | None = None,
        *,
        settings: Settings | None = None,
        guard: OutboundGuard | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._provider = provider or build_smartlead_provider(self._settings)
        self._guard = guard or OutboundGuard(self._settings)

    def plan_lead(
        self,
        db: Session,
        lead_id: UUID,
        *,
        campaign_id: UUID | None = None,
        campaign_name: str | None = None,
        commit: bool = True,
    ) -> OutreachPlanResult:
        lead = db.get(Lead, lead_id)
        if lead is None:
            raise OutreachEnrollmentError(f"Lead not found: {lead_id}")
        return self._plan(
            db,
            leads=(lead,),
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            input_params={"lead_id": str(lead_id)},
            commit=commit,
        )

    def plan_batch(
        self,
        db: Session,
        *,
        limit: int = 50,
        state: str | None = None,
        city: str | None = None,
        campaign_id: UUID | None = None,
        campaign_name: str | None = None,
        commit: bool = True,
    ) -> OutreachPlanResult:
        query = (
            select(Lead)
            .join(Organization, Organization.id == Lead.organization_id)
            .order_by(Lead.created_at.asc())
        )
        if state:
            query = query.where(Organization.state == state.strip().upper())
        if city:
            query = query.where(Organization.city == city.strip().upper())
        leads = db.scalars(query.limit(min(max(limit, 1), BATCH_MAX))).all()
        return self._plan(
            db,
            leads=tuple(leads),
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            input_params={
                "limit": min(max(limit, 1), BATCH_MAX),
                "state": state,
                "city": city,
            },
            commit=commit,
        )

    def _plan(
        self,
        db: Session,
        *,
        leads: tuple[Lead, ...],
        campaign_id: UUID | None,
        campaign_name: str | None,
        input_params: dict[str, object],
        commit: bool,
    ) -> OutreachPlanResult:
        campaign = self._resolve_campaign(
            db, campaign_id=campaign_id, campaign_name=campaign_name
        )
        run = OutreachPlanRun(
            campaign_id=campaign.id,
            status=OutreachPlanRunStatus.RUNNING.value,
            started_at=datetime.now(tz=UTC),
            input_params={
                **input_params,
                "campaign_id": str(campaign.id),
                "campaign_name": campaign.name,
                "dry_run": True,
                "outbound_attempted": False,
                "provider": "stub" if not getattr(self._provider, "live", False) else "live",
            },
        )
        db.add(run)
        db.flush()

        items: list[EnrollmentItemResult] = []
        try:
            for lead in leads:
                items.append(self._plan_one(db, run=run, campaign=campaign, lead=lead))
        except OutreachEnrollmentError:
            raise
        except Exception as exc:
            run.status = OutreachPlanRunStatus.FAILED.value
            run.finished_at = datetime.now(tz=UTC)
            run.error_message = str(exc)
            self._record_activity(
                db,
                lead_id=None,
                action="outreach_plan_failed",
                details={
                    "outreach_plan_run_id": str(run.id),
                    "campaign_id": str(campaign.id),
                    "error": str(exc),
                    "outbound_attempted": False,
                    "live_send_attempted": False,
                },
            )
            if commit:
                db.commit()
            logger.exception("outreach_plan_failed", outreach_plan_run_id=str(run.id))
            raise

        self._finalize_run(db, run, items)
        if commit:
            db.commit()
        logger.info(
            "outreach_plan_completed",
            outreach_plan_run_id=str(run.id),
            planned=run.planned_count,
            skipped=run.skipped_count,
            suppressed=run.suppressed_count,
            blocked=run.blocked_count,
            reused=run.reused_count,
        )
        return OutreachPlanResult(
            outreach_plan_run_id=run.id,
            campaign_id=campaign.id,
            planned_count=run.planned_count,
            skipped_count=run.skipped_count,
            suppressed_count=run.suppressed_count,
            blocked_count=run.blocked_count,
            reused_count=run.reused_count,
            status=OutreachPlanRunStatus.COMPLETED,
            items=tuple(items),
        )

    def _plan_one(
        self,
        db: Session,
        *,
        run: OutreachPlanRun,
        campaign: Campaign,
        lead: Lead,
    ) -> EnrollmentItemResult:
        organization = db.get(Organization, lead.organization_id)
        if organization is None:
            raise OutreachEnrollmentError(f"Organization not found for lead: {lead.id}")

        contact = self._best_contact_with_email(db, organization.id)
        draft = self._ready_draft(db, lead.id) if contact is not None else None
        score = self._latest_score(db, lead.id)
        key = enrollment_idempotency_key(
            campaign_id=campaign.id,
            lead_id=lead.id,
            contact_id=contact.id if contact is not None else None,
        )
        existing = db.scalar(
            select(CampaignEnrollment).where(CampaignEnrollment.idempotency_key == key)
        )
        if existing is not None and existing.status == EnrollmentStatus.PLANNED.value:
            existing.outreach_plan_run_id = run.id
            details = dict(existing.details_json)
            details["idempotent_reuse"] = True
            existing.details_json = details
            db.flush()
            self._record_activity(
                db,
                lead_id=lead.id,
                action="outreach_enrollment_idempotent",
                details={
                    "enrollment_id": str(existing.id),
                    "outreach_plan_run_id": str(run.id),
                    "campaign_id": str(campaign.id),
                    "status": existing.status,
                    "dry_run": existing.dry_run,
                    "live_send_attempted": existing.live_send_attempted,
                    "outbound_attempted": False,
                },
            )
            return EnrollmentItemResult(
                enrollment_id=existing.id,
                lead_id=lead.id,
                organization_id=organization.id,
                status=EnrollmentStatus.PLANNED,
                skip_reason=None,
                reused=True,
                dry_run=existing.dry_run,
                live_send_attempted=existing.live_send_attempted,
                provider_name=existing.provider_name,
            )

        status, reason, details, provider_result = self._decide(
            db,
            lead=lead,
            organization=organization,
            contact=contact,
            draft=draft,
            score=score,
            campaign=campaign,
            idempotency_key=key,
        )
        enrollment = existing or CampaignEnrollment(
            campaign_id=campaign.id,
            lead_id=lead.id,
            organization_id=organization.id,
            idempotency_key=key,
        )
        enrollment.outreach_plan_run_id = run.id
        enrollment.contact_id = contact.id if contact is not None else None
        enrollment.personalization_draft_id = draft.id if draft is not None else None
        enrollment.status = status.value
        enrollment.skip_reason = reason.value if reason is not None else None
        enrollment.provider_name = (
            provider_result.provider_name if provider_result is not None else "none"
        )
        enrollment.provider_enrollment_id = (
            provider_result.provider_enrollment_id if provider_result is not None else None
        )
        enrollment.dry_run = True
        enrollment.live_send_attempted = False
        enrollment.details_json = details
        if existing is None:
            db.add(enrollment)
        db.flush()
        self._record_activity(
            db,
            lead_id=lead.id,
            action=_activity_action(status),
            details={
                "enrollment_id": str(enrollment.id),
                "outreach_plan_run_id": str(run.id),
                "campaign_id": str(campaign.id),
                "status": status.value,
                "skip_reason": reason.value if reason is not None else None,
                "dry_run": True,
                "live_send_attempted": False,
                "outbound_attempted": False,
                "provider": enrollment.provider_name,
            },
        )
        return EnrollmentItemResult(
            enrollment_id=enrollment.id,
            lead_id=lead.id,
            organization_id=organization.id,
            status=status,
            skip_reason=reason,
            reused=existing is not None,
            dry_run=True,
            live_send_attempted=False,
            provider_name=enrollment.provider_name,
        )

    def _decide(
        self,
        db: Session,
        *,
        lead: Lead,
        organization: Organization,
        contact: Contact | None,
        draft: PersonalizationDraft | None,
        score: LeadScore | None,
        campaign: Campaign,
        idempotency_key: str,
    ) -> tuple[
        EnrollmentStatus,
        EnrollmentSkipReason | None,
        dict[str, object],
        SmartleadPlanResult | None,
    ]:
        details: dict[str, object] = {
            "dry_run": True,
            "live_send_attempted": False,
            "outbound_attempted": False,
            "fabricated_facts": False,
        }
        stage = _lead_stage(lead.stage)
        if stage not in ELIGIBLE_STAGES:
            return (
                EnrollmentStatus.SKIPPED,
                EnrollmentSkipReason.INELIGIBLE_STAGE,
                {**details, "stage": lead.stage},
                None,
            )
        if score is None:
            return EnrollmentStatus.SKIPPED, EnrollmentSkipReason.MISSING_LEAD_SCORE, details, None
        band = _score_band(score)
        details["score"] = score.score
        details["score_band"] = band.value if band is not None else None
        if band is None or band not in ELIGIBLE_BANDS:
            return EnrollmentStatus.SKIPPED, EnrollmentSkipReason.INELIGIBLE_SCORE, details, None
        if contact is None or clean_optional_text(contact.email) is None:
            return (
                EnrollmentStatus.SKIPPED,
                EnrollmentSkipReason.MISSING_CONTACT_EMAIL,
                details,
                None,
            )
        if draft is None:
            not_ready = self._any_draft(db, lead.id)
            reason = (
                EnrollmentSkipReason.PERSONALIZATION_NOT_READY
                if not_ready is not None
                else EnrollmentSkipReason.MISSING_PERSONALIZATION
            )
            return EnrollmentStatus.SKIPPED, reason, details, None

        email = contact.email
        assert email is not None
        suppression = suppression_status(
            db,
            email=email,
            domain=domain_from_email(email),
            organization_id=organization.id,
        )
        details["suppression_decision"] = suppression.reason
        if not suppression.allowed:
            if suppression.reason == "suppression_check_unavailable":
                return (
                    EnrollmentStatus.BLOCKED,
                    EnrollmentSkipReason.SUPPRESSION_CHECK_UNAVAILABLE,
                    details,
                    None,
                )
            return EnrollmentStatus.SUPPRESSED, EnrollmentSkipReason.SUPPRESSED, details, None

        outbound = self._guard.evaluate(
            db,
            action=OutboundAction.CAMPAIGN_ENROLL,
            email=email,
            domain=domain_from_email(email),
            organization_id=organization.id,
        )
        details["outbound_decision"] = outbound.reason
        details["live_send_allowed"] = outbound.allowed

        first_name, last_name = split_stored_name(contact.full_name)
        payload = SmartleadLeadPayload(
            campaign_key=campaign.provider_campaign_key or campaign.name,
            email=email,
            company_name=organization.name,
            idempotency_key=idempotency_key,
            organization_id=organization.id,
            first_name=first_name,
            last_name=last_name,
            custom_fields=stored_custom_fields(
                organization_name=organization.name,
                city=organization.city,
                state=organization.state,
                specialty=organization.specialty,
                website=organization.website,
                npi=organization.npi,
                opening_line=draft.opening_line,
                outreach_angle=draft.outreach_angle,
                suggested_offer=draft.suggested_offer,
                personalization_draft_id=str(draft.id),
            ),
        )
        details["personalization_draft_id"] = str(draft.id)
        details["contact_id"] = str(contact.id)

        if getattr(self._provider, "live", False):
            return self._call_live_boundary(db, payload, details, email, organization.id)
        return self._call_stub(payload, details)

    def _call_stub(
        self,
        payload: SmartleadLeadPayload,
        details: dict[str, object],
    ) -> tuple[
        EnrollmentStatus,
        EnrollmentSkipReason | None,
        dict[str, object],
        SmartleadPlanResult | None,
    ]:
        try:
            parsed = parse_smartlead_plan_result(self._provider.plan_enrollment(payload))
        except MalformedSmartleadOutput:
            return (
                EnrollmentStatus.SKIPPED,
                EnrollmentSkipReason.MALFORMED_PROVIDER_OUTPUT,
                details,
                None,
            )
        except RetryableSmartleadError:
            return (
                EnrollmentStatus.SKIPPED,
                EnrollmentSkipReason.PROVIDER_RETRYABLE_ERROR,
                details,
                None,
            )
        except SmartleadProviderError:
            return (
                EnrollmentStatus.SKIPPED,
                EnrollmentSkipReason.PROVIDER_NON_RETRYABLE_ERROR,
                details,
                None,
            )
        return self._accept_or_reject(parsed, details)

    def _call_live_boundary(
        self,
        db: Session,
        payload: SmartleadLeadPayload,
        details: dict[str, object],
        email: str,
        organization_id: UUID,
    ) -> tuple[
        EnrollmentStatus,
        EnrollmentSkipReason | None,
        dict[str, object],
        SmartleadPlanResult | None,
    ]:
        try:
            self._guard.require_allowed(
                db,
                action=OutboundAction.CAMPAIGN_ENROLL,
                email=email,
                domain=domain_from_email(email),
                organization_id=organization_id,
            )
            parsed = parse_smartlead_plan_result(self._provider.plan_enrollment(payload))
        except OutboundBlockedError as exc:
            return EnrollmentStatus.BLOCKED, _reason_from_outbound(str(exc)), details, None
        except LiveSmartleadDisabledError:
            return (
                EnrollmentStatus.BLOCKED,
                EnrollmentSkipReason.SMARTLEAD_LIVE_DISABLED,
                details,
                None,
            )
        except LiveSmartleadNotImplementedError:
            return (
                EnrollmentStatus.BLOCKED,
                EnrollmentSkipReason.LIVE_SMARTLEAD_NOT_IMPLEMENTED,
                details,
                None,
            )
        except MalformedSmartleadOutput:
            return (
                EnrollmentStatus.SKIPPED,
                EnrollmentSkipReason.MALFORMED_PROVIDER_OUTPUT,
                details,
                None,
            )
        except RetryableSmartleadError:
            return (
                EnrollmentStatus.SKIPPED,
                EnrollmentSkipReason.PROVIDER_RETRYABLE_ERROR,
                details,
                None,
            )
        except SmartleadProviderError:
            return (
                EnrollmentStatus.SKIPPED,
                EnrollmentSkipReason.PROVIDER_NON_RETRYABLE_ERROR,
                details,
                None,
            )
        return self._accept_or_reject(parsed, details)

    def _accept_or_reject(
        self,
        parsed: SmartleadPlanResult,
        details: dict[str, object],
    ) -> tuple[
        EnrollmentStatus,
        EnrollmentSkipReason | None,
        dict[str, object],
        SmartleadPlanResult | None,
    ]:
        details["provider_name"] = parsed.provider_name
        if parsed.live_call_attempted or not parsed.dry_run:
            return (
                EnrollmentStatus.BLOCKED,
                EnrollmentSkipReason.LIVE_SEND_REJECTED,
                details,
                parsed,
            )
        if not parsed.accepted:
            return (
                EnrollmentStatus.SKIPPED,
                EnrollmentSkipReason.PROVIDER_NOT_ACCEPTED,
                details,
                parsed,
            )
        return EnrollmentStatus.PLANNED, None, details, parsed

    def _resolve_campaign(
        self,
        db: Session,
        *,
        campaign_id: UUID | None,
        campaign_name: str | None,
    ) -> Campaign:
        if campaign_id is not None:
            campaign = db.get(Campaign, campaign_id)
            if campaign is None:
                raise OutreachEnrollmentError(f"Campaign not found: {campaign_id}")
            return campaign
        name = clean_optional_text(campaign_name) or DEFAULT_CAMPAIGN_NAME
        existing = db.scalar(select(Campaign).where(Campaign.name == name))
        if existing is not None:
            return existing
        campaign = Campaign(
            name=name,
            active=False,
            channel="email",
            provider="smartlead",
            dry_run_only=True,
            provider_campaign_key=name,
        )
        db.add(campaign)
        db.flush()
        return campaign

    def _best_contact_with_email(self, db: Session, organization_id: UUID) -> Contact | None:
        contacts = list(
            db.scalars(select(Contact).where(Contact.organization_id == organization_id)).all()
        )
        with_email = [row for row in contacts if clean_optional_text(row.email)]
        if not with_email:
            return None
        with_email.sort(
            key=lambda row: (
                row.role_rank is None,
                row.role_rank if row.role_rank is not None else 0,
                row.created_at,
            )
        )
        return with_email[0]

    def _latest_score(self, db: Session, lead_id: UUID) -> LeadScore | None:
        return db.scalar(
            select(LeadScore)
            .where(LeadScore.lead_id == lead_id)
            .order_by(LeadScore.created_at.desc())
        )

    def _ready_draft(self, db: Session, lead_id: UUID) -> PersonalizationDraft | None:
        return db.scalar(
            select(PersonalizationDraft)
            .where(
                PersonalizationDraft.lead_id == lead_id,
                PersonalizationDraft.readiness_status == PersonalizationReadiness.READY.value,
            )
            .order_by(PersonalizationDraft.created_at.desc())
        )

    def _any_draft(self, db: Session, lead_id: UUID) -> PersonalizationDraft | None:
        return db.scalar(
            select(PersonalizationDraft)
            .where(PersonalizationDraft.lead_id == lead_id)
            .order_by(PersonalizationDraft.created_at.desc())
        )

    def _finalize_run(
        self,
        db: Session,
        run: OutreachPlanRun,
        items: list[EnrollmentItemResult],
    ) -> None:
        planned = skipped = suppressed = blocked = reused = 0
        for item in items:
            if item.reused:
                reused += 1
            match item.status:
                case EnrollmentStatus.PLANNED:
                    planned += 1
                case EnrollmentStatus.SKIPPED:
                    skipped += 1
                case EnrollmentStatus.SUPPRESSED:
                    suppressed += 1
                case EnrollmentStatus.BLOCKED:
                    blocked += 1
                case _:
                    unreachable: Never = item.status
                    raise RuntimeError(f"unhandled enrollment status: {unreachable}")
        run.planned_count = planned
        run.skipped_count = skipped
        run.suppressed_count = suppressed
        run.blocked_count = blocked
        run.reused_count = reused
        run.status = OutreachPlanRunStatus.COMPLETED.value
        run.finished_at = datetime.now(tz=UTC)
        self._record_activity(
            db,
            lead_id=None,
            action="outreach_plan_completed",
            details={
                "outreach_plan_run_id": str(run.id),
                "campaign_id": str(run.campaign_id),
                "planned": planned,
                "skipped": skipped,
                "suppressed": suppressed,
                "blocked": blocked,
                "reused": reused,
                "dry_run": True,
                "outbound_attempted": False,
                "live_send_attempted": False,
            },
        )

    def _record_activity(
        self,
        db: Session,
        *,
        lead_id: UUID | None,
        action: str,
        details: dict[str, object],
    ) -> None:
        db.add(Activity(lead_id=lead_id, actor=OUTREACH_PLAN_ACTOR, action=action, details=details))


def _lead_stage(value: str) -> LeadStage | None:
    for stage in LeadStage:
        if stage.value == value:
            return stage
    return None


def _score_band(score: LeadScore) -> ScoreBand | None:
    raw = score.rationale.get("band") if isinstance(score.rationale, dict) else None
    if not isinstance(raw, str):
        return None
    for band in ScoreBand:
        if band.value == raw:
            return band
    return None


def _reason_from_outbound(reason: str) -> EnrollmentSkipReason:
    mapping = {
        "global_outbound_disabled": EnrollmentSkipReason.GLOBAL_OUTBOUND_DISABLED,
        "operator_global_halt": EnrollmentSkipReason.OPERATOR_GLOBAL_HALT,
        "operator_halt_unavailable": EnrollmentSkipReason.OPERATOR_HALT_UNAVAILABLE,
        "suppressed": EnrollmentSkipReason.SUPPRESSED,
        "suppression_check_unavailable": EnrollmentSkipReason.SUPPRESSION_CHECK_UNAVAILABLE,
        "target_unidentified": EnrollmentSkipReason.TARGET_UNIDENTIFIED,
    }
    return mapping.get(reason, EnrollmentSkipReason.GLOBAL_OUTBOUND_DISABLED)


def _activity_action(status: EnrollmentStatus) -> str:
    match status:
        case EnrollmentStatus.PLANNED:
            return "outreach_enrollment_planned"
        case EnrollmentStatus.SKIPPED:
            return "outreach_enrollment_skipped"
        case EnrollmentStatus.SUPPRESSED:
            return "outreach_enrollment_suppressed"
        case EnrollmentStatus.BLOCKED:
            return "outreach_enrollment_blocked"
        case _:
            unreachable: Never = status
            raise RuntimeError(f"unhandled enrollment status: {unreachable}")
