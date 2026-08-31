from __future__ import annotations

import json
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

MANIFEST_PATH = "/internal/release-artifact-manifest"


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


def test_release_artifact_manifest_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(MANIFEST_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["packet_kind"] == "release_artifact_manifest"
    assert body["purpose"] == "future_manual_owner_review_only"
    assert body["read_only"] is True
    assert body["no_execution"] is True
    assert body["dry_run_only"] is True
    assert body["executed"] == 0
    assert body["execution_allowed"] is False
    assert body["future_execution_phase_exists"] is False
    assert body["future_deployment_phase_exists"] is False
    assert body["go_live_permitted"] is False
    assert body["deployment_allowed"] is False
    assert body["deployment_attempted"] is False
    assert body["deployed"] is False
    assert body["build_allowed"] is False
    assert body["artifact_publish_allowed"] is False
    assert body["manifest_is_not_a_build_or_deploy"] is True
    assert body["runbook_is_not_deployment"] is True
    assert body["settings_applied"] is False
    assert body["owner_approved"] is False
    assert body["live_action"] is False
    assert body["outbound_enabled"] is False
    assert body["operator_halt_status"] == HaltStatus.HALTED.value
    assert "source_provenance" in body
    assert "artifact_inventory" in body
    assert "migration_inventory" in body
    assert "runtime_command_inventory" in body
    assert "safety_gate_inventory" in body
    assert "no_build_no_deploy" in body
    assert "remaining_manual_owner_checklist" in body
    assert body["source_provenance"]["git_provider_called"] is False
    assert body["source_provenance"]["github_actions_called"] is False
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_release_artifact_manifest_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(MANIFEST_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_release_artifact_manifest_rejects_invalid_key_and_disallows_post(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    denied = api_client.get(
        MANIFEST_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        MANIFEST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert denied.status_code == 401
    assert post.status_code == 405


def test_release_artifact_manifest_api_redacts_secrets_and_stays_read_only(
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
        idempotency_key="api-manifest",
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
        MANIFEST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    dumped = json.dumps(body)
    assert body["read_only"] is True
    assert body["execution_allowed"] is False
    assert body["build_allowed"] is False
    assert body["artifact_publish_allowed"] is False
    assert body["deployment_allowed"] is False
    assert body["manifest_is_not_a_build_or_deploy"] is True
    assert body["owner_approved"] is False
    assert body["settings_applied"] is False
    assert body["halt_changed"] is False
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
