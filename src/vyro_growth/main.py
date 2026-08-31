from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from vyro_growth.api.approval_packets import (
    ApprovalPacketRunRequest,
    ApprovalPacketRunResponse,
    approval_packet_http_error,
    build_approval_packet_run_response,
    build_latest_approval_packet_response,
)
from vyro_growth.api.channel_plans import (
    ChannelPlanRunResponse,
    ChannelPlanSeedRequest,
    build_channel_plan_run_response,
    build_latest_channel_plan_response,
)
from vyro_growth.api.command_center import (
    CommandCenterResponse,
    build_command_center_response,
)
from vyro_growth.api.content_briefs import (
    ContentBriefRunResponse,
    GenerateContentBriefsRequest,
    build_content_brief_run_response,
    build_latest_content_brief_response,
    content_brief_http_error,
)
from vyro_growth.api.dashboard import (
    DashboardSummaryResponse,
    SafetyCardResponse,
    build_dashboard_summary_response,
)
from vyro_growth.api.discovery import NppesDiscoveryRequest, run_nppes_discovery
from vyro_growth.api.execution_plans import (
    ExecutionPlanRunRequest,
    ExecutionPlanRunResponse,
    build_execution_plan_run_response,
    build_latest_execution_plan_response,
    execution_planning_http_error,
)
from vyro_growth.api.internal_auth import (
    evaluate_internal_http_trigger,
    internal_trigger_http_error,
)
from vyro_growth.api.monitoring import (
    MonitoringStatusResponse,
    build_monitoring_status_response,
)
from vyro_growth.api.optimizer import (
    OptimizerRunResponse,
    build_latest_optimizer_response,
    build_optimizer_run_response,
)
from vyro_growth.api.review_queue import (
    RecordReviewDecisionRequest,
    RecordReviewDecisionResponse,
    ReviewQueueResponse,
    build_review_decision_response,
    build_review_queue_response,
    review_queue_http_error,
)
from vyro_growth.config import Settings, get_settings, require_valid_runtime_settings
from vyro_growth.database import get_db
from vyro_growth.observability import configure_logging
from vyro_growth.services.approval_packets import ApprovalPacketError
from vyro_growth.services.content_brief import ContentBriefError
from vyro_growth.services.execution_planning import ExecutionPlanningError
from vyro_growth.services.readiness import HealthPayload, assess_readiness, build_health_payload
from vyro_growth.services.review_queue import ReviewQueueError

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    require_valid_runtime_settings(get_settings())
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

DbSession = Annotated[Session, Depends(get_db)]


@app.get("/health", tags=["system"])
def health() -> HealthPayload:
    return build_health_payload(get_settings())


@app.get("/ready", tags=["system"])
def ready(db: DbSession) -> JSONResponse:
    status_code, payload = assess_readiness(get_settings(), db)
    return JSONResponse(status_code=status_code, content=payload)


def _require_internal_key(active_settings: Settings, provided_key: str | None) -> None:
    denied = internal_trigger_http_error(
        evaluate_internal_http_trigger(active_settings, provided_key)
    )
    if denied is not None:
        status_code, detail = denied
        raise HTTPException(status_code=status_code, detail=detail)


@app.get("/internal/dashboard/summary", tags=["internal"])
def dashboard_summary(
    db: DbSession,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> DashboardSummaryResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    return build_dashboard_summary_response(db, active_settings)


@app.get("/internal/dashboard/safety", tags=["internal"])
def dashboard_safety(
    db: DbSession,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> SafetyCardResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    return build_dashboard_summary_response(db, active_settings).safety


@app.get("/internal/monitoring/status", tags=["internal"])
def monitoring_status(
    db: DbSession,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> MonitoringStatusResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    return build_monitoring_status_response(db, active_settings)


@app.get("/internal/operator-command-center", tags=["internal"])
def operator_command_center(
    db: DbSession,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> CommandCenterResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    return build_command_center_response(db, active_settings)


@app.post("/internal/optimizer/run", tags=["internal"])
def run_growth_optimizer(
    db: DbSession,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> OptimizerRunResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    return build_optimizer_run_response(db, active_settings)


@app.get("/internal/optimizer/recommendations", tags=["internal"])
def latest_growth_recommendations(
    db: DbSession,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> OptimizerRunResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    return build_latest_optimizer_response(db)


@app.post("/internal/channel-plans/run", tags=["internal"])
def run_channel_planning(
    db: DbSession,
    request: ChannelPlanSeedRequest | None = None,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> ChannelPlanRunResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    return build_channel_plan_run_response(db, request)


@app.get("/internal/channel-plans", tags=["internal"])
def latest_channel_plans(
    db: DbSession,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> ChannelPlanRunResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    return build_latest_channel_plan_response(db)


@app.post("/internal/content-briefs/generate", tags=["internal"])
def generate_content_briefs(
    db: DbSession,
    request: GenerateContentBriefsRequest | None = None,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> ContentBriefRunResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    try:
        return build_content_brief_run_response(db, active_settings, request)
    except ContentBriefError as exc:
        status_code, detail = content_brief_http_error(exc)
        raise HTTPException(status_code=status_code, detail=detail) from exc


@app.get("/internal/content-briefs", tags=["internal"])
def latest_content_briefs(
    db: DbSession,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> ContentBriefRunResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    return build_latest_content_brief_response(db)


@app.post("/internal/execution-plans/run", tags=["internal"])
def run_execution_planning(
    db: DbSession,
    request: ExecutionPlanRunRequest | None = None,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> ExecutionPlanRunResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    try:
        return build_execution_plan_run_response(db, active_settings, request)
    except ExecutionPlanningError as exc:
        status_code, detail = execution_planning_http_error(exc)
        raise HTTPException(status_code=status_code, detail=detail) from exc


@app.get("/internal/execution-plans", tags=["internal"])
def latest_execution_plans(
    db: DbSession,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> ExecutionPlanRunResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    return build_latest_execution_plan_response(db)


@app.post("/internal/approval-packets/run", tags=["internal"])
def run_approval_packets(
    db: DbSession,
    request: ApprovalPacketRunRequest | None = None,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> ApprovalPacketRunResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    try:
        return build_approval_packet_run_response(db, active_settings, request)
    except ApprovalPacketError as exc:
        status_code, detail = approval_packet_http_error(exc)
        raise HTTPException(status_code=status_code, detail=detail) from exc


@app.get("/internal/approval-packets", tags=["internal"])
def latest_approval_packets(
    db: DbSession,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> ApprovalPacketRunResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    return build_latest_approval_packet_response(db)


@app.get("/internal/review-queue", tags=["internal"])
def review_queue(
    db: DbSession,
    x_internal_api_key: Annotated[str | None, Header()] = None,
    include_decided: Annotated[bool, Query()] = False,
    artifact_type: Annotated[str | None, Query()] = None,
) -> ReviewQueueResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    try:
        return build_review_queue_response(
            db,
            active_settings,
            include_decided=include_decided,
            artifact_type=artifact_type,
        )
    except ReviewQueueError as exc:
        status_code, detail = review_queue_http_error(exc)
        raise HTTPException(status_code=status_code, detail=detail) from exc


@app.post("/internal/review-queue/decisions", tags=["internal"])
def record_review_decision(
    request: RecordReviewDecisionRequest,
    db: DbSession,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> RecordReviewDecisionResponse:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)
    try:
        return build_review_decision_response(db, request)
    except ReviewQueueError as exc:
        status_code, detail = review_queue_http_error(exc)
        raise HTTPException(status_code=status_code, detail=detail) from exc


@app.post("/internal/discovery/nppes", tags=["internal"])
def trigger_nppes_discovery(
    request: NppesDiscoveryRequest,
    db: DbSession,
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    active_settings = get_settings()
    _require_internal_key(active_settings, x_internal_api_key)

    result = run_nppes_discovery(db, request, settings=active_settings)
    return {
        "discovery_run_id": str(result.discovery_run_id),
        "records_fetched": result.records_fetched,
        "records_upserted": result.records_upserted,
        "records_skipped": result.records_skipped,
        "status": result.status.value,
    }
