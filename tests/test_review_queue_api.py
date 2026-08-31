from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from tests.test_review_queue_service import _seed_optimizer_recommendation
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import ReviewArtifactType, ReviewDecisionStatus
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


def test_review_queue_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.get("/internal/review-queue")

    assert response.status_code == 200
    body = response.json()
    assert body["pending_count"] == 0
    assert body["items"] == []
    assert body["outbound_attempted"] is False
    assert body["executed_count"] == 0
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_review_queue_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get("/internal/review-queue")

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_review_queue_rejects_invalid_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    response = api_client.get(
        "/internal/review-queue",
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    assert response.status_code == 401


def test_review_queue_and_decision_require_auth_and_stay_dry_run(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    _seed_pipeline(db_session)
    recommendation = _seed_optimizer_recommendation(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting))
    before_enrollments = db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage))

    listed = api_client.get(
        "/internal/review-queue",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    denied = api_client.get("/internal/review-queue")
    recorded = api_client.post(
        "/internal/review-queue/decisions",
        headers={"X-Internal-Api-Key": "internal-secret"},
        json={
            "artifact_type": ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value,
            "artifact_id": str(recommendation.id),
            "decision": ReviewDecisionStatus.APPROVED.value,
            "reviewer": "ops",
        },
    )
    after = api_client.get(
        "/internal/review-queue",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert listed.status_code == 200
    assert denied.status_code == 401
    assert recorded.status_code == 200
    assert recorded.json()["executed"] is False
    assert recorded.json()["recommendation_applied"] is False
    assert recorded.json()["outbound_attempted"] is False
    assert after.status_code == 200
    assert after.json()["pending_count"] == listed.json()["pending_count"] - 1
    assert PHI_SNIPPET not in listed.text
    assert PROSPECT_EMAIL not in listed.text
    assert "diabetes" not in listed.text.lower()
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_review_decision_rejects_unknown_artifact(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="development", internal_api_key=""),
    )

    response = api_client.post(
        "/internal/review-queue/decisions",
        json={
            "artifact_type": "personalization_draft",
            "artifact_id": "00000000-0000-0000-0000-000000000001",
            "decision": "approved",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Review artifact was not found"
