from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_approval_packet_service import _approve_all_families
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from tests.test_monitoring_service import UNSAFE_ERROR
from vyro_growth.api.command_center import (
    ApprovalPacketSummaryResponse,
    CommandCenterResponse,
    FindingCountsResponse,
    NextActionResponse,
    OutstandingReviewResponse,
    PipelineCountsResponse,
)
from vyro_growth.api.monitoring import (
    LatestJobStatusResponse,
    MonitoringReadinessResponse,
    MonitoringSafetyResponse,
    OperationalFindingResponse,
)
from vyro_growth.api.operator_dashboard import (
    OPERATOR_DASHBOARD_PATH,
    parse_dashboard_section,
    render_operator_dashboard,
    render_operator_dashboard_error,
)
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import DiscoveryRunStatus, NextActionCode
from vyro_growth.main import app
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    DiscoveryRun,
    Meeting,
    OutreachMessage,
    OwnerApprovalPacket,
)
from vyro_growth.services.approval_packets import ApprovalPacketService
from vyro_growth.services.execution_planning import ExecutionPlanningService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

XSS_LABEL = "<script>alert(1)</script>"
ACTION_MARKERS = ("<button", "<form", "javascript:", "onclick=", "<input")


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


def _empty_summary(**overrides: object) -> CommandCenterResponse:
    payload = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "read_only": True,
        "overall_severity": "warning",
        "safety": MonitoringSafetyResponse(
            outbound_enabled=False,
            outbound_halted_settings=False,
            operator_halt_status="unavailable",
            operator_halt_reason=None,
            live_providers_enabled=False,
            live_providers={"personalization_live": False},
            live_calendar_events=0,
            live_meet_links=0,
            live_phone_calls=0,
            live_send_attempted_enrollments=0,
            outbound_attempted_classifications=0,
            booking_events_created=0,
            booking_meet_links_created=0,
            voice_calls_placed=0,
            phi_fields_present=False,
        ),
        "readiness": MonitoringReadinessResponse(
            status="ready",
            environment="development",
            database="ok",
            config_ok=True,
            config_issues=[],
            outbound_enabled=False,
            live_providers_enabled=False,
            live_providers={},
            ready_for_manual_rollout=True,
        ),
        "pipeline": PipelineCountsResponse(
            organizations=0,
            leads=0,
            discovery_runs=0,
            website_enrichment_runs=0,
            decision_maker_contacts=0,
            latest_scores=0,
            personalization_drafts=0,
            outreach_plans_planned=0,
            reply_classifications=0,
            booking_plans=0,
            voice_qualification_plans=0,
            optimizer_recommendations=0,
            channel_plans=0,
            content_briefs=0,
            execution_plans=0,
            approval_packets=0,
        ),
        "latest_runs": [
            LatestJobStatusResponse(
                phase="discovery",
                job_name=None,
                implemented=True,
                status="not_started",
                started_at=None,
                finished_at=None,
                run_id=None,
            )
        ],
        "recent_failures": [],
        "finding_counts": FindingCountsResponse(blocked=0, warning=1, info=0, total=1),
        "findings": [
            OperationalFindingResponse(
                severity="warning",
                code="operator_halt_unavailable",
                message="Persistent operator halt is not recorded.",
                phase=None,
            )
        ],
        "outstanding_review": OutstandingReviewResponse(
            pending_count=0,
            decided_count=0,
            approved_count=0,
            rejected_count=0,
            needs_changes_count=0,
            by_artifact_type={},
            executed_count=0,
        ),
        "approval_packets": ApprovalPacketSummaryResponse(
            packets=0,
            latest_run_status="not_started",
        ),
        "next_actions": [
            NextActionResponse(
                code=NextActionCode.KEEP_OUTBOUND_DISABLED.value,
                label="Keep OUTBOUND_ENABLED=false.",
                severity="info",
            )
        ],
    }
    payload.update(overrides)
    return CommandCenterResponse.model_validate(payload)


def test_parse_dashboard_section_defaults_unknown_to_all() -> None:
    assert parse_dashboard_section(None) == "all"
    assert parse_dashboard_section("pipeline") == "pipeline"
    assert parse_dashboard_section("execute") == "all"
    assert parse_dashboard_section("../secrets") == "all"


def test_renderer_empty_state_is_read_only_and_escaped() -> None:
    html = render_operator_dashboard(
        _empty_summary(
            next_actions=[
                NextActionResponse(
                    code="keep_outbound_disabled",
                    label=XSS_LABEL,
                    severity="info",
                )
            ]
        )
    )

    assert 'id="operator-dashboard"' in html
    assert "No pipeline activity yet" in html
    assert "No jobs have started" in html
    assert "No outstanding review items" in html
    assert "No owner approval packets" in html
    assert XSS_LABEL not in html
    assert escape_marker() in html
    for marker in ACTION_MARKERS:
        assert marker not in html.lower()
    assert "Executed=0" in html
    assert "Outbound attempted=no" in html


def escape_marker() -> str:
    return "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_renderer_populated_section_filter_hides_other_panels() -> None:
    html = render_operator_dashboard(
        _empty_summary(
            pipeline=PipelineCountsResponse(
                organizations=4,
                leads=3,
                discovery_runs=1,
                website_enrichment_runs=0,
                decision_maker_contacts=0,
                latest_scores=2,
                personalization_drafts=1,
                outreach_plans_planned=0,
                reply_classifications=0,
                booking_plans=0,
                voice_qualification_plans=0,
                optimizer_recommendations=0,
                channel_plans=0,
                content_briefs=0,
                execution_plans=0,
                approval_packets=0,
            )
        ),
        section="pipeline",
    )

    assert "Pipeline counts" in html
    assert "Organizations" in html
    assert ">4<" in html
    assert 'id="findings"' not in html
    assert 'id="next-actions"' not in html
    assert 'id="packets"' not in html
    assert "JSON summary" in html
    for marker in ACTION_MARKERS:
        assert marker not in html.lower()


def test_error_page_has_no_raw_exception_or_actions() -> None:
    html = render_operator_dashboard_error()
    assert 'id="operator-dashboard-error"' in html
    assert "Unable to load the operator dashboard" in html
    assert "sk-testsecret12345" not in html
    for marker in ACTION_MARKERS:
        assert marker not in html.lower()


def test_operator_dashboard_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.get(OPERATOR_DASHBOARD_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Operator dashboard" in body
    assert "No pipeline activity yet" in body
    assert "read-only" in body.lower()
    assert "Outbound" in body
    assert "disabled" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in ACTION_MARKERS:
        assert marker not in body.lower()


def test_operator_dashboard_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(OPERATOR_DASHBOARD_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_operator_dashboard_rejects_missing_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="development", internal_api_key="internal-secret"),
    )

    response = api_client.get(OPERATOR_DASHBOARD_PATH)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing internal API key"


def test_operator_dashboard_rejects_invalid_key_and_disallows_post(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    post = api_client.post(
        OPERATOR_DASHBOARD_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    assert post.status_code == 405

    response = api_client.get(
        OPERATOR_DASHBOARD_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing internal API key"


def test_operator_dashboard_accepts_valid_key_and_stays_read_only(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    _seed_pipeline(db_session)
    db_session.add(
        DiscoveryRun(
            source="nppes",
            status=DiscoveryRunStatus.FAILED.value,
            error_message=UNSAFE_ERROR,
        )
    )
    db_session.flush()
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before_activities = db_session.scalar(select(func.count()).select_from(Activity))
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting))
    before_enrollments = db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage))

    response = api_client.get(
        OPERATOR_DASHBOARD_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    body = response.text
    assert "Operator dashboard" in body
    assert "Pipeline counts" in body
    assert "Outstanding review" in body
    assert "Safe next-action labels" in body
    assert HaltStatus.HALTED.value in body
    assert "disabled" in body
    assert PHI_SNIPPET not in body
    assert PROSPECT_EMAIL not in body
    assert "diabetes" not in body.lower()
    assert "sk-testsecret12345" not in body
    assert "jordan.blake" not in body
    for marker in ACTION_MARKERS:
        assert marker not in body.lower()
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_operator_dashboard_section_filter_is_read_only(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    before = db_session.scalar(select(func.count()).select_from(Activity))

    response = api_client.get(f"{OPERATOR_DASHBOARD_PATH}?section=actions")

    assert response.status_code == 200
    assert "Safe next-action labels" in response.text
    assert 'id="pipeline"' not in response.text
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before


def test_operator_dashboard_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def boom(*_args: object, **_kwargs: object) -> CommandCenterResponse:
        raise RuntimeError("db exploded sk-testsecret12345 patient diabetes")

    monkeypatch.setattr(
        "vyro_growth.api.operator_dashboard.build_command_center_response",
        boom,
    )

    response = api_client.get(OPERATOR_DASHBOARD_PATH)

    assert response.status_code == 500
    assert "Unable to load the operator dashboard" in response.text
    assert "sk-testsecret12345" not in response.text
    assert "diabetes" not in response.text.lower()
    assert "No pipeline rows were written" in response.text
    for marker in ACTION_MARKERS:
        assert marker not in response.text.lower()


def test_operator_dashboard_reports_packets_without_executing(
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
    before_packets = db_session.scalar(select(func.count()).select_from(OwnerApprovalPacket))
    before_activities = db_session.scalar(select(func.count()).select_from(Activity))

    response = api_client.get(
        OPERATOR_DASHBOARD_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    body = response.text
    assert "Approval packets and preflight" in body
    assert "Executed=0" in body
    assert "Outbound attempted=no" in body
    assert PHI_SNIPPET not in body
    assert PROSPECT_EMAIL not in body
    assert db_session.scalar(select(func.count()).select_from(OwnerApprovalPacket)) == before_packets
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert read_operator_halt(db_session) is HaltStatus.HALTED
