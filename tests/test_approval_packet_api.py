from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import ReviewArtifactType, ReviewDecisionStatus
from vyro_growth.main import app
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    Meeting,
    OutreachMessage,
    PersonalizationDraft,
)
from vyro_growth.services.execution_planning import ExecutionPlanningService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.review_queue import ReviewQueueService


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


def test_approval_packet_run_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.post("/internal/approval-packets/run", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run_only"] is True
    assert body["no_execution"] is True
    assert body["auto_executed"] is False
    assert body["executed_count"] == 0
    assert body["outbound_attempted"] is False
    assert body["packet_count"] == len(body["packets"])
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 1


def test_approval_packet_run_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.post("/internal/approval-packets/run", json={})

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_approval_packet_run_rejects_invalid_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    response = api_client.post(
        "/internal/approval-packets/run",
        headers={"X-Internal-Api-Key": "wrong-secret"},
        json={},
    )
    assert response.status_code == 401


def test_approval_packet_run_accepts_valid_key_and_stays_dry_run(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(environment="production", internal_api_key="internal-secret")
    _patch_settings(monkeypatch, settings)
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    draft = db_session.scalars(select(PersonalizationDraft)).first()
    assert draft is not None
    ReviewQueueService().record_decision(
        db_session,
        artifact_type=ReviewArtifactType.PERSONALIZATION_DRAFT.value,
        artifact_id=draft.id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
    )
    ExecutionPlanningService().generate(db_session, settings)
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting))
    before_enrollments = db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage))

    response = api_client.post(
        "/internal/approval-packets/run",
        headers={"X-Internal-Api-Key": "internal-secret"},
        json={},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["auto_executed"] is False
    assert body["executed_count"] == 0
    assert all(item["executed"] is False for item in body["packets"])
    assert all(item["no_execution"] is True for item in body["packets"])
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


def test_latest_approval_packets_require_auth_and_reuse_run(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    empty = api_client.get(
        "/internal/approval-packets",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert empty.status_code == 200
    assert empty.json()["status"] == "not_started"
    assert empty.json()["packets"] == []

    created = api_client.post(
        "/internal/approval-packets/run",
        headers={"X-Internal-Api-Key": "internal-secret"},
        json={},
    )
    latest = api_client.get(
        "/internal/approval-packets",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    denied = api_client.get("/internal/approval-packets")

    assert created.status_code == 200
    assert latest.status_code == 200
    assert latest.json()["approval_packet_run_id"] == created.json()["approval_packet_run_id"]
    assert denied.status_code == 401
    assert db_session is not None


def test_approval_packet_run_rejects_unknown_plan_type(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.post(
        "/internal/approval-packets/run",
        json={"plan_type": "not_a_real_type"},
    )
    assert response.status_code == 400
