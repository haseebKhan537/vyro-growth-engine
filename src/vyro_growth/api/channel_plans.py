from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.services.channel_planning import (
    ChannelPlanningService,
    ChannelPlanRunResult,
    ChannelPlanSeeds,
    ChannelPlanView,
)


class ChannelPlanSeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_specialty: str | None = None
    seed_state: str | None = None
    seed_keywords: list[str] = Field(default_factory=list)
    seed_partner_type: str | None = None


class ChannelPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    plan_key: str
    channel: str
    plan_type: str
    title: str
    summary: str
    target_specialty: str | None = None
    target_geography: str | None = None
    target_icp: str | None = None
    priority: str
    confidence: float
    source_metrics: dict[str, object] = Field(default_factory=dict)
    seed_input_refs: dict[str, object] = Field(default_factory=dict)
    generated_at: datetime
    approval_status: str
    dry_run_only: bool = True
    no_spend: bool = True
    launched: bool = False
    spend_attempted: bool = False
    campaign_launched: bool = False
    pages_published: bool = False
    outbound_attempted: bool = False


class ChannelPlanRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_plan_run_id: UUID | None = None
    status: str
    model_version: str | None = None
    snapshot_fingerprint: str | None = None
    plan_count: int = 0
    reused_existing: bool = False
    dry_run_only: bool = True
    no_spend: bool = True
    spend_attempted: bool = False
    campaign_launched: bool = False
    pages_published: bool = False
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    generated_at: datetime | None = None
    operator_halt_before: str | None = None
    operator_halt_after: str | None = None
    auto_launched: bool = False
    plans: list[ChannelPlanResponse] = Field(default_factory=list)


def seeds_from_request(request: ChannelPlanSeedRequest | None) -> ChannelPlanSeeds:
    if request is None:
        return ChannelPlanSeeds()
    return ChannelPlanSeeds(
        specialty=request.seed_specialty,
        geography=request.seed_state,
        keywords=tuple(request.seed_keywords),
        partner_type=request.seed_partner_type,
    )


def plan_to_response(item: ChannelPlanView) -> ChannelPlanResponse:
    return ChannelPlanResponse(
        id=item.id,
        plan_key=item.plan_key,
        channel=item.channel,
        plan_type=item.plan_type,
        title=item.title,
        summary=item.summary,
        target_specialty=item.target_specialty,
        target_geography=item.target_geography,
        target_icp=item.target_icp,
        priority=item.priority,
        confidence=item.confidence,
        source_metrics=item.source_metrics,
        seed_input_refs=item.seed_input_refs,
        generated_at=item.generated_at,
        approval_status=item.approval_status,
        dry_run_only=item.dry_run_only,
        no_spend=item.no_spend,
        launched=item.launched,
        spend_attempted=item.spend_attempted,
        campaign_launched=item.campaign_launched,
        pages_published=item.pages_published,
        outbound_attempted=item.outbound_attempted,
    )


def channel_plan_run_to_response(result: ChannelPlanRunResult) -> ChannelPlanRunResponse:
    return ChannelPlanRunResponse(
        channel_plan_run_id=result.channel_plan_run_id,
        status=result.status.value,
        model_version=result.model_version,
        snapshot_fingerprint=result.snapshot_fingerprint,
        plan_count=result.plan_count,
        reused_existing=result.reused_existing,
        dry_run_only=result.dry_run_only,
        no_spend=result.no_spend,
        spend_attempted=result.spend_attempted,
        campaign_launched=result.campaign_launched,
        pages_published=result.pages_published,
        outbound_attempted=result.outbound_attempted,
        live_call_attempted=result.live_call_attempted,
        generated_at=result.generated_at,
        operator_halt_before=result.operator_halt_before,
        operator_halt_after=result.operator_halt_after,
        auto_launched=False,
        plans=[plan_to_response(item) for item in result.plans],
    )


def empty_channel_plan_response() -> ChannelPlanRunResponse:
    return ChannelPlanRunResponse(status="not_started", auto_launched=False)


def build_channel_plan_run_response(
    db: Session,
    request: ChannelPlanSeedRequest | None = None,
    *,
    service: ChannelPlanningService | None = None,
) -> ChannelPlanRunResponse:
    planner = service or ChannelPlanningService()
    return channel_plan_run_to_response(planner.plan(db, seeds=seeds_from_request(request)))


def build_latest_channel_plan_response(
    db: Session,
    *,
    service: ChannelPlanningService | None = None,
) -> ChannelPlanRunResponse:
    planner = service or ChannelPlanningService()
    latest = planner.latest(db)
    if latest is None:
        return empty_channel_plan_response()
    return channel_plan_run_to_response(latest)
