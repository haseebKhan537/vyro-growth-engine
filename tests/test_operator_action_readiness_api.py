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
from vyro_growth.api.action_readiness import (
    ActionReadinessCandidateResponse,
    ActionReadinessQueueResponse,
)
from vyro_growth.api.operator_action_readiness import (
    OPERATOR_ACTION_READINESS_PATH,
    parse_blocker_status,
    parse_decision_status,
    parse_plan_family,
    parse_readiness_status,
    render_action_readiness_detail,
    render_action_readiness_error,
    render_action_readiness_list,
    render_action_readiness_missing,
)
from vyro_growth.api.operator_ui import OPERATOR_ACTION_READINESS_PATH as READINESS_PATH
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import (
    ActionReadinessStatus,
    ExecutionPlanType,
)
from vyro_growth.main import app
from vyro_growth.models import Activity, CampaignEnrollment, Meeting, OutreachMessage
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


def _empty_queue(**overrides: object) -> ActionReadinessQueueResponse:
    payload = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "candidates": [],
    }
    payload.update(overrides)
    return ActionReadinessQueueResponse.model_validate(payload)


def _candidate(**overrides: object) -> ActionReadinessCandidateResponse:
    payload = {
        "candidate_id": uuid4(),
        "artifact_type": "optimizer_recommendation",
        "artifact_id": uuid4(),
        "plan_family": ExecutionPlanType.OPTIMIZER_APPLY.value,
        "sanitized_label": "Prepare later owner-approved action",
        "review_decision_status": "approved",
        "packet_decision_status": "missing",
        "preflight_status": "blocked",
        "readiness_status": ActionReadinessStatus.MISSING_OWNER_PACKET_DECISION.value,
        "blocker_status": "blocked",
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "blocker_codes": ["execution_disabled_in_this_phase"],
        "missing_approval_codes": ["missing_owner_packet_decision"],
        "missing_prerequisite_codes": [],
    }
    payload.update(overrides)
    return ActionReadinessCandidateResponse.model_validate(payload)


def test_parse_readiness_filters_ignore_unknown_values() -> None:
    assert parse_plan_family(None) is None
    assert parse_plan_family("outreach_enrollment") == "outreach_enrollment"
    assert parse_plan_family("execute") is None
    assert parse_readiness_status("preflight_blocked") == "preflight_blocked"
    assert parse_readiness_status("ready_to_send") is None
    assert parse_blocker_status("phase_safety_only") == "phase_safety_only"
    assert parse_blocker_status("clear") is None
    assert parse_decision_status("missing") == "missing"
    assert parse_decision_status("execute") is None
    assert READINESS_PATH == OPERATOR_ACTION_READINESS_PATH


def test_renderer_empty_state_is_read_only_and_escaped() -> None:
    html = render_action_readiness_list(
        _empty_queue(),
        plan_family=None,
        readiness_status=None,
        blocker_status=None,
        decision_status=None,
        candidates=[],
    )

    assert 'id="operator-action-readiness"' in html
    assert "No approved-action readiness candidates yet" in html
    assert "There are no execute" in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_renderer_populated_filters_and_xss_escape() -> None:
    item = _candidate(sanitized_label=XSS_LABEL)
    html = render_action_readiness_list(
        _empty_queue(candidate_count=1),
        plan_family=ExecutionPlanType.OPTIMIZER_APPLY.value,
        readiness_status=ActionReadinessStatus.MISSING_OWNER_PACKET_DECISION.value,
        blocker_status="blocked",
        decision_status="approved",
        candidates=[item],
    )
    detail = render_action_readiness_detail(item)
    missing = render_action_readiness_missing()
    error = render_action_readiness_error()

    assert XSS_LABEL not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "missing_owner_packet_decision" in html
    assert "explicit owner action" in html.lower()
    assert XSS_LABEL not in detail
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in detail
    assert "no execute" in detail.lower()
    assert 'id="operator-action-readiness-missing"' in missing
    assert 'id="operator-action-readiness-error"' in error
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()
        assert marker not in detail.lower()


def test_operator_action_readiness_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_ACTION_READINESS_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Approved action readiness" in body
    assert "Action readiness" in body
    assert "No approved-action readiness candidates yet" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in FORM_MARKERS:
        assert marker not in body.lower()


def test_operator_action_readiness_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_ACTION_READINESS_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_ACTION_READINESS_PATH)
    invalid = api_client.get(
        OPERATOR_ACTION_READINESS_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_ACTION_READINESS_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405


def test_operator_action_readiness_populated_detail_and_no_side_effects(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    _seed_plans_and_packets(db_session)
    before_activities = db_session.scalar(select(func.count()).select_from(Activity)) or 0
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting)) or 0
    before_enrollments = (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0
    )
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage)) or 0

    listed = api_client.get(
        OPERATOR_ACTION_READINESS_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    filtered = api_client.get(
        OPERATOR_ACTION_READINESS_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
        params={"readiness_status": ActionReadinessStatus.MISSING_OWNER_PACKET_DECISION.value},
    )
    json_queue = api_client.get(
        "/internal/action-readiness",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    candidate_id = json_queue.json()["candidates"][0]["candidate_id"]
    detail = api_client.get(
        f"{OPERATOR_ACTION_READINESS_PATH}/{candidate_id}",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    missing = api_client.get(
        f"{OPERATOR_ACTION_READINESS_PATH}/not-a-uuid",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert listed.status_code == 200
    assert filtered.status_code == 200
    assert detail.status_code == 200
    assert missing.status_code == 404
    assert "missing_owner_packet_decision" in listed.text
    assert "explicit owner action" in listed.text.lower()
    assert "Action readiness candidate" in detail.text
    assert "future explicit owner action" in detail.text.lower()
    assert PHI_SNIPPET not in listed.text
    assert PROSPECT_EMAIL not in listed.text
    for marker in FORM_MARKERS:
        assert marker not in listed.text.lower()
        assert marker not in detail.text.lower()
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_operator_action_readiness_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(
        "vyro_growth.api.operator_action_readiness.build_action_readiness_response",
        _boom,
    )
    response = api_client.get(OPERATOR_ACTION_READINESS_PATH)

    assert response.status_code == 500
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the approved action readiness queue" in response.text
