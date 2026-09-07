from __future__ import annotations

import re
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_action_readiness_service import _seed_plans_and_packets
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from tests.test_supervised_pilot_candidates_service import (
    NPI_NUMBER,
    PRACTICE_NAME,
    PROVIDER_NAME,
    WEBSITE,
    _seed_candidate,
)
from tests.test_supervised_pilot_launch_rehearsal_control_map_service import _assert_no_execution
from vyro_growth.api.operator_supervised_pilot_launch_rehearsal_control_map import (
    render_supervised_pilot_launch_rehearsal_control_map,
    render_supervised_pilot_launch_rehearsal_control_map_error,
)
from vyro_growth.api.operator_ui import (
    OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH,
)
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import FindingSeverity, NextActionCode, SettingsChangeRequestType
from vyro_growth.main import app
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    LiveSettingsChangeRequest,
    Meeting,
    OutreachMessage,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService
from vyro_growth.services.supervised_pilot_launch_rehearsal_control_map import (
    CLI_COMMAND,
    HTTP_ROUTE,
    ControlCount,
    ControlNextAction,
    ControlNode,
    SupervisedPilotLaunchRehearsalControlMap,
)

XSS_LABEL = "<script>alert(1)</script>"
ACTION_MARKERS = ("javascript:", "onclick=", "onerror=")
FORM_MARKERS = ("<form", "<button", "<input", "<select", "<textarea")
CONTACT_MARKERS = (
    "mailto:",
    "tel:",
    'href="sms:',
    "contact this candidate",
    "email this candidate",
    "call this candidate",
)
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
GIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
GIT_BRANCH_RE = re.compile(r"cursor/[A-Za-z0-9._/\-]+")
SECTION_IDS = (
    "live-blocking-flags",
    "control-map-flags",
    "source-rollups",
    "candidate-queue-counts",
    "control-counts",
    "expected-safe-assertions",
    "control-map-rows",
    "owner-decision-prerequisites",
    "remaining-owner-approvals",
    "blocker-gate-codes",
    "missing-names",
    "closed-provider-flags",
    "source-references",
    "related-routes",
    "related-commands",
    "local-git",
    "owner-next-steps",
    "side-effects",
)
LINKED_SURFACES = (
    "/internal/operator-dashboard",
    "/internal/operator-go-live-readiness-index",
    "/internal/go-live-readiness-index",
    "/internal/operator-launch-blockers-plan",
    "/internal/launch-blockers-plan",
    "/internal/operator-staged-rollout-plan",
    "/internal/staged-rollout-plan",
    "/internal/operator-owner-launch-dossier",
    "/internal/owner-launch-dossier",
    "/internal/operator-provider-setup-checklist",
    "/internal/provider-setup-checklist",
    "/internal/operator-go-live-rehearsal-checklist",
    "/internal/go-live-rehearsal-checklist",
    "/internal/operator-rehearsal-outcome-report",
    "/internal/rehearsal-outcome-report",
    "/internal/operator-supervised-pilot-plan",
    "/internal/supervised-pilot-plan",
    "/internal/operator-supervised-pilot-candidates",
    "/internal/supervised-pilot-candidates",
    "/internal/operator-supervised-pilot-go-no-go",
    "/internal/supervised-pilot-go-no-go",
    "/internal/operator-supervised-pilot-first-send-preflight",
    "/internal/supervised-pilot-first-send-preflight",
    "/internal/operator-supervised-pilot-launch-rehearsal-control-map",
    "/internal/supervised-pilot-launch-rehearsal-control-map",
    "/internal/launch-readiness",
    "/internal/operator-settings-execution-preflight",
    "/internal/settings-execution-preflight",
    "/internal/operator-owner-handoff-packet",
    "/internal/owner-handoff-packet",
    "/internal/operator-compliance-evidence-binder",
    "/internal/compliance-evidence-binder",
    "/internal/operator-release-candidate-runbook",
    "/internal/release-candidate-runbook",
    "/internal/operator-release-artifact-manifest",
    "/internal/release-artifact-manifest",
    "/internal/operator-audit-timeline",
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


def _count(**overrides: object) -> ControlCount:
    payload: dict[str, object] = {"key": "safety_gates", "count": 1}
    payload.update(overrides)
    return ControlCount(**payload)  # type: ignore[arg-type]


def _node(**overrides: object) -> ControlNode:
    payload: dict[str, object] = {
        "code": "first_send_not_permitted",
        "category": "supervised_pilot",
        "status": FindingSeverity.INFO.value,
        "label": "This control map is not permission to send.",
        "blocking": False,
        "command_name": CLI_COMMAND,
        "json_route": HTTP_ROUTE,
        "html_route": OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH,
    }
    payload.update(overrides)
    return ControlNode(**payload)  # type: ignore[arg-type]


def _action(**overrides: object) -> ControlNextAction:
    payload: dict[str, object] = {
        "code": NextActionCode.SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_IS_NOT_GO_LIVE.value,
        "status": FindingSeverity.INFO.value,
        "label": "This supervised pilot launch rehearsal control map is review only.",
        "command_name": CLI_COMMAND,
        "json_route": HTTP_ROUTE,
        "html_route": OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH,
        "config_name": None,
    }
    payload.update(overrides)
    return ControlNextAction(**payload)  # type: ignore[arg-type]


def _empty_packet(**overrides: object) -> SupervisedPilotLaunchRehearsalControlMap:
    payload: dict[str, object] = {
        "generated_at": datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        "packet_kind": "supervised_pilot_launch_rehearsal_control_map",
        "purpose": "manual_owner_supervised_pilot_launch_rehearsal_control_map_review_only",
        "overall_status": "blocked",
        "read_only": True,
        "no_execution": True,
        "no_go_live": True,
        "no_deployment": True,
        "no_outbound": True,
        "no_provider_calls": True,
        "no_spend": True,
        "no_first_send": True,
        "dry_run_only": True,
        "executed": 0,
        "execution_attempted": False,
        "outbound_attempted": False,
        "live_call_attempted": False,
        "recommendation_applied": False,
        "spend_attempted": False,
        "spend_allowed": False,
        "campaign_launched": False,
        "pages_published": False,
        "ads_launched": False,
        "owner_approved": False,
        "settings_applied": False,
        "halt_changed": False,
        "live_action": False,
        "execution_allowed": False,
        "future_execution_phase_exists": False,
        "future_deployment_phase_exists": False,
        "go_live_permitted": False,
        "deployment_allowed": False,
        "deployment_attempted": False,
        "deployed": False,
        "build_allowed": False,
        "artifact_publish_allowed": False,
        "container_build_attempted": False,
        "artifact_publish_attempted": False,
        "outbound_enabled": False,
        "live_providers_enabled": False,
        "manual_review_only": True,
        "first_send_allowed": False,
        "first_send_attempted": False,
        "first_send_executed": 0,
        "sends_executed": 0,
        "suggested_max_first_sends": 0,
        "supervised_pilot_launch_rehearsal_control_map_is_not_go_live": True,
        "rehearsal_control_map_is_not_a_script_runner": True,
        "control_map_is_not_execution": True,
        "first_send_preflight_is_not_a_send": True,
        "export_is_not_permission_to_go_live": True,
        "export_is_not_execution": True,
        "supervised_pilot_first_send_preflight_is_not_go_live": True,
        "supervised_pilot_go_no_go_is_not_go_live": True,
        "supervised_pilot_plan_is_not_go_live": True,
        "supervised_pilot_candidates_is_not_go_live": True,
        "rehearsal_outcome_report_is_not_go_live": True,
        "go_live_rehearsal_checklist_is_not_go_live": True,
        "provider_setup_checklist_is_not_go_live": True,
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "source_first_send_overall_status": "blocked",
        "source_go_no_go_overall_status": "blocked",
        "source_pilot_plan_overall_status": "blocked",
        "source_candidates_overall_status": "blocked",
        "ready_for_review_count": 0,
        "blocked_candidate_count": 0,
        "total_candidate_count": 0,
        "review_queue_pending_count": 0,
        "action_readiness_candidate_count": 0,
        "approval_packet_count": 0,
        "settings_request_count": 0,
        "settings_request_pending_count": 0,
        "blocking_control_count": 0,
        "warning_control_count": 0,
        "info_control_count": 0,
        "control_counts_by_category": (),
        "control_counts_by_status": (),
        "blocking_control_codes": (),
        "expected_safe_assertion_count": 0,
        "expected_safe_assertions_passed": 0,
        "expected_safe_assertions_failed": 0,
        "failed_safe_assertion_keys": (),
        "control_nodes": (),
        "owner_decision_prerequisites": (),
        "remaining_owner_approval_types": (),
        "closed_provider_flag_names": ("VOICE_LIVE_ENABLED",),
        "missing_credential_names": (),
        "missing_config_names": (),
        "missing_prerequisite_codes": (),
        "blocker_codes": ("execution_disabled_in_this_phase",),
        "gate_codes": ("no_execution", "no_go_live", "no_outbound", "no_first_send"),
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "source_first_send_command": "supervised-pilot-first-send-preflight",
        "source_first_send_route": "/internal/supervised-pilot-first-send-preflight",
        "source_first_send_html_route": (
            "/internal/operator-supervised-pilot-first-send-preflight"
        ),
        "source_go_no_go_command": "supervised-pilot-go-no-go",
        "source_go_no_go_route": "/internal/supervised-pilot-go-no-go",
        "source_go_no_go_html_route": "/internal/operator-supervised-pilot-go-no-go",
        "source_pilot_plan_command": "supervised-pilot-plan",
        "source_pilot_plan_route": "/internal/supervised-pilot-plan",
        "source_pilot_plan_html_route": "/internal/operator-supervised-pilot-plan",
        "source_candidates_command": "supervised-pilot-candidates",
        "source_candidates_route": "/internal/supervised-pilot-candidates",
        "source_candidates_html_route": "/internal/operator-supervised-pilot-candidates",
        "related_commands": (
            "supervised-pilot-launch-rehearsal-control-map",
            "supervised-pilot-first-send-preflight",
        ),
        "related_routes": LINKED_SURFACES,
        "local_git": LocalGitMetadata(
            available=True,
            current_branch="main",
            current_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            working_tree_status="not_inspected",
            git_provider_called=False,
            github_actions_called=False,
        ),
        "next_actions": (),
    }
    payload.update(overrides)
    return SupervisedPilotLaunchRehearsalControlMap(**payload)  # type: ignore[arg-type]


def _strip_volatile(html: str) -> str:
    stripped = TIMESTAMP_RE.sub("<timestamp>", html)
    stripped = GIT_SHA_RE.sub("<git-sha>", stripped)
    return GIT_BRANCH_RE.sub("<git-branch>", stripped)


def test_renderer_empty_state_is_read_only_and_has_no_execute_controls() -> None:
    html = render_supervised_pilot_launch_rehearsal_control_map(_empty_packet())

    assert 'id="operator-supervised-pilot-launch-rehearsal-control-map"' in html
    assert (
        OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH
        == "/internal/operator-supervised-pilot-launch-rehearsal-control-map"
    )
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in html
    assert "No control category counts" in html
    assert "No control status counts" in html
    assert "No control map rows" in html
    assert "No blocking control codes" in html
    assert "No owner next steps" in html
    assert "go_live_permitted=false" in html
    assert "execution_allowed=false" in html
    assert "first_send_allowed=false" in html
    assert "first_send_attempted=false" in html
    assert "first_send_executed=0" in html
    assert "sends_executed=0" in html
    assert "deployment_allowed=false" in html
    assert "build_allowed=false" in html
    assert "artifact_publish_allowed=false" in html
    assert "spend_allowed=false" in html
    assert "owner_approved=false" in html
    assert "OUTBOUND_ENABLED=false" in html
    assert "no_outbound=true" in html
    assert "no_provider_calls=true" in html
    assert "no_first_send=true" in html
    assert "supervised_pilot_launch_rehearsal_control_map_is_not_go_live=true" in html
    assert "rehearsal_control_map_is_not_a_script_runner=true" in html
    assert "control_map_is_not_execution=true" in html
    assert "export_is_not_permission_to_go_live=true" in html
    assert "export_is_not_execution=true" in html
    assert "control-map review view" in html
    assert "not a script runner" in html
    assert "not permission to send" in html
    assert "not permission to go live" in html
    assert "There are no apply, execute, lift-halt" in html
    assert 'data-execution-allowed="false"' in html
    assert 'data-go-live-permitted="false"' in html
    assert 'data-first-send-allowed="false"' in html
    assert 'data-first-send-attempted="false"' in html
    assert 'data-no-outbound="true"' in html
    assert 'data-no-provider-calls="true"' in html
    assert 'data-no-first-send="true"' in html
    assert 'data-spend-allowed="false"' in html
    assert 'data-supervised-pilot-launch-rehearsal-control-map-is-not-go-live="true"' in html
    assert 'data-rehearsal-control-map-is-not-a-script-runner="true"' in html
    assert 'data-control-map-is-not-execution="true"' in html
    assert "Halt unchanged" in html
    for href in LINKED_SURFACES:
        assert href in html
    lowered = html.lower()
    for marker in ACTION_MARKERS + FORM_MARKERS + CONTACT_MARKERS:
        assert marker not in lowered


def test_renderer_populated_sections_and_xss_escape() -> None:
    html = render_supervised_pilot_launch_rehearsal_control_map(
        _empty_packet(
            blocker_codes=["execution_disabled_in_this_phase", XSS_LABEL],
            gate_codes=["no_execution", XSS_LABEL],
            blocking_control_codes=("operator_halt", XSS_LABEL),
            missing_credential_names=["EXAMPLE_API_KEY", XSS_LABEL],
            missing_config_names=["OUTBOUND_ENABLED", XSS_LABEL],
            closed_provider_flag_names=["EXAMPLE_LIVE_ENABLED", XSS_LABEL],
            missing_prerequisite_codes=("website_credibility", XSS_LABEL),
            owner_decision_prerequisites=("live_enablement_review", XSS_LABEL),
            remaining_owner_approval_types=("live_enablement_review", XSS_LABEL),
            failed_safe_assertion_keys=("first_send_not_permitted", XSS_LABEL),
            control_counts_by_category=(_count(key=XSS_LABEL, count=2),),
            control_counts_by_status=(_count(key="blocked", count=1),),
            control_nodes=(_node(code=XSS_LABEL, label=XSS_LABEL, category=XSS_LABEL), _node()),
            next_actions=(
                _action(code=XSS_LABEL, label=XSS_LABEL, config_name=XSS_LABEL),
                _action(),
            ),
        )
    )
    error = render_supervised_pilot_launch_rehearsal_control_map_error()

    assert XSS_LABEL not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert SECRET_VALUE not in html
    assert "EXAMPLE_API_KEY" in html
    assert "EXAMPLE_LIVE_ENABLED" in html
    assert "execution_disabled_in_this_phase" in html
    assert "live_enablement_review" in html
    assert "blocked" in html
    assert "Supervised pilot launch rehearsal control map" in html
    assert 'id="operator-supervised-pilot-launch-rehearsal-control-map-error"' in error
    assert "sk-testsecret" not in error
    lowered = html.lower()
    error_lowered = error.lower()
    for marker in ACTION_MARKERS + FORM_MARKERS + CONTACT_MARKERS:
        assert marker not in lowered
        assert marker not in error_lowered


def test_renderer_is_deterministic_aside_from_timestamps_and_git_metadata() -> None:
    first = render_supervised_pilot_launch_rehearsal_control_map(_empty_packet())
    second = render_supervised_pilot_launch_rehearsal_control_map(
        _empty_packet(generated_at=datetime(2026, 9, 8, 8, 30, tzinfo=UTC))
    )
    git_variant = render_supervised_pilot_launch_rehearsal_control_map(
        _empty_packet(
            local_git=LocalGitMetadata(
                available=True,
                current_branch="cursor/phase-64-rehearsal-control-map-ui-c9e0",
                current_sha="dddddddddddddddddddddddddddddddddddddddd",
                working_tree_status="not_inspected",
                git_provider_called=False,
                github_actions_called=False,
            )
        )
    )

    assert _strip_volatile(first) == _strip_volatile(second)
    assert "dddddddddddddddddddddddddddddddddddddddd" in git_variant
    assert "cursor/phase-64-rehearsal-control-map-ui-c9e0" in git_variant
    assert TIMESTAMP_RE.search(first)
    assert TIMESTAMP_RE.search(second)


def test_operator_supervised_pilot_launch_rehearsal_control_map_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    body = response.text
    assert "Supervised pilot launch rehearsal control map" in body
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "first_send_allowed=false" in body
    assert "first_send_attempted=false" in body
    assert "first_send_executed=0" in body
    assert "sends_executed=0" in body
    assert "deployment_allowed=false" in body
    assert "spend_allowed=false" in body
    assert "owner_approved=false" in body
    assert "OUTBOUND_ENABLED=false" in body
    assert "no_outbound=true" in body
    assert "no_provider_calls=true" in body
    assert "no_first_send=true" in body
    assert "supervised_pilot_launch_rehearsal_control_map_is_not_go_live=true" in body
    assert "rehearsal_control_map_is_not_a_script_runner=true" in body
    assert "control_map_is_not_execution=true" in body
    assert "export_is_not_permission_to_go_live=true" in body
    assert "export_is_not_execution=true" in body
    assert "not a script runner" in body
    assert "not permission to send" in body
    assert "not permission to go live" in body
    assert "Source first-send, go/no-go, pilot-plan, and candidate rollups" in body
    assert "Candidate, review, action, settings, and approval counts" in body
    assert "Control counts by category and status" in body
    assert "Expected safe assertions" in body
    assert "Control map rows" in body
    assert "Closed provider and live flag names" in body
    assert "Non-executable owner next steps" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    lowered = body.lower()
    for marker in FORM_MARKERS + CONTACT_MARKERS:
        assert marker not in lowered


def test_operator_supervised_pilot_launch_rehearsal_control_map_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH)
    invalid = api_client.get(
        OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    put = api_client.put(
        OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    delete = api_client.delete(
        OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    patch = api_client.patch(
        OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405
    assert put.status_code == 405
    assert delete.status_code == 405
    assert patch.status_code == 405


def test_operator_supervised_pilot_launch_rehearsal_control_map_populated_and_no_side_effects(
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
    _seed_candidate(
        db_session,
        verified_contact=True,
        add_evidence=True,
        add_enrichment=True,
        score_band="high",
    )
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="ui-supervised-pilot-launch-rehearsal-control-map-main",
        reviewer_notes=PHI_SNIPPET,
    )
    SettingsChangeRequestService().record_decision(
        db_session,
        settings,
        request_id=created.request_id,
        decision="approved",
        reviewer="owner",
    )
    SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="ui-supervised-pilot-launch-rehearsal-control-map-pending",
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
    before_halt = read_operator_halt(db_session)

    first = api_client.get(
        OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    second = api_client.get(
        OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    json_export = api_client.get(
        HTTP_ROUTE,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    first_send_export = api_client.get(
        "/internal/supervised-pilot-first-send-preflight",
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    cli_json = api_client.get(
        HTTP_ROUTE,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert json_export.status_code == 200
    assert first_send_export.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    body = first.text
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "OUTBOUND_ENABLED" in body
    assert "execution_disabled_in_this_phase" in body
    assert (
        NextActionCode.SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_IS_NOT_GO_LIVE.value in body
    )
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "first_send_allowed=false" in body
    assert "first_send_executed=0" in body
    assert "deployment_allowed=false" in body
    assert "spend_allowed=false" in body
    assert "owner_approved=false" in body
    assert "no_outbound=true" in body
    assert "no_provider_calls=true" in body
    assert "no_first_send=true" in body
    assert "supervised_pilot_launch_rehearsal_control_map_is_not_go_live=true" in body
    assert "rehearsal_control_map_is_not_a_script_runner=true" in body
    assert "control_map_is_not_execution=true" in body
    assert "export_is_not_permission_to_go_live=true" in body
    assert "export_is_not_execution=true" in body
    assert "supervised-pilot-launch-rehearsal-control-map" in body
    assert "supervised-pilot-first-send-preflight" in body
    assert "supervised-pilot-go-no-go" in body
    assert "supervised-pilot-plan" in body
    assert "Halt unchanged" in body
    assert "Control map rows" in body
    payload = json_export.json()
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE
    _assert_no_execution(payload)
    assert payload["read_only"] is True
    assert payload["no_execution"] is True
    assert payload["no_outbound"] is True
    assert payload["no_provider_calls"] is True
    assert payload["no_spend"] is True
    assert payload["no_first_send"] is True
    assert payload["executed"] == 0
    assert payload["first_send_allowed"] is False
    assert payload["first_send_executed"] == 0
    assert payload["go_live_permitted"] is False
    first_send_payload = first_send_export.json()
    assert first_send_payload["packet_kind"] == "supervised_pilot_first_send_preflight"
    assert first_send_payload["read_only"] is True
    assert first_send_payload["no_execution"] is True
    assert first_send_payload["executed"] == 0
    assert first_send_payload["go_live_permitted"] is False
    assert cli_json.json()["cli_command"] == CLI_COMMAND
    _assert_no_leakage(body, SECRET_VALUE)
    assert PHI_SNIPPET not in body
    assert PROSPECT_EMAIL not in body
    assert PRACTICE_NAME not in body
    assert PROVIDER_NAME not in body
    assert NPI_NUMBER not in body
    assert WEBSITE not in body
    assert "reviewer_notes" not in body
    lowered = body.lower()
    for marker in FORM_MARKERS + CONTACT_MARKERS:
        assert marker not in lowered
    assert _strip_volatile(first.text) == _strip_volatile(second.text)
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
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False
    assert settings.voice_live_enabled is False


def test_operator_supervised_pilot_launch_rehearsal_control_map_failure_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(
        "vyro_growth.api.operator_supervised_pilot_launch_rehearsal_control_map"
        ".SupervisedPilotLaunchRehearsalControlMapService.build",
        _boom,
    )
    response = api_client.get(OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH)

    assert response.status_code == 500
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the supervised pilot launch rehearsal control map" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()
