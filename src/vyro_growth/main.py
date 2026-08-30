from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from vyro_growth.api.discovery import NppesDiscoveryRequest, run_nppes_discovery
from vyro_growth.config import get_settings
from vyro_growth.database import get_db
from vyro_growth.observability import configure_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

DbSession = Annotated[Session, Depends(get_db)]


@app.get("/health", tags=["system"])
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "environment": settings.environment,
        "outbound_enabled": settings.outbound_enabled,
    }


@app.post("/internal/discovery/nppes", tags=["internal"])
def trigger_nppes_discovery(
    request: NppesDiscoveryRequest,
    db: DbSession,
) -> dict[str, object]:
    active_settings = get_settings()
    if active_settings.environment != "development":
        raise HTTPException(
            status_code=403,
            detail="Discovery trigger is only available in development",
        )

    result = run_nppes_discovery(db, request, settings=active_settings)
    return {
        "discovery_run_id": str(result.discovery_run_id),
        "records_fetched": result.records_fetched,
        "records_upserted": result.records_upserted,
        "records_skipped": result.records_skipped,
        "status": result.status.value,
    }
