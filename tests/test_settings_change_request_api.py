from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import SettingsChangeRequestType
from vyro_growth.main import app
from vyro_growth.models import Activity, LiveSettingsChangeRequest
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

QUEUE_PATH = "/internal/settings-change-requests"
PROPOSE_PATH = "/internal/settings-change-requests/propose-from-launch-readiness"


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


def test_settings_change_queue_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(QUEUE_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["record_only"] is True
    assert body["no_execution"] is True
    assert body["executed"] == 0
    assert body["settings_applied"] is False
    assert body["live_action"] is False
    assert body["owner_approved"] is False
    assert body["operator_halt_status"] == HaltStatus.HALTED.value


def test_settings_change_queue_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(QUEUE_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_create_list_detail_decision_and_idempotency(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(
            environment="production",
            internal_api_key="internal-secret",
            openai_api_key=SECRET_VALUE,
        ),
    )
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    headers = {"X-Internal-Api-Key": "internal-secret"}
    payload = {
        "request_type": SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        "requested_setting_names": ["OUTBOUND_ENABLED"],
        "idempotency_key": "api-keep-outbound",
    }

    created = api_client.post(QUEUE_PATH, json=payload, headers=headers)
    reused = api_client.post(QUEUE_PATH, json=payload, headers=headers)
    listed = api_client.get(QUEUE_PATH, headers=headers)

    assert created.status_code == 200
    body = created.json()
    request_id = body["request_id"]
    assert reused.status_code == 200
    assert reused.json()["reused"] is True
    assert reused.json()["request_id"] == request_id
    assert listed.json()["request_count"] == 1
    _assert_no_leakage(created.text + reused.text + listed.text, SECRET_VALUE, "internal-secret")

    detail = api_client.get(f"{QUEUE_PATH}/{request_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["settings_applied"] is False

    decided = api_client.post(
        f"{QUEUE_PATH}/{request_id}/decision",
        json={"decision": "approved", "reviewer": "owner"},
        headers=headers,
    )
    assert decided.status_code == 200
    decision_body = decided.json()
    assert decision_body["owner_decision_status"] == "approved"
    assert decision_body["owner_approved"] is False
    assert decision_body["settings_applied"] is False
    assert decision_body["halt_changed"] is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) == 1


def test_propose_from_launch_readiness_and_missing_detail(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    headers = {"X-Internal-Api-Key": "internal-secret"}
    before_activities = int(db_session.scalar(select(func.count()).select_from(Activity)) or 0)

    proposed = api_client.post(PROPOSE_PATH, headers=headers)
    missing = api_client.get(f"{QUEUE_PATH}/{uuid4()}", headers=headers)
    denied = api_client.get(QUEUE_PATH, headers={"X-Internal-Api-Key": "wrong-secret"})

    assert proposed.status_code == 200
    body = proposed.json()
    assert body["created_count"] >= 1
    assert body["settings_applied"] is False
    assert body["live_action"] is False
    assert body["owner_approved"] is False
    assert missing.status_code == 404
    assert denied.status_code == 401
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert db_session.scalar(select(func.count()).select_from(Activity)) >= before_activities


def test_rejects_secret_payload(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="development", internal_api_key=""),
    )
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.post(
        QUEUE_PATH,
        json={
            "request_type": "request_credential_configuration_review",
            "requested_setting_names": ["OPENAI_API_KEY"],
            "reviewer_notes": f"key={SECRET_VALUE}",
        },
    )

    assert response.status_code == 400
    assert "secret" in response.json()["detail"].lower()
    assert SECRET_VALUE not in response.text
    assert db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) == 0
    assert read_operator_halt(db_session) is HaltStatus.HALTED
