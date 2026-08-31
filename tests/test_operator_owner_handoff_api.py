from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_action_readiness_service import _seed_plans_and_packets
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from vyro_growth.api.operator_owner_handoff import (
    render_owner_handoff,
    render_owner_handoff_error,
)
from vyro_growth.api.operator_ui import OPERATOR_OWNER_HANDOFF_PACKET_PATH
from vyro_growth.api.owner_handoff import (
    HandoffActionReadinessItemResponse,
    HandoffApprovalPacketItemResponse,
    HandoffChecklistItemResponse,
    HandoffSettingsPreflightItemResponse,
    HandoffSettingsRequestItemResponse,
    OwnerHandoffPacketResponse,
)
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import (
    FindingSeverity,
    NextActionCode,
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
SECTION_IDS = (
    "launch-readiness",
    "settings-change-requests",
    "settings-execution-preflight",
    "owner-approval-packets",
    "approved-action-readiness",
    "remaining-manual-owner-checklist",
)


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


def _empty_packet(**overrides: object) -> OwnerHandoffPacketResponse:
    payload: dict[str, object] = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "overall_status": "blocked",
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "launch_readiness": {
            "overall_status": "blocked",
            "operator_halt_status": "halted",
            "ci_smoke_gate_job_name": "smoke-dry-run",
        },
        "settings_change_requests": {},
        "settings_execution_preflight": {"overall_status": "blocked"},
        "owner_approval_packets": {},
        "approved_action_readiness": {},
    }
    payload.update(overrides)
    return OwnerHandoffPacketResponse.model_validate(payload)


def _settings_request(**overrides: object) -> HandoffSettingsRequestItemResponse:
    payload: dict[str, object] = {
        "request_id": uuid4(),
        "request_type": SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        "request_status": "pending",
        "decision_status": SettingsChangeDecisionStatus.PENDING.value,
        "requested_setting_names": ["OUTBOUND_ENABLED"],
        "desired_boolean": False,
        "desired_status": "disabled",
        "finding_code": "safe_defaults",
        "next_action_code": NextActionCode.KEEP_OUTBOUND_DISABLED.value,
        "requested_at": datetime(2026, 8, 31, 11, 0, tzinfo=UTC),
    }
    payload.update(overrides)
    return HandoffSettingsRequestItemResponse.model_validate(payload)


def _preflight_item(**overrides: object) -> HandoffSettingsPreflightItemResponse:
    payload: dict[str, object] = {
        "request_id": uuid4(),
        "request_type": SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        "decision_status": SettingsChangeDecisionStatus.PENDING.value,
        "execution_status": SettingsExecutionPreflightStatus.PENDING_DECISION.value,
        "requested_setting_names": ["OUTBOUND_ENABLED"],
        "desired_boolean": False,
        "desired_status": "disabled",
        "blocker_codes": ["pending_decision", "execution_disabled_in_this_phase"],
        "missing_approval_codes": ["pending_decision"],
        "missing_gate_codes": ["owner_decision_gate"],
        "missing_credential_names": ["EXAMPLE_API_KEY"],
        "closed_provider_flag_names": ["EXAMPLE_LIVE_ENABLED"],
        "requested_at": datetime(2026, 8, 31, 11, 0, tzinfo=UTC),
        "simulated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
    }
    payload.update(overrides)
    return HandoffSettingsPreflightItemResponse.model_validate(payload)


def _packet_item(**overrides: object) -> HandoffApprovalPacketItemResponse:
    payload: dict[str, object] = {
        "packet_id": uuid4(),
        "plan_family": "outreach",
        "preflight_status": "blocked",
        "decision_status": "pending",
        "generated_at": datetime(2026, 8, 31, 10, 0, tzinfo=UTC),
    }
    payload.update(overrides)
    return HandoffApprovalPacketItemResponse.model_validate(payload)


def _candidate(**overrides: object) -> HandoffActionReadinessItemResponse:
    payload: dict[str, object] = {
        "candidate_id": uuid4(),
        "plan_family": "outreach",
        "readiness_status": "blocked",
        "blocker_status": "blocked",
        "review_decision_status": "approved",
        "packet_decision_status": "pending",
        "approval_packet_id": uuid4(),
        "blocker_codes": ["missing_owner_packet_decision"],
        "missing_approval_codes": ["owner_packet_decision"],
        "missing_prerequisite_codes": ["explicit_live_owner_action"],
    }
    payload.update(overrides)
    return HandoffActionReadinessItemResponse.model_validate(payload)


def _checklist(**overrides: object) -> HandoffChecklistItemResponse:
    payload: dict[str, object] = {
        "code": NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value,
        "severity": FindingSeverity.INFO.value,
        "source_section": "owner_handoff",
        "status": "open",
    }
    payload.update(overrides)
    return HandoffChecklistItemResponse.model_validate(payload)


def test_renderer_empty_state_is_read_only_and_has_no_execute_controls() -> None:
    html = render_owner_handoff(_empty_packet())

    assert 'id="operator-owner-handoff-packet"' in html
    assert OPERATOR_OWNER_HANDOFF_PACKET_PATH == "/internal/operator-owner-handoff-packet"
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in html
    assert "No settings-change requests in this packet" in html
    assert "No settings-change requests to simulate" in html
    assert "No owner approval packets in this handoff" in html
    assert "No approved action-readiness candidates" in html
    assert "go_live_permitted=false" in html
    assert "execution_allowed=false" in html
    assert "not permission or machinery for going live" in html
    assert "There are no apply, execute, lift-halt" in html
    assert 'data-execution-allowed="false"' in html
    assert 'data-go-live-permitted="false"' in html
    assert 'data-manual-review-only="true"' in html
    assert 'data-no-execution="true"' in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_renderer_populated_sections_and_xss_escape() -> None:
    request_item = _settings_request(
        requested_setting_names=[XSS_LABEL, "OUTBOUND_ENABLED"],
        finding_code=XSS_LABEL,
    )
    preflight_item = _preflight_item(
        request_id=request_item.request_id,
        requested_setting_names=[XSS_LABEL, "OUTBOUND_ENABLED"],
        blocker_codes=[XSS_LABEL, "pending_decision"],
    )
    packet_item = _packet_item(plan_family=XSS_LABEL)
    candidate = _candidate(blocker_codes=[XSS_LABEL, "missing_owner_packet_decision"])
    checklist = _checklist(code=XSS_LABEL, severity=FindingSeverity.WARNING.value)
    html = render_owner_handoff(
        _empty_packet(
            blocker_codes=["execution_disabled_in_this_phase"],
            missing_credential_names=["EXAMPLE_API_KEY"],
            closed_provider_flag_names=["EXAMPLE_LIVE_ENABLED"],
            launch_readiness={
                "overall_status": "blocked",
                "operator_halt_status": "halted",
                "ci_smoke_gate_job_name": "smoke-dry-run",
                "finding_codes": ["safe_defaults"],
                "blocker_codes": ["outbound_disabled"],
                "next_action_codes": [NextActionCode.KEEP_OUTBOUND_DISABLED.value],
                "missing_credential_names": ["EXAMPLE_API_KEY"],
                "closed_provider_flag_names": ["EXAMPLE_LIVE_ENABLED"],
            },
            settings_change_requests={
                "request_count": 1,
                "pending_count": 1,
                "request_ids": [str(request_item.request_id)],
                "setting_names": ["OUTBOUND_ENABLED"],
                "requests": [request_item],
            },
            settings_execution_preflight={
                "overall_status": "blocked",
                "request_count": 1,
                "pending_decision_count": 1,
                "blocked_count": 1,
                "blocker_codes": ["pending_decision"],
                "missing_credential_names": ["EXAMPLE_API_KEY"],
                "closed_provider_flag_names": ["EXAMPLE_LIVE_ENABLED"],
                "requests": [preflight_item],
            },
            owner_approval_packets={
                "packet_count": 1,
                "pending_count": 1,
                "packet_ids": [str(packet_item.packet_id)],
                "packets": [packet_item],
            },
            approved_action_readiness={
                "candidate_count": 1,
                "blocked_count": 1,
                "candidate_ids": [str(candidate.candidate_id)],
                "candidates": [candidate],
            },
            remaining_manual_owner_checklist=[
                checklist,
                _checklist(code="execution_disabled_in_this_phase"),
            ],
        )
    )
    error = render_owner_handoff_error()

    assert XSS_LABEL not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Launch readiness summary" in html
    assert "Settings change request summary" in html
    assert "Settings execution preflight summary" in html
    assert "Owner approval packet summary" in html
    assert "Approved action readiness summary" in html
    assert "Remaining manual owner checklist" in html
    assert str(request_item.request_id) in html
    assert str(packet_item.packet_id) in html
    assert str(candidate.candidate_id) in html
    assert "EXAMPLE_API_KEY" in html
    assert "EXAMPLE_LIVE_ENABLED" in html
    assert "execution_disabled_in_this_phase" in html
    assert "go live permitted" in html.lower()
    assert "execution allowed" in html.lower()
    assert 'id="operator-owner-handoff-packet-error"' in error
    assert "sk-testsecret" not in error
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()
        assert marker not in error.lower()


def test_operator_owner_handoff_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_OWNER_HANDOFF_PACKET_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Owner go-live handoff packet" in body
    assert "Owner handoff" in body
    assert "Launch readiness summary" in body
    assert "Settings change request summary" in body
    assert "Settings execution preflight summary" in body
    assert "Owner approval packet summary" in body
    assert "Approved action readiness summary" in body
    assert "Remaining manual owner checklist" in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "not permission or machinery for going live" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in FORM_MARKERS:
        assert marker not in body.lower()


def test_operator_owner_handoff_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_OWNER_HANDOFF_PACKET_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_OWNER_HANDOFF_PACKET_PATH)
    invalid = api_client.get(
        OPERATOR_OWNER_HANDOFF_PACKET_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_OWNER_HANDOFF_PACKET_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405


def test_operator_owner_handoff_populated_sections_and_no_side_effects(
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
    _seed_plans_and_packets(db_session)
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="ui-handoff",
        reviewer_notes=PHI_SNIPPET,
    )
    SettingsChangeRequestService().record_decision(
        db_session,
        settings,
        request_id=created.request_id,
        decision="approved",
        reviewer="owner",
    )
    pending = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="ui-handoff-pending",
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

    response = api_client.get(
        OPERATOR_OWNER_HANDOFF_PACKET_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    body = response.text
    assert str(created.request_id) in body
    assert str(pending.request_id) in body
    assert "approved" in body
    assert "OUTBOUND_ENABLED" in body
    assert "execution_disabled_in_this_phase" in body
    assert NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "not permission or machinery for going live" in body
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    _assert_no_leakage(body, SECRET_VALUE)
    assert PHI_SNIPPET not in body
    assert PROSPECT_EMAIL not in body
    assert "reviewer_notes" not in body
    for marker in FORM_MARKERS:
        assert marker not in body.lower()
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


def test_operator_owner_handoff_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(
        "vyro_growth.api.operator_owner_handoff.build_owner_handoff_response",
        _boom,
    )
    response = api_client.get(OPERATOR_OWNER_HANDOFF_PACKET_PATH)

    assert response.status_code == 500
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the owner go-live handoff packet" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()
