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
    BookingPlanStatus,
    MessageDirection,
    VoiceConsentChannel,
    VoiceConsentSource,
    VoicePlanStatus,
    VoiceQualificationRunStatus,
    VoiceSkipReason,
    WebsiteFactType,
)
from vyro_growth.models import (
    Activity,
    BookingPlan,
    Contact,
    Lead,
    Meeting,
    Organization,
    OutreachMessage,
    ReplyClassification,
    SourceEvidence,
    VoiceQualificationPlan,
    VoiceQualificationRun,
)
from vyro_growth.providers.decision_makers import clean_optional_text
from vyro_growth.providers.voice_qualification import (
    DEFAULT_OPERATOR_REQUEST_KEY,
    LiveVoiceDisabledError,
    LiveVoiceNotImplementedError,
    MalformedVoicePlanOutput,
    RetryableVoiceQualificationError,
    VoiceConsentProof,
    VoiceQualificationError,
    VoiceQualificationProvider,
    VoiceQualificationRequest,
    VoiceQualificationResult,
    build_voice_qualification_provider,
    contains_suspected_phi,
    message_requests_call,
    parse_consent_timestamp,
    parse_voice_qualification_result,
    sanitize_stored_facts,
    voice_idempotency_key,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.outbound_guard import (
    OutboundAction,
    OutboundBlockedError,
    OutboundGuard,
    domain_from_email,
    normalize_phone,
    suppression_status,
)

logger = structlog.get_logger(__name__)

VOICE_PLAN_ACTOR = "voice_qualification"
BATCH_MAX = 200


class VoiceQualificationServiceError(ValueError):
    """Raised when a dry-run voice qualification plan cannot load the requested records."""


@dataclass(frozen=True)
class VoiceItemResult:
    voice_plan_id: UUID
    lead_id: UUID
    organization_id: UUID
    status: VoicePlanStatus
    skip_reason: VoiceSkipReason | None
    reused: bool
    dry_run: bool
    live_call_attempted: bool
    call_placed: bool
    provider_name: str


@dataclass(frozen=True)
class VoiceQualificationJobResult:
    voice_qualification_run_id: UUID
    planned_count: int
    skipped_count: int
    suppressed_count: int
    blocked_count: int
    reused_count: int
    status: VoiceQualificationRunStatus
    items: tuple[VoiceItemResult, ...]


@dataclass(frozen=True)
class VoiceConsentInput:
    source: VoiceConsentSource | None = None
    channel: VoiceConsentChannel | None = None
    consented_at: datetime | None = None
    permitted_phone: str | None = None
    evidence_reference_id: str | None = None


@dataclass(frozen=True)
class _LeadPlanSpec:
    lead: Lead
    message_id: UUID | None = None
    meeting_id: UUID | None = None
    booking_plan_id: UUID | None = None
    operator_request: bool = False
    request_key: str | None = None
    consent: VoiceConsentInput | None = None
    extra_facts: dict[str, str] | None = None


class VoiceQualificationService:
    """Plan dry-run consent-based voice qualification. Does not place calls."""

    def __init__(
        self,
        provider: VoiceQualificationProvider | None = None,
        *,
        settings: Settings | None = None,
        guard: OutboundGuard | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._provider = provider or build_voice_qualification_provider(self._settings)
        self._guard = guard or OutboundGuard(self._settings)

    def plan_lead(
        self,
        db: Session,
        lead_id: UUID,
        *,
        message_id: UUID | None = None,
        meeting_id: UUID | None = None,
        booking_plan_id: UUID | None = None,
        operator_request: bool = False,
        request_key: str | None = None,
        consent: VoiceConsentInput | None = None,
        extra_facts: dict[str, str] | None = None,
        commit: bool = True,
    ) -> VoiceQualificationJobResult:
        lead = db.get(Lead, lead_id)
        if lead is None:
            raise VoiceQualificationServiceError(f"Lead not found: {lead_id}")
        return self._plan(
            db,
            specs=(
                _LeadPlanSpec(
                    lead=lead,
                    message_id=message_id,
                    meeting_id=meeting_id,
                    booking_plan_id=booking_plan_id,
                    operator_request=operator_request,
                    request_key=request_key,
                    consent=consent,
                    extra_facts=extra_facts,
                ),
            ),
            input_params={
                "lead_id": str(lead_id),
                "message_id": str(message_id) if message_id else None,
                "meeting_id": str(meeting_id) if meeting_id else None,
                "booking_plan_id": str(booking_plan_id) if booking_plan_id else None,
                "operator_request": operator_request,
                "request_key": request_key,
            },
            commit=commit,
        )

    def plan_message(
        self,
        db: Session,
        message_id: UUID,
        *,
        commit: bool = True,
    ) -> VoiceQualificationJobResult:
        message = db.get(OutreachMessage, message_id)
        if message is None:
            raise VoiceQualificationServiceError(f"Outreach message not found: {message_id}")
        if message.direction != MessageDirection.INBOUND.value:
            raise VoiceQualificationServiceError(f"Outreach message is not inbound: {message_id}")
        lead = db.get(Lead, message.lead_id)
        if lead is None:
            raise VoiceQualificationServiceError(f"Lead not found for message: {message_id}")
        return self._plan(
            db,
            specs=(_LeadPlanSpec(lead=lead, message_id=message.id),),
            input_params={"message_id": str(message_id)},
            commit=commit,
        )

    def plan_meeting(
        self,
        db: Session,
        meeting_id: UUID,
        *,
        consent: VoiceConsentInput | None = None,
        commit: bool = True,
    ) -> VoiceQualificationJobResult:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            raise VoiceQualificationServiceError(f"Meeting not found: {meeting_id}")
        lead = db.get(Lead, meeting.lead_id)
        if lead is None:
            raise VoiceQualificationServiceError(f"Lead not found for meeting: {meeting_id}")
        return self._plan(
            db,
            specs=(_LeadPlanSpec(lead=lead, meeting_id=meeting.id, consent=consent),),
            input_params={"meeting_id": str(meeting_id)},
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
    ) -> VoiceQualificationJobResult:
        messages = self._eligible_call_request_messages(
            db,
            limit=min(max(limit, 1), BATCH_MAX),
            state=state,
            city=city,
        )
        specs: list[_LeadPlanSpec] = []
        for message in messages:
            lead = db.get(Lead, message.lead_id)
            if lead is None:
                continue
            specs.append(_LeadPlanSpec(lead=lead, message_id=message.id))
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
    ) -> VoiceQualificationJobResult:
        halt_before = _halt_value(read_operator_halt(db))
        run = VoiceQualificationRun(
            status=VoiceQualificationRunStatus.RUNNING.value,
            started_at=datetime.now(tz=UTC),
            input_params={
                **input_params,
                "dry_run": True,
                "outbound_attempted": False,
                "call_placed": False,
                "operator_halt_before": halt_before,
                "provider": "stub" if not getattr(self._provider, "live", False) else "live",
            },
        )
        db.add(run)
        db.flush()

        items: list[VoiceItemResult] = []
        try:
            for spec in specs:
                items.append(self._plan_one(db, run=run, spec=spec, halt_before=halt_before))
        except VoiceQualificationServiceError:
            raise
        except Exception as exc:
            run.status = VoiceQualificationRunStatus.FAILED.value
            run.finished_at = datetime.now(tz=UTC)
            run.error_message = str(exc)
            self._record_activity(
                db,
                lead_id=None,
                action="voice_qualification_failed",
                details={
                    "voice_qualification_run_id": str(run.id),
                    "error": str(exc),
                    "outbound_attempted": False,
                    "live_call_attempted": False,
                    "call_placed": False,
                },
            )
            if commit:
                db.commit()
            logger.exception("voice_qualification_failed", voice_qualification_run_id=str(run.id))
            raise

        self._finalize_run(db, run, items, halt_before=halt_before)
        if commit:
            db.commit()
        logger.info(
            "voice_qualification_completed",
            voice_qualification_run_id=str(run.id),
            planned=run.planned_count,
            skipped=run.skipped_count,
            suppressed=run.suppressed_count,
            blocked=run.blocked_count,
            reused=run.reused_count,
        )
        return VoiceQualificationJobResult(
            voice_qualification_run_id=run.id,
            planned_count=run.planned_count,
            skipped_count=run.skipped_count,
            suppressed_count=run.suppressed_count,
            blocked_count=run.blocked_count,
            reused_count=run.reused_count,
            status=VoiceQualificationRunStatus.COMPLETED,
            items=tuple(items),
        )

    def _plan_one(
        self,
        db: Session,
        *,
        run: VoiceQualificationRun,
        spec: _LeadPlanSpec,
        halt_before: str,
    ) -> VoiceItemResult:
        lead = spec.lead
        organization = db.get(Organization, lead.organization_id)
        if organization is None:
            raise VoiceQualificationServiceError(f"Organization not found for lead: {lead.id}")

        context = self._resolve_context(db, spec)
        contact = context.contact
        key = voice_idempotency_key(
            lead_id=lead.id,
            contact_id=contact.id if contact is not None else None,
            consent_source=context.source,
            request_key=context.request_key,
        )
        existing = db.scalar(
            select(VoiceQualificationPlan).where(VoiceQualificationPlan.idempotency_key == key)
        )
        if existing is not None and existing.status == VoicePlanStatus.PLANNED.value:
            existing.voice_qualification_run_id = run.id
            audit = dict(existing.audit_json)
            audit["idempotent_reuse"] = True
            existing.audit_json = audit
            db.flush()
            self._record_activity(
                db,
                lead_id=lead.id,
                action="voice_qualification_idempotent",
                details={
                    "voice_plan_id": str(existing.id),
                    "voice_qualification_run_id": str(run.id),
                    "status": existing.status,
                    "dry_run": existing.dry_run,
                    "live_call_attempted": existing.live_call_attempted,
                    "call_placed": existing.call_placed,
                    "outbound_attempted": False,
                    "operator_halt_before": halt_before,
                    "operator_halt_after": _halt_value(read_operator_halt(db)),
                },
            )
            return VoiceItemResult(
                voice_plan_id=existing.id,
                lead_id=lead.id,
                organization_id=organization.id,
                status=VoicePlanStatus.PLANNED,
                skip_reason=None,
                reused=True,
                dry_run=existing.dry_run,
                live_call_attempted=existing.live_call_attempted,
                call_placed=existing.call_placed,
                provider_name=existing.provider_name,
            )

        status, reason, audit, consent_json, facts, provider_result = self._decide(
            db,
            lead=lead,
            organization=organization,
            context=context,
            extra_facts=spec.extra_facts,
            idempotency_key=key,
            halt_before=halt_before,
        )
        plan = existing or VoiceQualificationPlan(
            lead_id=lead.id,
            organization_id=organization.id,
            idempotency_key=key,
        )
        plan.voice_qualification_run_id = run.id
        plan.contact_id = contact.id if contact is not None else None
        plan.outreach_message_id = context.message.id if context.message is not None else None
        plan.reply_classification_id = (
            context.classification.id if context.classification is not None else None
        )
        plan.meeting_id = context.meeting.id if context.meeting is not None else None
        plan.booking_plan_id = context.booking_plan.id if context.booking_plan is not None else None
        plan.request_source = context.source.value
        plan.request_key = context.request_key
        plan.status = status.value
        plan.skip_reason = reason.value if reason is not None else None
        plan.provider_name = (
            provider_result.provider_name if provider_result is not None else "none"
        )
        plan.provider_plan_id = (
            provider_result.provider_plan_id if provider_result is not None else None
        )
        proof = context.proof
        plan.consent_source = proof.source.value if proof is not None else None
        plan.consent_channel = proof.channel.value if proof is not None else None
        plan.consent_timestamp = proof.consented_at if proof is not None else None
        plan.consent_evidence_id = proof.evidence_reference_id if proof is not None else None
        plan.permitted_phone = (
            normalize_phone(proof.permitted_phone) if proof is not None else None
        )
        plan.dry_run = True
        plan.live_call_attempted = False
        plan.call_placed = False
        plan.facts_json = dict(facts)
        plan.consent_json = dict(consent_json)
        plan.audit_json = audit
        if existing is None:
            db.add(plan)
        db.flush()
        self._record_activity(
            db,
            lead_id=lead.id,
            action=_activity_action(status),
            details={
                "voice_plan_id": str(plan.id),
                "voice_qualification_run_id": str(run.id),
                "status": status.value,
                "skip_reason": reason.value if reason is not None else None,
                "dry_run": True,
                "live_call_attempted": False,
                "call_placed": False,
                "outbound_attempted": False,
                "provider": plan.provider_name,
                "meetings_created": 0,
                "campaigns_enrolled": False,
            },
        )
        return VoiceItemResult(
            voice_plan_id=plan.id,
            lead_id=lead.id,
            organization_id=organization.id,
            status=status,
            skip_reason=reason,
            reused=existing is not None,
            dry_run=True,
            live_call_attempted=False,
            call_placed=False,
            provider_name=plan.provider_name,
        )

    def _decide(
        self,
        db: Session,
        *,
        lead: Lead,
        organization: Organization,
        context: _ResolvedContext,
        extra_facts: dict[str, str] | None,
        idempotency_key: str,
        halt_before: str,
    ) -> tuple[
        VoicePlanStatus,
        VoiceSkipReason | None,
        dict[str, object],
        dict[str, object],
        dict[str, str],
        VoiceQualificationResult | None,
    ]:
        halt_after = _halt_value(read_operator_halt(db))
        audit: dict[str, object] = {
            "dry_run": True,
            "live_call_attempted": False,
            "call_placed": False,
            "outbound_attempted": False,
            "fabricated_facts": False,
            "operator_halt_before": halt_before,
            "operator_halt_after": halt_after,
            "request_source": context.source.value,
            "request_key": context.request_key,
        }
        consent_json: dict[str, object] = {}
        if context.phi_detected:
            return (
                VoicePlanStatus.BLOCKED,
                VoiceSkipReason.SUSPECTED_PHI,
                {**audit, "phi_detected": True},
                consent_json,
                {},
                None,
            )
        if context.skip_reason is not None:
            status = (
                VoicePlanStatus.BLOCKED
                if context.skip_reason is VoiceSkipReason.COLD_CALL_FORBIDDEN
                else VoicePlanStatus.SKIPPED
            )
            return status, context.skip_reason, audit, consent_json, {}, None
        proof = context.proof
        if proof is None:
            return (
                VoicePlanStatus.SKIPPED,
                VoiceSkipReason.MISSING_CONSENT_PROOF,
                audit,
                consent_json,
                {},
                None,
            )
        consent_json = proof.to_audit()
        phone = normalize_phone(proof.permitted_phone)
        if phone is None:
            return (
                VoicePlanStatus.SKIPPED,
                VoiceSkipReason.MISSING_BUSINESS_PHONE,
                audit,
                consent_json,
                {},
                None,
            )

        email = context.contact.email if context.contact is not None else None
        suppression = suppression_status(
            db,
            email=email,
            domain=domain_from_email(email),
            phone=phone,
            organization_id=organization.id,
        )
        audit["suppression_decision"] = suppression.reason
        if not suppression.allowed:
            if suppression.reason == "suppression_check_unavailable":
                return (
                    VoicePlanStatus.BLOCKED,
                    VoiceSkipReason.SUPPRESSION_CHECK_UNAVAILABLE,
                    audit,
                    consent_json,
                    {},
                    None,
                )
            if suppression.reason == "target_unidentified":
                return (
                    VoicePlanStatus.BLOCKED,
                    VoiceSkipReason.TARGET_UNIDENTIFIED,
                    audit,
                    consent_json,
                    {},
                    None,
                )
            return (
                VoicePlanStatus.SUPPRESSED,
                VoiceSkipReason.SUPPRESSED,
                audit,
                consent_json,
                {},
                None,
            )

        outbound = self._guard.evaluate(
            db,
            action=OutboundAction.PHONE_DIAL,
            email=email,
            domain=domain_from_email(email),
            phone=phone,
            organization_id=organization.id,
            consent_to_call=True,
        )
        audit["outbound_decision"] = outbound.reason
        audit["live_call_allowed"] = outbound.allowed

        facts = self._stored_facts(db, organization=organization, contact=context.contact)
        if extra_facts:
            if contains_suspected_phi(*extra_facts.values()):
                return (
                    VoicePlanStatus.BLOCKED,
                    VoiceSkipReason.SUSPECTED_PHI,
                    {**audit, "phi_detected": True},
                    consent_json,
                    {},
                    None,
                )
            facts.update(sanitize_stored_facts(dict(extra_facts)))
        if context.contact is not None:
            audit["contact_id"] = str(context.contact.id)

        request = VoiceQualificationRequest(
            lead_id=lead.id,
            organization_id=organization.id,
            idempotency_key=idempotency_key,
            request_key=context.request_key,
            consent=proof,
            organization_name=organization.name,
            contact_id=context.contact.id if context.contact is not None else None,
            stored_facts=facts,
        )
        if getattr(self._provider, "live", False):
            status, reason, audit, provider_result = self._call_live_boundary(
                db, request, audit, phone, organization.id
            )
        else:
            status, reason, audit, provider_result = self._call_stub(request, audit)
        planned_facts = provider_result.facts if provider_result is not None else facts
        return status, reason, audit, consent_json, planned_facts, provider_result

    def _call_stub(
        self,
        request: VoiceQualificationRequest,
        audit: dict[str, object],
    ) -> tuple[
        VoicePlanStatus,
        VoiceSkipReason | None,
        dict[str, object],
        VoiceQualificationResult | None,
    ]:
        try:
            parsed = parse_voice_qualification_result(
                self._provider.plan_qualification(request),
                allowed_facts=request.stored_facts,
            )
        except MalformedVoicePlanOutput:
            return (
                VoicePlanStatus.SKIPPED,
                VoiceSkipReason.MALFORMED_PROVIDER_OUTPUT,
                audit,
                None,
            )
        except RetryableVoiceQualificationError:
            return (
                VoicePlanStatus.SKIPPED,
                VoiceSkipReason.PROVIDER_RETRYABLE_ERROR,
                audit,
                None,
            )
        except VoiceQualificationError:
            return (
                VoicePlanStatus.SKIPPED,
                VoiceSkipReason.PROVIDER_NON_RETRYABLE_ERROR,
                audit,
                None,
            )
        return self._accept_or_reject(parsed, audit)

    def _call_live_boundary(
        self,
        db: Session,
        request: VoiceQualificationRequest,
        audit: dict[str, object],
        phone: str,
        organization_id: UUID,
    ) -> tuple[
        VoicePlanStatus,
        VoiceSkipReason | None,
        dict[str, object],
        VoiceQualificationResult | None,
    ]:
        try:
            self._guard.require_allowed(
                db,
                action=OutboundAction.PHONE_DIAL,
                phone=phone,
                organization_id=organization_id,
                consent_to_call=True,
            )
            parsed = parse_voice_qualification_result(
                self._provider.plan_qualification(request),
                allowed_facts=request.stored_facts,
            )
        except OutboundBlockedError as exc:
            return VoicePlanStatus.BLOCKED, _reason_from_outbound(str(exc)), audit, None
        except LiveVoiceDisabledError:
            return VoicePlanStatus.BLOCKED, VoiceSkipReason.VOICE_LIVE_DISABLED, audit, None
        except LiveVoiceNotImplementedError:
            return (
                VoicePlanStatus.BLOCKED,
                VoiceSkipReason.LIVE_VOICE_NOT_IMPLEMENTED,
                audit,
                None,
            )
        except MalformedVoicePlanOutput:
            return (
                VoicePlanStatus.SKIPPED,
                VoiceSkipReason.MALFORMED_PROVIDER_OUTPUT,
                audit,
                None,
            )
        except RetryableVoiceQualificationError:
            return (
                VoicePlanStatus.SKIPPED,
                VoiceSkipReason.PROVIDER_RETRYABLE_ERROR,
                audit,
                None,
            )
        except VoiceQualificationError:
            return (
                VoicePlanStatus.SKIPPED,
                VoiceSkipReason.PROVIDER_NON_RETRYABLE_ERROR,
                audit,
                None,
            )
        return self._accept_or_reject(parsed, audit)

    def _accept_or_reject(
        self,
        parsed: VoiceQualificationResult,
        audit: dict[str, object],
    ) -> tuple[
        VoicePlanStatus,
        VoiceSkipReason | None,
        dict[str, object],
        VoiceQualificationResult | None,
    ]:
        audit["provider_name"] = parsed.provider_name
        if parsed.call_placed or parsed.live_call_attempted or not parsed.dry_run:
            return (
                VoicePlanStatus.BLOCKED,
                VoiceSkipReason.LIVE_CALL_REJECTED,
                audit,
                parsed,
            )
        if not parsed.accepted:
            return (
                VoicePlanStatus.SKIPPED,
                VoiceSkipReason.PROVIDER_NOT_ACCEPTED,
                audit,
                parsed,
            )
        return VoicePlanStatus.PLANNED, None, audit, parsed

    def _resolve_context(self, db: Session, spec: _LeadPlanSpec) -> _ResolvedContext:
        if spec.operator_request:
            return self._operator_context(db, spec)
        if spec.meeting_id is not None or spec.booking_plan_id is not None:
            return self._meeting_permission_context(db, spec)
        return self._inbound_reply_context(db, spec)

    def _operator_context(self, db: Session, spec: _LeadPlanSpec) -> _ResolvedContext:
        contact = self._best_contact(db, spec.lead.organization_id)
        input_consent = spec.consent
        phone = None
        if input_consent is not None:
            phone = normalize_phone(input_consent.permitted_phone)
        if phone is None and contact is not None:
            phone = normalize_phone(contact.phone)
        consented_at = input_consent.consented_at if input_consent is not None else None
        channel = (
            input_consent.channel if input_consent is not None else VoiceConsentChannel.OPERATOR
        )
        evidence_id = (
            input_consent.evidence_reference_id if input_consent is not None else spec.request_key
        )
        request_key = clean_optional_text(spec.request_key) or DEFAULT_OPERATOR_REQUEST_KEY
        if contains_suspected_phi(
            input_consent.evidence_reference_id if input_consent is not None else None,
            *(spec.extra_facts.values() if spec.extra_facts else ()),
        ):
            return _ResolvedContext(
                source=VoiceConsentSource.OPERATOR_REQUEST,
                request_key=request_key,
                contact=contact,
                phi_detected=True,
            )
        if consented_at is None or channel is None or phone is None:
            return _ResolvedContext(
                source=VoiceConsentSource.OPERATOR_REQUEST,
                request_key=request_key,
                contact=contact,
                skip_reason=VoiceSkipReason.MISSING_CONSENT_PROOF,
            )
        proof = VoiceConsentProof(
            source=VoiceConsentSource.OPERATOR_REQUEST,
            channel=channel,
            consented_at=consented_at,
            permitted_phone=phone,
            evidence_reference_id=clean_optional_text(evidence_id),
        )
        return _ResolvedContext(
            source=VoiceConsentSource.OPERATOR_REQUEST,
            request_key=request_key,
            contact=contact,
            proof=proof,
        )

    def _meeting_permission_context(self, db: Session, spec: _LeadPlanSpec) -> _ResolvedContext:
        meeting = db.get(Meeting, spec.meeting_id) if spec.meeting_id is not None else None
        if spec.meeting_id is not None and meeting is None:
            raise VoiceQualificationServiceError(f"Meeting not found: {spec.meeting_id}")
        if meeting is not None and meeting.lead_id != spec.lead.id:
            raise VoiceQualificationServiceError("Meeting does not belong to the requested lead")
        booking = (
            db.get(BookingPlan, spec.booking_plan_id) if spec.booking_plan_id is not None else None
        )
        if spec.booking_plan_id is not None and booking is None:
            raise VoiceQualificationServiceError(f"Booking plan not found: {spec.booking_plan_id}")
        if booking is not None and booking.lead_id != spec.lead.id:
            raise VoiceQualificationServiceError(
                "Booking plan does not belong to the requested lead"
            )
        if booking is not None and booking.status != BookingPlanStatus.PLANNED.value:
            return _ResolvedContext(
                source=VoiceConsentSource.MEETING_PERMISSION,
                request_key=str(booking.id),
                booking_plan=booking,
                skip_reason=VoiceSkipReason.INELIGIBLE_CONSENT_CONTEXT,
            )
        contact = self._best_contact(db, spec.lead.organization_id)
        input_consent = spec.consent
        phone = None
        if input_consent is not None:
            phone = normalize_phone(input_consent.permitted_phone)
        if phone is None and contact is not None:
            phone = normalize_phone(contact.phone)
        consented_at = input_consent.consented_at if input_consent is not None else None
        if consented_at is None and meeting is not None:
            consented_at = parse_consent_timestamp(meeting.created_at) or meeting.starts_at
        if consented_at is None and booking is not None:
            consented_at = parse_consent_timestamp(booking.created_at)
        evidence_id = None
        if input_consent is not None:
            evidence_id = input_consent.evidence_reference_id
        if evidence_id is None and meeting is not None:
            evidence_id = str(meeting.id)
        if evidence_id is None and booking is not None:
            evidence_id = str(booking.id)
        request_key = evidence_id or "missing"
        if contains_suspected_phi(
            evidence_id,
            *(spec.extra_facts.values() if spec.extra_facts else ()),
        ):
            return _ResolvedContext(
                source=VoiceConsentSource.MEETING_PERMISSION,
                request_key=request_key,
                contact=contact,
                meeting=meeting,
                booking_plan=booking,
                phi_detected=True,
            )
        if consented_at is None or phone is None:
            return _ResolvedContext(
                source=VoiceConsentSource.MEETING_PERMISSION,
                request_key=request_key,
                contact=contact,
                meeting=meeting,
                booking_plan=booking,
                skip_reason=VoiceSkipReason.MISSING_CONSENT_PROOF,
            )
        channel = VoiceConsentChannel.BOOKING
        if input_consent is not None and input_consent.channel is not None:
            channel = input_consent.channel
        proof = VoiceConsentProof(
            source=VoiceConsentSource.MEETING_PERMISSION,
            channel=channel,
            consented_at=consented_at,
            permitted_phone=phone,
            evidence_reference_id=evidence_id,
        )
        return _ResolvedContext(
            source=VoiceConsentSource.MEETING_PERMISSION,
            request_key=request_key,
            contact=contact,
            meeting=meeting,
            booking_plan=booking,
            proof=proof,
        )

    def _inbound_reply_context(self, db: Session, spec: _LeadPlanSpec) -> _ResolvedContext:
        message = self._resolve_message(db, spec)
        classification = self._classification_for_message(db, spec.lead.id, message)
        contact = self._contact_for_message(db, spec.lead.organization_id, message)
        if message is None:
            return _ResolvedContext(
                source=VoiceConsentSource.INBOUND_REPLY,
                request_key="missing",
                contact=contact,
                skip_reason=VoiceSkipReason.MISSING_CONSENT_PROOF,
            )
        request_key = str(message.id)
        if contains_suspected_phi(message.subject, message.body):
            return _ResolvedContext(
                source=VoiceConsentSource.INBOUND_REPLY,
                request_key=request_key,
                contact=contact,
                message=message,
                classification=classification,
                phi_detected=True,
            )
        if not message_requests_call(message.body) and not message_requests_call(message.subject):
            return _ResolvedContext(
                source=VoiceConsentSource.INBOUND_REPLY,
                request_key=request_key,
                contact=contact,
                message=message,
                classification=classification,
                skip_reason=VoiceSkipReason.INELIGIBLE_CONSENT_CONTEXT,
            )
        phone = normalize_phone(contact.phone if contact is not None else None)
        if spec.consent is not None:
            phone = normalize_phone(spec.consent.permitted_phone) or phone
        if phone is None:
            return _ResolvedContext(
                source=VoiceConsentSource.INBOUND_REPLY,
                request_key=request_key,
                contact=contact,
                message=message,
                classification=classification,
                skip_reason=VoiceSkipReason.MISSING_BUSINESS_PHONE,
            )
        consented_at = parse_consent_timestamp(message.created_at) or datetime.now(tz=UTC)
        proof = VoiceConsentProof(
            source=VoiceConsentSource.INBOUND_REPLY,
            channel=VoiceConsentChannel.EMAIL,
            consented_at=consented_at,
            permitted_phone=phone,
            evidence_reference_id=str(message.id),
        )
        return _ResolvedContext(
            source=VoiceConsentSource.INBOUND_REPLY,
            request_key=request_key,
            contact=contact,
            message=message,
            classification=classification,
            proof=proof,
        )

    def _resolve_message(self, db: Session, spec: _LeadPlanSpec) -> OutreachMessage | None:
        if spec.message_id is not None:
            message = db.get(OutreachMessage, spec.message_id)
            if message is None:
                raise VoiceQualificationServiceError(
                    f"Outreach message not found: {spec.message_id}"
                )
            if message.lead_id != spec.lead.id:
                raise VoiceQualificationServiceError(
                    "Outreach message does not belong to the requested lead"
                )
            return message
        inbound = list(
            db.scalars(
                select(OutreachMessage)
                .where(
                    OutreachMessage.lead_id == spec.lead.id,
                    OutreachMessage.direction == MessageDirection.INBOUND.value,
                )
                .order_by(OutreachMessage.created_at.desc(), OutreachMessage.id.desc())
            ).all()
        )
        for message in inbound:
            if message_requests_call(message.body) or message_requests_call(message.subject):
                return message
        return inbound[0] if inbound else None

    def _classification_for_message(
        self,
        db: Session,
        lead_id: UUID,
        message: OutreachMessage | None,
    ) -> ReplyClassification | None:
        if message is None:
            return None
        return db.scalar(
            select(ReplyClassification).where(
                ReplyClassification.lead_id == lead_id,
                ReplyClassification.outreach_message_id == message.id,
            )
        )

    def _contact_for_message(
        self,
        db: Session,
        organization_id: UUID,
        message: OutreachMessage | None,
    ) -> Contact | None:
        if message is not None and message.contact_id is not None:
            contact = db.get(Contact, message.contact_id)
            if contact is not None:
                return contact
        return self._best_contact(db, organization_id)

    def _best_contact(self, db: Session, organization_id: UUID) -> Contact | None:
        contacts = list(
            db.scalars(select(Contact).where(Contact.organization_id == organization_id)).all()
        )
        with_phone = [row for row in contacts if normalize_phone(row.phone)]
        pool = with_phone or contacts
        if not pool:
            return None
        pool.sort(
            key=lambda row: (
                row.role_rank is None,
                row.role_rank if row.role_rank is not None else 0,
                row.created_at,
            )
        )
        return pool[0]

    def _stored_facts(
        self,
        db: Session,
        *,
        organization: Organization,
        contact: Contact | None,
    ) -> dict[str, str]:
        raw: dict[str, object] = {}
        if organization.specialty:
            raw["specialty"] = organization.specialty
        if contact is not None and contact.title:
            raw["decision_maker_status"] = contact.title
        evidence_rows = list(
            db.scalars(
                select(SourceEvidence).where(SourceEvidence.organization_id == organization.id)
            ).all()
        )
        for row in evidence_rows:
            if row.claim_type == WebsiteFactType.PROVIDER_COUNT.value and row.extracted_value:
                raw.setdefault("provider_count", row.extracted_value)
            if row.claim_type == WebsiteFactType.BILLING_SIGNAL.value and row.extracted_value:
                raw.setdefault("billing_setup", row.extracted_value)
        return sanitize_stored_facts(raw)

    def _eligible_call_request_messages(
        self,
        db: Session,
        *,
        limit: int,
        state: str | None,
        city: str | None,
    ) -> tuple[OutreachMessage, ...]:
        planned = select(VoiceQualificationPlan.outreach_message_id).where(
            VoiceQualificationPlan.status == VoicePlanStatus.PLANNED.value,
            VoiceQualificationPlan.outreach_message_id.is_not(None),
        )
        query = (
            select(OutreachMessage)
            .join(Lead, Lead.id == OutreachMessage.lead_id)
            .join(Organization, Organization.id == Lead.organization_id)
            .where(
                OutreachMessage.direction == MessageDirection.INBOUND.value,
                OutreachMessage.id.not_in(planned),
            )
            .order_by(OutreachMessage.created_at.asc(), OutreachMessage.id.asc())
        )
        if state:
            query = query.where(Organization.state == state.strip().upper())
        if city:
            query = query.where(Organization.city == city.strip().upper())
        candidates = list(db.scalars(query.limit(min(limit * 10, BATCH_MAX))).all())
        selected: list[OutreachMessage] = []
        for message in candidates:
            if message_requests_call(message.body) or message_requests_call(message.subject):
                selected.append(message)
            if len(selected) >= limit:
                break
        return tuple(selected)

    def _finalize_run(
        self,
        db: Session,
        run: VoiceQualificationRun,
        items: list[VoiceItemResult],
        *,
        halt_before: str,
    ) -> None:
        planned = skipped = suppressed = blocked = reused = 0
        for item in items:
            if item.reused:
                reused += 1
            match item.status:
                case VoicePlanStatus.PLANNED:
                    planned += 1
                case VoicePlanStatus.SKIPPED:
                    skipped += 1
                case VoicePlanStatus.SUPPRESSED:
                    suppressed += 1
                case VoicePlanStatus.BLOCKED:
                    blocked += 1
                case _:
                    unreachable: Never = item.status
                    raise RuntimeError(f"unhandled voice status: {unreachable}")
        run.planned_count = planned
        run.skipped_count = skipped
        run.suppressed_count = suppressed
        run.blocked_count = blocked
        run.reused_count = reused
        run.status = VoiceQualificationRunStatus.COMPLETED.value
        run.finished_at = datetime.now(tz=UTC)
        halt_after = _halt_value(read_operator_halt(db))
        self._record_activity(
            db,
            lead_id=None,
            action="voice_qualification_completed",
            details={
                "voice_qualification_run_id": str(run.id),
                "planned": planned,
                "skipped": skipped,
                "suppressed": suppressed,
                "blocked": blocked,
                "reused": reused,
                "dry_run": True,
                "outbound_attempted": False,
                "live_call_attempted": False,
                "call_placed": False,
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
        db.add(Activity(lead_id=lead_id, actor=VOICE_PLAN_ACTOR, action=action, details=details))


@dataclass(frozen=True)
class _ResolvedContext:
    source: VoiceConsentSource
    request_key: str
    contact: Contact | None = None
    message: OutreachMessage | None = None
    classification: ReplyClassification | None = None
    meeting: Meeting | None = None
    booking_plan: BookingPlan | None = None
    proof: VoiceConsentProof | None = None
    skip_reason: VoiceSkipReason | None = None
    phi_detected: bool = False


def _halt_value(status: HaltStatus) -> str:
    return status.value


def _reason_from_outbound(reason: str) -> VoiceSkipReason:
    mapping = {
        "global_outbound_disabled": VoiceSkipReason.GLOBAL_OUTBOUND_DISABLED,
        "operator_global_halt": VoiceSkipReason.OPERATOR_GLOBAL_HALT,
        "operator_halt_unavailable": VoiceSkipReason.OPERATOR_HALT_UNAVAILABLE,
        "suppressed": VoiceSkipReason.SUPPRESSED,
        "suppression_check_unavailable": VoiceSkipReason.SUPPRESSION_CHECK_UNAVAILABLE,
        "target_unidentified": VoiceSkipReason.TARGET_UNIDENTIFIED,
        "voice_consent_required": VoiceSkipReason.MISSING_CONSENT_PROOF,
    }
    return mapping.get(reason, VoiceSkipReason.GLOBAL_OUTBOUND_DISABLED)


def _activity_action(status: VoicePlanStatus) -> str:
    match status:
        case VoicePlanStatus.PLANNED:
            return "voice_qualification_planned"
        case VoicePlanStatus.SKIPPED:
            return "voice_qualification_skipped"
        case VoicePlanStatus.SUPPRESSED:
            return "voice_qualification_suppressed"
        case VoicePlanStatus.BLOCKED:
            return "voice_qualification_blocked"
        case _:
            unreachable: Never = status
            raise RuntimeError(f"unhandled voice status: {unreachable}")
