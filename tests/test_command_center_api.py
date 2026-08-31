from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_approval_packet_service import _approve_all_families
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from tests.test_monitoring_service import UNSAFE_ERROR
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import DiscoveryRunStatus, NextActionCode
from vyro_growth.main import app
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    DiscoveryRun,
    Meeting,
    OutreachMessage,
    OwnerApprovalPacket,
)
from vyro_growth.services.approval_packets import ApprovalPacketService
from vyro_growth.services.execution_planning import ExecutionPlanningService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

COMMAND_CENTER_PATH = "/internal/operator-command-center"


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


def test_command_center_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.get(COMMAND_CENTER_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["safety"]["outbound_enabled"] is False
    assert body["safety"]["phi_fields_present"] is False
    assert body["pipeline"]["organizations"] == 0
    assert body["outstanding_review"]["pending_count"] == 0
    assert body["approval_packets"]["packets"] == 0
    assert body["executed_count"] == 0
    assert body["outbound_attempted"] is False
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in {
        item["code"] for item in body["next_actions"]
    }
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_command_center_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(COMMAND_CENTER_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_command_center_rejects_missing_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="development", internal_api_key="internal-secret"),
    )

    response = api_client.get(COMMAND_CENTER_PATH)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing internal API key"


def test_command_center_rejects_invalid_key_and_disallows_post(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    post = api_client.post(
        COMMAND_CENTER_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    assert post.status_code == 405

    response = api_client.get(
        COMMAND_CENTER_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing internal API key"


def test_command_center_accepts_valid_key_and_stays_read_only(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    _seed_pipeline(db_session)
    db_session.add(
        DiscoveryRun(
            source="nppes",
            status=DiscoveryRunStatus.FAILED.value,
            error_message=UNSAFE_ERROR,
        )
    )
    db_session.flush()
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before_activities = db_session.scalar(select(func.count()).select_from(Activity))
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting))
    before_enrollments = db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage))

    response = api_client.get(
        COMMAND_CENTER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["pipeline"]["organizations"] == 1
    assert body["outstanding_review"]["pending_count"] >= 1
    assert body["safety"]["operator_halt_status"] == HaltStatus.HALTED.value
    assert body["safety"]["outbound_enabled"] is False
    assert body["finding_counts"]["total"] == len(body["findings"])
    assert body["next_actions"]
    assert body["recent_failures"]
    assert PHI_SNIPPET not in response.text
    assert PROSPECT_EMAIL not in response.text
    assert "diabetes" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_command_center_reports_owner_approved_packet_count(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    _approve_all_families(db_session)
    ExecutionPlanningService().generate(db_session, Settings())
    ApprovalPacketService().generate(db_session, Settings())
    packet = db_session.scalars(select(OwnerApprovalPacket)).first()
    assert packet is not None
    packet.owner_approved = True
    db_session.flush()
    before_activities = db_session.scalar(select(func.count()).select_from(Activity))
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting))
    before_enrollments = db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage))
    before_packets = db_session.scalar(select(func.count()).select_from(OwnerApprovalPacket))

    response = api_client.get(
        COMMAND_CENTER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    packets = body["approval_packets"]
    assert packets["packets"] == before_packets
    assert packets["owner_approved"] == 1
    assert packets["executed"] == 0
    assert body["executed_count"] == 0
    assert body["outbound_attempted"] is False
    assert body["read_only"] is True
    assert body["safety"]["outbound_enabled"] is False
    assert body["safety"]["operator_halt_status"] == HaltStatus.HALTED.value
    assert PHI_SNIPPET not in response.text
    assert PROSPECT_EMAIL not in response.text
    assert "diabetes" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert (
        db_session.scalar(select(func.count()).select_from(OwnerApprovalPacket)) == before_packets
    )
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert packet.executed is False
    assert packet.execution_attempted is False
    assert packet.outbound_attempted is False
