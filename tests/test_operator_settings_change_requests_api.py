from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from vyro_growth.api.operator_settings_change_requests import (
    OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH,
    parse_owner_decision_status,
    parse_request_status,
    parse_request_type,
    render_settings_change_detail,
    render_settings_change_error,
    render_settings_change_list,
    render_settings_change_missing,
)
from vyro_growth.api.settings_change_requests import (
    SettingsChangeRequestListResponse,
    SettingsChangeRequestResponse,
)
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import (
    SettingsChangeDecisionStatus,
    SettingsChangeRequestStatus,
    SettingsChangeRequestType,
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


def _empty_queue(**overrides: object) -> SettingsChangeRequestListResponse:
    payload = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "requests": [],
    }
    payload.update(overrides)
    return SettingsChangeRequestListResponse.model_validate(payload)


def _request(**overrides: object) -> SettingsChangeRequestResponse:
    payload = {
        "request_id": uuid4(),
        "request_type": SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        "status": SettingsChangeRequestStatus.PENDING.value,
        "owner_decision_status": SettingsChangeDecisionStatus.PENDING.value,
        "idempotency_key": "scr-keep-outbound",
        "requested_setting_names": ["OUTBOUND_ENABLED"],
        "desired_boolean": False,
        "desired_status": "disabled",
        "finding_code": "safe_defaults",
        "next_action_code": "keep_outbound_disabled",
        "source": "cli",
        "requested_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
    }
    payload.update(overrides)
    return SettingsChangeRequestResponse.model_validate(payload)


def escape_marker() -> str:
    return "&lt;script&gt;alert(1)&lt;/script&gt;"


def _seed_request(db: Session, **overrides: object) -> LiveSettingsChangeRequest:
    set_operator_halt(db, halted=True, reason="keep-halted")
    payload = {
        "request_type": SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        "requested_setting_names": ["OUTBOUND_ENABLED"],
        "desired_boolean": False,
        "desired_status": "disabled",
        "idempotency_key": "ui-keep-outbound",
    }
    payload.update(overrides)
    view = SettingsChangeRequestService().create(db, Settings(), **payload)
    row = db.get(LiveSettingsChangeRequest, view.request_id)
    assert row is not None
    return row


def test_parse_settings_change_filters_ignore_unknown_values() -> None:
    assert parse_request_type(None) is None
    assert parse_request_type("keep_outbound_disabled") == "keep_outbound_disabled"
    assert parse_request_type("apply_now") is None
    assert parse_request_status("pending") == "pending"
    assert parse_request_status("../secrets") is None
    assert parse_owner_decision_status("approved") == "approved"
    assert parse_owner_decision_status("execute") is None


def test_renderer_empty_state_is_read_only() -> None:
    html = render_settings_change_list(
        _empty_queue(),
        request_type=None,
        status=None,
        owner_decision_status=None,
        requests=[],
    )

    assert 'id="operator-settings-change-requests"' in html
    assert "No live settings change requests yet" in html
    assert "There are no apply, execute, enable outbound, or lift-halt controls" in html
    assert "/internal/launch-readiness" in html
    assert "/internal/operator-settings-execution-preflight" in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_renderer_populated_filter_and_xss_escape() -> None:
    item = _request(finding_code=XSS_LABEL, requested_setting_names=["OUTBOUND_ENABLED"])
    other = _request(
        request_type=SettingsChangeRequestType.KEEP_SAFE_DEFAULT.value,
        requested_setting_names=["OPERATOR_HALT"],
    )
    html = render_settings_change_list(
        _empty_queue(request_count=2, pending_count=2, requests=[item, other]),
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        status=None,
        owner_decision_status=None,
        requests=[item],
    )

    assert XSS_LABEL not in html
    assert escape_marker() in html
    assert str(item.request_id) in html
    assert str(other.request_id) not in html
    assert "request_type=keep_outbound_disabled" in html
    assert "OUTBOUND_ENABLED" in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_detail_renderer_and_missing_pages_are_safe() -> None:
    html = render_settings_change_detail(
        _request(
            source=XSS_LABEL,
            finding_code="safe_defaults",
            next_action_code="keep_outbound_disabled",
        )
    )
    missing = render_settings_change_missing()
    error = render_settings_change_error()

    assert 'id="operator-settings-change-request"' in html
    assert 'data-decision-record-only="true"' in html
    assert "/internal/operator-settings-execution-preflight" in html
    assert XSS_LABEL not in html
    assert escape_marker() in html
    assert "OUTBOUND_ENABLED" in html
    assert "Record owner decision" in html
    assert 'id="operator-settings-change-decision-form"' in html
    assert "There is no apply, execute, enable outbound, or lift-halt control" in html
    assert 'id="operator-settings-change-requests-missing"' in missing
    assert 'id="operator-settings-change-requests-error"' in error
    assert "sk-testsecret12345" not in error
    for marker in ACTION_MARKERS:
        assert marker not in html.lower()
        assert marker not in missing.lower()
        assert marker not in error.lower()
    for marker in FORM_MARKERS:
        assert marker not in missing.lower()
        assert marker not in error.lower()


def test_settings_change_ui_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Live settings change requests" in body
    assert "No live settings change requests yet" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in body.lower()


def test_settings_change_ui_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_settings_change_ui_rejects_missing_and_invalid_key_and_disallows_post(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    missing = api_client.get(OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH)
    assert missing.status_code == 401

    post = api_client.post(
        OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    assert post.status_code == 405

    invalid = api_client.get(
        OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    assert invalid.status_code == 401


def test_settings_change_ui_populated_filters_and_detail_stay_record_only(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    row = _seed_request(db_session)
    SettingsChangeRequestService().create(
        db_session,
        Settings(),
        request_type=SettingsChangeRequestType.KEEP_SAFE_DEFAULT.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        desired_boolean=False,
        desired_status="disabled",
        idempotency_key="ui-keep-safe",
    )
    before_requests = db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest))
    before_activities = db_session.scalar(select(func.count()).select_from(Activity))
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting))
    before_enrollments = db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage))
    headers = {"X-Internal-Api-Key": "internal-secret"}

    listed = api_client.get(OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH, headers=headers)
    filtered = api_client.get(
        f"{OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH}"
        "?request_type=keep_outbound_disabled&status=pending",
        headers=headers,
    )
    detail = api_client.get(
        f"{OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH}/{row.id}",
        headers=headers,
    )
    missing = api_client.get(
        f"{OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH}/{uuid4()}",
        headers=headers,
    )
    invalid = api_client.get(
        f"{OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH}/not-a-uuid",
        headers=headers,
    )

    assert listed.status_code == 200
    assert str(row.id) in listed.text
    assert "OUTBOUND_ENABLED" in listed.text
    assert "keep_outbound_disabled" in listed.text or "keep outbound disabled" in listed.text
    assert filtered.status_code == 200
    assert str(row.id) in filtered.text
    assert detail.status_code == 200
    assert "Settings change request" in detail.text
    assert "OUTBOUND_ENABLED" in detail.text
    assert "Record owner decision" in detail.text
    assert "There is no apply, execute, enable outbound, or lift-halt control" in detail.text
    assert "Settings applied=no" in listed.text or "settings applied=no" in listed.text.lower()
    assert missing.status_code == 404
    assert invalid.status_code == 404
    assert PHI_SNIPPET not in listed.text
    assert PROSPECT_EMAIL not in listed.text
    assert "diabetes" not in listed.text.lower()
    assert "sk-testsecret12345" not in listed.text
    for body in (listed.text, filtered.text, missing.text):
        for marker in ACTION_MARKERS + FORM_MARKERS:
            assert marker not in body.lower()
    for marker in ACTION_MARKERS:
        assert marker not in detail.text.lower()
    assert (
        db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest))
        == before_requests
    )
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    db_session.refresh(row)
    assert row.settings_applied is False
    assert row.executed is False
    assert row.owner_approved is False
    assert row.halt_changed is False


def test_settings_change_ui_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def boom(*_args: object, **_kwargs: object) -> SettingsChangeRequestListResponse:
        raise RuntimeError("db exploded sk-testsecret12345 patient diabetes")

    monkeypatch.setattr(
        "vyro_growth.api.operator_settings_change_requests.build_settings_change_list_response",
        boom,
    )

    response = api_client.get(OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH)

    assert response.status_code == 500
    body = " ".join(response.text.split())
    assert "Unable to load live settings change requests" in body
    assert "sk-testsecret12345" not in body
    assert "diabetes" not in body.lower()
    assert "No pipeline rows were written" in body
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in response.text.lower()


def test_settings_change_ui_unknown_filter_does_not_mutate(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = db_session.scalar(select(func.count()).select_from(Activity))

    response = api_client.get(
        f"{OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH}?request_type=apply&status=go"
    )

    assert response.status_code == 200
    assert "No live settings change requests yet" in response.text
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
