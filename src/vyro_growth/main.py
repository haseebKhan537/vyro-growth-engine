from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from vyro_growth.api.dashboard import (
    DashboardSummaryResponse,
    SafetyCardResponse,
    build_dashboard_summary_response,
)
from vyro_growth.api.discovery import NppesDiscoveryRequest, run_nppes_discovery
from vyro_growth.api.internal_auth import (
    evaluate_internal_http_trigger,
    internal_trigger_http_error,
)
from vyro_growth.api.optimizer import (
    OptimizerRunResponse,
    build_latest_optimizer_response,
    build_optimizer_run_response,
)
from vyro_growth.config import Settings, get_settings, require_valid_runtime_settings
from vyro_growth.database import get_db
from vyro_growth.observability import configure_logging
from vyro_growth.services.readiness import HealthPayload, assess_readiness, build_health_payload

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
