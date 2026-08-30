from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.main import app
from vyro_growth.services.readiness import assess_readiness, build_health_payload, database_is_ready


@pytest.fixture
def api_client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def test_health_payload_reports_safe_defaults() -> None:
    payload = build_health_payload(Settings())

    assert payload["status"] == "ok"
    assert payload["outbound_enabled"] is False
    assert payload["live_providers_enabled"] is False


def test_ready_ok_with_sqlite_and_development_settings(db_session: Session) -> None:
    status_code, payload = assess_readiness(Settings(environment="development"), db_session)

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["database"] == "ok"
    assert payload["config_ok"] is True
    assert payload["config_issues"] == []
    assert payload["outbound_enabled"] is False
    assert payload["live_providers_enabled"] is False
    assert payload["live_providers"]["smartlead"] is False
    assert payload["live_providers"]["google_calendar"] is False
    assert payload["live_providers"]["voice"] is False


def test_ready_fails_closed_for_production_without_internal_key(db_session: Session) -> None:
    status_code, payload = assess_readiness(
        Settings(environment="production", internal_api_key=""),
        db_session,
    )

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["config_ok"] is False
    assert payload["database"] == "ok"
    assert any("INTERNAL_API_KEY" in issue for issue in payload["config_issues"])


def test_ready_fails_when_database_is_unavailable() -> None:
    db = MagicMock()
    db.execute.side_effect = SQLAlchemyError("unavailable")

    status_code, payload = assess_readiness(Settings(environment="development"), db)

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["database"] == "unavailable"
    assert database_is_ready(db) is False


def test_ready_http_ok(api_client: TestClient) -> None:
    response = api_client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["outbound_enabled"] is False
    assert body["live_providers_enabled"] is False


def test_ready_http_fails_closed_in_production(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vyro_growth.main.get_settings",
        lambda: Settings(environment="production", internal_api_key=""),
    )

    response = api_client.get("/ready")

    assert response.status_code == 503
    assert response.json()["config_ok"] is False
