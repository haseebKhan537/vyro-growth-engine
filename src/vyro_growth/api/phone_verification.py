"""Human phone-verification task JSON surface.

Phase 70 lists sanitized contact_discovery_call tasks and records human-entered
outcomes. It never places calls, autodials, uses AI voice, or routes through
VoiceProvider.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.phone_verification import (
    HTTP_ROUTE,
    PhoneVerificationError,
    PhoneVerificationOutcomeInput,
    PhoneVerificationQueueResult,
    PhoneVerificationService,
    PhoneVerificationTaskView,
)


class PhoneVerificationTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    organization_id: UUID
    lead_id: UUID | None = None
    enrichment_run_id: UUID | None = None
    contact_id: UUID | None = None
    status: str
    queued_reason: str
    source: str
    reused: bool = False
    dry_run: bool = True
    no_execution: bool = True
    executed: bool = False
    execution_attempted: bool = False
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    voice_provider_used: bool = False
    autodial_attempted: bool = False
    suppression_created: bool = False
    contact_fact_created: bool = False
    has_name: bool = False
    has_title: bool = False
    has_phone: bool = False
    has_email: bool = False
    role_category: str | None = None
    operator_label: str | None = None
    operator_notes: str | None = None
    queued_at: datetime
    completed_at: datetime | None = None


class PhoneVerificationQueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    queued_count: int = 0
    decided_count: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    suppression_created_count: int = 0
    contact_fact_created_count: int = 0
    executed_count: int = 0
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    voice_provider_used: bool = False
    autodial_attempted: bool = False
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    outbound_enabled: bool = False
    http_route: str = HTTP_ROUTE
    items: list[PhoneVerificationTaskResponse] = Field(default_factory=list)


class RecordPhoneVerificationOutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str
    operator: str | None = None
    notes: str | None = None
    full_name: str | None = None
    title: str | None = None
    phone: str | None = None
    email: str | None = None
    role_category: str | None = None


def task_view_to_response(item: PhoneVerificationTaskView) -> PhoneVerificationTaskResponse:
    return PhoneVerificationTaskResponse(
        task_id=item.task_id,
        organization_id=item.organization_id,
        lead_id=item.lead_id,
        enrichment_run_id=item.enrichment_run_id,
        contact_id=item.contact_id,
        status=item.status,
        queued_reason=item.queued_reason,
        source=item.source,
        reused=item.reused,
        dry_run=item.dry_run,
        no_execution=item.no_execution,
        executed=False,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        voice_provider_used=False,
        autodial_attempted=False,
        suppression_created=item.suppression_created,
        contact_fact_created=item.contact_fact_created,
        has_name=item.has_name,
        has_title=item.has_title,
        has_phone=item.has_phone,
        has_email=item.has_email,
        role_category=item.role_category,
        operator_label=item.operator_label,
        operator_notes=item.operator_notes,
        queued_at=item.queued_at,
        completed_at=item.completed_at,
    )


def queue_to_response(result: PhoneVerificationQueueResult) -> PhoneVerificationQueueResponse:
    return PhoneVerificationQueueResponse(
        generated_at=result.generated_at,
        queued_count=result.queued_count,
        decided_count=result.decided_count,
        by_status=result.by_status,
        suppression_created_count=result.suppression_created_count,
        contact_fact_created_count=result.contact_fact_created_count,
        executed_count=0,
        outbound_attempted=False,
        live_call_attempted=False,
        voice_provider_used=False,
        autodial_attempted=False,
        operator_halt_status=result.operator_halt_status,
        operator_halt_before=result.operator_halt_before,
        operator_halt_after=result.operator_halt_after,
        outbound_enabled=result.outbound_enabled,
        items=[task_view_to_response(item) for item in result.items],
    )


def build_phone_verification_queue_response(
    db: Session,
    settings: Settings,
    *,
    status: str | None = None,
    include_completed: bool = False,
    service: PhoneVerificationService | None = None,
) -> PhoneVerificationQueueResponse:
    queue = service or PhoneVerificationService(settings)
    return queue_to_response(
        queue.list_tasks(
            db,
            settings,
            status=status,
            include_completed=include_completed,
        )
    )


def build_phone_verification_outcome_response(
    db: Session,
    task_id: UUID,
    request: RecordPhoneVerificationOutcomeRequest,
    *,
    source: str = "internal_api",
    service: PhoneVerificationService | None = None,
) -> PhoneVerificationTaskResponse:
    queue = service or PhoneVerificationService()
    result = queue.record_outcome(
        db,
        task_id,
        PhoneVerificationOutcomeInput(
            outcome=request.outcome,
            operator=request.operator,
            notes=request.notes,
            full_name=request.full_name,
            title=request.title,
            phone=request.phone,
            email=request.email,
            role_category=request.role_category,
        ),
        source=source,
    )
    return task_view_to_response(result)


def phone_verification_http_error(error: PhoneVerificationError) -> tuple[int, str]:
    if error.code in {"task_not_found", "organization_not_found"}:
        return (404, error.message)
    return (400, error.message)
