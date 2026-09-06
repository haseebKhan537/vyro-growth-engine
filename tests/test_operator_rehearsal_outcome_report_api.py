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
from vyro_growth.api.operator_rehearsal_outcome_report import (
    render_rehearsal_outcome_report,
    render_rehearsal_outcome_report_error,
)
from vyro_growth.api.operator_ui import OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH
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
from vyro_growth.services.rehearsal_outcome_report import (
    OutcomeCount,
    OutcomeNextAction,
    RehearsalOutcomeReport,
)
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

XSS_LABEL = "<script>alert(1)</script>"
ACTION_MARKERS = ("javascript:", "onclick=", "onerror=")
FORM_MARKERS = ("<form", "<button", "<input", "<select", "<textarea")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
GIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
GIT_BRANCH_RE = re.compile(r"cursor/[A-Za-z0-9._/\-]+")
SECTION_IDS = (
    "live-blocking-flags",
    "report-gates",
    "rehearsal-step-counts",
    "expected-safe-assertions",
    "remaining-owner-approvals",
    "blocker-gate-codes",
    "missing-names",
    "closed-provider-flags",
    "outcome-summary",
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


def _count(key: str, count: int) -> OutcomeCount:
    return OutcomeCount(key=key, count=count)


def _action(**overrides: object) -> OutcomeNextAction:
    payload: dict[str, object] = {
        "code": NextActionCode.REHEARSAL_OUTCOME_REPORT_IS_NOT_GO_LIVE.value,
        "status": FindingSeverity.INFO.value,
        "label": "This rehearsal outcome report is a sanitized review export only.",
        "command_name": "rehearsal-outcome-report",
        "json_route": "/internal/rehearsal-outcome-report",
        "html_route": OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH,
        "config_name": None,
    }
    payload.update(overrides)
    return OutcomeNextAction(**payload)  # type: ignore[arg-type]


def _empty_report(**overrides: object) -> RehearsalOutcomeReport:
    payload: dict[str, object] = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "packet_kind": "rehearsal_outcome_report",
        "purpose": "manual_owner_rehearsal_outcome_review_only",
        "overall_status": "blocked",
        "read_only": True,
        "no_execution": True,
        "no_go_live": True,
        "no_deployment": True,
        "dry_run_only": True,
        "executed": 0,
        "execution_attempted": False,
        "outbound_attempted": False,
        "live_call_attempted": False,
        "recommendation_applied": False,
        "spend_attempted": False,
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
        "rehearsal_outcome_report_is_not_go_live": True,
        "report_is_not_permission_to_go_live": True,
        "report_is_not_execution": True,
        "go_live_rehearsal_checklist_is_not_go_live": True,
        "rehearsal_is_not_a_script_runner": True,
        "index_is_not_permission_to_go_live": True,
        "dossier_is_not_permission_to_go_live": True,
        "staged_rollout_plan_is_not_go_live": True,
        "provider_setup_checklist_is_not_go_live": True,
        "runbook_is_not_deployment": True,
        "manifest_is_not_a_build_or_deploy": True,
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "rehearsal_step_count": 0,
        "rehearsal_step_counts_by_status": (),
        "rehearsal_step_counts_by_kind": (),
        "rehearsal_step_counts_by_required_owner_approval_type": (),
        "expected_safe_assertion_count": 0,
        "expected_safe_assertions_passed": 0,
        "expected_safe_assertions_failed": 0,
        "failed_safe_assertion_keys": (),
        "remaining_owner_approval_types": (),
        "closed_provider_flag_names": ("VOICE_LIVE_ENABLED",),
        "missing_credential_names": (),
        "missing_config_names": (),
        "blocker_codes": ("execution_disabled_in_this_phase",),
        "gate_codes": ("no_execution", "no_go_live"),
        "outcome_summary": (
            "Manual rehearsal outcome only, not permission to go live. "
            "status=blocked steps=0 blocked=0 warning=0 assertions_failed=0 "
            "failed_keys=none remaining_owner_approval_types=0."
        ),
        "cli_command": "rehearsal-outcome-report",
        "http_route": "/internal/rehearsal-outcome-report",
        "source_rehearsal_command": "go-live-rehearsal-checklist",
        "source_rehearsal_route": "/internal/go-live-rehearsal-checklist",
        "source_rehearsal_html_route": "/internal/operator-go-live-rehearsal-checklist",
        "source_rehearsal_overall_status": "blocked",
        "source_launch_readiness_command": "launch-readiness",
        "source_launch_readiness_route": "/internal/launch-readiness",
        "source_launch_readiness_overall_status": "blocked",
        "source_index_command": "go-live-readiness-index",
        "source_index_route": "/internal/go-live-readiness-index",
        "source_index_overall_status": "blocked",
        "source_blockers_plan_command": "launch-blockers-plan",
        "source_blockers_plan_route": "/internal/launch-blockers-plan",
        "source_blockers_plan_overall_status": "blocked",
        "source_staged_rollout_command": "staged-rollout-plan",
        "source_staged_rollout_route": "/internal/staged-rollout-plan",
        "source_staged_rollout_overall_status": "blocked",
        "source_dossier_command": "owner-launch-dossier",
        "source_dossier_route": "/internal/owner-launch-dossier",
        "source_dossier_overall_status": "blocked",
        "source_provider_setup_command": "provider-setup-checklist",
        "source_provider_setup_route": "/internal/provider-setup-checklist",
        "source_provider_setup_overall_status": "blocked",
        "source_preflight_command": "settings-execution-preflight",
        "source_preflight_route": "/internal/settings-execution-preflight",
        "source_preflight_overall_status": "blocked",
        "related_commands": ("go-live-rehearsal-checklist", "rehearsal-outcome-report"),
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
    return RehearsalOutcomeReport(**payload)  # type: ignore[arg-type]


def _strip_volatile(html: str) -> str:
    stripped = TIMESTAMP_RE.sub("<timestamp>", html)
    stripped = GIT_SHA_RE.sub("<git-sha>", stripped)
    return GIT_BRANCH_RE.sub("<git-branch>", stripped)


def test_renderer_empty_state_is_read_only_and_has_no_execute_controls() -> None:
    html = render_rehearsal_outcome_report(_empty_report())

    assert 'id="operator-rehearsal-outcome-report"' in html
    assert OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH == "/internal/operator-rehearsal-outcome-report"
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in html
    assert "No status counts" in html
    assert "No failed safe assertion keys" in html
    assert "No remaining owner approval types" in html
    assert "No owner next steps" in html
    assert "go_live_permitted=false" in html
    assert "execution_allowed=false" in html
    assert "deployment_allowed=false" in html
    assert "build_allowed=false" in html
    assert "artifact_publish_allowed=false" in html
    assert "owner_approved=false" in html
    assert "OUTBOUND_ENABLED=false" in html
    assert "rehearsal_outcome_report_is_not_go_live=true" in html
    assert "report_is_not_permission_to_go_live=true" in html
    assert "report_is_not_execution=true" in html
    assert "outcome report review view" in html
    assert "not permission to go live" in html
    assert "There are no apply, execute, lift-halt" in html
    assert 'data-execution-allowed="false"' in html
    assert 'data-go-live-permitted="false"' in html
    assert 'data-deployment-allowed="false"' in html
    assert 'data-build-allowed="false"' in html
    assert 'data-artifact-publish-allowed="false"' in html
    assert 'data-rehearsal-outcome-report-is-not-go-live="true"' in html
    assert 'data-report-is-not-permission-to-go-live="true"' in html
    assert 'data-report-is-not-execution="true"' in html
    assert "go-live-readiness-index" in html
    assert "launch-blockers-plan" in html
    assert "staged-rollout-plan" in html
    assert "/internal/go-live-readiness-index" in html
    assert "/internal/launch-blockers-plan" in html
    assert "/internal/staged-rollout-plan" in html
    for href in LINKED_SURFACES:
        assert href in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_renderer_populated_sections_and_xss_escape() -> None:
    html = render_rehearsal_outcome_report(
        _empty_report(
            blocker_codes=["execution_disabled_in_this_phase", XSS_LABEL],
            gate_codes=["no_execution", XSS_LABEL],
            missing_credential_names=["EXAMPLE_API_KEY", XSS_LABEL],
            missing_config_names=["OUTBOUND_ENABLED", XSS_LABEL],
            closed_provider_flag_names=["EXAMPLE_LIVE_ENABLED", XSS_LABEL],
            failed_safe_assertion_keys=(XSS_LABEL, "go_live_permitted"),
            remaining_owner_approval_types=("live_enablement_review", XSS_LABEL),
            rehearsal_step_count=2,
            rehearsal_step_counts_by_status=(
                _count(FindingSeverity.BLOCKED.value, 1),
                _count(XSS_LABEL, 1),
            ),
            rehearsal_step_counts_by_kind=(_count("manual_review", 2),),
            rehearsal_step_counts_by_required_owner_approval_type=(
                _count("live_enablement_review", 1),
            ),
            outcome_summary=XSS_LABEL,
            next_actions=(
                _action(code=XSS_LABEL, label=XSS_LABEL, config_name=XSS_LABEL),
                _action(
                    code=NextActionCode.REHEARSAL_OUTCOME_REPORT_IS_NOT_GO_LIVE.value,
                    html_route=OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH,
                    json_route="/internal/rehearsal-outcome-report",
                    command_name="rehearsal-outcome-report",
                ),
            ),
        )
    )
    error = render_rehearsal_outcome_report_error()

    assert XSS_LABEL not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "EXAMPLE_API_KEY" in html
    assert "EXAMPLE_LIVE_ENABLED" in html
    assert "execution_disabled_in_this_phase" in html
    assert "live_enablement_review" in html
    assert "Rehearsal outcome report" in html
    assert 'id="operator-rehearsal-outcome-report-error"' in error
    assert "sk-testsecret" not in error
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()
        assert marker not in error.lower()


def test_renderer_is_deterministic_aside_from_timestamps_and_git_metadata() -> None:
    first = render_rehearsal_outcome_report(_empty_report())
    second = render_rehearsal_outcome_report(
        _empty_report(generated_at=datetime(2026, 9, 1, 8, 30, tzinfo=UTC))
    )
    git_variant = render_rehearsal_outcome_report(
        _empty_report(
            local_git=LocalGitMetadata(
                available=True,
                current_branch="cursor/phase-54-rehearsal-outcome-ui-a116",
                current_sha="cccccccccccccccccccccccccccccccccccccccc",
                working_tree_status="not_inspected",
                git_provider_called=False,
                github_actions_called=False,
            )
        )
    )

    assert _strip_volatile(first) == _strip_volatile(second)
    assert "cccccccccccccccccccccccccccccccccccccccc" in git_variant
    assert "cursor/phase-54-rehearsal-outcome-ui-a116" in git_variant
    assert TIMESTAMP_RE.search(first)
    assert TIMESTAMP_RE.search(second)


def test_operator_rehearsal_outcome_report_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    body = response.text
    assert "Rehearsal outcome report" in body
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "owner_approved=false" in body
    assert "OUTBOUND_ENABLED=false" in body
    assert "rehearsal_outcome_report_is_not_go_live=true" in body
    assert "report_is_not_permission_to_go_live=true" in body
    assert "report_is_not_execution=true" in body
    assert "not permission to go live" in body
    assert "Rehearsal step counts" in body
    assert "Expected safe assertions" in body
    assert "Failed safe assertion keys" in body
    assert "Remaining owner approval types" in body
    assert "Closed provider and live flag names" in body
    assert "Outcome summary" in body
    assert "Non-executable owner next steps" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in FORM_MARKERS:
        assert marker not in body.lower()


def test_operator_rehearsal_outcome_report_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH)
    invalid = api_client.get(
        OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    put = api_client.put(
        OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    delete = api_client.delete(
        OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    patch = api_client.patch(
        OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405
    assert put.status_code == 405
    assert delete.status_code == 405
    assert patch.status_code == 405


def test_operator_rehearsal_outcome_report_populated_sections_and_no_side_effects(
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
        idempotency_key="ui-rehearsal-outcome-report-main",
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
        idempotency_key="ui-rehearsal-outcome-report-pending",
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
        OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    second = api_client.get(
        OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    body = first.text
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "OUTBOUND_ENABLED" in body
    assert "execution_disabled_in_this_phase" in body
    assert NextActionCode.REHEARSAL_OUTCOME_REPORT_IS_NOT_GO_LIVE.value in body
    assert NextActionCode.GO_LIVE_REHEARSAL_CHECKLIST_IS_NOT_GO_LIVE.value in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "owner_approved=false" in body
    assert "rehearsal_outcome_report_is_not_go_live=true" in body
    assert "report_is_not_permission_to_go_live=true" in body
    assert "report_is_not_execution=true" in body
    assert "rehearsal-outcome-report" in body
    assert "go-live-rehearsal-checklist" in body
    assert "go-live-readiness-index" in body
    assert "launch-blockers-plan" in body
    assert "staged-rollout-plan" in body
    assert "Launch readiness" in body
    assert "Go-live readiness index" in body
    assert "Launch blockers remediation plan" in body
    assert "Staged go-live rollout plan" in body
    assert "Owner launch dossier" in body
    assert "Provider setup checklist" in body
    assert "Settings execution preflight" in body
    assert "Failed safe assertion keys" in body
    assert "Halt unchanged" in body
    _assert_no_leakage(body, SECRET_VALUE)
    assert PHI_SNIPPET not in body
    assert PROSPECT_EMAIL not in body
    assert "reviewer_notes" not in body
    for marker in FORM_MARKERS:
        assert marker not in body.lower()
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


def test_operator_rehearsal_outcome_report_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(
        "vyro_growth.api.operator_rehearsal_outcome_report.RehearsalOutcomeReportService.build",
        _boom,
    )
    response = api_client.get(OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH)

    assert response.status_code == 500
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the rehearsal outcome report" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()
