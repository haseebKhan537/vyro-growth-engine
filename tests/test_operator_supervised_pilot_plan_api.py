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
from vyro_growth.api.operator_supervised_pilot_plan import (
    render_supervised_pilot_plan,
    render_supervised_pilot_plan_error,
)
from vyro_growth.api.operator_ui import OPERATOR_SUPERVISED_PILOT_PLAN_PATH
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
from vyro_growth.services.supervised_pilot_plan import (
    CLI_COMMAND,
    HTML_ROUTE,
    HTTP_ROUTE,
    PilotAbortCriterion,
    PilotAssertion,
    PilotNextAction,
    PilotPrerequisite,
    PilotRunbookStep,
    PilotScopeRecommendation,
    SupervisedPilotPlan,
)

XSS_LABEL = "<script>alert(1)</script>"
ACTION_MARKERS = ("javascript:", "onclick=", "onerror=")
FORM_MARKERS = ("<form", "<button", "<input", "<select", "<textarea")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
GIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
GIT_BRANCH_RE = re.compile(r"cursor/[A-Za-z0-9._/\-]+")
SECTION_IDS = (
    "live-blocking-flags",
    "plan-gates",
    "pilot-scope",
    "prerequisites",
    "safety-assertions",
    "remaining-owner-approvals",
    "blocker-gate-codes",
    "missing-names",
    "closed-provider-flags",
    "runbook-steps",
    "abort-criteria",
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


def _assertion(**overrides: object) -> PilotAssertion:
    payload: dict[str, object] = {
        "key": "OUTBOUND_ENABLED",
        "expected": "false",
        "observed": "false",
        "passed": True,
    }
    payload.update(overrides)
    return PilotAssertion(**payload)  # type: ignore[arg-type]


def _scope(**overrides: object) -> PilotScopeRecommendation:
    payload: dict[str, object] = {
        "suggested_max_leads": 10,
        "suggested_max_drafts": 5,
        "suggested_max_manually_reviewed_sends": 0,
        "suggested_max_daily_activity": 5,
        "stop_conditions": ("stop_if_outbound_enabled",),
        "recommendation_summary": "Supervised first-pilot count limits only.",
    }
    payload.update(overrides)
    return PilotScopeRecommendation(**payload)  # type: ignore[arg-type]


def _prerequisite(**overrides: object) -> PilotPrerequisite:
    payload: dict[str, object] = {
        "key": "website_credibility",
        "category": "website_credibility",
        "label": "Website credibility",
        "status": FindingSeverity.INFO.value,
        "required_owner_approval_type": "owner_review",
        "missing_credential_names": (),
        "closed_provider_flag_names": (),
        "blocker_codes": (),
        "related_commands": ("launch-readiness",),
        "related_routes": ("/internal/launch-readiness",),
        "review_text": "Inspect website credibility status only.",
    }
    payload.update(overrides)
    return PilotPrerequisite(**payload)  # type: ignore[arg-type]


def _step(**overrides: object) -> PilotRunbookStep:
    payload: dict[str, object] = {
        "step_key": "confirm_safe_defaults",
        "label": "Confirm safe defaults and operator halt",
        "instruction": "Confirm OUTBOUND_ENABLED=false. Do not lift halt.",
        "status": FindingSeverity.INFO.value,
        "runnable": False,
        "executed": 0,
        "command_name": CLI_COMMAND,
        "json_route": HTTP_ROUTE,
        "html_route": HTML_ROUTE,
        "config_name": "OUTBOUND_ENABLED",
    }
    payload.update(overrides)
    return PilotRunbookStep(**payload)  # type: ignore[arg-type]


def _abort(**overrides: object) -> PilotAbortCriterion:
    payload: dict[str, object] = {
        "code": "keep_outbound_disabled",
        "label": "Keep outbound disabled",
        "instruction": "Leave OUTBOUND_ENABLED=false.",
    }
    payload.update(overrides)
    return PilotAbortCriterion(**payload)  # type: ignore[arg-type]


def _action(**overrides: object) -> PilotNextAction:
    payload: dict[str, object] = {
        "code": NextActionCode.SUPERVISED_PILOT_PLAN_IS_NOT_GO_LIVE.value,
        "status": FindingSeverity.INFO.value,
        "label": "This supervised pilot plan is a sanitized review export only.",
        "command_name": CLI_COMMAND,
        "json_route": HTTP_ROUTE,
        "html_route": OPERATOR_SUPERVISED_PILOT_PLAN_PATH,
        "config_name": None,
    }
    payload.update(overrides)
    return PilotNextAction(**payload)  # type: ignore[arg-type]


def _empty_plan(**overrides: object) -> SupervisedPilotPlan:
    payload: dict[str, object] = {
        "generated_at": datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
        "packet_kind": "supervised_pilot_plan",
        "purpose": "manual_owner_supervised_pilot_review_only",
        "overall_status": "blocked",
        "read_only": True,
        "no_execution": True,
        "no_go_live": True,
        "no_deployment": True,
        "no_spend": True,
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
        "supervised_pilot_plan_is_not_go_live": True,
        "plan_is_not_permission_to_go_live": True,
        "plan_is_not_execution": True,
        "rehearsal_outcome_report_is_not_go_live": True,
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
        "safety_assertions": (),
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
        "pilot_scope": _scope(),
        "prerequisites": (),
        "runbook_steps": (),
        "abort_criteria": (),
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "source_outcome_command": "rehearsal-outcome-report",
        "source_outcome_route": "/internal/rehearsal-outcome-report",
        "source_outcome_html_route": "/internal/operator-rehearsal-outcome-report",
        "source_outcome_overall_status": "blocked",
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
        "related_commands": ("supervised-pilot-plan", "rehearsal-outcome-report"),
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
    return SupervisedPilotPlan(**payload)  # type: ignore[arg-type]


def _strip_volatile(html: str) -> str:
    stripped = TIMESTAMP_RE.sub("<timestamp>", html)
    stripped = GIT_SHA_RE.sub("<git-sha>", stripped)
    return GIT_BRANCH_RE.sub("<git-branch>", stripped)


def test_renderer_empty_state_is_read_only_and_has_no_execute_controls() -> None:
    html = render_supervised_pilot_plan(_empty_plan())

    assert 'id="operator-supervised-pilot-plan"' in html
    assert OPERATOR_SUPERVISED_PILOT_PLAN_PATH == "/internal/operator-supervised-pilot-plan"
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in html
    assert "No grouped prerequisites" in html
    assert "No failed safe assertion keys" in html
    assert "No remaining owner approval types" in html
    assert "No manual runbook steps" in html
    assert "No abort or rollback criteria" in html
    assert "No owner next steps" in html
    assert "go_live_permitted=false" in html
    assert "execution_allowed=false" in html
    assert "deployment_allowed=false" in html
    assert "build_allowed=false" in html
    assert "artifact_publish_allowed=false" in html
    assert "spend_allowed=false" in html
    assert "owner_approved=false" in html
    assert "OUTBOUND_ENABLED=false" in html
    assert "supervised_pilot_plan_is_not_go_live=true" in html
    assert "plan_is_not_permission_to_go_live=true" in html
    assert "plan_is_not_execution=true" in html
    assert "supervised pilot planning review view" in html
    assert "not permission to go live" in html
    assert "There are no apply, execute, lift-halt" in html
    assert 'data-execution-allowed="false"' in html
    assert 'data-go-live-permitted="false"' in html
    assert 'data-deployment-allowed="false"' in html
    assert 'data-build-allowed="false"' in html
    assert 'data-artifact-publish-allowed="false"' in html
    assert 'data-spend-allowed="false"' in html
    assert 'data-no-spend="true"' in html
    assert 'data-supervised-pilot-plan-is-not-go-live="true"' in html
    assert 'data-plan-is-not-permission-to-go-live="true"' in html
    assert 'data-plan-is-not-execution="true"' in html
    assert "Halt unchanged" in html
    for href in LINKED_SURFACES:
        assert href in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_renderer_populated_sections_and_xss_escape() -> None:
    html = render_supervised_pilot_plan(
        _empty_plan(
            blocker_codes=["execution_disabled_in_this_phase", XSS_LABEL],
            gate_codes=["no_execution", XSS_LABEL],
            missing_credential_names=["EXAMPLE_API_KEY", XSS_LABEL],
            missing_config_names=["OUTBOUND_ENABLED", XSS_LABEL],
            closed_provider_flag_names=["EXAMPLE_LIVE_ENABLED", XSS_LABEL],
            failed_safe_assertion_keys=(XSS_LABEL, "go_live_permitted"),
            remaining_owner_approval_types=("live_enablement_review", XSS_LABEL),
            safety_assertions=(
                _assertion(key=XSS_LABEL, expected=SECRET_VALUE, observed=SECRET_VALUE),
                _assertion(key="go_live_permitted", passed=False),
            ),
            expected_safe_assertion_count=2,
            expected_safe_assertions_passed=0,
            expected_safe_assertions_failed=2,
            pilot_scope=_scope(recommendation_summary=XSS_LABEL),
            prerequisites=(
                _prerequisite(key=XSS_LABEL, label=XSS_LABEL, review_text=XSS_LABEL),
                _prerequisite(
                    key="email_outreach_setup",
                    category="email_outreach_setup",
                    label="Email / outreach setup",
                ),
            ),
            runbook_steps=(
                _step(step_key=XSS_LABEL, label=XSS_LABEL, instruction=XSS_LABEL),
                _step(),
            ),
            abort_criteria=(_abort(code=XSS_LABEL, label=XSS_LABEL, instruction=XSS_LABEL),),
            next_actions=(
                _action(code=XSS_LABEL, label=XSS_LABEL, config_name=XSS_LABEL),
                _action(),
            ),
        )
    )
    error = render_supervised_pilot_plan_error()

    assert XSS_LABEL not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert SECRET_VALUE not in html
    assert "EXAMPLE_API_KEY" in html
    assert "EXAMPLE_LIVE_ENABLED" in html
    assert "execution_disabled_in_this_phase" in html
    assert "live_enablement_review" in html
    assert "Email / outreach setup" in html
    assert "runnable=false" in html
    assert "executed=0" in html
    assert "Supervised pilot launch plan" in html
    assert 'id="operator-supervised-pilot-plan-error"' in error
    assert "sk-testsecret" not in error
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()
        assert marker not in error.lower()


def test_renderer_is_deterministic_aside_from_timestamps_and_git_metadata() -> None:
    first = render_supervised_pilot_plan(_empty_plan())
    second = render_supervised_pilot_plan(
        _empty_plan(generated_at=datetime(2026, 9, 7, 8, 30, tzinfo=UTC))
    )
    git_variant = render_supervised_pilot_plan(
        _empty_plan(
            local_git=LocalGitMetadata(
                available=True,
                current_branch="cursor/phase-56-supervised-pilot-plan-ui-e46d",
                current_sha="cccccccccccccccccccccccccccccccccccccccc",
                working_tree_status="not_inspected",
                git_provider_called=False,
                github_actions_called=False,
            )
        )
    )

    assert _strip_volatile(first) == _strip_volatile(second)
    assert "cccccccccccccccccccccccccccccccccccccccc" in git_variant
    assert "cursor/phase-56-supervised-pilot-plan-ui-e46d" in git_variant
    assert TIMESTAMP_RE.search(first)
    assert TIMESTAMP_RE.search(second)


def test_operator_supervised_pilot_plan_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_SUPERVISED_PILOT_PLAN_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    body = response.text
    assert "Supervised pilot launch plan" in body
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "spend_allowed=false" in body
    assert "owner_approved=false" in body
    assert "OUTBOUND_ENABLED=false" in body
    assert "supervised_pilot_plan_is_not_go_live=true" in body
    assert "plan_is_not_permission_to_go_live=true" in body
    assert "plan_is_not_execution=true" in body
    assert "not permission to go live" in body
    assert "Safe count-only pilot scope" in body
    assert "Grouped prerequisites" in body
    assert "Safety assertions" in body
    assert "Failed safe assertion keys" in body
    assert "Manual runbook steps" in body
    assert "Abort and rollback criteria" in body
    assert "Closed provider and live flag names" in body
    assert "Non-executable owner next steps" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in FORM_MARKERS:
        assert marker not in body.lower()


def test_operator_supervised_pilot_plan_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_SUPERVISED_PILOT_PLAN_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_SUPERVISED_PILOT_PLAN_PATH)
    invalid = api_client.get(
        OPERATOR_SUPERVISED_PILOT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_SUPERVISED_PILOT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    put = api_client.put(
        OPERATOR_SUPERVISED_PILOT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    delete = api_client.delete(
        OPERATOR_SUPERVISED_PILOT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    patch = api_client.patch(
        OPERATOR_SUPERVISED_PILOT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405
    assert put.status_code == 405
    assert delete.status_code == 405
    assert patch.status_code == 405


def test_operator_supervised_pilot_plan_populated_sections_and_no_side_effects(
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
        idempotency_key="ui-supervised-pilot-plan-main",
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
        idempotency_key="ui-supervised-pilot-plan-pending",
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
        OPERATOR_SUPERVISED_PILOT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    second = api_client.get(
        OPERATOR_SUPERVISED_PILOT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    json_export = api_client.get(
        HTTP_ROUTE,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert json_export.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    body = first.text
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "OUTBOUND_ENABLED" in body
    assert "execution_disabled_in_this_phase" in body
    assert NextActionCode.SUPERVISED_PILOT_PLAN_IS_NOT_GO_LIVE.value in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "spend_allowed=false" in body
    assert "owner_approved=false" in body
    assert "supervised_pilot_plan_is_not_go_live=true" in body
    assert "plan_is_not_permission_to_go_live=true" in body
    assert "plan_is_not_execution=true" in body
    assert "supervised-pilot-plan" in body
    assert "rehearsal-outcome-report" in body
    assert "go-live-rehearsal-checklist" in body
    assert "Website credibility" in body
    assert "Email / domain setup" in body
    assert "Email / outreach setup" in body
    assert "runnable=false" in body
    assert "executed=0" in body
    assert "Halt unchanged" in body
    assert "Suggested max leads" in body
    payload = json_export.json()
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE
    assert payload["read_only"] is True
    assert payload["no_execution"] is True
    assert payload["no_spend"] is True
    assert payload["executed"] == 0
    assert payload["go_live_permitted"] is False
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


def test_operator_supervised_pilot_plan_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(
        "vyro_growth.api.operator_supervised_pilot_plan.SupervisedPilotPlanService.build",
        _boom,
    )
    response = api_client.get(OPERATOR_SUPERVISED_PILOT_PLAN_PATH)

    assert response.status_code == 500
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the supervised pilot launch plan" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()

