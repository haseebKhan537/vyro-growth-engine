from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from vyro_growth.api.operator_audit_timeline import (
    render_operator_audit_timeline,
    render_operator_audit_timeline_error,
)
from vyro_growth.api.operator_ui import OPERATOR_AUDIT_TIMELINE_PATH
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import (
    ReviewArtifactType,
    ReviewDecisionStatus,
    ReviewItemStatus,
    SettingsChangeRequestType,
)
from vyro_growth.main import app
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    LiveSettingsChangeRequest,
    Meeting,
    OperatorReviewDecision,
    OutreachMessage,
)
from vyro_growth.services.operator_audit_timeline import OperatorAuditTimeline
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


def _empty_timeline(**overrides: object) -> OperatorAuditTimeline:
    payload = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "read_only": True,
        "no_execution": True,
        "dry_run_only": True,
        "executed": 0,
        "live_action": False,
        "outbound_attempted": False,
        "owner_approved": False,
        "settings_applied": False,
        "halt_changed": False,
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "outbound_enabled": False,
        "matching_count": 0,
        "shown_count": 0,
        "truncated": False,
        "event_type": None,
        "source": None,
        "status": None,
        "window": "all",
        "available_event_types": (),
        "available_sources": (),
        "available_statuses": (),
        "entries": (),
    }
    payload.update(overrides)
    return OperatorAuditTimeline(**payload)  # type: ignore[arg-type]


def test_renderer_empty_state_is_read_only_and_has_no_execute_controls() -> None:
    html = render_operator_audit_timeline(_empty_timeline())

    assert 'id="operator-audit-timeline"' in html
    assert "No activity, audit, or decision records yet" in html
    assert "There are no apply, execute, lift-halt" in html
    assert 'data-no-execution="true"' in html
    assert 'data-read-only="true"' in html
    assert "Audit timeline" in html
    assert "/internal/operator-compliance-evidence-binder" in html
    assert "/internal/operator-owner-handoff-packet" in html
    assert "/internal/operator-release-candidate-runbook" in html
    assert "/internal/operator-release-artifact-manifest" in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_renderer_populated_filters_and_xss_escape() -> None:
    result = OperatorAuditTimeline(
        generated_at=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        read_only=True,
        no_execution=True,
        dry_run_only=True,
        executed=0,
        live_action=False,
        outbound_attempted=False,
        owner_approved=False,
        settings_applied=False,
        halt_changed=False,
        operator_halt_status="halted",
        operator_halt_before="halted",
        operator_halt_after="halted",
        outbound_enabled=False,
        matching_count=1,
        shown_count=1,
        truncated=False,
        event_type="approval_packets_generated",
        source="approval_packets",
        status="completed",
        window="7d",
        available_event_types=("approval_packets_generated",),
        available_sources=("approval_packets",),
        available_statuses=("completed",),
        entries=(),
    )
    html = render_operator_audit_timeline(result)
    error = render_operator_audit_timeline_error()

    assert "event_type=approval_packets_generated" in html
    assert "source=approval_packets" in html
    assert "status=completed" in html
    assert "window=7d" in html
    assert "No activity, audit, or decision records match" in html
    assert 'id="operator-audit-timeline-error"' in error
    assert "sk-testsecret" not in error
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()
        assert marker not in error.lower()


def test_operator_audit_timeline_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_AUDIT_TIMELINE_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Operator activity audit timeline" in body
    assert "Audit timeline" in body
    assert "No activity, audit, or decision records yet" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in FORM_MARKERS:
        assert marker not in body.lower()


def test_operator_audit_timeline_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_AUDIT_TIMELINE_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_AUDIT_TIMELINE_PATH)
    invalid = api_client.get(
        OPERATOR_AUDIT_TIMELINE_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_AUDIT_TIMELINE_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405


def test_operator_audit_timeline_populated_filters_and_no_side_effects(
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
    packet_id = uuid4()
    artifact_id = uuid4()
    db_session.add(
        Activity(
            lead_id=None,
            actor="approval_packets",
            action="approval_packets_generated",
            details={
                "owner_approval_packet_id": str(packet_id),
                "status": "completed",
                "reason": XSS_LABEL,
                "email": PROSPECT_EMAIL,
                "body": "full outreach draft copy must not render",
            },
        )
    )
    db_session.add(
        Activity(
            lead_id=None,
            actor="nppes_discovery",
            action="nppes_discovery_completed",
            details={"discovery_run_id": str(uuid4()), "reason": PHI_SNIPPET},
        )
    )
    old = Activity(
        lead_id=None,
        actor="lead_scoring",
        action="lead_scored",
        details={"status": "completed"},
    )
    db_session.add(old)
    db_session.flush()
    old.created_at = datetime.now(tz=UTC) - timedelta(days=12)
    db_session.add(
        OperatorReviewDecision(
            artifact_type=ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value,
            artifact_id=artifact_id,
            decision=ReviewDecisionStatus.APPROVED.value,
            reviewer="owner",
            source="operator_ui",
            reviewer_notes=PHI_SNIPPET,
            decided_at=datetime.now(tz=UTC),
            item_status=ReviewItemStatus.APPROVED.value,
        )
    )
    db_session.flush()
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="ui-timeline",
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
    before_meetings = int(db_session.scalar(select(func.count()).select_from(Meeting)) or 0)
    before_enrollments = int(
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0
    )
    before_messages = int(db_session.scalar(select(func.count()).select_from(OutreachMessage)) or 0)
    before_requests = int(
        db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) or 0
    )

    listed = api_client.get(
        OPERATOR_AUDIT_TIMELINE_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    filtered = api_client.get(
        OPERATOR_AUDIT_TIMELINE_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
        params={"event_type": "operator_review_decision", "status": "approved"},
    )
    unknown_filter = api_client.get(
        OPERATOR_AUDIT_TIMELINE_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
        params={"event_type": "../secrets", "window": "ready_to_apply"},
    )

    assert listed.status_code == 200
    assert filtered.status_code == 200
    assert unknown_filter.status_code == 200
    assert str(packet_id) in listed.text
    assert str(artifact_id) in listed.text
    assert str(created.request_id) in listed.text
    assert "approval packets generated" in listed.text.lower()
    assert "operator review decision" in listed.text.lower()
    assert str(artifact_id) in filtered.text
    assert str(packet_id) not in filtered.text
    assert str(packet_id) in unknown_filter.text
    assert XSS_LABEL not in listed.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in listed.text
    assert PHI_SNIPPET not in listed.text
    assert PROSPECT_EMAIL not in listed.text
    assert "full outreach draft copy must not render" not in listed.text
    assert "reviewer_notes" not in listed.text
    _assert_no_leakage(listed.text, SECRET_VALUE)
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


def test_operator_audit_timeline_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(
        "vyro_growth.api.operator_audit_timeline.OperatorAuditTimelineService.timeline",
        _boom,
    )
    response = api_client.get(OPERATOR_AUDIT_TIMELINE_PATH)

    assert response.status_code == 500
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the operator activity audit timeline" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()
