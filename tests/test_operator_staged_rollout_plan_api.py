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
from vyro_growth.api.operator_staged_rollout_plan import (
    render_staged_rollout_plan,
    render_staged_rollout_plan_error,
)
from vyro_growth.api.operator_ui import OPERATOR_STAGED_ROLLOUT_PLAN_PATH
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
from vyro_growth.services.staged_rollout_plan import (
    STAGE_KEYS,
    StagedRolloutChecklistItem,
    StagedRolloutPlan,
    StagedRolloutStage,
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
    "source-references",
    "related-routes",
    "related-commands",
    "rollout-stages",
    "side-effects",
)
STAGE_SECTION_IDS = tuple(f"stage-{key}" for key in STAGE_KEYS)
LINKED_SURFACES = (
    "/internal/operator-dashboard",
    "/internal/operator-command-center",
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
    "/internal/operator-go-live-readiness-index",
    "/internal/go-live-readiness-index",
    "/internal/operator-launch-blockers-plan",
    "/internal/launch-blockers-plan",
    "/internal/operator-audit-timeline",
    "/internal/operator-staged-rollout-plan",
    "/internal/staged-rollout-plan",
    "/internal/operator-owner-launch-dossier",
    "/internal/operator-provider-setup-checklist",
    "/internal/operator-go-live-rehearsal-checklist",
    "/internal/operator-rehearsal-outcome-report",
    "/internal/operator-supervised-pilot-plan",
    "/internal/operator-supervised-pilot-candidates",
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


def _item(**overrides: object) -> StagedRolloutChecklistItem:
    payload: dict[str, object] = {
        "code": NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value,
        "status": FindingSeverity.INFO.value,
        "label": "Inspect the read-only staged rollout plan.",
        "owner_approval_type": "none",
        "html_route": OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
        "json_route": "/internal/staged-rollout-plan",
        "command_name": "staged-rollout-plan",
        "config_name": None,
    }
    payload.update(overrides)
    return StagedRolloutChecklistItem(**payload)  # type: ignore[arg-type]


def _stage(**overrides: object) -> StagedRolloutStage:
    payload: dict[str, object] = {
        "stage_key": "stage_0",
        "stage_label": "Safe defaults and operator halt verification",
        "status": FindingSeverity.INFO.value,
        "blocker_codes": (NextActionCode.KEEP_OUTBOUND_DISABLED.value,),
        "gate_codes": ("outbound_disabled",),
        "required_owner_approval_type": "none",
        "checklist_items": (_item(),),
        "related_commands": ("staged-rollout-plan",),
        "related_routes": (OPERATOR_STAGED_ROLLOUT_PLAN_PATH,),
        "related_config_names": ("OUTBOUND_ENABLED",),
        "read_only": True,
        "no_execution": True,
        "execution_allowed": False,
        "go_live_permitted": False,
        "deployment_allowed": False,
        "settings_applied": False,
        "halt_changed": False,
        "outbound_enabled": False,
        "owner_approved": False,
        "staged_rollout_plan_is_not_go_live": True,
    }
    payload.update(overrides)
    return StagedRolloutStage(**payload)  # type: ignore[arg-type]


def _empty_plan(**overrides: object) -> StagedRolloutPlan:
    payload: dict[str, object] = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "packet_kind": "staged_go_live_rollout_plan",
        "purpose": "manual_owner_staged_rollout_planning_only",
        "overall_status": "blocked",
        "read_only": True,
        "no_execution": True,
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
        "staged_rollout_plan_is_not_go_live": True,
        "plan_is_not_permission_to_go_live": True,
        "plan_is_not_execution": True,
        "index_is_not_permission_to_go_live": True,
        "handoff_is_not_go_live": True,
        "binder_is_not_go_live": True,
        "runbook_is_not_deployment": True,
        "manifest_is_not_a_build_or_deploy": True,
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "closed_provider_flag_names": ("VOICE_LIVE_ENABLED",),
        "missing_credential_names": (),
        "blocker_codes": ("execution_disabled_in_this_phase",),
        "cli_command": "staged-rollout-plan",
        "http_route": "/internal/staged-rollout-plan",
        "source_index_command": "go-live-readiness-index",
        "source_index_route": "/internal/go-live-readiness-index",
        "source_index_overall_status": "blocked",
        "source_blockers_plan_command": "launch-blockers-plan",
        "source_blockers_plan_route": "/internal/launch-blockers-plan",
        "source_blockers_plan_overall_status": "blocked",
        "source_launch_readiness_command": "launch-readiness",
        "source_launch_readiness_route": "/internal/launch-readiness",
        "source_launch_readiness_overall_status": "blocked",
        "source_binder_command": "compliance-evidence-binder",
        "source_binder_route": "/internal/compliance-evidence-binder",
        "source_binder_overall_status": "blocked",
        "source_runbook_command": "release-candidate-runbook",
        "source_runbook_route": "/internal/release-candidate-runbook",
        "source_runbook_overall_status": "blocked",
        "source_manifest_command": "release-artifact-manifest",
        "source_manifest_route": "/internal/release-artifact-manifest",
        "source_manifest_overall_status": "blocked",
        "related_commands": ("go-live-readiness-index", "staged-rollout-plan"),
        "related_routes": LINKED_SURFACES,
        "local_git": LocalGitMetadata(
            available=True,
            current_branch="main",
            current_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            working_tree_status="not_inspected",
            git_provider_called=False,
            github_actions_called=False,
        ),
        "stages": (),
    }
    payload.update(overrides)
    return StagedRolloutPlan(**payload)  # type: ignore[arg-type]


def _strip_volatile(html: str) -> str:
    stripped = TIMESTAMP_RE.sub("<timestamp>", html)
    stripped = GIT_SHA_RE.sub("<git-sha>", stripped)
    return GIT_BRANCH_RE.sub("<git-branch>", stripped)


def test_renderer_empty_state_is_read_only_and_has_no_execute_controls() -> None:
    html = render_staged_rollout_plan(_empty_plan())

    assert 'id="operator-staged-rollout-plan"' in html
    assert OPERATOR_STAGED_ROLLOUT_PLAN_PATH == "/internal/operator-staged-rollout-plan"
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in html
    assert "No staged rollout groups" in html
    assert "go_live_permitted=false" in html
    assert "execution_allowed=false" in html
    assert "deployment_allowed=false" in html
    assert "build_allowed=false" in html
    assert "artifact_publish_allowed=false" in html
    assert "OUTBOUND_ENABLED=false" in html
    assert "staged_rollout_plan_is_not_go_live=true" in html
    assert "staged rollout planning view" in html
    assert "not permission to go live" in html
    assert "There are no apply, execute, lift-halt" in html
    assert 'data-execution-allowed="false"' in html
    assert 'data-go-live-permitted="false"' in html
    assert 'data-deployment-allowed="false"' in html
    assert 'data-build-allowed="false"' in html
    assert 'data-artifact-publish-allowed="false"' in html
    assert 'data-staged-rollout-plan-is-not-go-live="true"' in html
    assert 'data-plan-is-not-permission-to-go-live="true"' in html
    assert 'data-plan-is-not-execution="true"' in html
    assert "go-live-readiness-index" in html
    assert "launch-blockers-plan" in html
    assert "/internal/go-live-readiness-index" in html
    assert "/internal/launch-blockers-plan" in html
    for href in LINKED_SURFACES:
        assert href in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_renderer_populated_sections_and_xss_escape() -> None:
    html = render_staged_rollout_plan(
        _empty_plan(
            blocker_codes=["execution_disabled_in_this_phase", XSS_LABEL],
            missing_credential_names=["EXAMPLE_API_KEY", XSS_LABEL],
            closed_provider_flag_names=["EXAMPLE_LIVE_ENABLED", XSS_LABEL],
            stages=(
                _stage(
                    stage_key="stage_0",
                    stage_label=XSS_LABEL,
                    checklist_items=(
                        _item(
                            code=XSS_LABEL,
                            label=XSS_LABEL,
                            config_name=XSS_LABEL,
                        ),
                    ),
                ),
                _stage(
                    stage_key="stage_5",
                    stage_label="Future owner-approved live enablement prerequisites only",
                    required_owner_approval_type="live_enablement_review",
                    checklist_items=(
                        _item(
                            code=NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value,
                            html_route=OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
                            json_route="/internal/staged-rollout-plan",
                            command_name="staged-rollout-plan",
                        ),
                    ),
                ),
            ),
        )
    )
    error = render_staged_rollout_plan_error()

    assert XSS_LABEL not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "EXAMPLE_API_KEY" in html
    assert "EXAMPLE_LIVE_ENABLED" in html
    assert "execution_disabled_in_this_phase" in html
    assert 'id="stage-stage_0"' in html
    assert 'id="stage-stage_5"' in html
    assert "Staged rollout" in html
    assert 'id="operator-staged-rollout-plan-error"' in error
    assert "sk-testsecret" not in error
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()
        assert marker not in error.lower()


def test_renderer_is_deterministic_aside_from_timestamps_and_git_metadata() -> None:
    first = render_staged_rollout_plan(_empty_plan())
    second = render_staged_rollout_plan(
        _empty_plan(generated_at=datetime(2026, 9, 1, 8, 30, tzinfo=UTC))
    )
    git_variant = render_staged_rollout_plan(
        _empty_plan(
            local_git=LocalGitMetadata(
                available=True,
                current_branch="cursor/phase-46-staged-rollout-plan-ui-7b0a",
                current_sha="cccccccccccccccccccccccccccccccccccccccc",
                working_tree_status="not_inspected",
                git_provider_called=False,
                github_actions_called=False,
            )
        )
    )

    assert _strip_volatile(first) == _strip_volatile(second)
    assert "cccccccccccccccccccccccccccccccccccccccc" in git_variant
    assert "cursor/phase-46-staged-rollout-plan-ui-7b0a" in git_variant
    assert TIMESTAMP_RE.search(first)
    assert TIMESTAMP_RE.search(second)


def test_operator_staged_rollout_plan_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_STAGED_ROLLOUT_PLAN_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Staged go-live rollout plan" in body
    assert "Staged rollout" in body
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for stage_id in STAGE_SECTION_IDS:
        assert f'id="{stage_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "OUTBOUND_ENABLED=false" in body
    assert "staged_rollout_plan_is_not_go_live=true" in body
    assert "not permission to go live" in body
    assert "Safe defaults and operator halt verification" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in FORM_MARKERS:
        assert marker not in body.lower()


def test_operator_staged_rollout_plan_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_STAGED_ROLLOUT_PLAN_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_STAGED_ROLLOUT_PLAN_PATH)
    invalid = api_client.get(
        OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    put = api_client.put(
        OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    delete = api_client.delete(
        OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    patch = api_client.patch(
        OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405
    assert put.status_code == 405
    assert delete.status_code == 405
    assert patch.status_code == 405


def test_operator_staged_rollout_plan_populated_sections_and_no_side_effects(
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
        idempotency_key="ui-staged-plan-main",
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
        idempotency_key="ui-staged-plan-pending",
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
        OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    second = api_client.get(
        OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    body = first.text
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for stage_id in STAGE_SECTION_IDS:
        assert f'id="{stage_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "OUTBOUND_ENABLED" in body
    assert "execution_disabled_in_this_phase" in body
    assert NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value in body
    assert NextActionCode.LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION.value in body
    assert NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "staged_rollout_plan_is_not_go_live=true" in body
    assert "staged-rollout-plan" in body
    assert "go-live-readiness-index" in body
    assert "launch-blockers-plan" in body
    assert "Safe defaults and operator halt verification" in body
    assert "Credential and configuration preparation" in body
    assert "Local dry-run verification and CI gates" in body
    assert "Owner review of packets, checklists, and readiness surfaces" in body
    assert "Future manual deployment preparation only" in body
    assert "Future owner-approved live enablement prerequisites only" in body
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


def test_operator_staged_rollout_plan_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(
        "vyro_growth.api.operator_staged_rollout_plan.StagedRolloutPlanService.build",
        _boom,
    )
    response = api_client.get(OPERATOR_STAGED_ROLLOUT_PLAN_PATH)

    assert response.status_code == 500
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the staged go-live rollout plan" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()
