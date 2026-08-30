from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.main import app
from vyro_growth.models import Activity, CampaignEnrollment, Meeting, OutreachMessage
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt


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


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr("vyro_growth.main.get_settings", lambda: settings)


def test_dashboard_summary_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.get("/internal/dashboard/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["discovery"]["organizations"] == 0
    assert body["safety"]["outbound_enabled"] is False
    assert body["safety"]["phi_fields_present"] is False
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_dashboard_summary_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get("/internal/dashboard/summary")

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_dashboard_summary_rejects_missing_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="development", internal_api_key="internal-secret"),
    )

    response = api_client.get("/internal/dashboard/summary")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing internal API key"


def test_dashboard_summary_rejects_invalid_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    response = api_client.post(
        "/internal/dashboard/summary",
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    # GET is the only allowed method; a POST should not create a write path.
    assert response.status_code == 405

    response = api_client.get(
        "/internal/dashboard/summary",
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing internal API key"


def test_dashboard_summary_accepts_valid_key_and_stays_read_only(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before_activities = db_session.scalar(select(func.count()).select_from(Activity))
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting))
    before_enrollments = db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage))

    response = api_client.get(
        "/internal/dashboard/summary",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["discovery"]["organizations"] == 1
    assert body["scoring"]["by_band"]["hot"] == 1
    assert body["booking_plans"]["planned_count"] == 1
    assert body["voice_qualification_plans"]["planned_count"] == 1
    assert body["safety"]["operator_halt_status"] == HaltStatus.HALTED.value
    assert body["safety"]["outbound_enabled"] is False
    assert PHI_SNIPPET not in response.text
    assert PROSPECT_EMAIL not in response.text
    assert "diabetes" not in response.text.lower()
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_dashboard_safety_endpoint_is_authorized(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    set_operator_halt(db_session, halted=True, reason="safety-card")

    denied = api_client.get("/internal/dashboard/safety")
    assert denied.status_code == 401

    response = api_client.get(
        "/internal/dashboard/safety",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outbound_enabled"] is False
    assert body["operator_halt_status"] == HaltStatus.HALTED.value
    assert body["phi_fields_present"] is False
    assert "discovery" not in body
