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
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.provider_setup_checklist import (
    CLI_COMMAND as PROVIDER_CLI_COMMAND,
)
from vyro_growth.services.provider_setup_checklist import ProviderSetupChecklistService
from vyro_growth.services.rehearsal_outcome_report import (
    CLI_COMMAND as OUTCOME_CLI_COMMAND,
)
from vyro_growth.services.rehearsal_outcome_report import RehearsalOutcomeReportService
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService
from vyro_growth.services.supervised_pilot_plan import (
    CLI_COMMAND,
    HTML_ROUTE,
    HTTP_ROUTE,
    PREREQUISITE_KEYS,
    SUGGESTED_MAX_DAILY_ACTIVITY,
    SUGGESTED_MAX_DRAFTS,
    SUGGESTED_MAX_LEADS,
    SUGGESTED_MAX_MANUALLY_REVIEWED_SENDS,
    SupervisedPilotPlanService,
    format_supervised_pilot_plan,
    supervised_pilot_plan_payload,
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
    assert payload["no_go_live"] is True
    assert payload["no_deployment"] is True
    assert payload["no_spend"] is True
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
    assert payload["spend_allowed"] is False
    assert payload["spend_attempted"] is False
    assert payload["manual_review_only"] is True
    assert payload["supervised_pilot_plan_is_not_go_live"] is True
    assert payload["plan_is_not_permission_to_go_live"] is True
    assert payload["plan_is_not_execution"] is True
    assert payload["packet_kind"] == "supervised_pilot_plan"
    assert payload["purpose"] == "manual_owner_supervised_pilot_review_only"
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE
    assert payload["source_outcome_command"] == OUTCOME_CLI_COMMAND
    assert payload["source_rehearsal_command"] == "go-live-rehearsal-checklist"
    assert payload["source_launch_readiness_command"] == "launch-readiness"
    assert payload["source_index_command"] == "go-live-readiness-index"
    assert payload["source_blockers_plan_command"] == "launch-blockers-plan"
    assert payload["source_staged_rollout_command"] == "staged-rollout-plan"
    assert payload["source_dossier_command"] == "owner-launch-dossier"
    assert payload["source_provider_setup_command"] == PROVIDER_CLI_COMMAND
    assert payload["source_preflight_command"] == "settings-execution-preflight"


def test_empty_pilot_plan_reuses_existing_surfaces_and_is_not_permission_to_go_live(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)
    settings = _settings()
    before_halt = read_operator_halt(db_session)
    outcome = RehearsalOutcomeReportService().build(db_session, settings)
    provider = ProviderSetupChecklistService().build(db_session, settings)

    plan = SupervisedPilotPlanService().build(db_session, settings)
    payload = supervised_pilot_plan_payload(plan)

    assert plan.read_only is True
    assert plan.no_execution is True
    assert plan.no_go_live is True
    assert plan.no_deployment is True
    assert plan.no_spend is True
    assert plan.execution_allowed is False
    assert plan.go_live_permitted is False
    assert plan.deployment_allowed is False
    assert plan.settings_applied is False
    assert plan.halt_changed is False
    assert plan.owner_approved is False
    assert plan.spend_allowed is False
    assert plan.supervised_pilot_plan_is_not_go_live is True
    assert plan.plan_is_not_permission_to_go_live is True
    assert plan.outbound_enabled is False
    assert plan.executed == 0
    assert plan.source_outcome_overall_status == outcome.overall_status
    assert plan.source_rehearsal_overall_status == outcome.source_rehearsal_overall_status
    assert plan.source_index_overall_status == outcome.source_index_overall_status
    assert plan.source_provider_setup_overall_status == provider.overall_status
    assert plan.blocker_codes
    assert set(outcome.blocker_codes) <= set(plan.blocker_codes)
    assert set(provider.missing_credential_names) <= set(plan.missing_credential_names)
    assert {item.key for item in plan.prerequisites} == set(PREREQUISITE_KEYS)
    assert plan.pilot_scope.suggested_max_leads == SUGGESTED_MAX_LEADS
    assert plan.pilot_scope.suggested_max_drafts == SUGGESTED_MAX_DRAFTS
    assert (
        plan.pilot_scope.suggested_max_manually_reviewed_sends
        == SUGGESTED_MAX_MANUALLY_REVIEWED_SENDS
    )
    assert plan.pilot_scope.suggested_max_daily_activity == SUGGESTED_MAX_DAILY_ACTIVITY
    assert plan.pilot_scope.suggested_max_manually_reviewed_sends == 0
    assert all(step.runnable is False and step.executed == 0 for step in plan.runbook_steps)
    assert plan.abort_criteria
    codes = {action.code for action in plan.next_actions}
    assert NextActionCode.SUPERVISED_PILOT_PLAN_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.REHEARSAL_OUTCOME_REPORT_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    assert CLI_COMMAND in plan.related_commands
    assert OUTCOME_CLI_COMMAND in plan.related_commands
    assert HTTP_ROUTE in plan.related_routes
    assert HTML_ROUTE in plan.related_routes
    assert "planning counts only" in plan.pilot_scope.recommendation_summary
    _assert_no_execution(payload)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_pilot_plan_reuses_surfaces_and_does_not_leak_or_write(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    _seed_plans_and_packets(db_session)
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="supervised-pilot-plan-service",
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
    outcome = RehearsalOutcomeReportService().build(db_session, settings)

    first = SupervisedPilotPlanService().build(db_session, settings)
    second = SupervisedPilotPlanService().build(db_session, settings)

    assert first.source_outcome_overall_status == outcome.overall_status
    payload = supervised_pilot_plan_payload(first)
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
    for step in first.runbook_steps:
        assert step.runnable is False
        assert step.executed == 0
        assert PHI_SNIPPET not in step.instruction
    assert "pilot_scope" in payload
    assert "prerequisites" in payload
    assert "runbook_steps" in payload
    assert "abort_criteria" in payload
    assert _strip_volatile(supervised_pilot_plan_payload(first)) == _strip_volatile(
        supervised_pilot_plan_payload(second)
    )
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert settings.outbound_enabled is False
    assert first.local_git.git_provider_called is False
    assert first.local_git.github_actions_called is False
    assert dumped


def test_pilot_plan_lists_failed_assertion_keys(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(outbound_enabled=True)

    plan = SupervisedPilotPlanService().build(db_session, settings)
    payload = supervised_pilot_plan_payload(plan)

    assert plan.expected_safe_assertions_failed >= 1
    assert "OUTBOUND_ENABLED" in plan.failed_safe_assertion_keys
    dumped = json.dumps(payload)
    assert "OUTBOUND_ENABLED" in dumped
    assert SECRET_VALUE not in dumped
    assert plan.owner_approved is False
    assert plan.go_live_permitted is False
    assert plan.execution_allowed is False
    assert plan.spend_allowed is False


def test_pilot_plan_is_deterministic_aside_from_timestamps_and_git(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    first = SupervisedPilotPlanService().build(db_session, settings)
    second = SupervisedPilotPlanService().build(db_session, settings)
    assert first.generated_at != datetime(1999, 1, 1, tzinfo=UTC)
    assert _strip_volatile(supervised_pilot_plan_payload(first)) == _strip_volatile(
        supervised_pilot_plan_payload(second)
    )
    assert first.packet_kind == "supervised_pilot_plan"
    assert first.purpose == "manual_owner_supervised_pilot_review_only"
    assert first.cli_command == CLI_COMMAND
    assert first.http_route == HTTP_ROUTE


def test_cli_supervised_pilot_plan_json_is_sanitized(
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

    first_code = main(["supervised-pilot-plan", "--json"])
    first_output = capsys.readouterr().out
    second_code = main(["supervised-pilot-plan", "--json"])
    second_output = capsys.readouterr().out
    payload = _json_from_cli(first_output)

    assert first_code == 0
    assert second_code == 0
    _assert_no_execution(payload)
    assert _strip_volatile(_json_from_cli(first_output)) == _strip_volatile(
        _json_from_cli(second_output)
    )
    assert payload["outbound_enabled"] is False
    assert "pilot_scope" in payload
    assert "prerequisites" in payload
    assert "runbook_steps" in payload
    assert "local_git" in payload
    _assert_no_leakage(first_output, SECRET_VALUE, DB_SECRET_URL)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False


def test_cli_supervised_pilot_plan_markdown_is_sanitized(
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

    markdown = format_supervised_pilot_plan(
        SupervisedPilotPlanService().build(db_session, settings),
        as_json=False,
    )
    json_text = format_supervised_pilot_plan(
        SupervisedPilotPlanService().build(db_session, settings),
        as_json=True,
    )
    code = main(["supervised-pilot-plan"])
    output = capsys.readouterr().out

    assert code == 0
    assert "# Supervised pilot launch plan" in output
    assert "go_live_permitted: false" in output
    assert "execution_allowed: false" in output
    assert "deployment_allowed: false" in output
    assert "settings_applied: false" in output
    assert "halt_changed: false" in output
    assert "owner_approved: false" in output
    assert "spend_allowed: false" in output
    assert "no_spend: true" in output
    assert "supervised_pilot_plan_is_not_go_live: true" in output
    assert "plan_is_not_permission_to_go_live: true" in output
    assert "OUTBOUND_ENABLED=false" in output
    assert "## Live-blocking flags" in output
    assert "## Pilot scope recommendation" in output
    assert "## Safety assertions" in output
    assert "## Pilot prerequisites" in output
    assert "## Manual pilot runbook" in output
    assert "## Pilot abort and rollback criteria" in output
    assert "## Owner next actions" in output
    assert "cli_command: supervised-pilot-plan" in output
    assert "http_route: /internal/supervised-pilot-plan" in output
    assert "source_outcome_command: rehearsal-outcome-report" in output
    assert "source_index_command: go-live-readiness-index" in output
    assert "source_provider_setup_command: provider-setup-checklist" in output
    assert "suggested_max_manually_reviewed_sends: 0" in output
    assert "runnable=false" in output
    _assert_no_leakage(output, SECRET_VALUE)
    _assert_no_leakage(markdown, SECRET_VALUE)
    _assert_no_leakage(json_text, SECRET_VALUE)
    assert read_operator_halt(db_session) is HaltStatus.HALTED
