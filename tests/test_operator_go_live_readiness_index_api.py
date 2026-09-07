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
from vyro_growth.api.operator_go_live_readiness_index import (
    render_go_live_readiness_index,
    render_go_live_readiness_index_error,
)
from vyro_growth.api.operator_ui import OPERATOR_GO_LIVE_READINESS_INDEX_PATH
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
from vyro_growth.services.go_live_readiness_index import (
    GoLiveReadinessIndex,
    IndexChecklistItem,
    IndexCount,
    ReadinessSurfaceCard,
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
SECTION_IDS = (
    "live-blocking-flags",
    "readiness-surfaces",
    "surface-operator-dashboard",
    "surface-launch-readiness",
    "surface-settings-execution-preflight",
    "surface-owner-handoff-packet",
    "surface-compliance-evidence-binder",
    "surface-release-candidate-runbook",
    "surface-release-artifact-manifest",
    "surface-operator-audit-timeline",
    "remaining-manual-owner-checklist",
)
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
    "/internal/go-live-readiness-index",
    "/internal/operator-launch-blockers-plan",
    "/internal/operator-staged-rollout-plan",
    "/internal/operator-owner-launch-dossier",
    "/internal/operator-provider-setup-checklist",
    "/internal/operator-go-live-rehearsal-checklist",
    "/internal/operator-rehearsal-outcome-report",
    "/internal/operator-supervised-pilot-plan",
    "/internal/operator-supervised-pilot-candidates",
    "/internal/operator-supervised-pilot-go-no-go",
    "/internal/operator-supervised-pilot-first-send-preflight",
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


def _card(**overrides: object) -> ReadinessSurfaceCard:
    payload: dict[str, object] = {
        "key": "launch-readiness",
        "label": "Launch readiness",
        "html_route": "/internal/launch-readiness",
        "json_route": "/internal/launch-readiness",
        "command_name": "launch-readiness",
        "overall_status": "blocked",
        "counts": (IndexCount("Pending packets", "0"),),
        "blocker_codes": ("outbound_disabled",),
        "flag_states": ("go_live_permitted=false",),
    }
    payload.update(overrides)
    return ReadinessSurfaceCard(**payload)  # type: ignore[arg-type]


def _checklist(**overrides: object) -> IndexChecklistItem:
    payload: dict[str, object] = {
        "code": NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value,
        "severity": FindingSeverity.INFO.value,
        "source_section": "go_live_readiness_index",
        "status": "open",
        "html_route": OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
        "json_route": None,
        "command_name": None,
        "label": "Inspect the go-live readiness index",
    }
    payload.update(overrides)
    return IndexChecklistItem(**payload)  # type: ignore[arg-type]


def _empty_index(**overrides: object) -> GoLiveReadinessIndex:
    payload: dict[str, object] = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "packet_kind": "operator_go_live_readiness_index",
        "purpose": "manual_owner_review_index_only",
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
        "manual_review_only": True,
        "index_is_not_permission_to_go_live": True,
        "handoff_is_not_go_live": True,
        "binder_is_not_go_live": True,
        "runbook_is_not_deployment": True,
        "manifest_is_not_a_build_or_deploy": True,
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "outbound_enabled": False,
        "live_providers_enabled": False,
        "closed_provider_flag_names": ("VOICE_LIVE_ENABLED",),
        "missing_credential_names": (),
        "blocker_codes": ("execution_disabled_in_this_phase",),
        "cli_command": "go-live-readiness-index",
        "http_route": "/internal/go-live-readiness-index",
        "related_commands": ("launch-readiness",),
        "related_routes": LINKED_SURFACES,
        "local_git": LocalGitMetadata(
            available=True,
            current_branch="main",
            current_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            working_tree_status="not_inspected",
            git_provider_called=False,
            github_actions_called=False,
        ),
        "surfaces": (
            _card(
                key="operator-dashboard",
                label="Operator dashboard / command center",
                html_route="/internal/operator-dashboard",
                json_route="/internal/operator-command-center",
                command_name="operator-command-center",
            ),
            _card(),
            _card(
                key="settings-execution-preflight",
                label="Settings execution preflight",
                html_route="/internal/operator-settings-execution-preflight",
                json_route="/internal/settings-execution-preflight",
                command_name="settings-execution-preflight",
            ),
            _card(
                key="owner-handoff-packet",
                label="Owner handoff packet",
                html_route="/internal/operator-owner-handoff-packet",
                json_route="/internal/owner-handoff-packet",
                command_name="owner-handoff-packet",
            ),
            _card(
                key="compliance-evidence-binder",
                label="Compliance evidence binder",
                html_route="/internal/operator-compliance-evidence-binder",
                json_route="/internal/compliance-evidence-binder",
                command_name="compliance-evidence-binder",
            ),
            _card(
                key="release-candidate-runbook",
                label="Release-candidate runbook",
                html_route="/internal/operator-release-candidate-runbook",
                json_route="/internal/release-candidate-runbook",
                command_name="release-candidate-runbook",
            ),
            _card(
                key="release-artifact-manifest",
                label="Release artifact manifest",
                html_route="/internal/operator-release-artifact-manifest",
                json_route="/internal/release-artifact-manifest",
                command_name="release-artifact-manifest",
            ),
            _card(
                key="operator-audit-timeline",
                label="Operator audit timeline",
                html_route="/internal/operator-audit-timeline",
                json_route=None,
                command_name=None,
            ),
        ),
        "remaining_manual_owner_checklist": (),
    }
    payload.update(overrides)
    return GoLiveReadinessIndex(**payload)  # type: ignore[arg-type]


def _strip_volatile(html: str) -> str:
    stripped = TIMESTAMP_RE.sub("<timestamp>", html)
    stripped = GIT_SHA_RE.sub("<git-sha>", stripped)
    return GIT_BRANCH_RE.sub("<git-branch>", stripped)


def test_renderer_empty_state_is_read_only_and_has_no_execute_controls() -> None:
    html = render_go_live_readiness_index(_empty_index())

    assert 'id="operator-go-live-readiness-index"' in html
    assert OPERATOR_GO_LIVE_READINESS_INDEX_PATH == "/internal/operator-go-live-readiness-index"
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in html
    assert "No remaining checklist items" in html
    assert "go_live_permitted=false" in html
    assert "execution_allowed=false" in html
    assert "deployment_allowed=false" in html
    assert "build_allowed=false" in html
    assert "artifact_publish_allowed=false" in html
    assert "OUTBOUND_ENABLED=false" in html
    assert "index/review view" in html
    assert "not permission to go live" in html
    assert "There are no apply, execute, lift-halt" in html
    assert 'data-execution-allowed="false"' in html
    assert 'data-go-live-permitted="false"' in html
    assert 'data-deployment-allowed="false"' in html
    assert 'data-build-allowed="false"' in html
    assert 'data-artifact-publish-allowed="false"' in html
    assert 'data-index-is-not-permission-to-go-live="true"' in html
    for href in LINKED_SURFACES:
        assert href in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_renderer_populated_sections_and_xss_escape() -> None:
    html = render_go_live_readiness_index(
        _empty_index(
            blocker_codes=["execution_disabled_in_this_phase", XSS_LABEL],
            missing_credential_names=["EXAMPLE_API_KEY", XSS_LABEL],
            closed_provider_flag_names=["EXAMPLE_LIVE_ENABLED", XSS_LABEL],
            surfaces=(
                _card(label=XSS_LABEL, blocker_codes=(XSS_LABEL,), flag_states=(XSS_LABEL,)),
                _card(key="operator-dashboard", label="Operator dashboard / command center"),
                _card(
                    key="settings-execution-preflight",
                    label="Settings execution preflight",
                    html_route="/internal/operator-settings-execution-preflight",
                ),
                _card(
                    key="owner-handoff-packet",
                    label="Owner handoff packet",
                    html_route="/internal/operator-owner-handoff-packet",
                ),
                _card(
                    key="compliance-evidence-binder",
                    label="Compliance evidence binder",
                    html_route="/internal/operator-compliance-evidence-binder",
                ),
                _card(
                    key="release-candidate-runbook",
                    label="Release-candidate runbook",
                    html_route="/internal/operator-release-candidate-runbook",
                ),
                _card(
                    key="release-artifact-manifest",
                    label="Release artifact manifest",
                    html_route="/internal/operator-release-artifact-manifest",
                ),
                _card(
                    key="operator-audit-timeline",
                    label="Operator audit timeline",
                    html_route="/internal/operator-audit-timeline",
                    json_route=None,
                    command_name=None,
                ),
            ),
            remaining_manual_owner_checklist=(
                _checklist(code=XSS_LABEL, label=XSS_LABEL),
                _checklist(code="execution_disabled_in_this_phase"),
            ),
        )
    )
    error = render_go_live_readiness_index_error()

    assert XSS_LABEL not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "EXAMPLE_API_KEY" in html
    assert "EXAMPLE_LIVE_ENABLED" in html
    assert "execution_disabled_in_this_phase" in html
    assert "Go-live index" in html
    assert 'id="operator-go-live-readiness-index-error"' in error
    assert "sk-testsecret" not in error
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()
        assert marker not in error.lower()


def test_renderer_is_deterministic_aside_from_timestamps_and_git_metadata() -> None:
    first = render_go_live_readiness_index(_empty_index())
    second = render_go_live_readiness_index(
        _empty_index(generated_at=datetime(2026, 9, 1, 8, 30, tzinfo=UTC))
    )
    git_variant = render_go_live_readiness_index(
        _empty_index(
            local_git=LocalGitMetadata(
                available=True,
                current_branch="cursor/phase-41-go-live-readiness-index-7a60",
                current_sha="cccccccccccccccccccccccccccccccccccccccc",
                working_tree_status="not_inspected",
                git_provider_called=False,
                github_actions_called=False,
            )
        )
    )

    assert _strip_volatile(first) == _strip_volatile(second)
    assert "cccccccccccccccccccccccccccccccccccccccc" in git_variant
    assert "cursor/phase-41-go-live-readiness-index-7a60" in git_variant
    assert TIMESTAMP_RE.search(first)
    assert TIMESTAMP_RE.search(second)


def test_operator_go_live_readiness_index_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_GO_LIVE_READINESS_INDEX_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Go-live readiness index" in body
    assert "Go-live index" in body
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "OUTBOUND_ENABLED=false" in body
    assert "not permission to go live" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in FORM_MARKERS:
        assert marker not in body.lower()


def test_operator_go_live_readiness_index_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_GO_LIVE_READINESS_INDEX_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_GO_LIVE_READINESS_INDEX_PATH)
    invalid = api_client.get(
        OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    put = api_client.put(
        OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    delete = api_client.delete(
        OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    patch = api_client.patch(
        OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405
    assert put.status_code == 405
    assert delete.status_code == 405
    assert patch.status_code == 405


def test_operator_go_live_readiness_index_populated_sections_and_no_side_effects(
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
        idempotency_key="ui-index",
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
        idempotency_key="ui-index-pending",
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
        OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    second = api_client.get(
        OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    body = first.text
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "OUTBOUND_ENABLED" in body
    assert "execution_disabled_in_this_phase" in body
    assert NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value in body
    assert NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "launch-readiness" in body
    assert "operator-command-center" in body
    assert "release-artifact-manifest" in body
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


def test_operator_go_live_readiness_index_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(
        "vyro_growth.api.operator_go_live_readiness_index.GoLiveReadinessIndexService.build",
        _boom,
    )
    response = api_client.get(OPERATOR_GO_LIVE_READINESS_INDEX_PATH)

    assert response.status_code == 500
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the go-live readiness index" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()
