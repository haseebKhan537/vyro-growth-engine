from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_action_readiness_service import _seed_plans_and_packets
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import (
    ActionReadinessStatus,
    ExecutionPlanType,
    ReviewDecisionStatus,
)
from vyro_growth.main import app
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    Meeting,
    OutreachMessage,
    OwnerApprovalPacket,
)
from vyro_growth.services.approval_packets import ApprovalPacketService
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


def test_action_readiness_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get("/internal/action-readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["candidate_count"] == 0
    assert body["candidates"] == []
    assert body["executed_count"] == 0
    assert body["live_action"] is False
    assert body["read_only"] is True
    assert body["no_execution"] is True
    assert body["explicit_live_owner_action_required"] is True
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_action_readiness_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get("/internal/action-readiness")

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_action_readiness_rejects_invalid_key_and_disallows_post(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    denied = api_client.get(
        "/internal/action-readiness",
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        "/internal/action-readiness",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert denied.status_code == 401
    assert post.status_code == 405


def test_action_readiness_populated_filters_and_no_side_effects(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    _seed_plans_and_packets(db_session)
    packet = db_session.scalars(select(OwnerApprovalPacket)).first()
    assert packet is not None
    ApprovalPacketService().record_decision(
        db_session,
        packet_id=packet.id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
    )
    before_activities = db_session.scalar(select(func.count()).select_from(Activity)) or 0
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting)) or 0
    before_enrollments = (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0
    )
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage)) or 0

    listed = api_client.get(
        "/internal/action-readiness",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    filtered = api_client.get(
        "/internal/action-readiness",
        headers={"X-Internal-Api-Key": "internal-secret"},
        params={
            "plan_family": ExecutionPlanType.OPTIMIZER_APPLY.value,
            "readiness_status": ActionReadinessStatus.MISSING_OWNER_PACKET_DECISION.value,
        },
    )
    denied = api_client.get("/internal/action-readiness")

    assert listed.status_code == 200
    assert denied.status_code == 401
    body = listed.json()
    assert body["candidate_count"] == 8
    assert body["executed_count"] == 0
    assert body["live_action"] is False
    assert all(item["owner_approved"] is False for item in body["candidates"])
    assert all(item["live_action"] is False for item in body["candidates"])
    assert all(item["explicit_live_owner_action_required"] is True for item in body["candidates"])
    assert PHI_SNIPPET not in listed.text
    assert PROSPECT_EMAIL not in listed.text
    assert filtered.status_code == 200
    assert filtered.json()["candidate_count"] <= 1
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    stored = db_session.get(OwnerApprovalPacket, packet.id)
    assert stored is not None
    assert stored.owner_approved is False
    assert stored.executed is False
