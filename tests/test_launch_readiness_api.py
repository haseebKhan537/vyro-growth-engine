from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_action_readiness_service import _seed_plans_and_packets
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import FindingCode, LaunchReadinessStatus, SecretPresenceStatus
from vyro_growth.main import app
from vyro_growth.models import Activity
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

LAUNCH_READINESS_PATH = "/internal/launch-readiness"


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


def test_launch_readiness_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(LAUNCH_READINESS_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["no_execution"] is True
    assert body["executed"] == 0
    assert body["live_action"] is False
    assert body["owner_approved"] is False
    assert body["outbound_enabled"] is False
    assert body["operator_halt_status"] == HaltStatus.HALTED.value
    assert body["overall_status"] == LaunchReadinessStatus.WARNING.value
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_launch_readiness_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(LAUNCH_READINESS_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_launch_readiness_rejects_invalid_key_and_disallows_post(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    denied = api_client.get(
        LAUNCH_READINESS_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        LAUNCH_READINESS_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert denied.status_code == 401
    assert post.status_code == 405


def test_launch_readiness_api_redacts_secrets_and_reports_pending_packets(
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
    _seed_plans_and_packets(db_session)
    before_activities = int(db_session.scalar(select(func.count()).select_from(Activity)) or 0)

    response = api_client.get(
        LAUNCH_READINESS_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    dumped = response.text
    assert body["pending_owner_approval_packets"] > 0
    assert body["action_readiness_blocked_count"] > 0
    assert FindingCode.PENDING_OWNER_APPROVAL_PACKETS.value in {
        item["code"] for item in body["findings"]
    }
    openai = next(item for item in body["secret_inventory"] if item["name"] == "OPENAI_API_KEY")
    assert openai["present"] is True
    assert openai["status"] == SecretPresenceStatus.REDACTED.value
    _assert_no_leakage(dumped, SECRET_VALUE, "internal-secret")
    assert PROSPECT_EMAIL not in dumped
    assert PHI_SNIPPET not in dumped
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
