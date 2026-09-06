from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_action_readiness_service import _seed_plans_and_packets
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from tests.test_supervised_pilot_candidates_service import (
    NPI_NUMBER,
    PRACTICE_NAME,
    PROVIDER_NAME,
    STREET_HINT,
    WEBSITE,
    _seed_candidate,
)
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
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService
from vyro_growth.services.supervised_pilot_first_send_preflight import (
    CLI_COMMAND,
    HTTP_ROUTE,
    SupervisedPilotFirstSendPreflightService,
    format_supervised_pilot_first_send_preflight,
    supervised_pilot_first_send_preflight_payload,
)
from vyro_growth.services.supervised_pilot_go_no_go import (
    CLI_COMMAND as GO_NO_GO_CLI_COMMAND,
)
from vyro_growth.services.supervised_pilot_go_no_go import (
    HTTP_ROUTE as GO_NO_GO_HTTP_ROUTE,
)
from vyro_growth.services.supervised_pilot_go_no_go import SupervisedPilotGoNoGoService
from vyro_growth.services.supervised_pilot_plan import (
    CLI_COMMAND as PILOT_CLI_COMMAND,
)
from vyro_growth.services.supervised_pilot_plan import (
    HTTP_ROUTE as PILOT_HTTP_ROUTE,
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
    assert payload["no_outbound"] is True
    assert payload["no_provider_calls"] is True
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
    assert payload["first_send_allowed"] is False
    assert payload["first_send_attempted"] is False
    assert payload["first_send_executed"] == 0
    assert payload["sends_executed"] == 0
    assert payload["suggested_max_first_sends"] == 0
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
    assert payload["supervised_pilot_first_send_preflight_is_not_go_live"] is True
    assert payload["first_send_preflight_is_not_a_send"] is True
    assert payload["export_is_not_permission_to_go_live"] is True
    assert payload["export_is_not_execution"] is True
    assert payload["packet_kind"] == "supervised_pilot_first_send_preflight"
    assert payload["purpose"] == "manual_owner_supervised_pilot_first_send_preflight_review_only"
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE
    assert payload["source_go_no_go_command"] == GO_NO_GO_CLI_COMMAND
    assert payload["source_go_no_go_route"] == GO_NO_GO_HTTP_ROUTE
    assert payload["source_pilot_plan_command"] == PILOT_CLI_COMMAND
    assert payload["source_pilot_plan_route"] == PILOT_HTTP_ROUTE


def _assert_no_sensitive_leakage(text: str) -> None:
    lowered = text.lower()
    _assert_no_leakage(text, SECRET_VALUE, DB_SECRET_URL)
    assert PHI_SNIPPET not in text
    assert PROSPECT_EMAIL not in text
    assert PRACTICE_NAME not in text
    assert PROVIDER_NAME not in text
    assert NPI_NUMBER not in text
    assert WEBSITE not in text
    assert "austin family" not in lowered
    assert STREET_HINT.lower() not in lowered or "family medicine" not in lowered
    assert UNSAFE_ERROR not in text
    assert "sk-" not in lowered
    assert "please call me" not in lowered
    assert "this opening line" not in lowered


def test_empty_first_send_preflight_reuses_sources_and_is_not_a_send(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)
    settings = _settings()
    before_halt = read_operator_halt(db_session)
    go_no_go = SupervisedPilotGoNoGoService().build(db_session, settings)

    packet = SupervisedPilotFirstSendPreflightService().build(db_session, settings)
    payload = supervised_pilot_first_send_preflight_payload(packet)

    assert packet.read_only is True
    assert packet.no_execution is True
    assert packet.no_go_live is True
    assert packet.no_outbound is True
    assert packet.first_send_allowed is False
    assert packet.first_send_executed == 0
    assert packet.execution_allowed is False
    assert packet.go_live_permitted is False
    assert packet.owner_approved is False
    assert packet.supervised_pilot_first_send_preflight_is_not_go_live is True
    assert packet.first_send_preflight_is_not_a_send is True
    assert packet.outbound_enabled is False
    assert packet.executed == 0
    assert packet.overall_status == go_no_go.overall_status
    assert packet.source_go_no_go_overall_status == go_no_go.overall_status
    assert packet.total_candidate_count == go_no_go.total_candidate_count
    assert packet.ready_for_review_count == go_no_go.ready_for_review_count
    assert packet.overall_status in {"blocked", "warning", "ready_for_owner_review", "info"}
    codes = {action.code for action in packet.next_actions}
    assert NextActionCode.SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.SUPERVISED_PILOT_GO_NO_GO_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.SUPERVISED_PILOT_PLAN_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    assert CLI_COMMAND in packet.related_commands
    assert GO_NO_GO_CLI_COMMAND in packet.related_commands
    assert PILOT_CLI_COMMAND in packet.related_commands
    assert HTTP_ROUTE in packet.related_routes
    assert GO_NO_GO_HTTP_ROUTE in packet.related_routes
    assert PILOT_HTTP_ROUTE in packet.related_routes
    check_codes = {check.code for check in packet.preflight_checks}
    assert "first_send_not_permitted" in check_codes
    assert "preflight_is_not_a_send" in check_codes
    assert "source_go_no_go" in check_codes
    assert "outbound_disabled" in check_codes
    assert "operator_halt" in check_codes
    assert any(item.code == "abort_before_any_first_send" for item in packet.abort_criteria)
    assert packet.expected_safe_assertion_count >= 1
    assert packet.expected_safe_assertions_failed == 0
    assert packet.failed_safe_assertion_keys == ()
    _assert_no_execution(payload)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_first_send_preflight_counts_without_leaking(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    _seed_candidate(
        db_session,
        verified_contact=True,
        add_evidence=True,
        add_enrichment=True,
        score_band="hot",
    )
    _seed_candidate(
        db_session,
        verified_contact=False,
        add_evidence=False,
        add_enrichment=False,
        score_band=None,
    )
    _seed_plans_and_packets(db_session)
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="supervised-pilot-first-send-preflight-service",
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
    go_no_go = SupervisedPilotGoNoGoService().build(db_session, settings)

    first = SupervisedPilotFirstSendPreflightService().build(db_session, settings)
    second = SupervisedPilotFirstSendPreflightService().build(db_session, settings)
    payload = supervised_pilot_first_send_preflight_payload(first)
    dumped = json.dumps(payload)

    assert first.total_candidate_count == go_no_go.total_candidate_count
    assert first.total_candidate_count >= 2
    assert first.settings_request_count == go_no_go.settings_request_count
    assert first.approval_packet_count == go_no_go.approval_packet_count
    assert first.action_readiness_candidate_count == go_no_go.action_readiness_candidate_count
    assert first.overall_status == go_no_go.overall_status
    assert "preflight_checks" in payload
    assert "abort_criteria" in payload
    assert "failed_safe_assertion_keys" in payload
    _assert_no_execution(payload)
    _assert_no_sensitive_leakage(dumped)
    assert "Family Medicine" not in dumped
    assert _strip_volatile(supervised_pilot_first_send_preflight_payload(first)) == (
        _strip_volatile(supervised_pilot_first_send_preflight_payload(second))
    )
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert settings.outbound_enabled is False
    assert first.local_git.git_provider_called is False
    assert first.local_git.github_actions_called is False


def test_first_send_preflight_is_deterministic_aside_from_timestamps_and_git(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    first = SupervisedPilotFirstSendPreflightService().build(db_session, settings)
    second = SupervisedPilotFirstSendPreflightService().build(db_session, settings)
    assert first.generated_at != datetime(1999, 1, 1, tzinfo=UTC)
    assert _strip_volatile(supervised_pilot_first_send_preflight_payload(first)) == (
        _strip_volatile(supervised_pilot_first_send_preflight_payload(second))
    )
    assert first.packet_kind == "supervised_pilot_first_send_preflight"
    assert first.purpose == "manual_owner_supervised_pilot_first_send_preflight_review_only"
    assert first.cli_command == CLI_COMMAND
    assert first.http_route == HTTP_ROUTE


def test_cli_supervised_pilot_first_send_preflight_json_is_sanitized(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(voice_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    _seed_plans_and_packets(db_session)
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="supervised-pilot-first-send-preflight-cli",
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

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)

    first_code = main(["supervised-pilot-first-send-preflight", "--json"])
    first_output = capsys.readouterr().out
    second_code = main(["supervised-pilot-first-send-preflight", "--json"])
    second_output = capsys.readouterr().out
    payload = _json_from_cli(first_output)

    assert first_code == 0
    assert second_code == 0
    _assert_no_execution(payload)
    assert _strip_volatile(_json_from_cli(first_output)) == _strip_volatile(
        _json_from_cli(second_output)
    )
    assert payload["outbound_enabled"] is False
    assert payload["first_send_allowed"] is False
    assert "preflight_checks" in payload
    assert "abort_criteria" in payload
    assert "local_git" in payload
    _assert_no_sensitive_leakage(first_output)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False


def test_cli_supervised_pilot_first_send_preflight_markdown_is_sanitized(
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

    markdown = format_supervised_pilot_first_send_preflight(
        SupervisedPilotFirstSendPreflightService().build(db_session, settings),
        as_json=False,
    )
    json_text = format_supervised_pilot_first_send_preflight(
        SupervisedPilotFirstSendPreflightService().build(db_session, settings),
        as_json=True,
    )
    code = main(["supervised-pilot-first-send-preflight"])
    output = capsys.readouterr().out

    assert code == 0
    assert "# Supervised pilot first-send preflight" in output
    assert "go_live_permitted: false" in output
    assert "execution_allowed: false" in output
    assert "first_send_allowed: false" in output
    assert "first_send_executed: 0" in output
    assert "no_outbound: true" in output
    assert "no_provider_calls: true" in output
    assert "no_spend: true" in output
    assert "supervised_pilot_first_send_preflight_is_not_go_live: true" in output
    assert "first_send_preflight_is_not_a_send: true" in output
    assert "export_is_not_permission_to_go_live: true" in output
    assert "OUTBOUND_ENABLED=false" in output
    assert "## Live-blocking flags" in output
    assert "## First-send scope recommendation" in output
    assert "## First-send preflight checks" in output
    assert "## Abort and stop conditions" in output
    assert "## Owner next actions" in output
    assert "cli_command: supervised-pilot-first-send-preflight" in output
    assert "http_route: /internal/supervised-pilot-first-send-preflight" in output
    assert "source_go_no_go_command: supervised-pilot-go-no-go" in output
    assert "source_pilot_plan_command: supervised-pilot-plan" in output
    _assert_no_sensitive_leakage(output)
    _assert_no_sensitive_leakage(markdown)
    _assert_no_sensitive_leakage(json_text)
    assert read_operator_halt(db_session) is HaltStatus.HALTED
