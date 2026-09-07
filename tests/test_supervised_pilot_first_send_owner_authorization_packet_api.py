from __future__ import annotations

import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from tests.test_supervised_pilot_candidates_service import (
    NPI_NUMBER,
    PRACTICE_NAME,
    PROVIDER_NAME,
    WEBSITE,
    _seed_candidate,
)
from tests.test_supervised_pilot_first_send_owner_authorization_packet_service import (
    _assert_no_execution,
)
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import SettingsChangeRequestType
from vyro_growth.main import app
from vyro_growth.models import Activity, LiveSettingsChangeRequest, OwnerApprovalPacket
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

PACKET_PATH = "/internal/supervised-pilot-first-send-owner-authorization-packet"


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


def test_supervised_pilot_first_send_owner_authorization_packet_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(PACKET_PATH)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    _assert_no_execution(body)
    assert body["read_only"] is True
    assert body["no_execution"] is True
    assert body["no_go_live"] is True
    assert body["no_outbound"] is True
    assert body["no_provider_calls"] is True
    assert body["no_spend"] is True
    assert body["no_first_send"] is True
    assert body["dry_run_only"] is True
    assert body["executed"] == 0
    assert body["first_send_allowed"] is False
    assert body["first_send_executed"] == 0
    assert body["this_packet_is_not_approval"] is True
    assert body["authorization_granted"] is False
    assert body["approval_records_mutated"] is False
    assert body["outbound_enabled"] is False
    assert body["operator_halt_status"] == HaltStatus.HALTED.value
    assert body["operator_halt_before"] == HaltStatus.HALTED.value
    assert body["operator_halt_after"] == HaltStatus.HALTED.value
    assert body["source_control_map_command"] == "supervised-pilot-launch-rehearsal-control-map"
    assert body["source_first_send_command"] == "supervised-pilot-first-send-preflight"
    assert body["source_go_no_go_command"] == "supervised-pilot-go-no-go"
    assert body["source_pilot_plan_command"] == "supervised-pilot-plan"
    assert "blocking_control_codes" in body
    assert "control_counts_by_category" in body
    assert "remaining_owner_approval_types" in body
    assert "next_actions" in body
    assert "local_git" in body
    assert body["local_git"]["git_provider_called"] is False
    assert body["local_git"]["github_actions_called"] is False
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_supervised_pilot_first_send_owner_authorization_packet_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(PACKET_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_supervised_pilot_first_send_owner_authorization_packet_rejects_invalid_key_and_disallows_post(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    denied = api_client.get(
        PACKET_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        PACKET_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert denied.status_code == 401
    assert post.status_code == 405


def test_supervised_pilot_first_send_owner_authorization_packet_api_redacts_secrets_and_stays_read_only(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="production",
        internal_api_key="internal-secret",
        voice_api_key=SECRET_VALUE,
    )
    _patch_settings(monkeypatch, settings)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    _seed_candidate(
        db_session,
        verified_contact=True,
        add_evidence=True,
        add_enrichment=True,
        score_band="high",
    )
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="api-supervised-pilot-first-send-owner-authorization-packet",
        reviewer_notes=PHI_SNIPPET,
    )
    SettingsChangeRequestService().record_decision(
        db_session,
        settings,
        request_id=created.request_id,
        decision="approved",
        reviewer="owner",
    )
    before_activities = int(db_session.scalar(select(func.count()).select_from(Activity)) or 0)
    before_requests = int(
        db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) or 0
    )
    before_approvals = int(
        db_session.scalar(select(func.count()).select_from(OwnerApprovalPacket)) or 0
    )
    before_halt = read_operator_halt(db_session)

    response = api_client.get(
        PACKET_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    dumped = json.dumps(body)
    _assert_no_execution(body)
    assert body["read_only"] is True
    assert body["execution_allowed"] is False
    assert body["first_send_allowed"] is False
    assert body["no_first_send"] is True
    assert body["this_packet_is_not_approval"] is True
    assert body["approval_records_mutated"] is False
    assert body["deployment_allowed"] is False
    assert body["settings_applied"] is False
    assert body["halt_changed"] is False
    assert body["operator_halt_status"] == HaltStatus.HALTED.value
    assert SECRET_VALUE not in dumped
    assert PHI_SNIPPET not in dumped
    assert PROSPECT_EMAIL not in dumped
    assert PRACTICE_NAME not in dumped
    assert PROVIDER_NAME not in dumped
    assert NPI_NUMBER not in dumped
    assert WEBSITE not in dumped
    _assert_no_leakage(dumped, SECRET_VALUE)
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert (
        db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest))
        == before_requests
    )
    assert (
        db_session.scalar(select(func.count()).select_from(OwnerApprovalPacket))
        == before_approvals
    )
    assert read_operator_halt(db_session) is before_halt
    assert settings.outbound_enabled is False
