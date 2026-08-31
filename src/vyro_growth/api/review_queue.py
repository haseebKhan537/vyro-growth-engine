from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.review_queue import (
    ReviewDecisionResult,
    ReviewDecisionView,
    ReviewItem,
    ReviewQueueError,
    ReviewQueueResult,
    ReviewQueueService,
)


class ReviewDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    decision: str
    reviewer: str
    source: str
    reviewer_notes: str | None = None
    decided_at: datetime


class ReviewItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    artifact_id: UUID
    lead_id: UUID | None = None
    organization_id: UUID | None = None
    title: str
    summary: str
    status: str
    created_at: datetime
    risk_labels: list[str] = Field(default_factory=list)
    executable_later: bool
    executed: bool = False
    decision: ReviewDecisionResponse | None = None


class ReviewQueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    pending_count: int = 0
    decided_count: int = 0
    by_artifact_type: dict[str, int] = Field(default_factory=dict)
    by_decision: dict[str, int] = Field(default_factory=dict)
    executed_count: int = 0
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    recommendation_applied: bool = False
    operator_halt_status: str
    items: list[ReviewItemResponse] = Field(default_factory=list)


class RecordReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    artifact_id: UUID
    decision: str
    reviewer: str | None = None
    reviewer_notes: str | None = None


class RecordReviewDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    artifact_type: str
    artifact_id: UUID
    decision: str
    reviewer: str
    source: str
    reviewer_notes: str | None = None
    decided_at: datetime
    executed: bool = False
    execution_attempted: bool = False
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    recommendation_applied: bool = False
    operator_halt_before: str
    operator_halt_after: str


def decision_view_to_response(item: ReviewDecisionView) -> ReviewDecisionResponse:
    return ReviewDecisionResponse(
        decision_id=item.decision_id,
        decision=item.decision,
        reviewer=item.reviewer,
        source=item.source,
        reviewer_notes=item.reviewer_notes,
        decided_at=item.decided_at,
    )


def review_item_to_response(item: ReviewItem) -> ReviewItemResponse:
    return ReviewItemResponse(
        artifact_type=item.artifact_type,
        artifact_id=item.artifact_id,
        lead_id=item.lead_id,
        organization_id=item.organization_id,
        title=item.title,
        summary=item.summary,
        status=item.status,
        created_at=item.created_at,
        risk_labels=list(item.risk_labels),
        executable_later=item.executable_later,
        executed=False,
        decision=decision_view_to_response(item.decision) if item.decision is not None else None,
    )


def review_queue_to_response(result: ReviewQueueResult) -> ReviewQueueResponse:
    return ReviewQueueResponse(
        generated_at=result.generated_at,
        pending_count=result.pending_count,
        decided_count=result.decided_count,
        by_artifact_type=result.by_artifact_type,
        by_decision=result.by_decision,
        executed_count=0,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        operator_halt_status=result.operator_halt_status,
        items=[review_item_to_response(item) for item in result.items],
    )


def decision_result_to_response(result: ReviewDecisionResult) -> RecordReviewDecisionResponse:
    return RecordReviewDecisionResponse(
        decision_id=result.decision_id,
        artifact_type=result.artifact_type,
        artifact_id=result.artifact_id,
        decision=result.decision,
        reviewer=result.reviewer,
        source=result.source,
        reviewer_notes=result.reviewer_notes,
        decided_at=result.decided_at,
        executed=False,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        operator_halt_before=result.operator_halt_before,
        operator_halt_after=result.operator_halt_after,
    )


def build_review_queue_response(
    db: Session,
    settings: Settings,
    *,
    include_decided: bool = False,
    artifact_type: str | None = None,
    service: ReviewQueueService | None = None,
) -> ReviewQueueResponse:
    queue = service or ReviewQueueService()
    return review_queue_to_response(
        queue.list_queue(
            db,
            settings,
            include_decided=include_decided,
            artifact_type=artifact_type,
        )
    )


def build_review_decision_response(
    db: Session,
    request: RecordReviewDecisionRequest,
    *,
    source: str = "internal_api",
    service: ReviewQueueService | None = None,
) -> RecordReviewDecisionResponse:
    queue = service or ReviewQueueService()
    result = queue.record_decision(
        db,
        artifact_type=request.artifact_type,
        artifact_id=request.artifact_id,
        decision=request.decision,
        reviewer=request.reviewer,
        source=source,
        reviewer_notes=request.reviewer_notes,
    )
    return decision_result_to_response(result)


def review_queue_http_error(error: ReviewQueueError) -> tuple[int, str]:
    if error.code == "artifact_not_found":
        return (404, error.message)
    return (400, error.message)
