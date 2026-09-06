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
from vyro_growth.api.operator_go_live_rehearsal_checklist import (
    render_go_live_rehearsal_checklist,
    render_go_live_rehearsal_checklist_error,
)
from vyro_growth.api.operator_ui import OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH
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
from vyro_growth.services.go_live_rehearsal_checklist import (
    GATE_KEYS,
    GoLiveRehearsalChecklist,
    RehearsalAssertion,
    RehearsalNextAction,
    RehearsalRollbackNote,
    RehearsalSourceSurface,
    RehearsalStep,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

XSS_LABEL = "<script>alert(1)</script>"
ACTION_MARKERS = ("javascript:", "onclick=", "onerror=")
FORM_MARKERS = ("<form", "<button", "<input", "<select", "<textarea")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
GIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
GIT_BRANCH_RE = re.compile(r"cursor/[A-Za-z0-9._/\-]+")
STEP_KEYS = (
    "verify_safe_defaults",
    "review_launch_readiness",
    "review_go_live_readiness_index",
    "review_launch_blockers_plan",
    "review_provider_setup_checklist",
    "review_settings_execution_preflight",
    "review_staged_rollout_plan",
    "review_owner_launch_dossier",
    "review_release_candidate_runbook",
    "review_release_artifact_manifest",
    "confirm_expected_safe_assertions",
    "abort_or_rollback_review",
)
SECTION_IDS = (
    "live-blocking-flags",
    "checklist-gates",
    "expected-safe-assertions",
    "source-references",
    "included-surfaces",
    "rehearsal-steps",
    "rollback-guidance",
    "related-routes",
    "related-commands",
    "local-git",
    "owner-next-steps",
    "side-effects",
)
STEP_SECTION_IDS = tuple(f"step-{key}" for key in STEP_KEYS)
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
    "/internal/operator-supervised-pilot-plan",
    "/internal/operator-supervised-pilot-candidates",
    "/internal/operator-supervised-pilot-go-no-go",
    "/internal/rehearsal-outcome-report",
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


def _assertion(**overrides: object) -> RehearsalAssertion:
    payload: dict[str, object] = {
        "key": "OUTBOUND_ENABLED",
        "expected": "false",
        "observed": "false",
        "passed": True,
    }
    payload.update(overrides)
    return RehearsalAssertion(**payload)  # type: ignore[arg-type]


def _source(**overrides: object) -> RehearsalSourceSurface:
    payload: dict[str, object] = {
        "key": "launch-readiness",
        "label": "Launch readiness",
        "purpose": "manual_review_only",
        "overall_status": FindingSeverity.INFO.value,
        "command_name": "launch-readiness",
        "json_route": "/internal/launch-readiness",
        "html_route": "/internal/launch-readiness",
        "blocker_codes": (),
        "gate_codes": ("no_execution",),
        "missing_credential_names": (),
        "read_only": True,
        "no_execution": True,
        "go_live_permitted": False,
        "deployment_allowed": False,
    }
    payload.update(overrides)
    return RehearsalSourceSurface(**payload)  # type: ignore[arg-type]


def _step(**overrides: object) -> RehearsalStep:
    payload: dict[str, object] = {
        "step_key": "verify_safe_defaults",
        "gate_key": "safe_defaults",
        "label": "Verify safe defaults",
        "instruction": "Confirm OUTBOUND_ENABLED remains false.",
        "status": FindingSeverity.INFO.value,
        "step_kind": "manual_review",
        "required_owner_approval_type": "none",
        "command_name": "launch-readiness",
        "json_route": "/internal/launch-readiness",
        "html_route": "/internal/launch-readiness",
        "config_name": "OUTBOUND_ENABLED",
        "expected_assertions": ("OUTBOUND_ENABLED",),
        "blocker_codes": (),
        "gate_codes": ("outbound_disabled",),
        "runnable": False,
        "executed": 0,
    }
    payload.update(overrides)
    return RehearsalStep(**payload)  # type: ignore[arg-type]


def _rollback(**overrides: object) -> RehearsalRollbackNote:
    payload: dict[str, object] = {
        "code": "keep_outbound_disabled",
        "label": "Keep outbound disabled",
        "instruction": "Leave OUTBOUND_ENABLED=false.",
    }
    payload.update(overrides)
    return RehearsalRollbackNote(**payload)  # type: ignore[arg-type]


def _action(**overrides: object) -> RehearsalNextAction:
    payload: dict[str, object] = {
        "code": NextActionCode.GO_LIVE_REHEARSAL_CHECKLIST_IS_NOT_GO_LIVE.value,
        "status": FindingSeverity.INFO.value,
        "label": "This go-live rehearsal checklist is a sanitized review export only.",
        "command_name": "go-live-rehearsal-checklist",
        "json_route": "/internal/go-live-rehearsal-checklist",
        "html_route": OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH,
        "config_name": None,
    }
    payload.update(overrides)
    return RehearsalNextAction(**payload)  # type: ignore[arg-type]


def _empty_checklist(**overrides: object) -> GoLiveRehearsalChecklist:
    payload: dict[str, object] = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "packet_kind": "go_live_rehearsal_checklist",
        "purpose": "manual_owner_go_live_rehearsal_review_only",
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
        "go_live_rehearsal_checklist_is_not_go_live": True,
        "checklist_is_not_permission_to_go_live": True,
        "checklist_is_not_execution": True,
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
        "closed_provider_flag_names": ("VOICE_LIVE_ENABLED",),
        "missing_credential_names": (),
        "blocker_codes": ("execution_disabled_in_this_phase",),
        "gate_codes": ("no_execution", "no_go_live"),
        "cli_command": "go-live-rehearsal-checklist",
        "http_route": "/internal/go-live-rehearsal-checklist",
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
        "source_runbook_command": "release-candidate-runbook",
        "source_runbook_route": "/internal/release-candidate-runbook",
        "source_runbook_overall_status": "blocked",
        "source_manifest_command": "release-artifact-manifest",
        "source_manifest_route": "/internal/release-artifact-manifest",
        "source_manifest_overall_status": "blocked",
        "related_commands": ("go-live-readiness-index", "go-live-rehearsal-checklist"),
        "related_routes": LINKED_SURFACES,
        "local_git": LocalGitMetadata(
            available=True,
            current_branch="main",
            current_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            working_tree_status="not_inspected",
            git_provider_called=False,
            github_actions_called=False,
        ),
        "expected_safe_assertions": (),
        "sources": (),
        "rehearsal_steps": (),
        "rollback_guidance": (),
        "next_actions": (),
    }
    payload.update(overrides)
    return GoLiveRehearsalChecklist(**payload)  # type: ignore[arg-type]


def _strip_volatile(html: str) -> str:
    stripped = TIMESTAMP_RE.sub("<timestamp>", html)
    stripped = GIT_SHA_RE.sub("<git-sha>", stripped)
    return GIT_BRANCH_RE.sub("<git-branch>", stripped)


def test_renderer_empty_state_is_read_only_and_has_no_execute_controls() -> None:
    html = render_go_live_rehearsal_checklist(_empty_checklist())

    assert 'id="operator-go-live-rehearsal-checklist"' in html
    assert (
        OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH
        == "/internal/operator-go-live-rehearsal-checklist"
    )
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in html
    assert "No rehearsal steps" in html
    assert "No expected safe assertions" in html
    assert "No rollback or abort guidance" in html
    assert "No owner next steps" in html
    assert "go_live_permitted=false" in html
    assert "execution_allowed=false" in html
    assert "deployment_allowed=false" in html
    assert "build_allowed=false" in html
    assert "artifact_publish_allowed=false" in html
    assert "owner_approved=false" in html
    assert "OUTBOUND_ENABLED=false" in html
    assert "go_live_rehearsal_checklist_is_not_go_live=true" in html
    assert "rehearsal_is_not_a_script_runner=true" in html
    assert "manual rehearsal review view" in html
    assert "not permission to go live" in html
    assert "There are no apply, execute, lift-halt" in html
    assert 'data-execution-allowed="false"' in html
    assert 'data-go-live-permitted="false"' in html
    assert 'data-deployment-allowed="false"' in html
    assert 'data-build-allowed="false"' in html
    assert 'data-artifact-publish-allowed="false"' in html
    assert 'data-go-live-rehearsal-checklist-is-not-go-live="true"' in html
    assert 'data-checklist-is-not-permission-to-go-live="true"' in html
    assert 'data-checklist-is-not-execution="true"' in html
    assert 'data-rehearsal-is-not-a-script-runner="true"' in html
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
    html = render_go_live_rehearsal_checklist(
        _empty_checklist(
            blocker_codes=["execution_disabled_in_this_phase", XSS_LABEL],
            gate_codes=["no_execution", XSS_LABEL],
            missing_credential_names=["EXAMPLE_API_KEY", XSS_LABEL],
            closed_provider_flag_names=["EXAMPLE_LIVE_ENABLED", XSS_LABEL],
            expected_safe_assertions=(
                _assertion(key=XSS_LABEL, expected=XSS_LABEL, observed=XSS_LABEL),
                _assertion(key="go_live_permitted", expected="false", observed="false"),
            ),
            sources=(
                _source(key="launch-readiness", label=XSS_LABEL),
                _source(
                    key="provider-setup-checklist",
                    label="Provider setup checklist",
                    missing_credential_names=(XSS_LABEL,),
                ),
            ),
            rehearsal_steps=(
                _step(step_key="verify_safe_defaults", label=XSS_LABEL),
                _step(
                    step_key="review_provider_setup_checklist",
                    gate_key="provider_setup_checklist",
                    label="Review provider setup",
                    instruction=XSS_LABEL,
                    required_owner_approval_type="live_enablement_review",
                ),
            ),
            rollback_guidance=(_rollback(code=XSS_LABEL, label=XSS_LABEL, instruction=XSS_LABEL),),
            next_actions=(
                _action(code=XSS_LABEL, label=XSS_LABEL, config_name=XSS_LABEL),
                _action(
                    code=NextActionCode.GO_LIVE_REHEARSAL_CHECKLIST_IS_NOT_GO_LIVE.value,
                    html_route=OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH,
                    json_route="/internal/go-live-rehearsal-checklist",
                    command_name="go-live-rehearsal-checklist",
                ),
            ),
        )
    )
    error = render_go_live_rehearsal_checklist_error()

    assert XSS_LABEL not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "EXAMPLE_API_KEY" in html
    assert "EXAMPLE_LIVE_ENABLED" in html
    assert "execution_disabled_in_this_phase" in html
    assert 'id="step-verify_safe_defaults"' in html
    assert 'id="step-review_provider_setup_checklist"' in html
    assert "live_enablement_review" in html
    assert "Go-live rehearsal checklist" in html
    assert 'id="operator-go-live-rehearsal-checklist-error"' in error
    assert "sk-testsecret" not in error
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()
        assert marker not in error.lower()


def test_renderer_is_deterministic_aside_from_timestamps_and_git_metadata() -> None:
    first = render_go_live_rehearsal_checklist(_empty_checklist())
    second = render_go_live_rehearsal_checklist(
        _empty_checklist(generated_at=datetime(2026, 9, 1, 8, 30, tzinfo=UTC))
    )
    git_variant = render_go_live_rehearsal_checklist(
        _empty_checklist(
            local_git=LocalGitMetadata(
                available=True,
                current_branch="cursor/phase-52-rehearsal-checklist-ui-1ea1",
                current_sha="cccccccccccccccccccccccccccccccccccccccc",
                working_tree_status="not_inspected",
                git_provider_called=False,
                github_actions_called=False,
            )
        )
    )

    assert _strip_volatile(first) == _strip_volatile(second)
    assert "cccccccccccccccccccccccccccccccccccccccc" in git_variant
    assert "cursor/phase-52-rehearsal-checklist-ui-1ea1" in git_variant
    assert TIMESTAMP_RE.search(first)
    assert TIMESTAMP_RE.search(second)


def test_operator_go_live_rehearsal_checklist_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    body = response.text
    assert "Go-live rehearsal checklist" in body
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for step_id in STEP_SECTION_IDS:
        assert f'id="{step_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "owner_approved=false" in body
    assert "OUTBOUND_ENABLED=false" in body
    assert "go_live_rehearsal_checklist_is_not_go_live=true" in body
    assert "rehearsal_is_not_a_script_runner=true" in body
    assert "not permission to go live" in body
    assert "runnable" in body.lower()
    assert "executed=0" in body or ">0<" in body
    assert "Manual rehearsal steps" in body
    assert "Expected safe assertions" in body
    assert "Rollback and abort guidance" in body
    assert "Non-executable owner next steps" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in FORM_MARKERS:
        assert marker not in body.lower()


def test_operator_go_live_rehearsal_checklist_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH)
    invalid = api_client.get(
        OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    put = api_client.put(
        OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    delete = api_client.delete(
        OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    patch = api_client.patch(
        OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405
    assert put.status_code == 405
    assert delete.status_code == 405
    assert patch.status_code == 405


def test_operator_go_live_rehearsal_checklist_populated_sections_and_no_side_effects(
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
        idempotency_key="ui-go-live-rehearsal-checklist-main",
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
        idempotency_key="ui-go-live-rehearsal-checklist-pending",
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
        OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    second = api_client.get(
        OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    body = first.text
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for step_id in STEP_SECTION_IDS:
        assert f'id="{step_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "OUTBOUND_ENABLED" in body
    assert "execution_disabled_in_this_phase" in body
    assert NextActionCode.GO_LIVE_REHEARSAL_CHECKLIST_IS_NOT_GO_LIVE.value in body
    assert NextActionCode.PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value in body
    assert NextActionCode.OWNER_LAUNCH_DOSSIER_IS_NOT_GO_LIVE.value in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "owner_approved=false" in body
    assert "go_live_rehearsal_checklist_is_not_go_live=true" in body
    assert "rehearsal_is_not_a_script_runner=true" in body
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
    assert "Release-candidate runbook" in body
    assert "Release artifact manifest" in body
    assert set(GATE_KEYS)
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


def test_operator_go_live_rehearsal_checklist_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(
        "vyro_growth.api.operator_go_live_rehearsal_checklist.GoLiveRehearsalChecklistService.build",
        _boom,
    )
    response = api_client.get(OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH)

    assert response.status_code == 500
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the go-live rehearsal checklist" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()
