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
from vyro_growth.services.go_live_rehearsal_checklist import (
    CLI_COMMAND as REHEARSAL_CLI_COMMAND,
)
from vyro_growth.services.go_live_rehearsal_checklist import (
    HTML_ROUTE as REHEARSAL_HTML_ROUTE,
)
from vyro_growth.services.go_live_rehearsal_checklist import (
    HTTP_ROUTE as REHEARSAL_HTTP_ROUTE,
)
from vyro_growth.services.go_live_rehearsal_checklist import GoLiveRehearsalChecklistService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.rehearsal_outcome_report import (
    CLI_COMMAND,
    HTML_ROUTE,
    HTTP_ROUTE,
    RehearsalOutcomeReportService,
    format_rehearsal_outcome_report,
    outcome_report_payload,
)
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

DB_SECRET_URL = "postgresql+psycopg://vyro:super-db-password@localhost:5432/vyro_growth"
VOLATILE_KEYS = {
    "generated_at",
    "current_sha",
    "current_branch",
    "working_tree_status",
    "available",
}
UNSAFE_ERROR = "Traceback (most recent call last): secret=sk-live-error-token"
FORBIDDEN_DETAIL_KEYS = {
    "expected",
    "observed",
    "rehearsal_steps",
    "expected_safe_assertions",
    "sources",
    "rollback_guidance",
}


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


def _count_map(items: object) -> dict[str, int]:
    assert isinstance(items, list)
    mapped: dict[str, int] = {}
    for item in items:
        assert isinstance(item, dict)
        key = item["key"]
        count = item["count"]
        assert isinstance(key, str)
        assert isinstance(count, int)
        mapped[key] = count
    return mapped


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
    assert payload["rehearsal_outcome_report_is_not_go_live"] is True
    assert payload["report_is_not_permission_to_go_live"] is True
    assert payload["report_is_not_execution"] is True
    assert payload["go_live_rehearsal_checklist_is_not_go_live"] is True
    assert payload["rehearsal_is_not_a_script_runner"] is True
    assert payload["packet_kind"] == "rehearsal_outcome_report"
    assert payload["purpose"] == "manual_owner_rehearsal_outcome_review_only"
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE
    assert payload["source_rehearsal_command"] == REHEARSAL_CLI_COMMAND
    assert payload["source_rehearsal_route"] == REHEARSAL_HTTP_ROUTE
    assert payload["source_rehearsal_html_route"] == REHEARSAL_HTML_ROUTE
    assert payload["source_launch_readiness_command"] == "launch-readiness"
    assert payload["source_index_command"] == "go-live-readiness-index"
    assert payload["source_blockers_plan_command"] == "launch-blockers-plan"
    assert payload["source_staged_rollout_command"] == "staged-rollout-plan"
    assert payload["source_dossier_command"] == "owner-launch-dossier"
    assert payload["source_provider_setup_command"] == "provider-setup-checklist"
    assert payload["source_preflight_command"] == "settings-execution-preflight"
    for key in FORBIDDEN_DETAIL_KEYS:
        assert key not in payload


def test_empty_outcome_reuses_rehearsal_checklist_and_is_not_permission_to_go_live(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)
    settings = _settings()
    before_halt = read_operator_halt(db_session)
    checklist = GoLiveRehearsalChecklistService().build(db_session, settings)

    report = RehearsalOutcomeReportService().build(db_session, settings)
    payload = outcome_report_payload(report)

    assert report.read_only is True
    assert report.no_execution is True
    assert report.no_go_live is True
    assert report.no_deployment is True
    assert report.execution_allowed is False
    assert report.go_live_permitted is False
    assert report.deployment_allowed is False
    assert report.settings_applied is False
    assert report.halt_changed is False
    assert report.owner_approved is False
    assert report.rehearsal_outcome_report_is_not_go_live is True
    assert report.report_is_not_permission_to_go_live is True
    assert report.outbound_enabled is False
    assert report.executed == 0
    assert report.source_rehearsal_overall_status == checklist.overall_status
    assert report.source_index_overall_status == checklist.source_index_overall_status
    assert (
        report.source_blockers_plan_overall_status == checklist.source_blockers_plan_overall_status
    )
    assert (
        report.source_staged_rollout_overall_status
        == checklist.source_staged_rollout_overall_status
    )
    assert report.source_dossier_overall_status == checklist.source_dossier_overall_status
    assert (
        report.source_provider_setup_overall_status
        == checklist.source_provider_setup_overall_status
    )
    assert report.source_preflight_overall_status == checklist.source_preflight_overall_status
    assert report.rehearsal_step_count == len(checklist.rehearsal_steps)
    assert report.expected_safe_assertion_count == len(checklist.expected_safe_assertions)
    assert report.expected_safe_assertions_passed == len(checklist.expected_safe_assertions)
    assert report.expected_safe_assertions_failed == 0
    assert report.failed_safe_assertion_keys == ()
    assert report.blocker_codes == checklist.blocker_codes
    assert report.gate_codes == checklist.gate_codes
    assert report.missing_credential_names == checklist.missing_credential_names
    assert report.closed_provider_flag_names == checklist.closed_provider_flag_names
    status_counts = {item.key: item.count for item in report.rehearsal_step_counts_by_status}
    assert sum(status_counts.values()) == report.rehearsal_step_count
    kind_counts = {item.key: item.count for item in report.rehearsal_step_counts_by_kind}
    assert sum(kind_counts.values()) == report.rehearsal_step_count
    approval_counts = {
        item.key: item.count
        for item in report.rehearsal_step_counts_by_required_owner_approval_type
    }
    assert sum(approval_counts.values()) == report.rehearsal_step_count
    codes = {action.code for action in report.next_actions}
    assert NextActionCode.REHEARSAL_OUTCOME_REPORT_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.GO_LIVE_REHEARSAL_CHECKLIST_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    assert CLI_COMMAND in report.related_commands
    assert REHEARSAL_CLI_COMMAND in report.related_commands
    assert HTTP_ROUTE in report.related_routes
    assert HTML_ROUTE in report.related_routes
    assert REHEARSAL_HTTP_ROUTE in report.related_routes
    assert "Manual rehearsal outcome only" in report.outcome_summary
    assert "not permission to go live" in report.outcome_summary
    _assert_no_execution(payload)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_outcome_reuses_checklist_and_does_not_leak_or_write(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    _seed_plans_and_packets(db_session)
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="rehearsal-outcome-report-service",
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
    checklist = GoLiveRehearsalChecklistService().build(db_session, settings)

    first = RehearsalOutcomeReportService().build(db_session, settings)
    second = RehearsalOutcomeReportService().build(db_session, settings)

    assert first.source_rehearsal_overall_status == checklist.overall_status
    assert set(checklist.blocker_codes) <= set(first.blocker_codes)
    payload = outcome_report_payload(first)
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
    assert "failed_safe_assertion_keys" in payload
    assert "rehearsal_step_counts_by_status" in payload
    assert "outcome_summary" in payload
    assert _strip_volatile(outcome_report_payload(first)) == _strip_volatile(
        outcome_report_payload(second)
    )
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert settings.outbound_enabled is False
    assert first.local_git.git_provider_called is False
    assert first.local_git.github_actions_called is False
    assert dumped


def test_outcome_lists_failed_assertion_keys_only(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(outbound_enabled=True)

    report = RehearsalOutcomeReportService().build(db_session, settings)
    payload = outcome_report_payload(report)

    assert report.expected_safe_assertions_failed >= 1
    assert "OUTBOUND_ENABLED" in report.failed_safe_assertion_keys
    assert "expected" not in payload
    assert "observed" not in payload
    assert "expected_safe_assertions" not in payload
    dumped = json.dumps(payload)
    assert "OUTBOUND_ENABLED" in dumped
    assert "true" in dumped
    assert SECRET_VALUE not in dumped
    assert report.owner_approved is False
    assert report.go_live_permitted is False
    assert report.execution_allowed is False


def test_outcome_is_deterministic_aside_from_timestamps_and_git(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    first = RehearsalOutcomeReportService().build(db_session, settings)
    second = RehearsalOutcomeReportService().build(db_session, settings)
    assert first.generated_at != datetime(1999, 1, 1, tzinfo=UTC)
    assert _strip_volatile(outcome_report_payload(first)) == _strip_volatile(
        outcome_report_payload(second)
    )
    assert first.packet_kind == "rehearsal_outcome_report"
    assert first.purpose == "manual_owner_rehearsal_outcome_review_only"
    assert first.cli_command == CLI_COMMAND
    assert first.http_route == HTTP_ROUTE


def test_cli_rehearsal_outcome_report_json_is_sanitized(
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

    first_code = main(["rehearsal-outcome-report", "--json"])
    first_output = capsys.readouterr().out
    second_code = main(["rehearsal-outcome-report", "--json"])
    second_output = capsys.readouterr().out
    payload = _json_from_cli(first_output)

    assert first_code == 0
    assert second_code == 0
    _assert_no_execution(payload)
    assert _strip_volatile(_json_from_cli(first_output)) == _strip_volatile(
        _json_from_cli(second_output)
    )
    assert payload["outbound_enabled"] is False
    assert "rehearsal_step_counts_by_status" in payload
    assert "failed_safe_assertion_keys" in payload
    assert "local_git" in payload
    assert _count_map(payload["rehearsal_step_counts_by_status"])
    _assert_no_leakage(first_output, SECRET_VALUE, DB_SECRET_URL)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False


def test_cli_rehearsal_outcome_report_markdown_is_sanitized(
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

    markdown = format_rehearsal_outcome_report(
        RehearsalOutcomeReportService().build(db_session, settings),
        as_json=False,
    )
    json_text = format_rehearsal_outcome_report(
        RehearsalOutcomeReportService().build(db_session, settings),
        as_json=True,
    )
    code = main(["rehearsal-outcome-report"])
    output = capsys.readouterr().out

    assert code == 0
    assert "# Rehearsal outcome report" in output
    assert "go_live_permitted: false" in output
    assert "execution_allowed: false" in output
    assert "deployment_allowed: false" in output
    assert "settings_applied: false" in output
    assert "halt_changed: false" in output
    assert "owner_approved: false" in output
    assert "rehearsal_outcome_report_is_not_go_live: true" in output
    assert "report_is_not_permission_to_go_live: true" in output
    assert "OUTBOUND_ENABLED=false" in output
    assert "## Live-blocking flags" in output
    assert "## Rehearsal step counts by status" in output
    assert "## Rehearsal step counts by kind" in output
    assert "## Rehearsal step counts by required owner approval type" in output
    assert "## Owner next actions" in output
    assert "cli_command: rehearsal-outcome-report" in output
    assert "http_route: /internal/rehearsal-outcome-report" in output
    assert "source_rehearsal_command: go-live-rehearsal-checklist" in output
    assert "source_index_command: go-live-readiness-index" in output
    assert "source_blockers_plan_command: launch-blockers-plan" in output
    assert "source_staged_rollout_command: staged-rollout-plan" in output
    assert "source_dossier_command: owner-launch-dossier" in output
    assert "source_provider_setup_command: provider-setup-checklist" in output
    assert "failed_safe_assertion_keys:" in output
    _assert_no_leakage(output, SECRET_VALUE)
    _assert_no_leakage(markdown, SECRET_VALUE)
    _assert_no_leakage(json_text, SECRET_VALUE)
    assert read_operator_halt(db_session) is HaltStatus.HALTED
