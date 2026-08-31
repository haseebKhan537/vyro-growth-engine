from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.action_readiness import (
    ActionReadinessCandidate,
    ActionReadinessFilters,
    ActionReadinessResult,
    ActionReadinessService,
)


class ActionReadinessCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID
    artifact_type: str
    artifact_id: UUID
    plan_family: str
    sanitized_label: str
    review_decision_status: str
    packet_decision_status: str
    preflight_status: str
    readiness_status: str
    blocker_status: str
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
    owner_approved: bool = False
    live_action: bool = False
    explicit_live_owner_action_required: bool = True
    generated_at: datetime
    execution_plan_id: UUID | None = None
    approval_packet_id: UUID | None = None
    review_decision_id: UUID | None = None
    packet_decision_id: UUID | None = None
    blocker_codes: list[str] = Field(default_factory=list)
    missing_approval_codes: list[str] = Field(default_factory=list)
    missing_prerequisite_codes: list[str] = Field(default_factory=list)


class ActionReadinessQueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    candidate_count: int = 0
    by_readiness_status: dict[str, int] = Field(default_factory=dict)
    by_plan_family: dict[str, int] = Field(default_factory=dict)
    by_blocker_status: dict[str, int] = Field(default_factory=dict)
    by_decision_status: dict[str, int] = Field(default_factory=dict)
    dry_run_only: bool = True
    no_execution: bool = True
    executed_count: int = 0
    execution_attempted: bool = False
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    recommendation_applied: bool = False
    spend_attempted: bool = False
    campaign_launched: bool = False
    pages_published: bool = False
    ads_launched: bool = False
    live_action: bool = False
    read_only: bool = True
    explicit_live_owner_action_required: bool = True
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    candidates: list[ActionReadinessCandidateResponse] = Field(default_factory=list)


def candidate_to_response(item: ActionReadinessCandidate) -> ActionReadinessCandidateResponse:
    return ActionReadinessCandidateResponse(
        candidate_id=item.candidate_id,
        artifact_type=item.artifact_type,
        artifact_id=item.artifact_id,
        plan_family=item.plan_family,
        sanitized_label=item.sanitized_label,
        review_decision_status=item.review_decision_status,
        packet_decision_status=item.packet_decision_status,
        preflight_status=item.preflight_status,
        readiness_status=item.readiness_status,
        blocker_status=item.blocker_status,
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
        owner_approved=False,
        live_action=False,
        explicit_live_owner_action_required=True,
        generated_at=item.generated_at,
        execution_plan_id=item.execution_plan_id,
        approval_packet_id=item.approval_packet_id,
        review_decision_id=item.review_decision_id,
        packet_decision_id=item.packet_decision_id,
        blocker_codes=list(item.blocker_codes),
        missing_approval_codes=list(item.missing_approval_codes),
        missing_prerequisite_codes=list(item.missing_prerequisite_codes),
    )


def queue_to_response(result: ActionReadinessResult) -> ActionReadinessQueueResponse:
    return ActionReadinessQueueResponse(
        generated_at=result.generated_at,
        candidate_count=result.candidate_count,
        by_readiness_status=dict(result.by_readiness_status),
        by_plan_family=dict(result.by_plan_family),
        by_blocker_status=dict(result.by_blocker_status),
        by_decision_status=dict(result.by_decision_status),
        dry_run_only=True,
        no_execution=True,
        executed_count=0,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        live_action=False,
        read_only=True,
        explicit_live_owner_action_required=True,
        operator_halt_status=result.operator_halt_status,
        operator_halt_before=result.operator_halt_before,
        operator_halt_after=result.operator_halt_after,
        candidates=[candidate_to_response(item) for item in result.candidates],
    )


def build_action_readiness_response(
    db: Session,
    settings: Settings,
    *,
    plan_family: str | None = None,
    readiness_status: str | None = None,
    blocker_status: str | None = None,
    decision_status: str | None = None,
    service: ActionReadinessService | None = None,
) -> ActionReadinessQueueResponse:
    queue = service or ActionReadinessService()
    return queue_to_response(
        queue.list_queue(
            db,
            settings,
            filters=ActionReadinessFilters(
                plan_family=plan_family,
                readiness_status=readiness_status,
                blocker_status=blocker_status,
                decision_status=decision_status,
            ),
        )
    )
