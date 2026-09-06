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
from vyro_growth.services.launch_blockers_plan import LaunchBlockersPlanService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
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
    CLI_COMMAND,
    HTTP_ROUTE,
    STAGE_KEYS,
    StagedRolloutPlanService,
    format_staged_rollout_plan,
    plan_payload,
)

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
    assert payload["staged_rollout_plan_is_not_go_live"] is True
    assert payload["plan_is_not_permission_to_go_live"] is True
    assert payload["plan_is_not_execution"] is True
    assert payload["index_is_not_permission_to_go_live"] is True
    assert payload["handoff_is_not_go_live"] is True
    assert payload["binder_is_not_go_live"] is True
    assert payload["runbook_is_not_deployment"] is True
    assert payload["manifest_is_not_a_build_or_deploy"] is True
    assert payload["packet_kind"] == "staged_go_live_rollout_plan"
    assert payload["purpose"] == "manual_owner_staged_rollout_planning_only"
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE
    assert payload["source_index_command"] == INDEX_CLI_COMMAND
    assert payload["source_index_route"] == INDEX_HTTP_ROUTE
    assert payload["source_blockers_plan_command"] == BLOCKERS_CLI_COMMAND
    assert payload["source_blockers_plan_route"] == BLOCKERS_HTTP_ROUTE
    assert payload["source_launch_readiness_command"] == "launch-readiness"
    assert payload["source_launch_readiness_route"] == "/internal/launch-readiness"
    assert payload["source_binder_command"] == BINDER_CLI_COMMAND
    assert payload["source_binder_route"] == BINDER_HTTP_ROUTE
    assert payload["source_runbook_command"] == RUNBOOK_CLI_COMMAND
    assert payload["source_runbook_route"] == RUNBOOK_HTTP_ROUTE
    assert payload["source_manifest_command"] == MANIFEST_CLI_COMMAND
    assert payload["source_manifest_route"] == MANIFEST_HTTP_ROUTE


def test_empty_plan_reuses_sources_and_is_not_permission_to_go_live(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)
    settings = _settings()
    before_halt = read_operator_halt(db_session)
    blockers = LaunchBlockersPlanService().build(db_session, settings)

    plan = StagedRolloutPlanService().build(db_session, settings)
    payload = plan_payload(plan)

    assert plan.read_only is True
    assert plan.no_execution is True
    assert plan.execution_allowed is False
    assert plan.go_live_permitted is False
    assert plan.deployment_allowed is False
    assert plan.settings_applied is False
    assert plan.halt_changed is False
    assert plan.owner_approved is False
    assert plan.staged_rollout_plan_is_not_go_live is True
    assert plan.plan_is_not_permission_to_go_live is True
    assert plan.plan_is_not_execution is True
    assert plan.outbound_enabled is False
    assert plan.executed == 0
    assert plan.source_index_overall_status == blockers.source_index_overall_status
    assert plan.source_blockers_plan_overall_status == blockers.overall_status
    assert INDEX_HTTP_ROUTE in plan.related_routes
    assert BLOCKERS_HTTP_ROUTE in plan.related_routes
    assert HTTP_ROUTE in plan.related_routes
    assert CLI_COMMAND in plan.related_commands
    assert tuple(stage.stage_key for stage in plan.stages) == STAGE_KEYS
    assert plan.stages[0].stage_label == "Safe defaults and operator halt verification"
    assert plan.stages[1].stage_label == "Credential and configuration preparation"
    assert plan.stages[2].stage_label == "Local dry-run verification and CI gates"
    assert (
        plan.stages[3].stage_label
        == "Owner review of packets, checklists, and readiness surfaces"
    )
    assert plan.stages[4].stage_label == "Future manual deployment preparation only"
    assert (
        plan.stages[5].stage_label
        == "Future owner-approved live enablement prerequisites only"
    )
    codes = {item.code for stage in plan.stages for item in stage.checklist_items}
    assert NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    for stage in plan.stages:
        assert stage.read_only is True
        assert stage.no_execution is True
        assert stage.execution_allowed is False
        assert stage.go_live_permitted is False
        assert stage.deployment_allowed is False
        assert stage.settings_applied is False
        assert stage.halt_changed is False
        assert stage.outbound_enabled is False
        assert stage.owner_approved is False
        assert stage.staged_rollout_plan_is_not_go_live is True
        assert stage.required_owner_approval_type in {
            "none",
            "owner_review",
            "owner_approval_packet",
            "settings_change_request",
            "live_enablement_review",
        }
    _assert_no_execution(payload)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_plan_reuses_source_blockers_and_does_not_leak_or_write(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    _seed_plans_and_packets(db_session)
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="staged-plan-service",
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
    blockers = LaunchBlockersPlanService().build(db_session, settings)

    first = StagedRolloutPlanService().build(db_session, settings)
    second = StagedRolloutPlanService().build(db_session, settings)

    assert set(blockers.blocker_codes) <= set(first.blocker_codes)
    assert first.source_index_overall_status == blockers.source_index_overall_status
    payload = plan_payload(first)
    _assert_no_execution(payload)
    _assert_no_leakage(str(payload), SECRET_VALUE)
    assert PHI_SNIPPET not in str(payload)
    assert PROSPECT_EMAIL not in str(payload)
    assert SECRET_VALUE not in str(payload)
    assert DB_SECRET_URL not in str(payload)
    assert UNSAFE_ERROR not in str(payload)
    assert "sk-" not in str(payload).lower()
    dumped = json.dumps(payload)
    for stage in first.stages:
        for item in stage.checklist_items:
            assert item.label
            assert PHI_SNIPPET not in item.label
            assert PROSPECT_EMAIL not in item.label
            assert SECRET_VALUE not in item.label
            assert UNSAFE_ERROR not in item.label
    assert "stages" in payload
    assert _strip_volatile(plan_payload(first)) == _strip_volatile(plan_payload(second))
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert settings.outbound_enabled is False
    assert first.local_git.git_provider_called is False
    assert first.local_git.github_actions_called is False
    assert dumped


def test_plan_is_deterministic_aside_from_timestamps_and_git(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    first = StagedRolloutPlanService().build(db_session, settings)
    second = StagedRolloutPlanService().build(db_session, settings)
    assert first.generated_at != datetime(1999, 1, 1, tzinfo=UTC)
    assert _strip_volatile(plan_payload(first)) == _strip_volatile(plan_payload(second))
    assert first.packet_kind == "staged_go_live_rollout_plan"
    assert first.purpose == "manual_owner_staged_rollout_planning_only"
    assert first.cli_command == CLI_COMMAND
    assert first.http_route == HTTP_ROUTE


def test_cli_staged_rollout_plan_json_is_sanitized(
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

    first_code = main(["staged-rollout-plan", "--json"])
    first_output = capsys.readouterr().out
    second_code = main(["staged-rollout-plan", "--json"])
    second_output = capsys.readouterr().out
    payload = _json_from_cli(first_output)

    assert first_code == 0
    assert second_code == 0
    _assert_no_execution(payload)
    assert _strip_volatile(_json_from_cli(first_output)) == _strip_volatile(
        _json_from_cli(second_output)
    )
    assert payload["outbound_enabled"] is False
    assert "stages" in payload
    assert "local_git" in payload
    stages = payload["stages"]
    assert isinstance(stages, list)
    keys = {item["stage_key"] for item in stages if isinstance(item, dict)}
    assert keys == set(STAGE_KEYS)
    _assert_no_leakage(first_output, SECRET_VALUE, DB_SECRET_URL)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False


def test_cli_staged_rollout_plan_markdown_is_sanitized(
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

    markdown = format_staged_rollout_plan(
        StagedRolloutPlanService().build(db_session, settings),
        as_json=False,
    )
    json_text = format_staged_rollout_plan(
        StagedRolloutPlanService().build(db_session, settings),
        as_json=True,
    )
    code = main(["staged-rollout-plan"])
    output = capsys.readouterr().out

    assert code == 0
    assert "# Staged go-live rollout plan" in output
    assert "go_live_permitted: false" in output
    assert "execution_allowed: false" in output
    assert "deployment_allowed: false" in output
    assert "settings_applied: false" in output
    assert "halt_changed: false" in output
    assert "owner_approved: false" in output
    assert "staged_rollout_plan_is_not_go_live: true" in output
    assert "plan_is_not_permission_to_go_live: true" in output
    assert "OUTBOUND_ENABLED=false" in output
    assert "## Live-blocking flags" in output
    assert "## Staged rollout groups" in output
    assert "cli_command: staged-rollout-plan" in output
    assert "http_route: /internal/staged-rollout-plan" in output
    assert "source_index_command: go-live-readiness-index" in output
    assert "source_blockers_plan_command: launch-blockers-plan" in output
    assert "source_runbook_command: release-candidate-runbook" in output
    assert "source_binder_command: compliance-evidence-binder" in output
    assert "source_manifest_command: release-artifact-manifest" in output
    _assert_no_leakage(output, SECRET_VALUE)
    _assert_no_leakage(markdown, SECRET_VALUE)
    _assert_no_leakage(json_text, SECRET_VALUE)
    assert read_operator_halt(db_session) is HaltStatus.HALTED
