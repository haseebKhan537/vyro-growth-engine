from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import RecommendationApprovalStatus
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


def test_optimizer_run_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.post("/internal/optimizer/run")

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run_only"] is True
    assert body["auto_applied"] is False
    assert body["applied_count"] == 0
    assert body["outbound_attempted"] is False
    assert body["recommendation_count"] == len(body["recommendations"])
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 1


def test_optimizer_run_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.post("/internal/optimizer/run")

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_optimizer_run_rejects_invalid_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    response = api_client.post(
        "/internal/optimizer/run",
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    assert response.status_code == 401


def test_optimizer_run_accepts_valid_key_and_stays_dry_run(
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
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting))
    before_enrollments = db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage))

    response = api_client.post(
        "/internal/optimizer/run",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["auto_applied"] is False
    assert all(
        item["approval_status"] == RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value
        for item in body["recommendations"]
    )
    assert all(item["applied"] is False for item in body["recommendations"])
    assert PHI_SNIPPET not in response.text
    assert PROSPECT_EMAIL not in response.text
    assert "diabetes" not in response.text.lower()
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_latest_recommendations_require_auth_and_reuse_run(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    empty = api_client.get(
        "/internal/optimizer/recommendations",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert empty.status_code == 200
    assert empty.json()["status"] == "not_started"
    assert empty.json()["recommendations"] == []

    created = api_client.post(
        "/internal/optimizer/run",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    latest = api_client.get(
        "/internal/optimizer/recommendations",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    denied = api_client.get("/internal/optimizer/recommendations")

    assert created.status_code == 200
    assert latest.status_code == 200
    assert latest.json()["optimizer_run_id"] == created.json()["optimizer_run_id"]
    assert denied.status_code == 401
    assert db_session is not None
