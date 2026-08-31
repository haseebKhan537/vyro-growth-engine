from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from vyro_growth.api.operator_settings_execution_preflight import (
    OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
    parse_decision_status,
    parse_execution_status,
    parse_request_type,
    render_settings_execution_preflight,
    render_settings_execution_preflight_error,
)
from vyro_growth.api.operator_ui import (
    OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH as PREFLIGHT_PATH,
)
from vyro_growth.api.settings_execution_preflight import (
    SettingsExecutionPreflightItemResponse,
    SettingsExecutionPreflightResponse,
)
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import (
    SettingsChangeDecisionStatus,
    SettingsChangeRequestType,
    SettingsExecutionPreflightStatus,
)
from vyro_growth.main import app
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    LiveSettingsChangeRequest,
    Meeting,
    OutreachMessage,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

XSS_LABEL = "<script>alert(1)</script>"
ACTION_MARKERS = ("javascript:", "onclick=", "onerror=")
FORM_MARKERS = ("<form", "<button", "<input", "<select", "<textarea")


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


def _empty_preflight(**overrides: object) -> SettingsExecutionPreflightResponse:
    payload = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "overall_status": SettingsExecutionPreflightStatus.BLOCKED.value,
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "requests": [],
    }
    payload.update(overrides)
    return SettingsExecutionPreflightResponse.model_validate(payload)


def _item(**overrides: object) -> SettingsExecutionPreflightItemResponse:
    payload = {
        "request_id": uuid4(),
        "request_type": SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        "request_status": "pending",
        "decision_status": SettingsChangeDecisionStatus.PENDING.value,
        "requested_setting_names": ["OUTBOUND_ENABLED"],
        "desired_boolean": False,
        "desired_status": "disabled",
        "execution_status": SettingsExecutionPreflightStatus.PENDING_DECISION.value,
        "blocker_codes": ["pending_decision", "execution_disabled_in_this_phase"],
        "missing_approval_codes": ["pending_decision"],
        "missing_gate_codes": ["owner_decision_gate"],
        "missing_credential_names": ["EXAMPLE_API_KEY"],
        "closed_provider_flag_names": ["EXAMPLE_LIVE_ENABLED"],
        "requested_at": datetime(2026, 8, 31, 11, 0, tzinfo=UTC),
        "simulated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
    }
    payload.update(overrides)
    return SettingsExecutionPreflightItemResponse.model_validate(payload)


def test_parse_preflight_filters_ignore_unknown_values() -> None:
    assert parse_request_type(None) is None
    assert parse_request_type("keep_outbound_disabled") == "keep_outbound_disabled"
    assert parse_request_type("apply_now") is None
    assert parse_decision_status("approved") == "approved"
    assert parse_decision_status("execute") is None
    assert parse_execution_status("pending_decision") == "pending_decision"
    assert parse_execution_status("ready_to_apply") is None
    assert parse_execution_status("../secrets") is None
    assert PREFLIGHT_PATH == OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH


def test_renderer_empty_state_is_read_only_and_has_no_execute_controls() -> None:
    html = render_settings_execution_preflight(
        _empty_preflight(),
        request_type=None,
        decision_status=None,
        execution_status=None,
    )

    assert 'id="operator-settings-execution-preflight"' in html
    assert "No settings-change requests to simulate" in html
    assert "not permission or machinery for going live" in html
    assert "There are no apply, execute, lift-halt" in html
    assert 'data-execution-allowed="false"' in html
    assert 'data-dry-run-only="true"' in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_renderer_populated_filters_and_xss_escape() -> None:
    item = _item(
        requested_setting_names=[XSS_LABEL, "OUTBOUND_ENABLED"],
        blocker_codes=[XSS_LABEL, "pending_decision"],
    )
    html = render_settings_execution_preflight(
        _empty_preflight(
            request_count=1,
            pending_decision_count=1,
            blocked_count=1,
            requests=[item],
            blocker_codes=["pending_decision"],
            missing_credential_names=["EXAMPLE_API_KEY"],
            closed_provider_flag_names=["EXAMPLE_LIVE_ENABLED"],
        ),
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        decision_status=SettingsChangeDecisionStatus.PENDING.value,
        execution_status=SettingsExecutionPreflightStatus.PENDING_DECISION.value,
    )
    error = render_settings_execution_preflight_error()

    assert XSS_LABEL not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "pending_decision" in html
    assert "EXAMPLE_API_KEY" in html
    assert "EXAMPLE_LIVE_ENABLED" in html
    assert "execution_allowed" in html.lower() or "Execution allowed" in html
    assert "no" in html
    assert 'id="operator-settings-execution-preflight-error"' in error
    assert "sk-testsecret" not in error
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()
        assert marker not in error.lower()


def test_operator_settings_execution_preflight_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Settings execution preflight" in body
    assert "Settings preflight" in body
    assert "No settings-change requests to simulate" in body
    assert "execution allowed" in body.lower()
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in FORM_MARKERS:
        assert marker not in body.lower()


def test_operator_settings_execution_preflight_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH)
    invalid = api_client.get(
        OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405


def test_operator_settings_execution_preflight_populated_filters_and_no_side_effects(
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
        idempotency_key="ui-preflight",
        reviewer_notes=f"{PHI_SNIPPET} {PROSPECT_EMAIL}",
    )
    SettingsChangeRequestService().record_decision(
        db_session,
        settings,
        request_id=created.request_id,
        decision="approved",
        reviewer="owner",
    )
    other = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="ui-preflight-pending",
    )
    before_activities = int(db_session.scalar(select(func.count()).select_from(Activity)) or 0)
    before_meetings = int(db_session.scalar(select(func.count()).select_from(Meeting)) or 0)
    before_enrollments = int(
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0
    )
    before_messages = int(db_session.scalar(select(func.count()).select_from(OutreachMessage)) or 0)
    before_requests = int(
        db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) or 0
    )

    listed = api_client.get(
        OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    filtered = api_client.get(
        OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
        params={"decision_status": SettingsChangeDecisionStatus.APPROVED.value},
    )
    unknown_filter = api_client.get(
        OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
        params={"execution_status": "ready_to_apply"},
    )

    assert listed.status_code == 200
    assert filtered.status_code == 200
    assert unknown_filter.status_code == 200
    assert str(created.request_id) in listed.text
    assert str(other.request_id) in listed.text
    assert str(created.request_id) in filtered.text
    assert str(other.request_id) not in filtered.text
    assert str(created.request_id) in unknown_filter.text
    assert "approved" in filtered.text
    assert "execution_disabled_in_this_phase" in listed.text
    assert "not permission or machinery for going live" in listed.text
    _assert_no_leakage(listed.text, SECRET_VALUE)
    assert PHI_SNIPPET not in listed.text
    assert PROSPECT_EMAIL not in listed.text
    assert "reviewer_notes" not in listed.text
    for marker in FORM_MARKERS:
        assert marker not in listed.text.lower()
        assert marker not in filtered.text.lower()
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert (
        db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest))
        == before_requests
    )
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False


def test_operator_settings_execution_preflight_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(
        "vyro_growth.api.operator_settings_execution_preflight"
        ".build_settings_execution_preflight_response",
        _boom,
    )
    response = api_client.get(OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH)

    assert response.status_code == 500
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the settings execution preflight" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()
