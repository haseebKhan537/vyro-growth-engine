"""Human-in-the-loop phone verification queue for NO_CONTACT_FOUND.

Phase 70 creates sanitized review/task records and stores operator-entered
outcomes. It never places calls, autodials, uses AI voice, or routes through
VoiceProvider or any phone API.
"""

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
    CONTACT_DISCOVERY_CALL_TERMINAL_STATUSES,
    ContactDiscoveryCallStatus,
    ContactFactType,
    ContactRoleCategory,
    ContactVerificationStatus,
    EnrichmentRunStatus,
)
from vyro_growth.models import (
    Activity,
    Contact,
    ContactDiscoveryCall,
    EnrichmentRun,
    Lead,
    Organization,
    SourceEvidence,
    Suppression,
)
from vyro_growth.observability import sanitize_mapping
from vyro_growth.providers.decision_makers import (
    DECISION_MAKER_SOURCE,
    EMAIL_MAX_LENGTH,
    FULL_NAME_MAX_LENGTH,
    NO_CONTACT_FOUND,
    PHONE_MAX_LENGTH,
    PROVIDER_MAX_LENGTH,
    SOURCE_URL_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    ContactProvenance,
    DecisionMakerCandidate,
    OrganizationContactContext,
    classify_candidate,
    clean_optional_text,
    clip_text,
    contact_dedupe_key,
)
from vyro_growth.services.operator_halt import read_operator_halt
from vyro_growth.services.outbound_guard import (
    OutboundAction,
    OutboundGuard,
    normalize_email,
    normalize_phone,
    suppression_status,
)
from vyro_growth.services.review_queue import MAX_NOTES_LENGTH, sanitize_operator_text

logger = structlog.get_logger(__name__)

PHONE_VERIFICATION_ACTOR = "phone_verification"
PHONE_VERIFICATION_SOURCE = "phone_verification"
QUEUED_REASON_NO_CONTACT_FOUND = NO_CONTACT_FOUND
CLI_QUEUE_COMMAND = "queue-phone-verification"
CLI_LIST_COMMAND = "list-phone-verification"
CLI_RECORD_COMMAND = "record-phone-verification"
HTTP_ROUTE = "/internal/phone-verification/tasks"
BATCH_MAX = 200
DO_NOT_CONTACT_REASON = "do_not_contact"


class PhoneVerificationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PhoneVerificationTaskView:
    task_id: UUID
    organization_id: UUID
    lead_id: UUID | None
    enrichment_run_id: UUID | None
    contact_id: UUID | None
    status: str
    queued_reason: str
    source: str
    reused: bool
    dry_run: bool
    no_execution: bool
    executed: bool
    execution_attempted: bool
    outbound_attempted: bool
    live_call_attempted: bool
    voice_provider_used: bool
    autodial_attempted: bool
    suppression_created: bool
    contact_fact_created: bool
    has_name: bool
    has_title: bool
    has_phone: bool
    has_email: bool
    role_category: str | None
    operator_label: str | None
    operator_notes: str | None
    queued_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class PhoneVerificationQueueResult:
    generated_at: datetime
    queued_count: int
    decided_count: int
    by_status: dict[str, int]
    suppression_created_count: int
    contact_fact_created_count: int
    executed_count: int
    outbound_attempted: bool
    live_call_attempted: bool
    voice_provider_used: bool
    autodial_attempted: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    outbound_enabled: bool
    items: tuple[PhoneVerificationTaskView, ...]


@dataclass(frozen=True)
class PhoneVerificationOutcomeInput:
    outcome: str
    operator: str | None = None
    notes: str | None = None
    full_name: str | None = None
    title: str | None = None
    phone: str | None = None
    email: str | None = None
    role_category: str | None = None


class PhoneVerificationService:
    """Queue human phone-verification tasks and record operator outcomes."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def queue_for_organization(
        self,
        db: Session,
        organization_id: UUID,
        *,
        enrichment_run_id: UUID | None = None,
        source: str = "contact_enrichment",
        commit: bool = True,
    ) -> PhoneVerificationTaskView:
        organization = db.get(Organization, organization_id)
        if organization is None:
            raise PhoneVerificationError("organization_not_found", "Organization was not found")
        halt_before = read_operator_halt(db)
        view = self._queue_one(
            db,
            organization,
            enrichment_run_id=enrichment_run_id,
            source=source,
        )
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("phone verification must not change operator halt status")
        if commit:
            db.commit()
        return view

    def queue_missing_contacts(
        self,
        db: Session,
        *,
        organization_id: UUID | None = None,
        limit: int = 50,
        state: str | None = None,
        city: str | None = None,
        source: str = "cli",
        commit: bool = True,
    ) -> tuple[PhoneVerificationTaskView, ...]:
        halt_before = read_operator_halt(db)
        organizations: tuple[Organization, ...]
        if organization_id is not None:
            organization = db.get(Organization, organization_id)
            if organization is None:
                raise PhoneVerificationError(
                    "organization_not_found",
                    "Organization was not found",
                )
            organizations = (organization,)
        else:
            organizations = _organizations_missing_contacts(
                db,
                limit=limit,
                state=state,
                city=city,
            )
        views = tuple(
            self._queue_one(db, organization, source=source) for organization in organizations
        )
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("phone verification must not change operator halt status")
        if commit:
            db.commit()
        return views

    def list_tasks(
        self,
        db: Session,
        settings: Settings | None = None,
        *,
        status: str | None = None,
        include_completed: bool = False,
    ) -> PhoneVerificationQueueResult:
        active_settings = settings or self._settings
        halt_before = read_operator_halt(db)
        selected = _parse_optional_status(status)
        rows = db.scalars(
            select(ContactDiscoveryCall).order_by(
                ContactDiscoveryCall.queued_at.asc(),
                ContactDiscoveryCall.created_at.asc(),
            )
        ).all()
        views = tuple(_task_view(row, reused=False) for row in rows)
        if selected is not None:
            visible = tuple(item for item in views if item.status == selected.value)
        elif include_completed:
            visible = views
        else:
            visible = tuple(
                item for item in views if item.status == ContactDiscoveryCallStatus.QUEUED.value
            )
        queued = [item for item in views if item.status == ContactDiscoveryCallStatus.QUEUED.value]
        decided = [
            item for item in views if item.status != ContactDiscoveryCallStatus.QUEUED.value
        ]
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("phone verification must not change operator halt status")
        result = PhoneVerificationQueueResult(
            generated_at=datetime.now(tz=UTC),
            queued_count=len(queued),
            decided_count=len(decided),
            by_status=_count_by_status(views),
            suppression_created_count=sum(1 for item in views if item.suppression_created),
            contact_fact_created_count=sum(1 for item in views if item.contact_fact_created),
            executed_count=0,
            outbound_attempted=False,
            live_call_attempted=False,
            voice_provider_used=False,
            autodial_attempted=False,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            outbound_enabled=active_settings.outbound_enabled,
            items=visible,
        )
        logger.info(
            "phone_verification_listed",
            queued_count=result.queued_count,
            decided_count=result.decided_count,
            outbound_attempted=False,
            live_call_attempted=False,
            voice_provider_used=False,
        )
        return result

    def record_outcome(
        self,
        db: Session,
        task_id: UUID,
        payload: PhoneVerificationOutcomeInput,
        *,
        source: str = "cli",
        commit: bool = True,
    ) -> PhoneVerificationTaskView:
        halt_before = read_operator_halt(db)
        task = db.get(ContactDiscoveryCall, task_id)
        if task is None:
            raise PhoneVerificationError("task_not_found", "Phone verification task was not found")
        outcome = _parse_recordable_outcome(payload.outcome)
        if (
            task.status != ContactDiscoveryCallStatus.QUEUED.value
            and task.status == outcome.value
        ):
            view = _task_view(task, reused=True)
            halt_after = read_operator_halt(db)
            if halt_after is not halt_before:
                raise RuntimeError("phone verification must not change operator halt status")
            return view
        if task.status != ContactDiscoveryCallStatus.QUEUED.value:
            raise PhoneVerificationError(
                "task_not_queued",
                "Phone verification task is no longer queued",
            )
        organization = db.get(Organization, task.organization_id)
        if organization is None:
            raise PhoneVerificationError("organization_not_found", "Organization was not found")
        _assert_no_live_call(self._settings, db, organization.id, payload.phone)

        operator = sanitize_operator_text(payload.operator) or "operator"
        notes = sanitize_operator_text(
            payload.notes[:MAX_NOTES_LENGTH] if payload.notes else None
        )
        full_name = clean_optional_text(payload.full_name)
        title = clean_optional_text(payload.title)
        phone = clean_optional_text(payload.phone)
        email = normalize_email(payload.email)
        role_category = _parse_optional_role(payload.role_category)
        now = datetime.now(tz=UTC)
        contact: Contact | None = None
        suppression: Suppression | None = None
        contact_fact_created = False
        suppression_created = False

        match outcome:
            case ContactDiscoveryCallStatus.DECISION_MAKER_IDENTIFIED:
                contact = _persist_human_contact(
                    db,
                    organization=organization,
                    task=task,
                    full_name=full_name,
                    title=title,
                    phone=phone,
                    email=email,
                    role_category=role_category,
                    recorded_at=now,
                )
                contact_fact_created = True
            case ContactDiscoveryCallStatus.DO_NOT_CONTACT:
                suppression = _persist_do_not_contact(
                    db,
                    organization=organization,
                    phone=phone,
                    email=email,
                )
                suppression_created = True
            case (
                ContactDiscoveryCallStatus.COMPLETED
                | ContactDiscoveryCallStatus.NO_ANSWER
                | ContactDiscoveryCallStatus.REFUSED
                | ContactDiscoveryCallStatus.WRONG_NUMBER
            ):
                pass
            case ContactDiscoveryCallStatus.QUEUED:
                raise PhoneVerificationError(
                    "invalid_outcome",
                    "Outcome must be a recorded phone-verification result",
                )
            case _:
                _unreachable(outcome)

        _persist_outcome_evidence(
            db,
            organization=organization,
            task=task,
            outcome=outcome,
            contact=contact,
            has_name=full_name is not None,
            has_title=title is not None,
            has_phone=phone is not None,
            has_email=email is not None,
            role_category=role_category,
            recorded_at=now,
        )
        details = _safe_details(
            queued_reason=task.queued_reason,
            has_name=full_name is not None,
            has_title=title is not None,
            has_phone=phone is not None,
            has_email=email is not None,
            role_category=role_category.value if role_category is not None else None,
            source=source,
        )
        task.status = outcome.value
        task.operator_label = operator
        task.operator_notes = notes
        task.source = sanitize_operator_text(source) or "cli"
        task.contact_id = contact.id if contact is not None else task.contact_id
        task.suppression_id = suppression.id if suppression is not None else task.suppression_id
        task.suppression_created = suppression_created or task.suppression_created
        task.contact_fact_created = contact_fact_created or task.contact_fact_created
        task.completed_at = now
        task.executed = False
        task.execution_attempted = False
        task.outbound_attempted = False
        task.live_call_attempted = False
        task.voice_provider_used = False
        task.autodial_attempted = False
        task.details_json = details
        db.add(
            Activity(
                lead_id=task.lead_id,
                actor=PHONE_VERIFICATION_ACTOR,
                action="phone_verification_outcome_recorded",
                details=sanitize_mapping(
                    {
                        "task_id": str(task.id),
                        "organization_id": str(task.organization_id),
                        "outcome": outcome.value,
                        "source": task.source,
                        "suppression_created": task.suppression_created,
                        "contact_fact_created": task.contact_fact_created,
                        "executed": False,
                        "execution_attempted": False,
                        "outbound_attempted": False,
                        "live_call_attempted": False,
                        "voice_provider_used": False,
                        "autodial_attempted": False,
                    }
                ),
            )
        )
        db.flush()
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("phone verification must not change operator halt status")
        logger.info(
            "phone_verification_outcome_recorded",
            task_id=str(task.id),
            organization_id=str(task.organization_id),
            outcome=outcome.value,
            suppression_created=task.suppression_created,
            contact_fact_created=task.contact_fact_created,
            live_call_attempted=False,
            voice_provider_used=False,
            outbound_attempted=False,
        )
        if commit:
            db.commit()
            db.refresh(task)
        return _task_view(task, reused=False)

    def _queue_one(
        self,
        db: Session,
        organization: Organization,
        *,
        enrichment_run_id: UUID | None = None,
        source: str = "contact_enrichment",
    ) -> PhoneVerificationTaskView:
        key = _idempotency_key(organization.id)
        existing = db.scalar(
            select(ContactDiscoveryCall).where(ContactDiscoveryCall.idempotency_key == key)
        )
        if existing is not None:
            return _task_view(existing, reused=True)
        now = datetime.now(tz=UTC)
        lead_id = _latest_lead_id(db, organization.id)
        task = ContactDiscoveryCall(
            organization_id=organization.id,
            lead_id=lead_id,
            enrichment_run_id=enrichment_run_id,
            status=ContactDiscoveryCallStatus.QUEUED.value,
            queued_reason=QUEUED_REASON_NO_CONTACT_FOUND,
            idempotency_key=key,
            source=sanitize_operator_text(source) or "contact_enrichment",
            dry_run=True,
            no_execution=True,
            executed=False,
            execution_attempted=False,
            outbound_attempted=False,
            live_call_attempted=False,
            voice_provider_used=False,
            autodial_attempted=False,
            details_json=_safe_details(
                queued_reason=QUEUED_REASON_NO_CONTACT_FOUND,
                source=source,
            ),
            queued_at=now,
        )
        db.add(task)
        db.flush()
        db.add(
            Activity(
                lead_id=lead_id,
                actor=PHONE_VERIFICATION_ACTOR,
                action="phone_verification_queued",
                details=sanitize_mapping(
                    {
                        "task_id": str(task.id),
                        "organization_id": str(organization.id),
                        "queued_reason": QUEUED_REASON_NO_CONTACT_FOUND,
                        "source": task.source,
                        "executed": False,
                        "outbound_attempted": False,
                        "live_call_attempted": False,
                        "voice_provider_used": False,
                        "autodial_attempted": False,
                    }
                ),
            )
        )
        logger.info(
            "phone_verification_queued",
            task_id=str(task.id),
            organization_id=str(organization.id),
            queued_reason=QUEUED_REASON_NO_CONTACT_FOUND,
            live_call_attempted=False,
            voice_provider_used=False,
            outbound_attempted=False,
        )
        return _task_view(task, reused=False)


def format_phone_verification_queue(
    result: PhoneVerificationQueueResult,
    *,
    as_json: bool = False,
) -> str:
    if as_json:
        import json

        return json.dumps(_queue_payload(result), sort_keys=True, default=str)
    lines = [
        "Phone verification queue: "
        f"queued={result.queued_count} "
        f"decided={result.decided_count} "
        f"shown={len(result.items)} "
        f"executed={result.executed_count} "
        f"outbound_attempted={result.outbound_attempted} "
        f"live_call_attempted={result.live_call_attempted} "
        f"voice_provider_used={result.voice_provider_used} "
        f"operator_halt={result.operator_halt_status}"
    ]
    for item in result.items:
        lines.append(
            "Phone verification task: "
            f"id={item.task_id} "
            f"organization_id={item.organization_id} "
            f"status={item.status} "
            f"queued_reason={item.queued_reason} "
            f"suppression_created={item.suppression_created} "
            f"contact_fact_created={item.contact_fact_created} "
            f"live_call_attempted={item.live_call_attempted}"
        )
    return "\n".join(lines)


def format_phone_verification_task(item: PhoneVerificationTaskView) -> str:
    return (
        "Phone verification task: "
        f"id={item.task_id} "
        f"organization_id={item.organization_id} "
        f"status={item.status} "
        f"queued_reason={item.queued_reason} "
        f"reused={item.reused} "
        f"suppression_created={item.suppression_created} "
        f"contact_fact_created={item.contact_fact_created} "
        f"executed={item.executed} "
        f"outbound_attempted={item.outbound_attempted} "
        f"live_call_attempted={item.live_call_attempted} "
        f"voice_provider_used={item.voice_provider_used}"
    )


def _queue_payload(result: PhoneVerificationQueueResult) -> dict[str, object]:
    return {
        "generated_at": result.generated_at.isoformat(),
        "queued_count": result.queued_count,
        "decided_count": result.decided_count,
        "by_status": result.by_status,
        "suppression_created_count": result.suppression_created_count,
        "contact_fact_created_count": result.contact_fact_created_count,
        "executed_count": result.executed_count,
        "outbound_attempted": result.outbound_attempted,
        "live_call_attempted": result.live_call_attempted,
        "voice_provider_used": result.voice_provider_used,
        "autodial_attempted": result.autodial_attempted,
        "operator_halt_status": result.operator_halt_status,
        "operator_halt_before": result.operator_halt_before,
        "operator_halt_after": result.operator_halt_after,
        "outbound_enabled": result.outbound_enabled,
        "items": [_task_payload(item) for item in result.items],
    }


def _task_payload(item: PhoneVerificationTaskView) -> dict[str, object]:
    return {
        "task_id": str(item.task_id),
        "organization_id": str(item.organization_id),
        "lead_id": str(item.lead_id) if item.lead_id is not None else None,
        "enrichment_run_id": (
            str(item.enrichment_run_id) if item.enrichment_run_id is not None else None
        ),
        "contact_id": str(item.contact_id) if item.contact_id is not None else None,
        "status": item.status,
        "queued_reason": item.queued_reason,
        "source": item.source,
        "reused": item.reused,
        "dry_run": item.dry_run,
        "no_execution": item.no_execution,
        "executed": item.executed,
        "execution_attempted": item.execution_attempted,
        "outbound_attempted": item.outbound_attempted,
        "live_call_attempted": item.live_call_attempted,
        "voice_provider_used": item.voice_provider_used,
        "autodial_attempted": item.autodial_attempted,
        "suppression_created": item.suppression_created,
        "contact_fact_created": item.contact_fact_created,
        "has_name": item.has_name,
        "has_title": item.has_title,
        "has_phone": item.has_phone,
        "has_email": item.has_email,
        "role_category": item.role_category,
        "operator_label": item.operator_label,
        "operator_notes": item.operator_notes,
        "queued_at": item.queued_at.isoformat(),
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }


def _task_view(row: ContactDiscoveryCall, *, reused: bool) -> PhoneVerificationTaskView:
    details = dict(row.details_json or {})
    return PhoneVerificationTaskView(
        task_id=row.id,
        organization_id=row.organization_id,
        lead_id=row.lead_id,
        enrichment_run_id=row.enrichment_run_id,
        contact_id=row.contact_id,
        status=row.status,
        queued_reason=row.queued_reason,
        source=row.source,
        reused=reused,
        dry_run=row.dry_run,
        no_execution=row.no_execution,
        executed=False,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        voice_provider_used=False,
        autodial_attempted=False,
        suppression_created=row.suppression_created,
        contact_fact_created=row.contact_fact_created,
        has_name=bool(details.get("has_name")),
        has_title=bool(details.get("has_title")),
        has_phone=bool(details.get("has_phone")),
        has_email=bool(details.get("has_email")),
        role_category=_safe_role_label(details.get("role_category")),
        operator_label=row.operator_label,
        operator_notes=row.operator_notes,
        queued_at=row.queued_at,
        completed_at=row.completed_at,
    )


def _persist_human_contact(
    db: Session,
    *,
    organization: Organization,
    task: ContactDiscoveryCall,
    full_name: str | None,
    title: str | None,
    phone: str | None,
    email: str | None,
    role_category: ContactRoleCategory | None,
    recorded_at: datetime,
) -> Contact:
    if full_name is None:
        raise PhoneVerificationError(
            "missing_name",
            "decision_maker_identified requires a human-entered full name",
        )
    name = clip_text(full_name, FULL_NAME_MAX_LENGTH)
    title_value = clip_text(title, TITLE_MAX_LENGTH) if title else None
    email_value = clip_text(email, EMAIL_MAX_LENGTH) if email else None
    phone_value = clip_text(phone, PHONE_MAX_LENGTH) if phone else None
    candidate = DecisionMakerCandidate(
        full_name=name,
        source_provider=PHONE_VERIFICATION_SOURCE,
        source_timestamp=recorded_at,
        title=title_value,
        role_category=role_category,
        business_email=email_value,
        business_phone=phone_value,
        confidence=0.5,
        verification_status=ContactVerificationStatus.UNVERIFIED,
        provenance=ContactProvenance(
            source_url="operator:phone_verification",
            evidence_snippet=None,
            metadata={
                "human_entered": True,
                "fabricated": False,
                "task_id": str(task.id),
            },
        ),
        provider_record_id=str(task.id),
    )
    context = OrganizationContactContext(
        organization_id=organization.id,
        name=organization.name,
        npi=organization.npi,
        city=organization.city,
        state=organization.state,
        specialty=organization.specialty,
        website=organization.website,
        website_match_status=organization.website_match_status,
    )
    disposition = classify_candidate(candidate, organization=context)
    classified = disposition.classified
    dedupe = contact_dedupe_key(
        email=email_value,
        source_provider=PHONE_VERIFICATION_SOURCE,
        provider_record_id=str(task.id),
        full_name=name,
        title=title_value,
    )
    if classified is not None:
        stored_role = classified.role_category.value
        stored_rank: int | None = classified.role_rank
        dedupe = classified.dedupe_key
    elif role_category is not None:
        stored_role = role_category.value
        stored_rank = None
    else:
        stored_role = None
        stored_rank = None
    existing = db.scalar(
        select(Contact).where(
            Contact.organization_id == organization.id,
            Contact.dedupe_key == dedupe,
        )
    )
    if existing is None:
        contact = Contact(
            organization_id=organization.id,
            full_name=name,
            title=title_value,
            email=email_value,
            phone=phone_value,
            email_verified=False,
            role_category=stored_role,
            role_rank=stored_rank,
            source_provider=clip_text(PHONE_VERIFICATION_SOURCE, PROVIDER_MAX_LENGTH),
            source_timestamp=recorded_at,
            confidence=0.5,
            verification_status=ContactVerificationStatus.UNVERIFIED.value,
            provenance_json={
                "source_url": "operator:phone_verification",
                "human_entered": True,
                "fabricated": False,
                "task_id": str(task.id),
            },
            dedupe_key=dedupe,
        )
        db.add(contact)
        db.flush()
        return contact
    existing.full_name = name
    if title_value:
        existing.title = title_value
    if email_value:
        existing.email = email_value
    if phone_value:
        existing.phone = phone_value
    existing.source_provider = clip_text(PHONE_VERIFICATION_SOURCE, PROVIDER_MAX_LENGTH)
    existing.source_timestamp = recorded_at
    existing.verification_status = ContactVerificationStatus.UNVERIFIED.value
    existing.provenance_json = {
        "source_url": "operator:phone_verification",
        "human_entered": True,
        "fabricated": False,
        "task_id": str(task.id),
    }
    existing.dedupe_key = dedupe
    if stored_rank is not None and (
        existing.role_rank is None or stored_rank <= existing.role_rank
    ):
        existing.role_category = stored_role
        existing.role_rank = stored_rank
    db.flush()
    return existing


def _persist_do_not_contact(
    db: Session,
    *,
    organization: Organization,
    phone: str | None,
    email: str | None,
) -> Suppression:
    phone_n = normalize_phone(phone)
    email_n = normalize_email(email)
    if phone_n is None and email_n is None:
        existing_org = db.scalar(
            select(Suppression).where(
                Suppression.organization_id == organization.id,
                Suppression.reason == DO_NOT_CONTACT_REASON,
            )
        )
        if existing_org is not None:
            return existing_org
        row = Suppression(
            organization_id=organization.id,
            reason=DO_NOT_CONTACT_REASON,
            permanent=True,
        )
        db.add(row)
        db.flush()
        return row
    if phone_n:
        existing_phone = db.scalar(select(Suppression).where(Suppression.phone == phone_n))
        if existing_phone is not None:
            if existing_phone.organization_id is None:
                existing_phone.organization_id = organization.id
            existing_phone.reason = DO_NOT_CONTACT_REASON
            existing_phone.permanent = True
            db.flush()
            return existing_phone
    if email_n:
        existing_email = db.scalar(select(Suppression).where(Suppression.email == email_n))
        if existing_email is not None:
            if existing_email.organization_id is None:
                existing_email.organization_id = organization.id
            existing_email.reason = DO_NOT_CONTACT_REASON
            existing_email.permanent = True
            db.flush()
            return existing_email
    row = Suppression(
        email=email_n,
        phone=phone_n,
        organization_id=organization.id,
        reason=DO_NOT_CONTACT_REASON,
        permanent=True,
    )
    db.add(row)
    db.flush()
    return row


def _persist_outcome_evidence(
    db: Session,
    *,
    organization: Organization,
    task: ContactDiscoveryCall,
    outcome: ContactDiscoveryCallStatus,
    contact: Contact | None,
    has_name: bool,
    has_title: bool,
    has_phone: bool,
    has_email: bool,
    role_category: ContactRoleCategory | None,
    recorded_at: datetime,
) -> None:
    db.add(
        SourceEvidence(
            organization_id=organization.id,
            enrichment_run_id=task.enrichment_run_id,
            contact_id=contact.id if contact is not None else None,
            source_url=clip_text("operator:phone_verification", SOURCE_URL_MAX_LENGTH),
            claim_type=ContactFactType.PHONE_VERIFICATION.value,
            extracted_value=outcome.value,
            confidence=0.5,
            evidence_snippet=None,
            metadata_json={
                "task_id": str(task.id),
                "outcome": outcome.value,
                "source_provider": PHONE_VERIFICATION_SOURCE,
                "human_entered": True,
                "fabricated": False,
                "has_name": has_name,
                "has_title": has_title,
                "has_phone": has_phone,
                "has_email": has_email,
                "role_category": role_category.value if role_category is not None else None,
                "recorded_at": recorded_at.isoformat(),
                "live_call_attempted": False,
                "voice_provider_used": False,
            },
        )
    )


def _assert_no_live_call(
    settings: Settings,
    db: Session,
    organization_id: UUID,
    phone: str | None,
) -> None:
    if settings.outbound_enabled:
        raise RuntimeError("phone verification must keep OUTBOUND_ENABLED=false")
    guard = OutboundGuard(settings)
    decision = guard.evaluate(
        db,
        action=OutboundAction.PHONE_DIAL,
        phone=phone,
        organization_id=organization_id,
        consent_to_call=False,
    )
    if decision.allowed:
        raise RuntimeError("phone verification must not allow a live phone dial")


def _organizations_missing_contacts(
    db: Session,
    *,
    limit: int,
    state: str | None,
    city: str | None,
) -> tuple[Organization, ...]:
    query = select(Organization).order_by(Organization.created_at.asc())
    if state:
        query = query.where(Organization.state == state.strip().upper())
    if city:
        query = query.where(Organization.city == city.strip().upper())
    organizations = tuple(db.scalars(query.limit(min(max(limit, 1), BATCH_MAX))).all())
    missing: list[Organization] = []
    for organization in organizations:
        if _organization_has_contact(db, organization.id):
            continue
        latest = _latest_decision_maker_run(db, organization.id)
        if latest is None:
            continue
        if latest.status != EnrichmentRunStatus.COMPLETED.value:
            continue
        missing.append(organization)
    return tuple(missing)


def _organization_has_contact(db: Session, organization_id: UUID) -> bool:
    return (
        db.scalar(
            select(Contact.id).where(Contact.organization_id == organization_id).limit(1)
        )
        is not None
    )


def _latest_decision_maker_run(db: Session, organization_id: UUID) -> EnrichmentRun | None:
    return db.scalar(
        select(EnrichmentRun)
        .where(
            EnrichmentRun.organization_id == organization_id,
            EnrichmentRun.source == DECISION_MAKER_SOURCE,
        )
        .order_by(EnrichmentRun.created_at.desc())
        .limit(1)
    )


def _latest_lead_id(db: Session, organization_id: UUID) -> UUID | None:
    lead = db.scalar(
        select(Lead)
        .where(Lead.organization_id == organization_id)
        .order_by(Lead.created_at.asc())
        .limit(1)
    )
    return lead.id if lead is not None else None


def _idempotency_key(organization_id: UUID) -> str:
    return f"contact_discovery_call:{organization_id}"


def _safe_details(
    *,
    queued_reason: str,
    source: str,
    has_name: bool = False,
    has_title: bool = False,
    has_phone: bool = False,
    has_email: bool = False,
    role_category: str | None = None,
) -> dict[str, object]:
    return sanitize_mapping(
        {
            "queued_reason": queued_reason,
            "source": source,
            "has_name": has_name,
            "has_title": has_title,
            "has_phone": has_phone,
            "has_email": has_email,
            "role_category": role_category,
            "human_entered": True,
            "fabricated": False,
            "live_call_attempted": False,
            "voice_provider_used": False,
            "autodial_attempted": False,
            "outbound_attempted": False,
        }
    )


def _parse_optional_status(value: str | None) -> ContactDiscoveryCallStatus | None:
    if value is None or not value.strip():
        return None
    try:
        return ContactDiscoveryCallStatus(value.strip())
    except ValueError as exc:
        raise PhoneVerificationError("invalid_status", "Unknown phone verification status") from exc


def _parse_recordable_outcome(value: str) -> ContactDiscoveryCallStatus:
    try:
        parsed = ContactDiscoveryCallStatus(value.strip())
    except ValueError as exc:
        raise PhoneVerificationError(
            "invalid_outcome",
            "Outcome must be a recorded phone-verification result",
        ) from exc
    if parsed not in CONTACT_DISCOVERY_CALL_TERMINAL_STATUSES:
        raise PhoneVerificationError(
            "invalid_outcome",
            "Outcome must be a recorded phone-verification result",
        )
    return parsed


def _parse_optional_role(value: str | None) -> ContactRoleCategory | None:
    cleaned = clean_optional_text(value)
    if cleaned is None:
        return None
    try:
        return ContactRoleCategory(cleaned)
    except ValueError as exc:
        raise PhoneVerificationError("invalid_role_category", "Unknown role category") from exc


def _safe_role_label(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return ContactRoleCategory(value.strip()).value
    except ValueError:
        return None


def _count_by_status(items: tuple[PhoneVerificationTaskView, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def _unreachable(value: object) -> Never:
    raise RuntimeError(f"unhandled phone verification outcome: {value!r}")


def suppression_blocks_phone(
    db: Session,
    *,
    phone: str | None,
    organization_id: UUID | None = None,
) -> bool:
    decision = suppression_status(
        db,
        phone=phone,
        organization_id=organization_id,
    )
    return not decision.allowed
