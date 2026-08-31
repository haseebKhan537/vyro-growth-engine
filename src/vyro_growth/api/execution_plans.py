from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.execution_planning import (
    ExecutionPlanFilters,
    ExecutionPlanningError,
    ExecutionPlanningService,
    ExecutionPlanRunResult,
    ExecutionPlanView,
)


class ExecutionPlanRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str | None = None
    artifact_id: UUID | None = None


class ExecutionPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_review_decision_id: UUID
    source_artifact_type: str
    source_artifact_id: UUID
    lead_id: UUID | None = None
    organization_id: UUID | None = None
    plan_type: str
    proposed_action: str
    readiness_status: str
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
    prerequisites: list[dict[str, object]] = Field(default_factory=list)
    blockers: list[dict[str, object]] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    required_owner_approvals: list[str] = Field(default_factory=list)


class ExecutionPlanRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_plan_run_id: UUID | None = None
    status: str
    model_version: str | None = None
    snapshot_fingerprint: str | None = None
    plan_count: int = 0
    reused_existing: bool = False
    reused_count: int = 0
    ignored_non_approved_count: int = 0
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
    plans: list[ExecutionPlanResponse] = Field(default_factory=list)


def filters_from_request(request: ExecutionPlanRunRequest | None) -> ExecutionPlanFilters:
    if request is None:
        return ExecutionPlanFilters()
    return ExecutionPlanFilters(
        artifact_type=request.artifact_type,
        artifact_id=request.artifact_id,
    )


def plan_to_response(item: ExecutionPlanView) -> ExecutionPlanResponse:
    return ExecutionPlanResponse(
        id=item.id,
        source_review_decision_id=item.source_review_decision_id,
        source_artifact_type=item.source_artifact_type,
        source_artifact_id=item.source_artifact_id,
        lead_id=item.lead_id,
        organization_id=item.organization_id,
        plan_type=item.plan_type,
        proposed_action=item.proposed_action,
        readiness_status=item.readiness_status,
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
        prerequisites=list(item.prerequisites),
        blockers=list(item.blockers),
        safety_notes=list(item.safety_notes),
        required_owner_approvals=list(item.required_owner_approvals),
    )


def execution_plan_run_to_response(result: ExecutionPlanRunResult) -> ExecutionPlanRunResponse:
    return ExecutionPlanRunResponse(
        execution_plan_run_id=result.execution_plan_run_id,
        status=result.status.value,
        model_version=result.model_version,
        snapshot_fingerprint=result.snapshot_fingerprint,
        plan_count=result.plan_count,
        reused_existing=result.reused_existing,
        reused_count=result.reused_count,
        ignored_non_approved_count=result.ignored_non_approved_count,
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
        plans=[plan_to_response(item) for item in result.plans],
    )


def empty_execution_plan_response() -> ExecutionPlanRunResponse:
    return ExecutionPlanRunResponse(status="not_started", auto_executed=False)


def build_execution_plan_run_response(
    db: Session,
    settings: Settings,
    request: ExecutionPlanRunRequest | None = None,
    *,
    service: ExecutionPlanningService | None = None,
) -> ExecutionPlanRunResponse:
    planner = service or ExecutionPlanningService()
    return execution_plan_run_to_response(
        planner.generate(db, settings, filters=filters_from_request(request))
    )


def build_latest_execution_plan_response(
    db: Session,
    *,
    service: ExecutionPlanningService | None = None,
) -> ExecutionPlanRunResponse:
    planner = service or ExecutionPlanningService()
    latest = planner.latest(db)
    if latest is None:
        return empty_execution_plan_response()
    return execution_plan_run_to_response(latest)


def execution_planning_http_error(error: ExecutionPlanningError) -> tuple[int, str]:
    if error.code == "artifact_not_found":
        return (404, error.message)
    return (400, error.message)
