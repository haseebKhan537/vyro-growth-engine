from __future__ import annotations

import json
from collections.abc import Generator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.decision_makers import candidate
from tests.test_contact_enrichment_service import _org, _service
from tests.test_contact_validation_service import (
    NPI,
    PRACTICE_NAME,
    PROSPECT_EMAIL,
    PROSPECT_PHONE,
    SECRET_VALUE,
)
from tests.test_live_provider_setup_checklist_service import _assert_no_execution
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import ContactVerificationStatus
from vyro_growth.main import app
from vyro_growth.models import Activity, CampaignEnrollment, Meeting, OutreachMessage
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

CHECKLIST_PATH = "/internal/live-provider-setup-checklist"


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


def test_checklist_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(CHECKLIST_PATH)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    _assert_no_execution(body)
    assert body["outbound_enabled"] is False
    assert body["owner_approved"] is False
    assert body["validation_permitted"] is False
    assert body["supervised_validation_run_permitted"] is False
    assert body["operator_halt_status"] == HaltStatus.HALTED.value
    assert body["operator_halt_before"] == HaltStatus.HALTED.value
    assert body["operator_halt_after"] == HaltStatus.HALTED.value
    assert body["operator_halt_unchanged"] is True
    assert body["source_provider_setup_command"] == "provider-setup-checklist"
    assert body["source_launch_readiness_command"] == "launch-readiness"
    assert body["source_validation_packet_command"] == "supervised-validation-run-packet"
    assert body["source_preflight_command"] == "settings-execution-preflight"
    assert body["source_binder_command"] == "compliance-evidence-binder"
    assert "provider_accounts" in body
    assert "required_credentials" in body
    assert "required_configs" in body
    assert "owner_decisions" in body
    assert "budget_rate_limits" in body
    assert "compliance_prerequisites" in body
    assert "validation_run_constraints" in body
    assert "next_actions" in body
    assert "local_git" in body
    assert body["local_git"]["git_provider_called"] is False
    assert body["local_git"]["github_actions_called"] is False
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_checklist_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(CHECKLIST_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_checklist_rejects_invalid_key_and_disallows_post(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    denied = api_client.get(
        CHECKLIST_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        CHECKLIST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert denied.status_code == 401
    assert post.status_code == 405


def test_checklist_api_redacts_secrets_and_stays_read_only(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="production",
        internal_api_key="internal-secret",
        voice_api_key=SECRET_VALUE,
        decision_maker_api_key=SECRET_VALUE,
    )
    _patch_settings(monkeypatch, settings)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    organization = _org(db_session)
    _service(
        [
            candidate(
                business_email=PROSPECT_EMAIL,
                verification_status=ContactVerificationStatus.PROVIDER_VERIFIED,
            )
        ]
    ).enrich_organization(db_session, organization.id)

    def _forbid_http(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("live provider HTTP is forbidden")

    monkeypatch.setattr(httpx, "Client", _forbid_http)
    monkeypatch.setattr(httpx, "AsyncClient", _forbid_http)

    before_activities = int(db_session.scalar(select(func.count()).select_from(Activity)) or 0)
    before_meetings = int(db_session.scalar(select(func.count()).select_from(Meeting)) or 0)
    before_enrollments = int(
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0
    )
    before_messages = int(
        db_session.scalar(select(func.count()).select_from(OutreachMessage)) or 0
    )
    before_halt = read_operator_halt(db_session)

    response = api_client.get(
        CHECKLIST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    dumped = json.dumps(body)
    _assert_no_execution(body)
    assert body["execution_allowed"] is False
    assert body["owner_approved"] is False
    assert body["validation_permitted"] is False
    assert body["supervised_validation_run_permitted"] is False
    assert body["halt_changed"] is False
    assert body["operator_halt_unchanged"] is True
    assert SECRET_VALUE not in dumped
    assert PROSPECT_EMAIL not in dumped
    assert PROSPECT_PHONE not in dumped
    assert PRACTICE_NAME not in dumped
    assert NPI not in dumped
    assert "email" not in body
    assert "phone" not in body
    assert "npi" not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert read_operator_halt(db_session) is before_halt
    assert settings.outbound_enabled is False
