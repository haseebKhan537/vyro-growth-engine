from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.approval_packets import (
    ApprovalPacketDecisionView,
    ApprovalPacketError,
    ApprovalPacketFilters,
    ApprovalPacketRunResult,
    ApprovalPacketService,
    ApprovalPacketView,
)


class ApprovalPacketRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_type: str | None = None
    execution_plan_id: UUID | None = None


class ApprovalPacketDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    decision: str
    reviewer: str
    source: str
    reviewer_notes: str | None = None
    decided_at: datetime


class ApprovalPacketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_execution_plan_id: UUID
    source_execution_plan_run_id: UUID
    source_artifact_type: str
    source_artifact_id: UUID
    plan_family: str
    proposed_action: str
    preflight_status: str
    dry_run_only: bool = True
    no_execution: bool = True
    executed: bool = False
    execution_attempted: bool = False
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    recommendation_applied: bool = False
    spend_attempted: bool = False
    campaign_launched: bool = False
    pages_published: bool = False
    ads_launched: bool = False
    owner_approval_required: bool = True
    owner_approved: bool = False
    generated_at: datetime
    idempotency_key: str
    preflight_checklist: list[dict[str, object]] = Field(default_factory=list)
    missing_prerequisites: list[dict[str, object]] = Field(default_factory=list)
    findings: list[dict[str, object]] = Field(default_factory=list)
    required_owner_decisions: list[str] = Field(default_factory=list)
    decision: ApprovalPacketDecisionResponse | None = None


class ApprovalPacketRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_packet_run_id: UUID | None = None
    status: str
    model_version: str | None = None
    snapshot_fingerprint: str | None = None
    packet_count: int = 0
    reused_existing: bool = False
    reused_count: int = 0
    missing_plan_count: int = 0
    executed_count: int = 0
    dry_run_only: bool = True
    no_execution: bool = True
    execution_attempted: bool = False
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    recommendation_applied: bool = False
    spend_attempted: bool = False
    campaign_launched: bool = False
    pages_published: bool = False
    ads_launched: bool = False
    generated_at: datetime | None = None
    operator_halt_before: str | None = None
    operator_halt_after: str | None = None
    auto_executed: bool = False
    packets: list[ApprovalPacketResponse] = Field(default_factory=list)


def filters_from_request(request: ApprovalPacketRunRequest | None) -> ApprovalPacketFilters:
    if request is None:
        return ApprovalPacketFilters()
    return ApprovalPacketFilters(
        plan_type=request.plan_type,
        execution_plan_id=request.execution_plan_id,
    )


def decision_view_to_response(
    item: ApprovalPacketDecisionView,
) -> ApprovalPacketDecisionResponse:
    return ApprovalPacketDecisionResponse(
        decision_id=item.decision_id,
        decision=item.decision,
        reviewer=item.reviewer,
        source=item.source,
        reviewer_notes=item.reviewer_notes,
        decided_at=item.decided_at,
    )


def packet_to_response(item: ApprovalPacketView) -> ApprovalPacketResponse:
    return ApprovalPacketResponse(
        id=item.id,
        source_execution_plan_id=item.source_execution_plan_id,
        source_execution_plan_run_id=item.source_execution_plan_run_id,
        source_artifact_type=item.source_artifact_type,
        source_artifact_id=item.source_artifact_id,
        plan_family=item.plan_family,
        proposed_action=item.proposed_action,
        preflight_status=item.preflight_status,
        dry_run_only=True,
        no_execution=True,
        executed=False,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        owner_approval_required=True,
        owner_approved=False,
        generated_at=item.generated_at,
        idempotency_key=item.idempotency_key,
        preflight_checklist=list(item.preflight_checklist),
        missing_prerequisites=list(item.missing_prerequisites),
        findings=list(item.findings),
        required_owner_decisions=list(item.required_owner_decisions),
        decision=decision_view_to_response(item.decision) if item.decision is not None else None,
    )


def approval_packet_run_to_response(result: ApprovalPacketRunResult) -> ApprovalPacketRunResponse:
    return ApprovalPacketRunResponse(
        approval_packet_run_id=result.approval_packet_run_id,
        status=result.status.value,
        model_version=result.model_version,
        snapshot_fingerprint=result.snapshot_fingerprint,
        packet_count=result.packet_count,
        reused_existing=result.reused_existing,
        reused_count=result.reused_count,
        missing_plan_count=result.missing_plan_count,
        executed_count=0,
        dry_run_only=True,
        no_execution=True,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        generated_at=result.generated_at,
        operator_halt_before=result.operator_halt_before,
        operator_halt_after=result.operator_halt_after,
        auto_executed=False,
        packets=[packet_to_response(item) for item in result.packets],
    )


def empty_approval_packet_response() -> ApprovalPacketRunResponse:
    return ApprovalPacketRunResponse(status="not_started", auto_executed=False)


def build_approval_packet_run_response(
    db: Session,
    settings: Settings,
    request: ApprovalPacketRunRequest | None = None,
    *,
    service: ApprovalPacketService | None = None,
) -> ApprovalPacketRunResponse:
    planner = service or ApprovalPacketService()
    return approval_packet_run_to_response(
        planner.generate(db, settings, filters=filters_from_request(request))
    )


def build_latest_approval_packet_response(
    db: Session,
    *,
    service: ApprovalPacketService | None = None,
) -> ApprovalPacketRunResponse:
    planner = service or ApprovalPacketService()
    latest = planner.latest(db)
    if latest is None:
        return empty_approval_packet_response()
    return approval_packet_run_to_response(latest)


def approval_packet_http_error(error: ApprovalPacketError) -> tuple[int, str]:
    if error.code in {"artifact_not_found", "packet_not_found"}:
        return (404, error.message)
    return (400, error.message)
