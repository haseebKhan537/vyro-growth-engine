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
from vyro_growth.api.operator_release_artifact_manifest import (
    render_release_artifact_manifest,
    render_release_artifact_manifest_error,
)
from vyro_growth.api.operator_ui import OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH
from vyro_growth.api.release_artifact_manifest import (
    ArtifactInventoryItemResponse,
    ManifestChecklistItemResponse,
    MigrationInventoryItemResponse,
    ReleaseArtifactManifestResponse,
    RuntimeCommandItemResponse,
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
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

XSS_LABEL = "<script>alert(1)</script>"
ACTION_MARKERS = ("javascript:", "onclick=", "onerror=")
FORM_MARKERS = ("<form", "<button", "<input", "<select", "<textarea")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
GIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
GIT_BRANCH_RE = re.compile(r"cursor/[A-Za-z0-9._/\-]+")
SECTION_IDS = (
    "source-and-provenance-expectations",
    "artifact-inventory",
    "migration-inventory",
    "runtime-command-inventory",
    "safety-gate-inventory",
    "no-build-no-deploy-evidence",
    "reused-summaries",
    "remaining-manual-owner-checklist",
)
SECTION_HEADINGS = (
    "Source and provenance expectations",
    "Artifact inventory",
    "Migration inventory",
    "Runtime command inventory",
    "Safety gate inventory",
    "No-build and no-deploy evidence",
    "Reused read-only summaries",
    "Remaining unresolved blockers and manual owner checklist",
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


def _empty_manifest(**overrides: object) -> ReleaseArtifactManifestResponse:
    payload: dict[str, object] = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "overall_status": "blocked",
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "source_provenance": {
            "expected_repo_name": "vyro-growth-engine",
            "expected_base_branch": "main",
            "expected_workflow_path": ".github/workflows/ci.yml",
            "expected_release_channel": "owner_reviewed_manual_deploy",
            "sha_source": "local_git_head",
            "local_git": {
                "current_branch": "main",
                "current_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "working_tree_status": "not_inspected",
            },
        },
        "safety_gate_inventory": {
            "smoke_gate": {
                "job_name": "smoke-dry-run",
                "command_name": "vyro-growth smoke-dry-run --local-only --json",
            },
            "deploy_config_gate": {
                "job_name": "deploy-config",
                "command_name": "docker compose config --quiet",
            },
        },
        "no_build_no_deploy": {},
        "reused_summaries": {
            "launch_readiness_overall_status": "blocked",
            "settings_preflight_overall_status": "blocked",
            "binder_command": "compliance-evidence-binder",
            "binder_route": "/internal/compliance-evidence-binder",
            "runbook_command": "release-candidate-runbook",
            "runbook_route": "/internal/release-candidate-runbook",
            "audit_timeline_route": "/internal/operator-audit-timeline",
        },
    }
    payload.update(overrides)
    return ReleaseArtifactManifestResponse.model_validate(payload)


def _artifact(**overrides: object) -> ArtifactInventoryItemResponse:
    payload: dict[str, object] = {
        "kind": "dockerfile",
        "path": "Dockerfile",
        "present": True,
        "is_directory": False,
    }
    payload.update(overrides)
    return ArtifactInventoryItemResponse.model_validate(payload)


def _migration(**overrides: object) -> MigrationInventoryItemResponse:
    payload: dict[str, object] = {
        "filename": "001_initial_schema.py",
        "revision_id": "001",
    }
    payload.update(overrides)
    return MigrationInventoryItemResponse.model_validate(payload)


def _command(**overrides: object) -> RuntimeCommandItemResponse:
    payload: dict[str, object] = {
        "kind": "check_config",
        "command_name": "vyro-growth check-config",
    }
    payload.update(overrides)
    return RuntimeCommandItemResponse.model_validate(payload)


def _checklist(**overrides: object) -> ManifestChecklistItemResponse:
    payload: dict[str, object] = {
        "code": NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value,
        "severity": FindingSeverity.INFO.value,
        "source_section": "release_artifact_manifest",
        "status": "open",
    }
    payload.update(overrides)
    return ManifestChecklistItemResponse.model_validate(payload)


def _strip_volatile(html: str) -> str:
    stripped = TIMESTAMP_RE.sub("<timestamp>", html)
    stripped = GIT_SHA_RE.sub("<git-sha>", stripped)
    return GIT_BRANCH_RE.sub("<git-branch>", stripped)


def test_renderer_empty_state_is_read_only_and_has_no_execute_controls() -> None:
    html = render_release_artifact_manifest(_empty_manifest())

    assert 'id="operator-release-artifact-manifest"' in html
    assert (
        OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH
        == "/internal/operator-release-artifact-manifest"
    )
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in html
    for heading in SECTION_HEADINGS:
        assert heading in html
    assert "No remaining checklist items" in html
    assert "No expected artifacts were inspected" in html
    assert "No migration revision files were inspected" in html
    assert "No runtime commands were listed" in html
    assert "go_live_permitted=false" in html
    assert "execution_allowed=false" in html
    assert "deployment_allowed=false" in html
    assert "build_allowed=false" in html
    assert "artifact_publish_allowed=false" in html
    assert "runbook_is_not_deployment=true" in html
    assert "manifest_is_not_a_build_or_deploy=true" in html
    assert "not a build, artifact publishing, deployment mechanism" in html
    assert "There are no apply, execute, lift-halt" in html
    assert 'data-execution-allowed="false"' in html
    assert 'data-go-live-permitted="false"' in html
    assert 'data-deployment-allowed="false"' in html
    assert 'data-build-allowed="false"' in html
    assert 'data-artifact-publish-allowed="false"' in html
    assert 'data-manual-review-only="true"' in html
    assert 'data-no-execution="true"' in html
    assert 'data-runbook-is-not-deployment="true"' in html
    assert 'data-manifest-is-not-a-build-or-deploy="true"' in html
    assert "/internal/operator-owner-handoff-packet" in html
    assert "/internal/operator-audit-timeline" in html
    assert "/internal/operator-compliance-evidence-binder" in html
    assert "/internal/operator-release-artifact-manifest" in html
    assert "/internal/operator-go-live-readiness-index" in html
    assert "/internal/release-artifact-manifest" in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_renderer_populated_sections_and_xss_escape() -> None:
    html = render_release_artifact_manifest(
        _empty_manifest(
            blocker_codes=["execution_disabled_in_this_phase", XSS_LABEL],
            missing_credential_names=["EXAMPLE_API_KEY", XSS_LABEL],
            closed_provider_flag_names=["EXAMPLE_LIVE_ENABLED"],
            related_commands=["release-artifact-manifest"],
            related_routes=[OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH],
            source_provenance={
                "expected_repo_name": XSS_LABEL,
                "expected_base_branch": XSS_LABEL,
                "expected_workflow_path": ".github/workflows/ci.yml",
                "expected_release_channel": "owner_reviewed_manual_deploy",
                "sha_source": "local_git_head",
                "local_git": {
                    "available": True,
                    "current_branch": XSS_LABEL,
                    "current_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "working_tree_status": "not_inspected",
                },
            },
            artifact_inventory=[
                _artifact(kind=XSS_LABEL, path=XSS_LABEL),
                _artifact(),
            ],
            migration_inventory=[
                _migration(filename=XSS_LABEL, revision_id=XSS_LABEL),
                _migration(),
            ],
            runtime_command_inventory=[
                _command(kind=XSS_LABEL, command_name=XSS_LABEL),
                _command(),
            ],
            safety_gate_inventory={
                "required_ci_job_names": ["smoke-dry-run", "deploy-config", XSS_LABEL],
                "smoke_gate": {
                    "present": True,
                    "documented": True,
                    "job_name": "smoke-dry-run",
                    "command_name": "vyro-growth smoke-dry-run --local-only --json",
                },
                "deploy_config_gate": {
                    "present": True,
                    "documented": True,
                    "job_name": "deploy-config",
                    "command_name": "docker compose config --quiet",
                },
                "required_flag_names": ["OUTBOUND_ENABLED", XSS_LABEL],
                "closed_provider_flag_names": ["VOICE_LIVE_ENABLED"],
                "missing_credential_names": ["EXAMPLE_API_KEY"],
                "env_example_defaults_present": True,
            },
            reused_summaries={
                "launch_readiness_overall_status": "blocked",
                "launch_readiness_blocker_codes": [XSS_LABEL, "outbound_disabled"],
                "settings_preflight_overall_status": "blocked",
                "binder_command": "compliance-evidence-binder",
                "binder_route": "/internal/compliance-evidence-binder",
                "runbook_command": "release-candidate-runbook",
                "runbook_route": "/internal/release-candidate-runbook",
                "audit_timeline_route": "/internal/operator-audit-timeline",
            },
            remaining_manual_owner_checklist=[
                _checklist(code=XSS_LABEL, severity=FindingSeverity.WARNING.value),
                _checklist(code="execution_disabled_in_this_phase"),
            ],
        )
    )
    error = render_release_artifact_manifest_error()

    assert XSS_LABEL not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    for heading in SECTION_HEADINGS:
        assert heading in html
    assert "EXAMPLE_API_KEY" in html
    assert "EXAMPLE_LIVE_ENABLED" in html
    assert "execution_disabled_in_this_phase" in html
    assert "smoke-dry-run" in html
    assert "deploy-config" in html
    assert ".github/workflows/ci.yml" in html
    assert "Dockerfile" in html
    assert "001_initial_schema.py" in html
    assert "vyro-growth check-config" in html
    assert "go live permitted" in html.lower()
    assert "execution allowed" in html.lower()
    assert "deployment allowed" in html.lower()
    assert "build allowed" in html.lower()
    assert 'id="operator-release-artifact-manifest-error"' in error
    assert "sk-testsecret" not in error
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()
        assert marker not in error.lower()


def test_renderer_is_deterministic_aside_from_timestamps_and_git_metadata() -> None:
    first = render_release_artifact_manifest(_empty_manifest())
    second = render_release_artifact_manifest(
        _empty_manifest(generated_at=datetime(2026, 9, 1, 8, 30, tzinfo=UTC))
    )
    git_variant = render_release_artifact_manifest(
        _empty_manifest(
            source_provenance={
                "expected_repo_name": "vyro-growth-engine",
                "expected_base_branch": "main",
                "expected_workflow_path": ".github/workflows/ci.yml",
                "expected_release_channel": "owner_reviewed_manual_deploy",
                "sha_source": "local_git_head",
                "local_git": {
                    "available": True,
                    "current_branch": "cursor/phase-40-release-artifact-manifest-ui-3272",
                    "current_sha": "cccccccccccccccccccccccccccccccccccccccc",
                    "working_tree_status": "not_inspected",
                },
            },
        )
    )

    assert _strip_volatile(first) == _strip_volatile(second)
    assert "cccccccccccccccccccccccccccccccccccccccc" in git_variant
    assert "cursor/phase-40-release-artifact-manifest-ui-3272" in git_variant
    assert TIMESTAMP_RE.search(first)
    assert TIMESTAMP_RE.search(second)


def test_operator_release_artifact_manifest_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Release artifact manifest" in body
    assert "Release manifest" in body
    for heading in SECTION_HEADINGS:
        assert heading in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "runbook_is_not_deployment=true" in body
    assert "manifest_is_not_a_build_or_deploy=true" in body
    assert "not a build, artifact publishing, deployment mechanism" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in FORM_MARKERS:
        assert marker not in body.lower()


def test_operator_release_artifact_manifest_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH)
    invalid = api_client.get(
        OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    put = api_client.put(
        OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    delete = api_client.delete(
        OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    patch = api_client.patch(
        OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405
    assert put.status_code == 405
    assert delete.status_code == 405
    assert patch.status_code == 405


def test_operator_release_artifact_manifest_populated_sections_and_no_side_effects(
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
        idempotency_key="ui-manifest",
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
        idempotency_key="ui-manifest-pending",
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
        OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    second = api_client.get(
        OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    body = first.text
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for heading in SECTION_HEADINGS:
        assert heading in body
    assert "OUTBOUND_ENABLED" in body
    assert "execution_disabled_in_this_phase" in body
    assert NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "deployment_allowed=false" in body
    assert "build_allowed=false" in body
    assert "artifact_publish_allowed=false" in body
    assert "runbook_is_not_deployment=true" in body
    assert "manifest_is_not_a_build_or_deploy=true" in body
    assert "not a build, artifact publishing, deployment mechanism" in body
    assert "smoke-dry-run" in body
    assert "deploy-config" in body
    assert "Dockerfile" in body
    assert "001_initial_schema.py" in body
    assert "vyro-growth check-config" in body
    assert "/health" in body
    assert "/ready" in body
    assert OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH in body
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


def test_operator_release_artifact_manifest_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(
        "vyro_growth.api.operator_release_artifact_manifest.build_release_artifact_manifest_response",
        _boom,
    )
    response = api_client.get(OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH)

    assert response.status_code == 500
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the release artifact manifest" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()
