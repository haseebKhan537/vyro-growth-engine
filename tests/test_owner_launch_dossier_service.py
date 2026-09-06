from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_action_readiness_service import _seed_plans_and_packets
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from vyro_growth.cli import main
from vyro_growth.config import Settings
from vyro_growth.domain import NextActionCode, SettingsChangeRequestType
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    LiveSettingsChangeRequest,
    Meeting,
    OutreachMessage,
)
from vyro_growth.services.compliance_evidence_binder import (
    CLI_COMMAND as BINDER_CLI_COMMAND,
)
from vyro_growth.services.compliance_evidence_binder import (
    HTTP_ROUTE as BINDER_HTTP_ROUTE,
)
from vyro_growth.services.go_live_readiness_index import (
    CLI_COMMAND as INDEX_CLI_COMMAND,
)
from vyro_growth.services.go_live_readiness_index import (
    HTTP_ROUTE as INDEX_HTTP_ROUTE,
)
from vyro_growth.services.launch_blockers_plan import (
    CLI_COMMAND as BLOCKERS_CLI_COMMAND,
)
from vyro_growth.services.launch_blockers_plan import (
    HTTP_ROUTE as BLOCKERS_HTTP_ROUTE,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.owner_handoff import OwnerHandoffPacketService
from vyro_growth.services.owner_launch_dossier import (
    CLI_COMMAND,
    HTML_ROUTE,
    HTTP_ROUTE,
    SOURCE_KEYS,
    OwnerLaunchDossierService,
    dossier_payload,
    format_owner_launch_dossier,
)
from vyro_growth.services.release_artifact_manifest import (
    CLI_COMMAND as MANIFEST_CLI_COMMAND,
)
from vyro_growth.services.release_artifact_manifest import (
    HTTP_ROUTE as MANIFEST_HTTP_ROUTE,
)
from vyro_growth.services.release_candidate_runbook import (
    CLI_COMMAND as RUNBOOK_CLI_COMMAND,
)
from vyro_growth.services.release_candidate_runbook import (
    HTTP_ROUTE as RUNBOOK_HTTP_ROUTE,
)
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService
from vyro_growth.services.staged_rollout_plan import (
    CLI_COMMAND as STAGED_CLI_COMMAND,
)
from vyro_growth.services.staged_rollout_plan import (
    HTTP_ROUTE as STAGED_HTTP_ROUTE,
)
from vyro_growth.services.staged_rollout_plan import StagedRolloutPlanService

DB_SECRET_URL = "postgresql+psycopg://vyro:super-db-password@localhost:5432/vyro_growth"
VOLATILE_KEYS = {
    "generated_at",
    "current_sha",
    "current_branch",
    "working_tree_status",
    "available",
}
UNSAFE_ERROR = "Traceback (most recent call last): secret=sk-live-error-token"


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _counts(db: Session) -> dict[str, int]:
    return {
        "activities": int(db.scalar(select(func.count()).select_from(Activity)) or 0),
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
        "requests": int(
            db.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) or 0
        ),
    }


def _strip_volatile(payload: object) -> object:
    if isinstance(payload, dict):
        return {
            key: "<volatile>" if key in VOLATILE_KEYS else _strip_volatile(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_strip_volatile(item) for item in payload]
    return payload


def _json_from_cli(output: str) -> dict[str, object]:
    start = output.find("{")
    assert start != -1
    payload = json.loads(output[start:])
    assert isinstance(payload, dict)
    return payload


def _assert_no_execution(payload: dict[str, object]) -> None:
    assert payload["read_only"] is True
    assert payload["no_execution"] is True
    assert payload["no_go_live"] is True
    assert payload["no_deployment"] is True
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
    assert payload["owner_launch_dossier_is_not_go_live"] is True
    assert payload["dossier_is_not_permission_to_go_live"] is True
    assert payload["dossier_is_not_execution"] is True
    assert payload["index_is_not_permission_to_go_live"] is True
    assert payload["handoff_is_not_go_live"] is True
    assert payload["binder_is_not_go_live"] is True
    assert payload["runbook_is_not_deployment"] is True
    assert payload["manifest_is_not_a_build_or_deploy"] is True
    assert payload["staged_rollout_plan_is_not_go_live"] is True
    assert payload["packet_kind"] == "owner_launch_dossier"
    assert payload["purpose"] == "manual_owner_review_export_only"
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE
    assert payload["source_index_command"] == INDEX_CLI_COMMAND
    assert payload["source_index_route"] == INDEX_HTTP_ROUTE
    assert payload["source_blockers_plan_command"] == BLOCKERS_CLI_COMMAND
    assert payload["source_blockers_plan_route"] == BLOCKERS_HTTP_ROUTE
    assert payload["source_staged_rollout_command"] == STAGED_CLI_COMMAND
    assert payload["source_staged_rollout_route"] == STAGED_HTTP_ROUTE
    assert payload["source_handoff_command"] == "owner-handoff-packet"
    assert payload["source_handoff_route"] == "/internal/owner-handoff-packet"
    assert payload["source_binder_command"] == BINDER_CLI_COMMAND
    assert payload["source_binder_route"] == BINDER_HTTP_ROUTE
    assert payload["source_runbook_command"] == RUNBOOK_CLI_COMMAND
    assert payload["source_runbook_route"] == RUNBOOK_HTTP_ROUTE
    assert payload["source_manifest_command"] == MANIFEST_CLI_COMMAND
    assert payload["source_manifest_route"] == MANIFEST_HTTP_ROUTE
    assert payload["source_preflight_command"] == "settings-execution-preflight"
    assert payload["source_preflight_route"] == "/internal/settings-execution-preflight"
    assert payload["source_audit_route"] == "/internal/operator-audit-timeline"
    preflight = payload["settings_preflight"]
    assert isinstance(preflight, dict)
    assert preflight["no_execution"] is True
    assert preflight["dry_run_only"] is True
    assert preflight["executed"] == 0
    assert preflight["settings_applied"] is False
    assert preflight["execution_allowed"] is False
    assert preflight["executable_count"] == 0
    audit = payload["operator_audit"]
    assert isinstance(audit, dict)
    assert audit["read_only"] is True
    assert audit["no_execution"] is True
    assert audit["executed"] == 0
    assert audit["halt_changed"] is False


def test_empty_dossier_reuses_sources_and_is_not_permission_to_go_live(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)
    settings = _settings()
    before_halt = read_operator_halt(db_session)
    staged = StagedRolloutPlanService().build(db_session, settings)
    handoff = OwnerHandoffPacketService().build(db_session, settings)

    dossier = OwnerLaunchDossierService().build(db_session, settings)
    payload = dossier_payload(dossier)

    assert dossier.read_only is True
    assert dossier.no_execution is True
    assert dossier.no_go_live is True
    assert dossier.no_deployment is True
    assert dossier.execution_allowed is False
    assert dossier.go_live_permitted is False
    assert dossier.deployment_allowed is False
    assert dossier.settings_applied is False
    assert dossier.halt_changed is False
    assert dossier.owner_approved is False
    assert dossier.owner_launch_dossier_is_not_go_live is True
    assert dossier.dossier_is_not_permission_to_go_live is True
    assert dossier.dossier_is_not_execution is True
    assert dossier.outbound_enabled is False
    assert dossier.executed == 0
    assert dossier.source_index_overall_status == staged.source_index_overall_status
    assert dossier.source_blockers_plan_overall_status == staged.source_blockers_plan_overall_status
    assert dossier.source_staged_rollout_overall_status == staged.overall_status
    assert dossier.source_handoff_overall_status == handoff.overall_status
    assert INDEX_HTTP_ROUTE in dossier.related_routes
    assert BLOCKERS_HTTP_ROUTE in dossier.related_routes
    assert STAGED_HTTP_ROUTE in dossier.related_routes
    assert HTTP_ROUTE in dossier.related_routes
    assert HTML_ROUTE in dossier.related_routes
    assert CLI_COMMAND in dossier.related_commands
    assert tuple(source.key for source in dossier.sources) == SOURCE_KEYS
    codes = {action.code for action in dossier.next_actions}
    assert NextActionCode.OWNER_LAUNCH_DOSSIER_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    for source in dossier.sources:
        assert source.read_only is True
        assert source.no_execution is True
        assert source.go_live_permitted is False
        assert source.deployment_allowed is False
    _assert_no_execution(payload)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_dossier_reuses_sources_and_does_not_leak_or_write(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    _seed_plans_and_packets(db_session)
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="owner-launch-dossier-service",
        reviewer_notes=PHI_SNIPPET,
    )
    SettingsChangeRequestService().record_decision(
        db_session,
        settings,
        request_id=created.request_id,
        decision="approved",
        reviewer="owner",
    )
    before = _counts(db_session)
    before_halt = read_operator_halt(db_session)
    staged = StagedRolloutPlanService().build(db_session, settings)

    first = OwnerLaunchDossierService().build(db_session, settings)
    second = OwnerLaunchDossierService().build(db_session, settings)

    assert set(staged.blocker_codes) <= set(first.blocker_codes)
    assert first.source_index_overall_status == staged.source_index_overall_status
    payload = dossier_payload(first)
    _assert_no_execution(payload)
    _assert_no_leakage(str(payload), SECRET_VALUE)
    assert PHI_SNIPPET not in str(payload)
    assert PROSPECT_EMAIL not in str(payload)
    assert SECRET_VALUE not in str(payload)
    assert DB_SECRET_URL not in str(payload)
    assert UNSAFE_ERROR not in str(payload)
    assert "sk-" not in str(payload).lower()
    dumped = json.dumps(payload)
    for action in first.next_actions:
        assert action.label
        assert PHI_SNIPPET not in action.label
        assert PROSPECT_EMAIL not in action.label
        assert SECRET_VALUE not in action.label
        assert UNSAFE_ERROR not in action.label
    assert "sources" in payload
    assert "next_actions" in payload
    assert _strip_volatile(dossier_payload(first)) == _strip_volatile(dossier_payload(second))
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert settings.outbound_enabled is False
    assert first.local_git.git_provider_called is False
    assert first.local_git.github_actions_called is False
    assert dumped


def test_dossier_is_deterministic_aside_from_timestamps_and_git(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    first = OwnerLaunchDossierService().build(db_session, settings)
    second = OwnerLaunchDossierService().build(db_session, settings)
    assert first.generated_at != datetime(1999, 1, 1, tzinfo=UTC)
    assert _strip_volatile(dossier_payload(first)) == _strip_volatile(dossier_payload(second))
    assert first.packet_kind == "owner_launch_dossier"
    assert first.purpose == "manual_owner_review_export_only"
    assert first.cli_command == CLI_COMMAND
    assert first.http_route == HTTP_ROUTE


def test_cli_owner_launch_dossier_json_is_sanitized(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(voice_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    before = _counts(db_session)
    before_halt = read_operator_halt(db_session)

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)

    first_code = main(["owner-launch-dossier", "--json"])
    first_output = capsys.readouterr().out
    second_code = main(["owner-launch-dossier", "--json"])
    second_output = capsys.readouterr().out
    payload = _json_from_cli(first_output)

    assert first_code == 0
    assert second_code == 0
    _assert_no_execution(payload)
    assert _strip_volatile(_json_from_cli(first_output)) == _strip_volatile(
        _json_from_cli(second_output)
    )
    assert payload["outbound_enabled"] is False
    assert "sources" in payload
    assert "local_git" in payload
    sources = payload["sources"]
    assert isinstance(sources, list)
    keys = {item["key"] for item in sources if isinstance(item, dict)}
    assert keys == set(SOURCE_KEYS)
    _assert_no_leakage(first_output, SECRET_VALUE, DB_SECRET_URL)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False


def test_cli_owner_launch_dossier_markdown_is_sanitized(
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

    markdown = format_owner_launch_dossier(
        OwnerLaunchDossierService().build(db_session, settings),
        as_json=False,
    )
    json_text = format_owner_launch_dossier(
        OwnerLaunchDossierService().build(db_session, settings),
        as_json=True,
    )
    code = main(["owner-launch-dossier"])
    output = capsys.readouterr().out

    assert code == 0
    assert "# Owner launch dossier" in output
    assert "go_live_permitted: false" in output
    assert "execution_allowed: false" in output
    assert "deployment_allowed: false" in output
    assert "settings_applied: false" in output
    assert "halt_changed: false" in output
    assert "owner_approved: false" in output
    assert "owner_launch_dossier_is_not_go_live: true" in output
    assert "dossier_is_not_permission_to_go_live: true" in output
    assert "OUTBOUND_ENABLED=false" in output
    assert "## Live-blocking flags" in output
    assert "## Included surfaces" in output
    assert "## Owner next actions" in output
    assert "cli_command: owner-launch-dossier" in output
    assert "http_route: /internal/owner-launch-dossier" in output
    assert "source_index_command: go-live-readiness-index" in output
    assert "source_blockers_plan_command: launch-blockers-plan" in output
    assert "source_staged_rollout_command: staged-rollout-plan" in output
    assert "source_handoff_command: owner-handoff-packet" in output
    assert "source_runbook_command: release-candidate-runbook" in output
    assert "source_binder_command: compliance-evidence-binder" in output
    assert "source_manifest_command: release-artifact-manifest" in output
    _assert_no_leakage(output, SECRET_VALUE)
    _assert_no_leakage(markdown, SECRET_VALUE)
    _assert_no_leakage(json_text, SECRET_VALUE)
    assert read_operator_halt(db_session) is HaltStatus.HALTED
