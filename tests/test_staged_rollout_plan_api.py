from __future__ import annotations

import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from tests.test_staged_rollout_plan_service import _assert_no_execution
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import SettingsChangeRequestType
from vyro_growth.main import app
from vyro_growth.models import Activity, LiveSettingsChangeRequest
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

PLAN_PATH = "/internal/staged-rollout-plan"


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


def test_staged_rollout_plan_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(PLAN_PATH)

    assert response.status_code == 200
    body = response.json()
    _assert_no_execution(body)
    assert body["read_only"] is True
    assert body["no_execution"] is True
    assert body["dry_run_only"] is True
    assert body["executed"] == 0
    assert body["outbound_enabled"] is False
    assert body["operator_halt_status"] == HaltStatus.HALTED.value
    assert body["source_index_command"] == "go-live-readiness-index"
    assert body["source_blockers_plan_command"] == "launch-blockers-plan"
    assert body["source_runbook_command"] == "release-candidate-runbook"
    assert body["source_binder_command"] == "compliance-evidence-binder"
    assert body["source_manifest_command"] == "release-artifact-manifest"
    assert "stages" in body
    assert "local_git" in body
    assert body["local_git"]["git_provider_called"] is False
    assert body["local_git"]["github_actions_called"] is False
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_staged_rollout_plan_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(PLAN_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_staged_rollout_plan_rejects_invalid_key_and_disallows_post(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    denied = api_client.get(
        PLAN_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert denied.status_code == 401
    assert post.status_code == 405


def test_staged_rollout_plan_api_redacts_secrets_and_stays_read_only(
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
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="api-staged-plan",
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

    response = api_client.get(
        PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    dumped = json.dumps(body)
    _assert_no_execution(body)
    assert body["read_only"] is True
    assert body["execution_allowed"] is False
    assert body["deployment_allowed"] is False
    assert body["settings_applied"] is False
    assert body["halt_changed"] is False
    assert body["owner_approved"] is False
    assert body["staged_rollout_plan_is_not_go_live"] is True
    assert body["plan_is_not_permission_to_go_live"] is True
    assert SECRET_VALUE not in dumped
    assert PHI_SNIPPET not in dumped
    assert PROSPECT_EMAIL not in dumped
    _assert_no_leakage(dumped, SECRET_VALUE)
    assert int(db_session.scalar(select(func.count()).select_from(Activity)) or 0) == (
        before_activities
    )
    assert int(
        db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) or 0
    ) == before_requests
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False
