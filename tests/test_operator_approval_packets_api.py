from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_approval_packet_service import _approve_all_families
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from vyro_growth.api.approval_packets import ApprovalPacketResponse, ApprovalPacketRunResponse
from vyro_growth.api.operator_approval_packets import (
    OPERATOR_APPROVAL_PACKETS_PATH,
    parse_plan_family,
    parse_preflight_status,
    render_approval_packet_detail,
    render_approval_packet_list,
    render_approval_packet_missing,
    render_approval_packets_error,
)
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import ExecutionPlanType, PreflightStatus
from vyro_growth.main import app
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    Meeting,
    OutreachMessage,
    OwnerApprovalPacket,
)
from vyro_growth.services.approval_packets import ApprovalPacketService
from vyro_growth.services.execution_planning import ExecutionPlanningService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

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


def _empty_run(**overrides: object) -> ApprovalPacketRunResponse:
    payload = {
        "status": "not_started",
        "packet_count": 0,
        "packets": [],
    }
    payload.update(overrides)
    return ApprovalPacketRunResponse.model_validate(payload)


def _packet(**overrides: object) -> ApprovalPacketResponse:
    payload = {
        "id": uuid4(),
        "source_execution_plan_id": uuid4(),
        "source_execution_plan_run_id": uuid4(),
        "source_artifact_type": "optimizer_recommendation",
        "source_artifact_id": uuid4(),
        "plan_family": ExecutionPlanType.OPTIMIZER_APPLY.value,
        "proposed_action": "Prepare later owner-approved action",
        "preflight_status": PreflightStatus.BLOCKED.value,
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "idempotency_key": "abc123",
        "preflight_checklist": [
            {
                "code": "execution_plan_present",
                "label": "Source dry-run execution plan is present",
                "met": True,
            }
        ],
        "findings": [
            {
                "severity": "blocked",
                "code": "execution_disabled_in_this_phase",
                "message": "Phase 18 records an approval packet only and does not execute",
            }
        ],
        "required_owner_decisions": ["Owner approval before applying an optimizer recommendation"],
    }
    payload.update(overrides)
    return ApprovalPacketResponse.model_validate(payload)


def escape_marker() -> str:
    return "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_parse_packet_filters_ignore_unknown_values() -> None:
    assert parse_plan_family(None) is None
    assert parse_plan_family("outreach_enrollment") == "outreach_enrollment"
    assert parse_plan_family("execute") is None
    assert parse_preflight_status("blocked") == "blocked"
    assert parse_preflight_status("../secrets") is None


def test_renderer_empty_state_is_read_only() -> None:
    html = render_approval_packet_list(
        _empty_run(),
        plan_family=None,
        preflight_status=None,
        packets=[],
    )

    assert 'id="operator-approval-packets"' in html
    assert "No owner approval packets" in html
    assert "There are no approve, reject, or execute controls" in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_renderer_populated_filter_and_xss_escape() -> None:
    packet = _packet(proposed_action=XSS_LABEL)
    other = _packet(plan_family=ExecutionPlanType.BOOKING.value, proposed_action="Booking packet")
    html = render_approval_packet_list(
        _empty_run(packet_count=2, status="completed", packets=[packet, other]),
        plan_family=ExecutionPlanType.OPTIMIZER_APPLY.value,
        preflight_status=None,
        packets=[packet],
    )

    assert XSS_LABEL not in html
    assert escape_marker() in html
    assert str(packet.id) in html
    assert str(other.id) not in html
    assert "plan_family=optimizer_apply" in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_detail_renderer_and_missing_pages_are_safe() -> None:
    html = render_approval_packet_detail(
        _packet(
            proposed_action=XSS_LABEL,
            required_owner_decisions=[XSS_LABEL],
            findings=[
                {"severity": "blocked", "code": "owner_decision_required", "message": XSS_LABEL}
            ],
        )
    )
    missing = render_approval_packet_missing()
    error = render_approval_packets_error()

    assert 'id="operator-approval-packet"' in html
    assert 'data-decision-record-only="true"' in html
    assert XSS_LABEL not in html
    assert escape_marker() in html
    assert "Required owner decision labels" in html
    assert "Record owner decision" in html
    assert 'id="operator-approval-packet-decision-form"' in html
    assert "There is no execute control" in html
    assert 'id="operator-approval-packets-missing"' in missing
    assert 'id="operator-approval-packets-error"' in error
    assert "sk-testsecret12345" not in error
    for marker in ACTION_MARKERS:
        assert marker not in html.lower()
        assert marker not in missing.lower()
        assert marker not in error.lower()
    for marker in FORM_MARKERS:
        assert marker not in missing.lower()
        assert marker not in error.lower()


def test_approval_packets_ui_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.get(OPERATOR_APPROVAL_PACKETS_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Owner approval packets" in body
    assert "No owner approval packets" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in body.lower()


def test_approval_packets_ui_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(OPERATOR_APPROVAL_PACKETS_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_approval_packets_ui_rejects_missing_and_invalid_key_and_disallows_post(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    missing = api_client.get(OPERATOR_APPROVAL_PACKETS_PATH)
    assert missing.status_code == 401

    post = api_client.post(
        OPERATOR_APPROVAL_PACKETS_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    assert post.status_code == 405

    invalid = api_client.get(
        OPERATOR_APPROVAL_PACKETS_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    assert invalid.status_code == 401


def test_approval_packets_ui_populated_filters_and_detail_stay_read_only(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    _approve_all_families(db_session)
    ExecutionPlanningService().generate(db_session, Settings())
    ApprovalPacketService().generate(db_session, Settings())
    packet = db_session.scalars(select(OwnerApprovalPacket)).first()
    assert packet is not None
    before_packets = db_session.scalar(select(func.count()).select_from(OwnerApprovalPacket))
    before_activities = db_session.scalar(select(func.count()).select_from(Activity))
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting))
    before_enrollments = db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage))

    listed = api_client.get(
        OPERATOR_APPROVAL_PACKETS_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    filtered = api_client.get(
        f"{OPERATOR_APPROVAL_PACKETS_PATH}?plan_family={packet.plan_family}&preflight_status=blocked",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    detail = api_client.get(
        f"{OPERATOR_APPROVAL_PACKETS_PATH}/{packet.id}",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    missing = api_client.get(
        f"{OPERATOR_APPROVAL_PACKETS_PATH}/{uuid4()}",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    invalid = api_client.get(
        f"{OPERATOR_APPROVAL_PACKETS_PATH}/not-a-uuid",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert listed.status_code == 200
    assert str(packet.id) in listed.text
    assert "blocked=" in listed.text
    assert filtered.status_code == 200
    assert str(packet.id) in filtered.text
    assert detail.status_code == 200
    assert "Approval packet" in detail.text
    assert packet.plan_family.replace("_", " ") in detail.text or packet.plan_family in detail.text
    assert "Required owner decision labels" in detail.text
    assert "Record owner decision" in detail.text
    assert "There is no execute control" in detail.text
    assert "There are no approve, reject, or execute controls" in listed.text
    assert "Executed=0" in listed.text or "executed=no" in listed.text
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
        db_session.scalar(select(func.count()).select_from(OwnerApprovalPacket))
        == before_packets
    )
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_approval_packets_ui_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def boom(*_args: object, **_kwargs: object) -> ApprovalPacketRunResponse:
        raise RuntimeError("db exploded sk-testsecret12345 patient diabetes")

    monkeypatch.setattr(
        "vyro_growth.api.operator_approval_packets.ApprovalPacketService.latest",
        boom,
    )

    response = api_client.get(OPERATOR_APPROVAL_PACKETS_PATH)

    assert response.status_code == 500
    body = " ".join(response.text.split())
    assert "Unable to load owner approval packets" in body
    assert "sk-testsecret12345" not in body
    assert "diabetes" not in body.lower()
    assert "No pipeline rows were written" in body
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in response.text.lower()


def test_approval_packets_ui_unknown_filter_does_not_mutate(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = db_session.scalar(select(func.count()).select_from(Activity))

    response = api_client.get(
        f"{OPERATOR_APPROVAL_PACKETS_PATH}?plan_family=execute&preflight_status=go"
    )

    assert response.status_code == 200
    assert "No owner approval packets" in response.text
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
