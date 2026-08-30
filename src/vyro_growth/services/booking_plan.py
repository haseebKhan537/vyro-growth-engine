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
    FORBIDDEN_BOOKING_STAGES,
    BookingPlanRunStatus,
    BookingPlanStatus,
    BookingRequestSource,
    BookingSkipReason,
    LeadStage,
    ReplyIntent,
    can_transition,
    desired_booking_stage,
)
from vyro_growth.models import (
    Activity,
    BookingPlan,
    BookingPlanRun,
    Contact,
    Lead,
    Organization,
    OutreachMessage,
    ReplyClassification,
)
from vyro_growth.providers.calendar_booking import (
    BookingCalendarError,
    BookingCalendarProvider,
    BookingPlanPayload,
    BookingPlanProviderResult,
    LiveGoogleCalendarDisabledError,
    LiveGoogleCalendarNotImplementedError,
    MalformedBookingPlanOutput,
    RetryableBookingCalendarError,
    build_booking_calendar_provider,
    booking_idempotency_key,
    parse_booking_plan_result,
)
from vyro_growth.providers.decision_makers import clean_optional_text
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.outbound_guard import (
    OutboundAction,
    OutboundBlockedError,
    OutboundGuard,
    domain_from_email,
    suppression_status,
)

logger = structlog.get_logger(__name__)

BOOKING_PLAN_ACTOR = "booking_plan"
BATCH_MAX = 200
DEFAULT_OPERATOR_REQUEST_KEY = "operator"


class BookingPlanError(ValueError):
    """Raised when a dry-run booking plan cannot load the requested records."""


@dataclass(frozen=True)
class BookingItemResult:
    booking_plan_id: UUID
    lead_id: UUID
    organization_id: UUID
    status: BookingPlanStatus
    skip_reason: BookingSkipReason | None
    reused: bool
    dry_run: bool
    event_created: bool
    meet_link_created: bool
    live_call_attempted: bool
    provider_name: str
    lead_stage_before: str
    lead_stage_after: str


@dataclass(frozen=True)
class BookingPlanJobResult:
    booking_plan_run_id: UUID
    planned_count: int
    skipped_count: int
    suppressed_count: int
    blocked_count: int
    reused_count: int
    status: BookingPlanRunStatus
    items: tuple[BookingItemResult, ...]


class BookingPlanService:
    """Plan dry-run meeting drafts. Does not create events, Meet links, or outbound."""

    def __init__(
        self,
        provider: BookingCalendarProvider | None = None,
        *,
        settings: Settings | None = None,
        guard: OutboundGuard | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._provider = provider or build_booking_calendar_provider(self._settings)
        self._guard = guard or OutboundGuard(self._settings)

    def plan_lead(
        self,
        db: Session,
        lead_id: UUID,
        *,
        classification_id: UUID | None = None,
        operator_request: bool = False,
        request_key: str | None = None,
        requested_window: dict[str, object] | None = None,
        commit: bool = True,
    ) -> BookingPlanJobResult:
        lead = db.get(Lead, lead_id)
        if lead is None:
            raise BookingPlanError(f"Lead not found: {lead_id}")
        return self._plan(
            db,
            specs=(
                _LeadPlanSpec(
                    lead=lead,
                    classification_id=classification_id,
                    operator_request=operator_request,
                    request_key=request_key,
                    requested_window=requested_window,
                ),
            ),
            input_params={
                "lead_id": str(lead_id),
                "classification_id": str(classification_id) if classification_id else None,
                "operator_request": operator_request,
                "request_key": request_key,
            },
            commit=commit,
        )

    def plan_classification(
        self,
        db: Session,
        classification_id: UUID,
        *,
        commit: bool = True,
    ) -> BookingPlanJobResult:
        classification = db.get(ReplyClassification, classification_id)
        if classification is None:
            raise BookingPlanError(f"Reply classification not found: {classification_id}")
        lead = db.get(Lead, classification.lead_id)
        if lead is None:
            raise BookingPlanError(f"Lead not found for classification: {classification_id}")
        return self._plan(
            db,
            specs=(
                _LeadPlanSpec(
                    lead=lead,
                    classification_id=classification.id,
                    operator_request=False,
                    request_key=None,
                    requested_window=None,
                ),
            ),
            input_params={"classification_id": str(classification_id)},
            commit=commit,
        )

    def plan_batch(
        self,
        db: Session,
        *,
        limit: int = 50,
        state: str | None = None,
        city: str | None = None,
        commit: bool = True,
    ) -> BookingPlanJobResult:
        classifications = self._eligible_meeting_requests(
            db,
            limit=min(max(limit, 1), BATCH_MAX),
            state=state,
            city=city,
        )
        specs: list[_LeadPlanSpec] = []
        for classification in classifications:
            lead = db.get(Lead, classification.lead_id)
            if lead is None:
                continue
            specs.append(
                _LeadPlanSpec(
                    lead=lead,
                    classification_id=classification.id,
                    operator_request=False,
                    request_key=None,
                    requested_window=None,
                )
            )
        return self._plan(
            db,
            specs=tuple(specs),
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
        specs: tuple[_LeadPlanSpec, ...],
        input_params: dict[str, object],
        commit: bool,
    ) -> BookingPlanJobResult:
        halt_before = _halt_value(read_operator_halt(db))
        run = BookingPlanRun(
            status=BookingPlanRunStatus.RUNNING.value,
            started_at=datetime.now(tz=UTC),
            input_params={
                **input_params,
                "dry_run": True,
                "outbound_attempted": False,
                "event_created": False,
                "meet_link_created": False,
                "operator_halt_before": halt_before,
                "provider": "stub" if not getattr(self._provider, "live", False) else "live",
            },
        )
        db.add(run)
        db.flush()

        items: list[BookingItemResult] = []
        try:
            for spec in specs:
                items.append(self._plan_one(db, run=run, spec=spec, halt_before=halt_before))
        except BookingPlanError:
            raise
        except Exception as exc:
            run.status = BookingPlanRunStatus.FAILED.value
            run.finished_at = datetime.now(tz=UTC)
            run.error_message = str(exc)
            self._record_activity(
                db,
                lead_id=None,
                action="booking_plan_failed",
                details={
                    "booking_plan_run_id": str(run.id),
                    "error": str(exc),
                    "outbound_attempted": False,
                    "event_created": False,
                    "meet_link_created": False,
                    "live_call_attempted": False,
                },
            )
            if commit:
                db.commit()
            logger.exception("booking_plan_failed", booking_plan_run_id=str(run.id))
            raise

        self._finalize_run(db, run, items, halt_before=halt_before)
        if commit:
            db.commit()
        logger.info(
            "booking_plan_completed",
            booking_plan_run_id=str(run.id),
            planned=run.planned_count,
            skipped=run.skipped_count,
            suppressed=run.suppressed_count,
            blocked=run.blocked_count,
            reused=run.reused_count,
        )
        return BookingPlanJobResult(
            booking_plan_run_id=run.id,
            planned_count=run.planned_count,
            skipped_count=run.skipped_count,
            suppressed_count=run.suppressed_count,
            blocked_count=run.blocked_count,
            reused_count=run.reused_count,
            status=BookingPlanRunStatus.COMPLETED,
            items=tuple(items),
        )

    def _plan_one(
        self,
        db: Session,
        *,
        run: BookingPlanRun,
        spec: _LeadPlanSpec,
        halt_before: str,
    ) -> BookingItemResult:
        lead = spec.lead
        organization = db.get(Organization, lead.organization_id)
        if organization is None:
            raise BookingPlanError(f"Organization not found for lead: {lead.id}")

        classification = self._resolve_classification(db, spec)
        contact = self._resolve_contact(db, organization.id, classification)
        source, request_key = self._request_identity(spec, classification)
        key = booking_idempotency_key(
            lead_id=lead.id,
            contact_id=contact.id if contact is not None else None,
            request_source=source,
            request_key=request_key,
        )
        existing = db.scalar(select(BookingPlan).where(BookingPlan.idempotency_key == key))
        if existing is not None and existing.status == BookingPlanStatus.PLANNED.value:
            existing.booking_plan_run_id = run.id
            audit = dict(existing.audit_json)
            audit["idempotent_reuse"] = True
            existing.audit_json = audit
            db.flush()
            self._record_activity(
                db,
                lead_id=lead.id,
                action="booking_plan_idempotent",
                details={
                    "booking_plan_id": str(existing.id),
                    "booking_plan_run_id": str(run.id),
                    "status": existing.status,
                    "dry_run": existing.dry_run,
                    "event_created": existing.event_created,
                    "meet_link_created": existing.meet_link_created,
                    "live_call_attempted": existing.live_call_attempted,
                    "outbound_attempted": False,
                    "operator_halt_before": halt_before,
                    "operator_halt_after": _halt_value(read_operator_halt(db)),
                },
            )
            return BookingItemResult(
                booking_plan_id=existing.id,
                lead_id=lead.id,
                organization_id=organization.id,
                status=BookingPlanStatus.PLANNED,
                skip_reason=None,
                reused=True,
                dry_run=existing.dry_run,
                event_created=existing.event_created,
                meet_link_created=existing.meet_link_created,
                live_call_attempted=existing.live_call_attempted,
                provider_name=existing.provider_name,
                lead_stage_before=existing.lead_stage_before,
                lead_stage_after=lead.stage,
            )

        stage_before = _lead_stage(lead.stage)
        status, reason, audit, provider_result, stage_after = self._decide(
            db,
            lead=lead,
            organization=organization,
            contact=contact,
            classification=classification,
            source=source,
            request_key=request_key,
            requested_window=spec.requested_window,
            idempotency_key=key,
            halt_before=halt_before,
            stage_before=stage_before,
        )
        if status is BookingPlanStatus.PLANNED and stage_after is not stage_before:
            if (
                stage_after not in FORBIDDEN_BOOKING_STAGES
                and can_transition(stage_before, stage_after)
            ):
                lead.stage = stage_after.value
            else:
                stage_after = stage_before

        plan = existing or BookingPlan(
            lead_id=lead.id,
            organization_id=organization.id,
            idempotency_key=key,
            lead_stage_before=stage_before.value,
            lead_stage_after=stage_after.value,
        )
        plan.booking_plan_run_id = run.id
        plan.contact_id = contact.id if contact is not None else None
        plan.reply_classification_id = classification.id if classification is not None else None
        plan.request_source = source.value
        plan.request_key = request_key
        plan.status = status.value
        plan.skip_reason = reason.value if reason is not None else None
        plan.provider_name = (
            provider_result.provider_name if provider_result is not None else "none"
        )
        plan.requested_window = spec.requested_window
        plan.proposed_slots = (
            [slot.to_dict() for slot in provider_result.proposed_slots]
            if provider_result is not None
            else []
        )
        plan.dry_run = True
        plan.event_created = False
        plan.meet_link_created = False
        plan.live_call_attempted = False
        plan.provider_event_id = None
        plan.meeting_url = None
        plan.lead_stage_before = stage_before.value
        plan.lead_stage_after = lead.stage
        plan.audit_json = audit
        if existing is None:
            db.add(plan)
        db.flush()
        self._record_activity(
            db,
            lead_id=lead.id,
            action=_activity_action(status),
            details={
                "booking_plan_id": str(plan.id),
                "booking_plan_run_id": str(run.id),
                "status": status.value,
                "skip_reason": reason.value if reason is not None else None,
                "dry_run": True,
                "event_created": False,
                "meet_link_created": False,
                "live_call_attempted": False,
                "outbound_attempted": False,
                "provider": plan.provider_name,
                "lead_stage_before": stage_before.value,
                "lead_stage_after": lead.stage,
                "meetings_created": 0,
                "campaigns_enrolled": False,
            },
        )
        return BookingItemResult(
            booking_plan_id=plan.id,
            lead_id=lead.id,
            organization_id=organization.id,
            status=status,
            skip_reason=reason,
            reused=existing is not None,
            dry_run=True,
            event_created=False,
            meet_link_created=False,
            live_call_attempted=False,
            provider_name=plan.provider_name,
            lead_stage_before=stage_before.value,
            lead_stage_after=lead.stage,
        )

    def _decide(
        self,
        db: Session,
        *,
        lead: Lead,
        organization: Organization,
        contact: Contact | None,
        classification: ReplyClassification | None,
        source: BookingRequestSource,
        request_key: str,
        requested_window: dict[str, object] | None,
        idempotency_key: str,
        halt_before: str,
        stage_before: LeadStage,
    ) -> tuple[
        BookingPlanStatus,
        BookingSkipReason | None,
        dict[str, object],
        BookingPlanProviderResult | None,
        LeadStage,
    ]:
        halt_after = _halt_value(read_operator_halt(db))
        audit: dict[str, object] = {
            "dry_run": True,
            "event_created": False,
            "meet_link_created": False,
            "live_call_attempted": False,
            "outbound_attempted": False,
            "fabricated_facts": False,
            "operator_halt_before": halt_before,
            "operator_halt_after": halt_after,
            "request_source": source.value,
            "request_key": request_key,
        }
        if source is BookingRequestSource.MEETING_REQUEST_REPLY:
            if classification is None:
                return (
                    BookingPlanStatus.SKIPPED,
                    BookingSkipReason.MISSING_MEETING_REQUEST,
                    audit,
                    None,
                    stage_before,
                )
            if classification.intent != ReplyIntent.MEETING_REQUEST.value:
                return (
                    BookingPlanStatus.SKIPPED,
                    BookingSkipReason.INELIGIBLE_CONSENT,
                    {**audit, "intent": classification.intent},
                    None,
                    stage_before,
                )
            if classification.suppressed:
                return (
                    BookingPlanStatus.SUPPRESSED,
                    BookingSkipReason.SUPPRESSED,
                    audit,
                    None,
                    stage_before,
                )
        elif source is not BookingRequestSource.OPERATOR_REQUEST:
            return (
                BookingPlanStatus.SKIPPED,
                BookingSkipReason.INELIGIBLE_CONSENT,
                audit,
                None,
                stage_before,
            )

        email = contact.email if contact is not None else None
        suppression = suppression_status(
            db,
            email=email,
            domain=domain_from_email(email),
            organization_id=organization.id,
        )
        audit["suppression_decision"] = suppression.reason
        if not suppression.allowed:
            if suppression.reason == "suppression_check_unavailable":
                return (
                    BookingPlanStatus.BLOCKED,
                    BookingSkipReason.SUPPRESSION_CHECK_UNAVAILABLE,
                    audit,
                    None,
                    stage_before,
                )
            if suppression.reason == "target_unidentified" and contact is None:
                return (
                    BookingPlanStatus.SKIPPED,
                    BookingSkipReason.MISSING_CONTACT,
                    audit,
                    None,
                    stage_before,
                )
            if suppression.reason == "target_unidentified":
                return (
                    BookingPlanStatus.BLOCKED,
                    BookingSkipReason.TARGET_UNIDENTIFIED,
                    audit,
                    None,
                    stage_before,
                )
            return (
                BookingPlanStatus.SUPPRESSED,
                BookingSkipReason.SUPPRESSED,
                audit,
                None,
                stage_before,
            )

        outbound = self._guard.evaluate(
            db,
            action=OutboundAction.CALENDAR_SCHEDULE,
            email=email,
            domain=domain_from_email(email),
            organization_id=organization.id,
        )
        audit["outbound_decision"] = outbound.reason
        audit["live_booking_allowed"] = outbound.allowed

        payload = BookingPlanPayload(
            lead_id=lead.id,
            organization_id=organization.id,
            idempotency_key=idempotency_key,
            request_source=source.value,
            organization_name=organization.name,
            contact_id=contact.id if contact is not None else None,
            attendee_email=email,
            requested_window=requested_window,
        )
        if contact is not None:
            audit["contact_id"] = str(contact.id)
        if classification is not None:
            audit["reply_classification_id"] = str(classification.id)

        if getattr(self._provider, "live", False):
            status, reason, audit, provider_result = self._call_live_boundary(
                db, payload, audit, email, organization.id
            )
        else:
            status, reason, audit, provider_result = self._call_stub(payload, audit)

        stage_after = stage_before
        if status is BookingPlanStatus.PLANNED:
            target = desired_booking_stage(stage_before)
            if target is not None and target not in FORBIDDEN_BOOKING_STAGES:
                stage_after = target
        return status, reason, audit, provider_result, stage_after

    def _call_stub(
        self,
        payload: BookingPlanPayload,
        audit: dict[str, object],
    ) -> tuple[
        BookingPlanStatus,
        BookingSkipReason | None,
        dict[str, object],
        BookingPlanProviderResult | None,
    ]:
        try:
            parsed = parse_booking_plan_result(self._provider.plan_booking(payload))
        except MalformedBookingPlanOutput:
            return (
                BookingPlanStatus.SKIPPED,
                BookingSkipReason.MALFORMED_PROVIDER_OUTPUT,
                audit,
                None,
            )
        except RetryableBookingCalendarError:
            return (
                BookingPlanStatus.SKIPPED,
                BookingSkipReason.PROVIDER_RETRYABLE_ERROR,
                audit,
                None,
            )
        except BookingCalendarError:
            return (
                BookingPlanStatus.SKIPPED,
                BookingSkipReason.PROVIDER_NON_RETRYABLE_ERROR,
                audit,
                None,
            )
        return self._accept_or_reject(parsed, audit)

    def _call_live_boundary(
        self,
        db: Session,
        payload: BookingPlanPayload,
        audit: dict[str, object],
        email: str | None,
        organization_id: UUID,
    ) -> tuple[
        BookingPlanStatus,
        BookingSkipReason | None,
        dict[str, object],
        BookingPlanProviderResult | None,
    ]:
        try:
            self._guard.require_allowed(
                db,
                action=OutboundAction.CALENDAR_SCHEDULE,
                email=email,
                domain=domain_from_email(email),
                organization_id=organization_id,
            )
            parsed = parse_booking_plan_result(self._provider.plan_booking(payload))
        except OutboundBlockedError as exc:
            return BookingPlanStatus.BLOCKED, _reason_from_outbound(str(exc)), audit, None
        except LiveGoogleCalendarDisabledError:
            return (
                BookingPlanStatus.BLOCKED,
                BookingSkipReason.GOOGLE_CALENDAR_LIVE_DISABLED,
                audit,
                None,
            )
        except LiveGoogleCalendarNotImplementedError:
            return (
                BookingPlanStatus.BLOCKED,
                BookingSkipReason.LIVE_GOOGLE_NOT_IMPLEMENTED,
                audit,
                None,
            )
        except MalformedBookingPlanOutput:
            return (
                BookingPlanStatus.SKIPPED,
                BookingSkipReason.MALFORMED_PROVIDER_OUTPUT,
                audit,
                None,
            )
        except RetryableBookingCalendarError:
            return (
                BookingPlanStatus.SKIPPED,
                BookingSkipReason.PROVIDER_RETRYABLE_ERROR,
                audit,
                None,
            )
        except BookingCalendarError:
            return (
                BookingPlanStatus.SKIPPED,
                BookingSkipReason.PROVIDER_NON_RETRYABLE_ERROR,
                audit,
                None,
            )
        return self._accept_or_reject(parsed, audit)

    def _accept_or_reject(
        self,
        parsed: BookingPlanProviderResult,
        audit: dict[str, object],
    ) -> tuple[
        BookingPlanStatus,
        BookingSkipReason | None,
        dict[str, object],
        BookingPlanProviderResult | None,
    ]:
        audit["provider_name"] = parsed.provider_name
        if parsed.event_created:
            return (
                BookingPlanStatus.BLOCKED,
                BookingSkipReason.EVENT_CREATION_REJECTED,
                audit,
                parsed,
            )
        if parsed.meet_link_created:
            return (
                BookingPlanStatus.BLOCKED,
                BookingSkipReason.MEET_LINK_REJECTED,
                audit,
                parsed,
            )
        if parsed.live_call_attempted or not parsed.dry_run:
            return (
                BookingPlanStatus.BLOCKED,
                BookingSkipReason.LIVE_BOOKING_REJECTED,
                audit,
                parsed,
            )
        if not parsed.accepted:
            return (
                BookingPlanStatus.SKIPPED,
                BookingSkipReason.PROVIDER_NOT_ACCEPTED,
                audit,
                parsed,
            )
        return BookingPlanStatus.PLANNED, None, audit, parsed

    def _resolve_classification(
        self,
        db: Session,
        spec: _LeadPlanSpec,
    ) -> ReplyClassification | None:
        if spec.classification_id is not None:
            classification = db.get(ReplyClassification, spec.classification_id)
            if classification is None:
                raise BookingPlanError(
                    f"Reply classification not found: {spec.classification_id}"
                )
            if classification.lead_id != spec.lead.id:
                raise BookingPlanError(
                    "Reply classification does not belong to the requested lead"
                )
            return classification
        if spec.operator_request:
            return None
        return db.scalar(
            select(ReplyClassification)
            .where(
                ReplyClassification.lead_id == spec.lead.id,
                ReplyClassification.intent == ReplyIntent.MEETING_REQUEST.value,
            )
            .order_by(ReplyClassification.created_at.desc(), ReplyClassification.id.desc())
        )

    def _resolve_contact(
        self,
        db: Session,
        organization_id: UUID,
        classification: ReplyClassification | None,
    ) -> Contact | None:
        if classification is not None and classification.outreach_message_id is not None:
            message = db.get(OutreachMessage, classification.outreach_message_id)
            if message is not None and message.contact_id is not None:
                contact = db.get(Contact, message.contact_id)
                if contact is not None:
                    return contact
        contacts = list(
            db.scalars(select(Contact).where(Contact.organization_id == organization_id)).all()
        )
        with_email = [row for row in contacts if clean_optional_text(row.email)]
        if not with_email:
            return contacts[0] if contacts else None
        with_email.sort(
            key=lambda row: (
                row.role_rank is None,
                row.role_rank if row.role_rank is not None else 0,
                row.created_at,
            )
        )
        return with_email[0]

    def _request_identity(
        self,
        spec: _LeadPlanSpec,
        classification: ReplyClassification | None,
    ) -> tuple[BookingRequestSource, str]:
        if spec.operator_request:
            key = clean_optional_text(spec.request_key) or DEFAULT_OPERATOR_REQUEST_KEY
            return BookingRequestSource.OPERATOR_REQUEST, key
        if classification is not None:
            return BookingRequestSource.MEETING_REQUEST_REPLY, str(classification.id)
        return BookingRequestSource.MEETING_REQUEST_REPLY, "missing"

    def _eligible_meeting_requests(
        self,
        db: Session,
        *,
        limit: int,
        state: str | None,
        city: str | None,
    ) -> tuple[ReplyClassification, ...]:
        planned = select(BookingPlan.reply_classification_id).where(
            BookingPlan.status == BookingPlanStatus.PLANNED.value,
            BookingPlan.reply_classification_id.is_not(None),
        )
        query = (
            select(ReplyClassification)
            .join(Lead, Lead.id == ReplyClassification.lead_id)
            .join(Organization, Organization.id == Lead.organization_id)
            .where(
                ReplyClassification.intent == ReplyIntent.MEETING_REQUEST.value,
                ReplyClassification.suppressed.is_(False),
                ReplyClassification.id.not_in(planned),
            )
            .order_by(ReplyClassification.created_at.asc(), ReplyClassification.id.asc())
        )
        if state:
            query = query.where(Organization.state == state.strip().upper())
        if city:
            query = query.where(Organization.city == city.strip().upper())
        return tuple(db.scalars(query.limit(limit)).all())

    def _finalize_run(
        self,
        db: Session,
        run: BookingPlanRun,
        items: list[BookingItemResult],
        *,
        halt_before: str,
    ) -> None:
        planned = skipped = suppressed = blocked = reused = 0
        for item in items:
            if item.reused:
                reused += 1
            match item.status:
                case BookingPlanStatus.PLANNED:
                    planned += 1
                case BookingPlanStatus.SKIPPED:
                    skipped += 1
                case BookingPlanStatus.SUPPRESSED:
                    suppressed += 1
                case BookingPlanStatus.BLOCKED:
                    blocked += 1
                case _:
                    unreachable: Never = item.status
                    raise RuntimeError(f"unhandled booking status: {unreachable}")
        run.planned_count = planned
        run.skipped_count = skipped
        run.suppressed_count = suppressed
        run.blocked_count = blocked
        run.reused_count = reused
        run.status = BookingPlanRunStatus.COMPLETED.value
        run.finished_at = datetime.now(tz=UTC)
        halt_after = _halt_value(read_operator_halt(db))
        self._record_activity(
            db,
            lead_id=None,
            action="booking_plan_completed",
            details={
                "booking_plan_run_id": str(run.id),
                "planned": planned,
                "skipped": skipped,
                "suppressed": suppressed,
                "blocked": blocked,
                "reused": reused,
                "dry_run": True,
                "outbound_attempted": False,
                "event_created": False,
                "meet_link_created": False,
                "live_call_attempted": False,
                "meetings_created": 0,
                "campaign_enrollments_created": False,
                "operator_halt_before": halt_before,
                "operator_halt_after": halt_after,
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
        db.add(Activity(lead_id=lead_id, actor=BOOKING_PLAN_ACTOR, action=action, details=details))


@dataclass(frozen=True)
class _LeadPlanSpec:
    lead: Lead
    classification_id: UUID | None
    operator_request: bool
    request_key: str | None
    requested_window: dict[str, object] | None


def _lead_stage(value: str) -> LeadStage:
    try:
        return LeadStage(value)
    except ValueError:
        return LeadStage.DISCOVERED


def _halt_value(status: HaltStatus) -> str:
    return status.value


def _reason_from_outbound(reason: str) -> BookingSkipReason:
    mapping = {
        "global_outbound_disabled": BookingSkipReason.GLOBAL_OUTBOUND_DISABLED,
        "operator_global_halt": BookingSkipReason.OPERATOR_GLOBAL_HALT,
        "operator_halt_unavailable": BookingSkipReason.OPERATOR_HALT_UNAVAILABLE,
        "suppressed": BookingSkipReason.SUPPRESSED,
        "suppression_check_unavailable": BookingSkipReason.SUPPRESSION_CHECK_UNAVAILABLE,
        "target_unidentified": BookingSkipReason.TARGET_UNIDENTIFIED,
    }
    return mapping.get(reason, BookingSkipReason.GLOBAL_OUTBOUND_DISABLED)


def _activity_action(status: BookingPlanStatus) -> str:
    match status:
        case BookingPlanStatus.PLANNED:
            return "booking_plan_planned"
        case BookingPlanStatus.SKIPPED:
            return "booking_plan_skipped"
        case BookingPlanStatus.SUPPRESSED:
            return "booking_plan_suppressed"
        case BookingPlanStatus.BLOCKED:
            return "booking_plan_blocked"
        case _:
            unreachable: Never = status
            raise RuntimeError(f"unhandled booking status: {unreachable}")

