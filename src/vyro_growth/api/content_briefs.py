from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import ContentBriefType
from vyro_growth.services.content_brief import (
    ContentBriefError,
    ContentBriefRunResult,
    ContentBriefSeed,
    ContentBriefService,
    ContentBriefView,
)


class ContentBriefSeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief_type: str | None = None
    specialty: str | None = None
    geography: str | None = None
    icp_label: str | None = None
    topic: str | None = None
    channel_plan_id: UUID | None = None


class GenerateContentBriefsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seeds: list[ContentBriefSeedRequest] = Field(default_factory=list)


class ContentBriefResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    brief_key: str
    brief_type: str
    source_channel_plan_id: UUID | None = None
    specialty: str | None = None
    geography: str | None = None
    icp_label: str | None = None
    priority: str
    confidence: float
    title: str
    summary: str
    outline_sections: list[str] = Field(default_factory=list)
    recommended_cta: str
    compliance_notes: list[str] = Field(default_factory=list)
    source_references: dict[str, object] = Field(default_factory=dict)
    generated_at: datetime
    approval_status: str
    published: bool = False
    publish_attempted: bool = False
    dry_run_only: bool = True


class ContentBriefRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_brief_run_id: UUID | None = None
    status: str
    model_version: str | None = None
    snapshot_fingerprint: str | None = None
    brief_count: int = 0
    reused_existing: bool = False
    published_count: int = 0
    dry_run_only: bool = True
    published: bool = False
    publish_attempted: bool = False
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    ads_launched: bool = False
    spend_attempted: bool = False
    generated_at: datetime | None = None
    operator_halt_before: str | None = None
    operator_halt_after: str | None = None
    auto_published: bool = False
    briefs: list[ContentBriefResponse] = Field(default_factory=list)


def brief_to_response(item: ContentBriefView) -> ContentBriefResponse:
    return ContentBriefResponse(
        id=item.id,
        brief_key=item.brief_key,
        brief_type=item.brief_type,
        source_channel_plan_id=item.source_channel_plan_id,
        specialty=item.specialty,
        geography=item.geography,
        icp_label=item.icp_label,
        priority=item.priority,
        confidence=item.confidence,
        title=item.title,
        summary=item.summary,
        outline_sections=list(item.outline_sections),
        recommended_cta=item.recommended_cta,
        compliance_notes=list(item.compliance_notes),
        source_references=item.source_references,
        generated_at=item.generated_at,
        approval_status=item.approval_status,
        published=item.published,
        publish_attempted=item.publish_attempted,
        dry_run_only=item.dry_run_only,
    )


def content_brief_run_to_response(result: ContentBriefRunResult) -> ContentBriefRunResponse:
    return ContentBriefRunResponse(
        content_brief_run_id=result.content_brief_run_id,
        status=result.status.value,
        model_version=result.model_version,
        snapshot_fingerprint=result.snapshot_fingerprint,
        brief_count=result.brief_count,
        reused_existing=result.reused_existing,
        published_count=result.published_count,
        dry_run_only=result.dry_run_only,
        published=result.published,
        publish_attempted=result.publish_attempted,
        outbound_attempted=result.outbound_attempted,
        live_call_attempted=result.live_call_attempted,
        ads_launched=result.ads_launched,
        spend_attempted=result.spend_attempted,
        generated_at=result.generated_at,
        operator_halt_before=result.operator_halt_before,
        operator_halt_after=result.operator_halt_after,
        auto_published=False,
        briefs=[brief_to_response(item) for item in result.briefs],
    )


def empty_content_brief_response() -> ContentBriefRunResponse:
    return ContentBriefRunResponse(status="not_started", auto_published=False)


def _parse_seed(item: ContentBriefSeedRequest) -> ContentBriefSeed:
    brief_type = None
    if item.brief_type:
        try:
            brief_type = ContentBriefType(item.brief_type.strip())
        except ValueError as exc:
            raise ContentBriefError("unknown_brief_type", "Unknown content brief type") from exc
    return ContentBriefSeed(
        brief_type=brief_type,
        specialty=item.specialty,
        geography=item.geography,
        icp_label=item.icp_label,
        topic=item.topic,
        channel_plan_id=item.channel_plan_id,
    )


def build_content_brief_run_response(
    db: Session,
    settings: Settings,
    request: GenerateContentBriefsRequest | None = None,
    *,
    service: ContentBriefService | None = None,
) -> ContentBriefRunResponse:
    generator = service or ContentBriefService()
    seeds = tuple(_parse_seed(item) for item in (request.seeds if request is not None else []))
    return content_brief_run_to_response(generator.generate(db, settings, seeds=seeds))


def build_latest_content_brief_response(
    db: Session,
    *,
    service: ContentBriefService | None = None,
) -> ContentBriefRunResponse:
    generator = service or ContentBriefService()
    latest = generator.latest(db)
    if latest is None:
        return empty_content_brief_response()
    return content_brief_run_to_response(latest)


def content_brief_http_error(error: ContentBriefError) -> tuple[int, str]:
    status = {
        "unknown_brief_type": 400,
    }.get(error.code, 400)
    return status, error.message
