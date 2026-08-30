from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.growth_optimizer import (
    GrowthOptimizerService,
    OptimizerRecommendationView,
    OptimizerRunResult,
)


class OptimizerRecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    recommendation_key: str
    category: str
    priority: str
    confidence: float
    title: str
    rationale: str
    source_metrics: dict[str, object] = Field(default_factory=dict)
    generated_at: datetime
    approval_status: str
    applied: bool = False


class OptimizerRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    optimizer_run_id: UUID | None = None
    status: str
    model_version: str | None = None
    snapshot_fingerprint: str | None = None
    recommendation_count: int = 0
    reused_existing: bool = False
    applied_count: int = 0
    dry_run_only: bool = True
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    generated_at: datetime | None = None
    operator_halt_before: str | None = None
    operator_halt_after: str | None = None
    auto_applied: bool = False
    recommendations: list[OptimizerRecommendationResponse] = Field(default_factory=list)


def recommendation_to_response(
    item: OptimizerRecommendationView,
) -> OptimizerRecommendationResponse:
    return OptimizerRecommendationResponse(
        id=item.id,
        recommendation_key=item.recommendation_key,
        category=item.category,
        priority=item.priority,
        confidence=item.confidence,
        title=item.title,
        rationale=item.rationale,
        source_metrics=item.source_metrics,
        generated_at=item.generated_at,
        approval_status=item.approval_status,
        applied=item.applied,
    )


def optimizer_run_to_response(result: OptimizerRunResult) -> OptimizerRunResponse:
    return OptimizerRunResponse(
        optimizer_run_id=result.optimizer_run_id,
        status=result.status.value,
        model_version=result.model_version,
        snapshot_fingerprint=result.snapshot_fingerprint,
        recommendation_count=result.recommendation_count,
        reused_existing=result.reused_existing,
        applied_count=result.applied_count,
        dry_run_only=result.dry_run_only,
        outbound_attempted=result.outbound_attempted,
        live_call_attempted=result.live_call_attempted,
        generated_at=result.generated_at,
        operator_halt_before=result.operator_halt_before,
        operator_halt_after=result.operator_halt_after,
        auto_applied=False,
        recommendations=[recommendation_to_response(item) for item in result.recommendations],
    )


def empty_optimizer_response() -> OptimizerRunResponse:
    return OptimizerRunResponse(status="not_started", auto_applied=False)


def build_optimizer_run_response(
    db: Session,
    settings: Settings,
    *,
    service: GrowthOptimizerService | None = None,
) -> OptimizerRunResponse:
    optimizer = service or GrowthOptimizerService()
    return optimizer_run_to_response(optimizer.recommend(db, settings))


def build_latest_optimizer_response(
    db: Session,
    *,
    service: GrowthOptimizerService | None = None,
) -> OptimizerRunResponse:
    optimizer = service or GrowthOptimizerService()
    latest = optimizer.latest(db)
    if latest is None:
        return empty_optimizer_response()
    return optimizer_run_to_response(latest)
