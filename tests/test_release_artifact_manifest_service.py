from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_action_readiness_service import _seed_plans_and_packets
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from tests.test_monitoring_service import UNSAFE_ERROR
from vyro_growth.cli import main
from vyro_growth.config import Settings
from vyro_growth.domain import NextActionCode, SecretName, SettingsChangeRequestType
from vyro_growth.models import (
    Activity,
    Campaign,
    CampaignEnrollment,
    LiveSettingsChangeRequest,
    LiveSettingsChangeRequestDecision,
    Meeting,
    OutreachMessage,
    OwnerApprovalPacket,
    OwnerApprovalPacketDecision,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.release_artifact_manifest import (
    ReleaseArtifactManifestService,
    format_release_artifact_manifest,
    inspect_local_git,
    manifest_payload,
)
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

DB_SECRET_URL = "postgresql+psycopg://vyro:super-db-password@localhost:5432/vyro_growth"
GIT_VOLATILE_KEYS = {
    "generated_at",
    "occurred_at",
    "requested_at",
    "simulated_at",
    "current_sha",
    "current_branch",
    "working_tree_status",
    "available",
}


def _json_from_cli(output: str) -> dict[str, object]:
    start = output.find("{")
    assert start != -1
    payload = json.loads(output[start:])
    assert isinstance(payload, dict)
    return payload


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _counts(db: Session) -> dict[str, int]:
    return {
        "activities": int(db.scalar(select(func.count()).select_from(Activity)) or 0),
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
        "packets": int(db.scalar(select(func.count()).select_from(OwnerApprovalPacket)) or 0),
        "packet_decisions": int(
            db.scalar(select(func.count()).select_from(OwnerApprovalPacketDecision)) or 0
        ),
        "campaigns": int(db.scalar(select(func.count()).select_from(Campaign)) or 0),
        "requests": int(
            db.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) or 0
        ),
        "decisions": int(
            db.scalar(select(func.count()).select_from(LiveSettingsChangeRequestDecision)) or 0
        ),
    }


def _flags(settings: Settings) -> dict[str, bool]:
    return {
        "outbound_enabled": settings.outbound_enabled,
        "openai_personalization_enabled": settings.openai_personalization_enabled,
        "smartlead_live_enabled": settings.smartlead_live_enabled,
        "openai_reply_classification_enabled": settings.openai_reply_classification_enabled,
        "google_calendar_live_enabled": settings.google_calendar_live_enabled,
        "voice_live_enabled": settings.voice_live_enabled,
        "outbound_halted": settings.outbound_halted,
    }


def _without_volatile(payload: dict[str, object]) -> dict[str, object]:
    cloned = deepcopy(payload)

    def _strip(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: _strip(item)
                for key, item in value.items()
                if key not in GIT_VOLATILE_KEYS
            }
        if isinstance(value, list):
            return [_strip(item) for item in value]
        return value

    return _strip(cloned)  # type: ignore[return-value]


def _assert_no_execution(payload: dict[str, object]) -> None:
    assert payload["read_only"] is True
    assert payload["no_execution"] is True
    assert payload["dry_run_only"] is True
    assert payload["executed"] == 0
    assert payload["execution_attempted"] is False
    assert payload["outbound_attempted"] is False
    assert payload["live_action"] is False
    assert payload["owner_approved"] is False
    assert payload["settings_applied"] is False
    assert payload["halt_changed"] is False
    assert payload["execution_allowed"] is False
    assert payload["future_execution_phase_exists"] is False
    assert payload["future_deployment_phase_exists"] is False
    assert payload["go_live_permitted"] is False
    assert payload["deployment_allowed"] is False
    assert payload["deployment_attempted"] is False
    assert payload["deployed"] is False
    assert payload["build_allowed"] is False
    assert payload["artifact_publish_allowed"] is False
    assert payload["container_build_attempted"] is False
    assert payload["artifact_publish_attempted"] is False
    assert payload["manual_review_only"] is True
    assert payload["runbook_is_not_deployment"] is True
    assert payload["manifest_is_not_a_build_or_deploy"] is True
    assert payload["packet_kind"] == "release_artifact_manifest"
    assert payload["purpose"] == "future_manual_owner_review_only"
    assert payload["cli_command"] == "release-artifact-manifest"
    assert payload["http_route"] == "/internal/release-artifact-manifest"
    no_build = payload["no_build_no_deploy"]
    assert isinstance(no_build, dict)
    assert no_build["build_allowed"] is False
    assert no_build["artifact_publish_allowed"] is False
    assert no_build["github_actions_called"] is False
    assert no_build["git_provider_called"] is False


def test_empty_manifest_is_read_only_without_side_effects(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    before_flags = _flags(settings)
    before = _counts(db_session)

    manifest = ReleaseArtifactManifestService().build(db_session, settings)
    text = format_release_artifact_manifest(manifest, as_json=True)
    markdown = format_release_artifact_manifest(manifest, as_json=False)
    payload = json.loads(text)

    assert manifest.overall_status in {"blocked", "warning", "ready_for_owner_review"}
    assert manifest.go_live_permitted is False
    assert manifest.execution_allowed is False
    assert manifest.deployment_allowed is False
    assert manifest.build_allowed is False
    assert manifest.artifact_publish_allowed is False
    assert manifest.manifest_is_not_a_build_or_deploy is True
    assert manifest.runbook_is_not_deployment is True
    assert manifest.source_provenance.expected_repo_name == "vyro-growth-engine"
    assert manifest.source_provenance.expected_base_branch == "main"
    assert manifest.source_provenance.expected_workflow_path == ".github/workflows/ci.yml"
    assert manifest.source_provenance.git_provider_called is False
    assert manifest.source_provenance.github_actions_called is False
    assert manifest.source_provenance.local_git.git_provider_called is False
    assert "/internal/operator-release-artifact-manifest" in manifest.related_routes
    assert "/internal/operator-go-live-readiness-index" in manifest.related_routes
    present = {item.kind: item.present for item in manifest.artifact_inventory}
    assert present["package_directory"] is True
    assert present["dockerfile"] is True
    assert present["docker_compose"] is True
    assert present["migrations_directory"] is True
    assert present["docs_directory"] is True
    assert present["tests_directory"] is True
    assert present["ci_workflow"] is True
    filenames = {item.filename for item in manifest.migration_inventory}
    assert "001_initial_schema.py" in filenames
    assert "018_live_settings_change_requests.py" in filenames
    assert "019_email_verification.py" in filenames
    assert "020_contact_discovery_calls.py" in filenames
    assert all("@" not in item.revision_id for item in manifest.migration_inventory)
    command_kinds = {item.kind for item in manifest.runtime_command_inventory}
    assert {"api", "worker_check", "smoke_dry_run", "check_config"} <= command_kinds
    assert "smoke-dry-run" in manifest.safety_gate_inventory.required_ci_job_names
    assert "deploy-config" in manifest.safety_gate_inventory.required_ci_job_names
    assert manifest.safety_gate_inventory.smoke_gate.documented is True
    assert manifest.safety_gate_inventory.deploy_config_gate.documented is True
    assert manifest.safety_gate_inventory.outbound_enabled_required is False
    assert manifest.safety_gate_inventory.github_actions_called is False
    assert manifest.no_build_no_deploy.container_build_attempted is False
    codes = {item.code for item in manifest.remaining_manual_owner_checklist}
    assert NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value in codes
    assert "execution_disabled_in_this_phase" in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    assert "## Source and provenance expectations" in markdown
    assert "## Artifact inventory" in markdown
    assert "## Migration inventory" in markdown
    assert "## Runtime command inventory" in markdown
    assert "## Safety gate inventory" in markdown
    assert "## No-build and no-deploy evidence" in markdown
    assert "## Remaining unresolved blockers and manual owner checklist" in markdown
    assert "not a build, artifact publishing, deployment mechanism" in markdown
    _assert_no_execution(payload)
    assert _counts(db_session) == before
    assert _flags(settings) == before_flags
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    _assert_no_leakage(text)
    _assert_no_leakage(markdown)


def test_populated_manifest_consolidates_safe_evidence(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(voice_api_key=SECRET_VALUE)
    _seed_plans_and_packets(db_session)
    activity = Activity(
        lead_id=None,
        actor="cli",
        action="nppes_discovery_completed",
        details={
            "body": PHI_SNIPPET,
            "email": PROSPECT_EMAIL,
            "status": "completed",
            "source": "cli",
        },
    )
    db_session.add(activity)
    db_session.flush()
    service = SettingsChangeRequestService()
    service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="manifest-pending",
        reviewer_notes=f"record only {PHI_SNIPPET}",
    )
    approved = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        desired_boolean=True,
        idempotency_key="manifest-approved",
    )
    service.record_decision(
        db_session,
        settings,
        request_id=approved.request_id,
        decision="approved",
        reviewer="owner",
        reviewer_notes=PHI_SNIPPET,
    )
    before = _counts(db_session)
    before_flags = _flags(settings)

    manifest = ReleaseArtifactManifestService().build(db_session, settings)
    text = format_release_artifact_manifest(manifest, as_json=True)
    markdown = format_release_artifact_manifest(manifest, as_json=False)

    assert manifest.reused_summaries.settings_preflight_blocked_count >= 1
    assert manifest.reused_summaries.settings_preflight_execution_allowed is False
    assert manifest.reused_summaries.owner_handoff_go_live_permitted is False
    assert manifest.reused_summaries.binder_is_not_go_live is True
    assert manifest.reused_summaries.runbook_is_not_deployment is True
    assert manifest.reused_summaries.audit_timeline_matching_count >= 1
    assert SecretName.SMARTLEAD_API_KEY.value in manifest.missing_credential_names
    assert "reviewer_notes" not in text
    _assert_no_leakage(text, SECRET_VALUE, DB_SECRET_URL)
    _assert_no_leakage(markdown, SECRET_VALUE)
    assert PROSPECT_EMAIL not in text
    assert PHI_SNIPPET not in text
    assert UNSAFE_ERROR not in text
    assert _counts(db_session) == before
    assert _flags(settings) == before_flags
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False


def test_manifest_is_deterministic_and_idempotent(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="manifest-idempotent",
    )
    builder = ReleaseArtifactManifestService()
    before = _counts(db_session)

    one = builder.build(db_session, settings)
    two = builder.build(db_session, settings)
    payload_one = _without_volatile(manifest_payload(one))
    payload_two = _without_volatile(manifest_payload(two))

    assert payload_one == payload_two
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False
    assert one.go_live_permitted is False
    assert two.deployment_allowed is False
    assert one.build_allowed is False
    assert two.manifest_is_not_a_build_or_deploy is True


def test_missing_files_are_reported_without_side_effects(
    db_session: Session,
    tmp_path: Path,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    before = _counts(db_session)

    manifest = ReleaseArtifactManifestService().build(db_session, settings, repo_root=tmp_path)
    text = format_release_artifact_manifest(manifest, as_json=True)
    markdown = format_release_artifact_manifest(manifest, as_json=False)

    assert all(item.present is False for item in manifest.artifact_inventory)
    assert manifest.migration_inventory == ()
    assert manifest.source_provenance.local_git.available is False
    assert manifest.source_provenance.local_git.current_sha == "unavailable"
    assert manifest.source_provenance.git_provider_called is False
    assert manifest.safety_gate_inventory.smoke_gate.present is False
    assert manifest.safety_gate_inventory.deploy_config_gate.present is False
    codes = {item.code for item in manifest.remaining_manual_owner_checklist}
    assert "restore_expected_release_artifacts" in codes
    assert NextActionCode.RESTORE_CI_SMOKE_GATE.value in codes
    assert "migration: none" in markdown
    _assert_no_leakage(text)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert manifest.build_allowed is False
    assert manifest.deployment_allowed is False


def test_inspect_local_git_reads_safe_metadata_only(tmp_path: Path) -> None:
    missing = inspect_local_git(tmp_path)
    assert missing.available is False
    assert missing.git_provider_called is False
    assert missing.github_actions_called is False

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    refs = git_dir / "refs" / "heads"
    refs.mkdir(parents=True)
    (refs / "main").write_text("abc123def4567890abc123def4567890abc123de\n", encoding="utf-8")

    metadata = inspect_local_git(tmp_path)
    assert metadata.available is True
    assert metadata.current_branch == "main"
    assert metadata.current_sha == "abc123def4567890abc123def4567890abc123de"
    assert metadata.working_tree_status == "not_inspected"
    assert metadata.git_provider_called is False

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    (unsafe / ".git").mkdir()
    (unsafe / ".git" / "HEAD").write_text(
        "ref: refs/heads/owner@example.com\n",
        encoding="utf-8",
    )
    redacted = inspect_local_git(unsafe)
    assert redacted.available is False
    assert redacted.current_branch == "unavailable"
    assert "@" not in redacted.current_branch
    assert "example.com" not in redacted.current_branch


def test_unreadable_migration_file_does_not_leak_contents(
    db_session: Session,
    tmp_path: Path,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "019_secret.py").write_text(
        'revision: str = "019_secret"\nSECRET = "sk-test-secret-value-12345"\n'
        f'email = "{PROSPECT_EMAIL}"\n',
        encoding="utf-8",
    )
    settings = _settings()

    manifest = ReleaseArtifactManifestService().build(db_session, settings, repo_root=tmp_path)
    text = format_release_artifact_manifest(manifest, as_json=True)
    markdown = format_release_artifact_manifest(manifest, as_json=False)

    assert any(item.filename == "019_secret.py" for item in manifest.migration_inventory)
    assert all(item.revision_id == "019_secret" for item in manifest.migration_inventory)
    assert SECRET_VALUE not in text
    assert SECRET_VALUE not in markdown
    assert PROSPECT_EMAIL not in text
    assert "sk-test" not in text


def test_cli_release_artifact_manifest_json_is_sanitized(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(voice_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)

    code = main(["release-artifact-manifest", "--json"])
    output = capsys.readouterr().out
    payload = _json_from_cli(output)

    assert code == 0
    _assert_no_execution(payload)
    assert payload["outbound_enabled"] is False
    assert payload["cli_command"] == "release-artifact-manifest"
    assert "source_provenance" in payload
    assert "artifact_inventory" in payload
    assert "migration_inventory" in payload
    assert "runtime_command_inventory" in payload
    assert "safety_gate_inventory" in payload
    assert "no_build_no_deploy" in payload
    assert "remaining_manual_owner_checklist" in payload
    _assert_no_leakage(output, SECRET_VALUE, DB_SECRET_URL)
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_cli_release_artifact_manifest_markdown_is_sanitized(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(voice_api_key=SECRET_VALUE)

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)

    code = main(["release-artifact-manifest"])
    output = capsys.readouterr().out

    assert code == 0
    assert "# Release artifact manifest" in output
    assert "go_live_permitted: false" in output
    assert "execution_allowed: false" in output
    assert "deployment_allowed: false" in output
    assert "build_allowed: false" in output
    assert "artifact_publish_allowed: false" in output
    assert "manifest_is_not_a_build_or_deploy: true" in output
    assert "## Remaining unresolved blockers and manual owner checklist" in output
    _assert_no_leakage(output, SECRET_VALUE)
    assert read_operator_halt(db_session) is HaltStatus.HALTED
