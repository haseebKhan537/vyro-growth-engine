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
from vyro_growth.api.operator_owner_launch_dossier import (
    render_owner_launch_dossier,
    render_owner_launch_dossier_error,
)
from vyro_growth.api.operator_ui import OPERATOR_OWNER_LAUNCH_DOSSIER_PATH
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
from vyro_growth.services.owner_launch_dossier import (
    SOURCE_KEYS,
    DossierAuditSummary,
    DossierNextAction,
    DossierSettingsPreflightSummary,
    DossierSourceSurface,
    OwnerLaunchDossier,
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
    "dossier-gates",
    "source-references",
    "included-surfaces",
    "related-routes",
    "related-commands",
    "local-git",
    "settings-preflight",
    "operator-audit",
    "owner-next-actions",
    "side-effects",
)
SOURCE_SECTION_IDS = tuple(f"surface-{key}" for key in SOURCE_KEYS)
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
    "/internal/operator-rehearsal-outcome-report",
    "/internal/operator-supervised-pilot-plan",
    "/internal/operator-supervised-pilot-candidates",
    "/internal/operator-supervised-pilot-go-no-go",
    "/internal/operator-supervised-pilot-first-send-preflight",
    "/internal/go-live-rehearsal-checklist",
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


def _source(**overrides: object) -> DossierSourceSurface:
    payload: dict[str, object] = {
        "key": "go-live-readiness-index",
        "label": "Go-live readiness index",
        "purpose": "manual_owner_review_index_only",
        "overall_status": FindingSeverity.INFO.value,
        "command_name": "go-live-readiness-index",
        "json_route": "/internal/go-live-readiness-index",
        "html_route": "/internal/operator-go-live-readiness-index",
        "blocker_codes": (NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value,),
        "gate_codes": ("owner_review",),
        "missing_credential_names": (),
        "read_only": True,
        "no_execution": True,
        "go_live_permitted": False,
        "deployment_allowed": False,
    }
    payload.update(overrides)
    return DossierSourceSurface(**payload)  # type: ignore[arg-type]


def _action(**overrides: object) -> DossierNextAction:
    payload: dict[str, object] = {
        "code": NextActionCode.OWNER_LAUNCH_DOSSIER_IS_NOT_GO_LIVE.value,
        "status": FindingSeverity.INFO.value,
        "label": "This owner launch dossier is a sanitized review export only.",
        "command_name": "owner-launch-dossier",
        "json_route": "/internal/owner-launch-dossier",
        "html_route": OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
        "config_name": None,
    }
    payload.update(overrides)
    return DossierNextAction(**payload)  # type: ignore[arg-type]


def _preflight(**overrides: object) -> DossierSettingsPreflightSummary:
    payload: dict[str, object] = {
        "overall_status": FindingSeverity.INFO.value,
        "request_count": 0,
        "pending_decision_count": 0,
        "approved_decision_count": 0,
        "blocked_count": 0,
        "executable_count": 0,
        "blocker_codes": (),
        "missing_gate_codes": (),
        "missing_credential_names": (),
        "closed_provider_flag_names": (),
        "no_execution": True,
        "dry_run_only": True,
        "executed": 0,
        "settings_applied": False,
        "execution_allowed": False,
    }
    payload.update(overrides)
    return DossierSettingsPreflightSummary(**payload)  # type: ignore[arg-type]


def _audit(**overrides: object) -> DossierAuditSummary:
    payload: dict[str, object] = {
        "matching_count": 0,
        "shown_count": 0,
        "truncated": False,
        "available_event_types": (),
        "available_sources": (),
        "available_statuses": (),
        "read_only": True,
        "no_execution": True,
        "executed": 0,
        "halt_changed": False,
        "outbound_enabled": False,
        "operator_halt_status": "halted",
    }
    payload.update(overrides)
    return DossierAuditSummary(**payload)  # type: ignore[arg-type]


def _empty_dossier(**overrides: object) -> OwnerLaunchDossier:
    payload: dict[str, object] = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "packet_kind": "owner_launch_dossier",
        "purpose": "manual_owner_review_export_only",
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
        "owner_launch_dossier_is_not_go_live": True,
        "dossier_is_not_permission_to_go_live": True,
        "dossier_is_not_execution": True,
        "index_is_not_permission_to_go_live": True,
        "handoff_is_not_go_live": True,
        "binder_is_not_go_live": True,
        "runbook_is_not_deployment": True,
        "manifest_is_not_a_build_or_deploy": True,
        "staged_rollout_plan_is_not_go_live": True,
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "closed_provider_flag_names": ("VOICE_LIVE_ENABLED",),
        "missing_credential_names": (),
        "blocker_codes": ("execution_disabled_in_this_phase",),
        "gate_codes": ("no_execution", "no_go_live"),
        "cli_command": "owner-launch-dossier",
        "http_route": "/internal/owner-launch-dossier",
        "source_index_command": "go-live-readiness-index",
        "source_index_route": "/internal/go-live-readiness-index",
        "source_index_overall_status": "blocked",
        "source_blockers_plan_command": "launch-blockers-plan",
        "source_blockers_plan_route": "/internal/launch-blockers-plan",
        "source_blockers_plan_overall_status": "blocked",
        "source_staged_rollout_command": "staged-rollout-plan",
        "source_staged_rollout_route": "/internal/staged-rollout-plan",
        "source_staged_rollout_overall_status": "blocked",
        "source_handoff_command": "owner-handoff-packet",
        "source_handoff_route": "/internal/owner-handoff-packet",
        "source_handoff_overall_status": "blocked",
        "source_binder_command": "compliance-evidence-binder",
        "source_binder_route": "/internal/compliance-evidence-binder",
        "source_binder_overall_status": "blocked",
        "source_runbook_command": "release-candidate-runbook",
        "source_runbook_route": "/internal/release-candidate-runbook",
        "source_runbook_overall_status": "blocked",
        "source_manifest_command": "release-artifact-manifest",
        "source_manifest_route": "/internal/release-artifact-manifest",
        "source_manifest_overall_status": "blocked",
        "source_preflight_command": "settings-execution-preflight",
        "source_preflight_route": "/internal/settings-execution-preflight",
        "source_preflight_overall_status": "blocked",
        "source_audit_route": "/internal/operator-audit-timeline",
        "source_audit_matching_count": 0,
        "related_commands": ("go-live-readiness-index", "owner-launch-dossier"),
        "related_routes": LINKED_SURFACES,
        "local_git": LocalGitMetadata(
            available=True,
            current_branch="main",
            current_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            working_tree_status="not_inspected",
            git_provider_called=False,
            github_actions_called=False,
        ),
        "sources": (),
        "settings_preflight": _preflight(),
        "operator_audit": _audit(),
        "next_actions": (),
    }
    payload.update(overrides)
    return OwnerLaunchDossier(**payload)  # type: ignore[arg-type]


def _strip_volatile(html: str) -> str:
    stripped = TIMESTAMP_RE.sub("<timestamp>", html)
    stripped = GIT_SHA_RE.sub("<git-sha>", stripped)
    return GIT_BRANCH_RE.sub("<git-branch>", stripped)


def test_renderer_empty_state_is_read_only_and_has_no_execute_controls() -> None:
    html = render_owner_launch_dossier(_empty_dossier())

    assert 'id="operator-owner-launch-dossier"' in html
    assert OPERATOR_OWNER_LAUNCH_DOSSIER_PATH == "/internal/operator-owner-launch-dossier"
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in html
    assert "No included source surfaces" in html
    assert "No owner next actions" in html
    assert "go_live_permitted=false" in html
    assert "execution_allowed=false" in html
    assert "deployment_allowed=false" in html
    assert "build_allowed=false" in html
    assert "artifact_publish_allowed=false" in html
    assert "OUTBOUND_ENABLED=false" in html
    assert "owner_launch_dossier_is_not_go_live=true" in html
    assert "launch dossier review view" in html
    assert "not permission to go live" in html
    assert "There are no apply, execute, lift-halt" in html
    assert 'data-execution-allowed="false"' in html
    assert 'data-go-live-permitted="false"' in html
    assert 'data-deployment-allowed="false"' in html
    assert 'data-build-allowed="false"' in html
    assert 'data-artifact-publish-allowed="false"' in html
    assert 'data-owner-launch-dossier-is-not-go-live="true"' in html
    assert 'data-dossier-is-not-permission-to-go-live="true"' in html
    assert 'data-dossier-is-not-execution="true"' in html
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
    html = render_owner_launch_dossier(
        _empty_dossier(
            blocker_codes=["execution_disabled_in_this_phase", XSS_LABEL],
            gate_codes=["no_execution", XSS_LABEL],
            missing_credential_names=["EXAMPLE_API_KEY", XSS_LABEL],
            closed_provider_flag_names=["EXAMPLE_LIVE_ENABLED", XSS_LABEL],
            sources=(
                _source(key="go-live-readiness-index", label=XSS_LABEL),
                _source(
                    key="settings-execution-preflight",
                    label="Settings execution preflight",
                    command_name="settings-execution-preflight",
                    json_route="/internal/settings-execution-preflight",
                    html_route="/internal/operator-settings-execution-preflight",
                    missing_credential_names=(XSS_LABEL,),
                ),
            ),
            settings_preflight=_preflight(
                blocker_codes=(XSS_LABEL,),
                missing_credential_names=("EXAMPLE_API_KEY",),
            ),
            operator_audit=_audit(available_event_types=(XSS_LABEL,)),
            next_actions=(
                _action(code=XSS_LABEL, label=XSS_LABEL, config_name=XSS_LABEL),
                _action(
                    code=NextActionCode.OWNER_LAUNCH_DOSSIER_IS_NOT_GO_LIVE.value,
                    html_route=OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
                    json_route="/internal/owner-launch-dossier",
                    command_name="owner-launch-dossier",
                ),
            ),
        )
    )
    error = render_owner_launch_dossier_error()

    assert XSS_LABEL not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "EXAMPLE_API_KEY" in html
    assert "EXAMPLE_LIVE_ENABLED" in html
    assert "execution_disabled_in_this_phase" in html
    assert 'id="surface-go-live-readiness-index"' in html
    assert 'id="surface-settings-execution-preflight"' in html
    assert "Owner launch dossier" in html
    assert 'id="operator-owner-launch-dossier-error"' in error
    assert "sk-testsecret" not in error
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()
        assert marker not in error.lower()


def test_renderer_is_deterministic_aside_from_timestamps_and_git_metadata() -> None:
    first = render_owner_launch_dossier(_empty_dossier())
    second = render_owner_launch_dossier(
        _empty_dossier(generated_at=datetime(2026, 9, 1, 8, 30, tzinfo=UTC))
    )
    git_variant = render_owner_launch_dossier(
        _empty_dossier(
            local_git=LocalGitMetadata(
                available=True,
                current_branch="cursor/phase-48-owner-launch-dossier-ui-bcb7",
                current_sha="cccccccccccccccccccccccccccccccccccccccc",
                working_tree_status="not_inspected",
                git_provider_called=False,
                github_actions_called=False,
            )
        )
    )

    assert _strip_volatile(first) == _strip_volatile(second)
    assert "cccccccccccccccccccccccccccccccccccccccc" in git_variant
    assert "cursor/phase-48-owner-launch-dossier-ui-bcb7" in git_variant
    assert TIMESTAMP_RE.search(first)
    assert TIMESTAMP_RE.search(second)


def test_operator_owner_launch_dossier_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_OWNER_LAUNCH_DOSSIER_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    body = response.text
    assert "Owner launch dossier" in body
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for source_id in SOURCE_SECTION_IDS:
        assert f'id="{source_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "OUTBOUND_ENABLED=false" in body
    assert "owner_launch_dossier_is_not_go_live=true" in body
    assert "not permission to go live" in body
    assert "Settings execution preflight summary" in body
    assert "Operator audit summary" in body
    assert "Non-executable owner next-action summary" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in FORM_MARKERS:
        assert marker not in body.lower()


def test_operator_owner_launch_dossier_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_OWNER_LAUNCH_DOSSIER_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_OWNER_LAUNCH_DOSSIER_PATH)
    invalid = api_client.get(
        OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    put = api_client.put(
        OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    delete = api_client.delete(
        OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    patch = api_client.patch(
        OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405
    assert put.status_code == 405
    assert delete.status_code == 405
    assert patch.status_code == 405


def test_operator_owner_launch_dossier_populated_sections_and_no_side_effects(
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
        idempotency_key="ui-owner-launch-dossier-main",
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
        idempotency_key="ui-owner-launch-dossier-pending",
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
        OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    second = api_client.get(
        OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    body = first.text
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for source_id in SOURCE_SECTION_IDS:
        assert f'id="{source_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "OUTBOUND_ENABLED" in body
    assert "execution_disabled_in_this_phase" in body
    assert NextActionCode.OWNER_LAUNCH_DOSSIER_IS_NOT_GO_LIVE.value in body
    assert NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value in body
    assert NextActionCode.LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION.value in body
    assert NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "owner_launch_dossier_is_not_go_live=true" in body
    assert "owner-launch-dossier" in body
    assert "go-live-readiness-index" in body
    assert "launch-blockers-plan" in body
    assert "staged-rollout-plan" in body
    assert "Go-live readiness index" in body
    assert "Launch blockers remediation plan" in body
    assert "Staged go-live rollout plan" in body
    assert "Owner go-live handoff packet" in body
    assert "Compliance evidence binder" in body
    assert "Release-candidate runbook" in body
    assert "Release artifact manifest" in body
    assert "Settings execution preflight" in body
    assert "Operator audit timeline" in body
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


def test_operator_owner_launch_dossier_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(
        "vyro_growth.api.operator_owner_launch_dossier.OwnerLaunchDossierService.build",
        _boom,
    )
    response = api_client.get(OPERATOR_OWNER_LAUNCH_DOSSIER_PATH)

    assert response.status_code == 500
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the owner launch dossier" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()
