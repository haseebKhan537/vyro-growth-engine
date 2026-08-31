from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import SettingsChangeRequestType
from vyro_growth.main import app
from vyro_growth.models import Activity, LiveSettingsChangeRequest
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

PREFLIGHT_PATH = "/internal/settings-execution-preflight"


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


def test_settings_execution_preflight_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(PREFLIGHT_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["record_only"] is True
    assert body["no_execution"] is True
    assert body["dry_run_only"] is True
    assert body["executed"] == 0
    assert body["executable_count"] == 0
    assert body["execution_allowed"] is False
    assert body["future_execution_phase_exists"] is False
    assert body["settings_applied"] is False
    assert body["owner_approved"] is False
    assert body["live_action"] is False
    assert body["outbound_enabled"] is False
    assert body["operator_halt_status"] == HaltStatus.HALTED.value
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_settings_execution_preflight_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(PREFLIGHT_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_settings_execution_preflight_rejects_invalid_key_and_disallows_post(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    denied = api_client.get(
        PREFLIGHT_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        PREFLIGHT_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert denied.status_code == 401
    assert post.status_code == 405


def test_settings_execution_preflight_api_redacts_secrets_and_stays_read_only(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="production",
        internal_api_key="internal-secret",
        openai_api_key=SECRET_VALUE,
    )
    _patch_settings(monkeypatch, settings)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="api-preflight",
        reviewer_notes=f"{PHI_SNIPPET}",
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

    response = api_client.get(
        PREFLIGHT_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_count"] == 1
    assert body["settings_applied"] is False
    assert body["execution_allowed"] is False
    assert body["requests"][0]["decision_status"] == "approved"
    assert body["requests"][0]["executed"] is False
    dumped = response.text
    _assert_no_leakage(dumped, SECRET_VALUE)
    assert PROSPECT_EMAIL not in dumped
    assert PHI_SNIPPET not in dumped
    assert "reviewer_notes" not in dumped
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert (
        db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest))
        == before_requests
    )
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False
