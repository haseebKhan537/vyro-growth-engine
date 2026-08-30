from __future__ import annotations

from typing import TypedDict

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from vyro_growth.config import (
    Settings,
    any_live_provider_enabled,
    live_provider_flags,
    validate_runtime_settings,
)


class HealthPayload(TypedDict):
    status: str
    environment: str
    outbound_enabled: bool
    live_providers_enabled: bool


class ReadinessPayload(TypedDict):
    status: str
    environment: str
    outbound_enabled: bool
    database: str
    config_ok: bool
    config_issues: list[str]
    live_providers_enabled: bool
    live_providers: dict[str, bool]


def database_is_ready(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


def build_health_payload(settings: Settings) -> HealthPayload:
    return {
        "status": "ok",
        "environment": settings.environment,
        "outbound_enabled": settings.outbound_enabled,
        "live_providers_enabled": any_live_provider_enabled(settings),
    }


def assess_readiness(settings: Settings, db: Session) -> tuple[int, ReadinessPayload]:
    """Return HTTP status and payload. Never calls live paid/external providers."""

    issues = list(validate_runtime_settings(settings))
    db_ok = database_is_ready(db)
    ready = not issues and db_ok
    payload: ReadinessPayload = {
        "status": "ready" if ready else "not_ready",
        "environment": settings.environment,
        "outbound_enabled": settings.outbound_enabled,
        "database": "ok" if db_ok else "unavailable",
        "config_ok": not issues,
        "config_issues": issues,
        "live_providers_enabled": any_live_provider_enabled(settings),
        "live_providers": live_provider_flags(settings),
    }
    return (200 if ready else 503, payload)
