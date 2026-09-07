from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.decision_makers import candidate
from tests.test_contact_enrichment_service import _org, _service
from tests.test_contact_validation_service import (
    NPI,
    PRACTICE_NAME,
    PROSPECT_EMAIL,
    PROSPECT_NAME,
    PROSPECT_PHONE,
    SECRET_VALUE,
)
from tests.test_dashboard_service import PHI_SNIPPET
from tests.test_launch_readiness_service import _assert_no_leakage
from vyro_growth.cli import main
from vyro_growth.config import Settings
from vyro_growth.domain import ContactVerificationStatus, NextActionCode
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    Contact,
    Meeting,
    OutreachMessage,
)
from vyro_growth.services.contact_validation import (
    HTML_ROUTE as CONTACT_VALIDATION_HTML_ROUTE,
)
from vyro_growth.services.contact_validation import (
    PLAN_CLI_COMMAND,
    PLAN_HTTP_ROUTE,
    REPORT_CLI_COMMAND,
    REPORT_HTTP_ROUTE,
    ContactValidationError,
    ContactValidationFilters,
)
from vyro_growth.services.live_provider_setup_checklist import (
    CLI_COMMAND as LIVE_PROVIDER_CLI_COMMAND,
)
from vyro_growth.services.live_provider_setup_checklist import (
    HTTP_ROUTE as LIVE_PROVIDER_HTTP_ROUTE,
)
from vyro_growth.services.live_provider_setup_checklist import LiveProviderSetupChecklistService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.supervised_validation_run_gate import (
    CLI_COMMAND,
    HTTP_ROUTE,
    PACKET_KIND,
    PACKET_PURPOSE,
    SupervisedValidationRunGateOptions,
    SupervisedValidationRunGateService,
    format_supervised_validation_run_gate,
    owner_approval_code_present,
    supervised_validation_run_gate_payload,
)
from vyro_growth.services.supervised_validation_run_packet import (
    CLI_COMMAND as VALIDATION_PACKET_CLI_COMMAND,
)
from vyro_growth.services.supervised_validation_run_packet import (
    HTTP_ROUTE as VALIDATION_PACKET_HTTP_ROUTE,
)
from vyro_growth.services.supervised_validation_run_packet import (
    SupervisedValidationRunPacketService,
)

DB_SECRET_URL = "postgresql+psycopg://vyro:super-db-password@localhost:5432/vyro_growth"
UNSAFE_ERROR = "Traceback (most recent call last): secret=sk-live-error-token"
OWNER_CODE = "owner-review-code-phase77"
VOLATILE_KEYS = {
    "generated_at",
    "current_sha",
    "current_branch",
    "working_tree_status",
    "available",
}


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _row_counts(db: Session) -> dict[str, int]:
    return {
        "activities": int(db.scalar(select(func.count()).select_from(Activity)) or 0),
        "contacts": int(db.scalar(select(func.count()).select_from(Contact)) or 0),
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
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
    assert payload["dry_run_only"] is True
    assert payload["no_execution"] is True
    assert payload["no_outbound"] is True
    assert payload["no_provider_calls"] is True
    assert payload["no_send"] is True
    assert payload["no_call"] is True
    assert payload["no_book"] is True
    assert payload["no_spend"] is True
    assert payload["no_deploy"] is True
    assert payload["no_autodial"] is True
    assert payload["no_ai_voice"] is True
    assert payload["manual_review_only"] is True
    assert payload["outbound_attempted"] is False
    assert payload["live_call_attempted"] is False
    assert payload["live_provider_calls_attempted"] is False
    assert payload["smtp_attempted"] is False
    assert payload["autodial_attempted"] is False
    assert payload["campaign_enrolled"] is False
    assert payload["booking_attempted"] is False
    assert payload["meet_link_created"] is False
    assert payload["ads_launched"] is False
    assert payload["execution_allowed"] is False
    assert payload["owner_approved"] is False
    assert payload["validation_permitted"] is False
    assert payload["spend_attempted"] is False
    assert payload["campaign_launched"] is False
    assert payload["halt_changed"] is False
    assert payload["settings_applied"] is False
    assert payload["scoring_thresholds_changed"] is False
    assert payload["outbound_enabled"] is False
    assert payload["supervised_validation_run_permitted"] is False
    assert payload["export_is_not_permission_to_run"] is True
    assert payload["supervised_validation_run_gate_is_not_execution"] is True
    assert payload["live_provider_setup_checklist_is_not_go_live"] is True
    assert payload["supervised_validation_run_packet_is_not_execution"] is True
    assert payload["contact_validation_is_not_outbound"] is True
    assert payload["contact_validation_is_not_live_send"] is True
    assert payload["credential_values_included"] is False
    assert payload["owner_approval_code_exported"] is False
    assert payload["run_executed"] is False
    assert payload["run_refused"] is True
    assert payload["gate_passed"] is False
    assert payload["overall_status"] == "blocked"
    assert payload["packet_kind"] == PACKET_KIND
    assert payload["purpose"] == PACKET_PURPOSE
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE
    assert payload["source_live_provider_command"] == LIVE_PROVIDER_CLI_COMMAND
    assert payload["source_live_provider_route"] == LIVE_PROVIDER_HTTP_ROUTE
    assert payload["source_validation_packet_command"] == VALIDATION_PACKET_CLI_COMMAND
    assert payload["source_validation_packet_route"] == VALIDATION_PACKET_HTTP_ROUTE
    assert payload["source_plan_command"] == PLAN_CLI_COMMAND
    assert payload["source_plan_route"] == PLAN_HTTP_ROUTE
    assert payload["source_report_command"] == REPORT_CLI_COMMAND
    assert payload["source_report_route"] == REPORT_HTTP_ROUTE
    assert payload["source_html_route"] == CONTACT_VALIDATION_HTML_ROUTE
    assert all(item["granted"] is False for item in payload["required_owner_decisions"])
    assert "this_phase_does_not_execute" in payload["refusal_reason_codes"]


def _assert_no_sensitive_output(text: str) -> None:
    lowered = text.lower()
    _assert_no_leakage(text, SECRET_VALUE, DB_SECRET_URL)
    assert PHI_SNIPPET not in text
    assert PROSPECT_EMAIL not in text
    assert PROSPECT_PHONE not in text
    assert PROSPECT_NAME not in text
    assert PRACTICE_NAME not in text
    assert NPI not in text
    assert UNSAFE_ERROR not in text
    assert OWNER_CODE not in text
    assert "sk-" not in lowered
    assert "austin family" not in lowered
    assert "512-555-0199" not in text
    assert "super-db-password" not in text


def test_empty_gate_reuses_sources_and_refuses_by_default(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _row_counts(db_session)
    settings = _settings()
    before_halt = read_operator_halt(db_session)
    checklist = LiveProviderSetupChecklistService().build(db_session, settings)
    packet = SupervisedValidationRunPacketService().build(db_session, settings)

    gate = SupervisedValidationRunGateService().evaluate(db_session, settings)
    payload = supervised_validation_run_gate_payload(gate)
    rendered = format_supervised_validation_run_gate(gate, as_json=True)

    _assert_no_execution(payload)
    assert gate.source_live_provider_overall_status == checklist.overall_status
    assert gate.source_validation_packet_overall_status == packet.overall_status
    assert gate.operator_halt_unchanged is True
    assert gate.operator_halt_before == HaltStatus.HALTED.value
    assert gate.operator_halt_after == HaltStatus.HALTED.value
    assert gate.outbound_enabled is False
    assert gate.owner_approved is False
    assert gate.validation_permitted is False
    assert gate.supervised_validation_run_permitted is False
    assert gate.requested_mode == "dry_run"
    assert gate.max_cohort_size == 200
    assert {item.code for item in gate.gates} >= {
        "this_phase_does_not_execute",
        "explicit_owner_approval",
        "max_cohort_size",
        "one_target_state",
        "one_target_specialty",
        "credential_readiness",
        "suppression_opt_out_prerequisites",
        "outbound_disabled",
        "operator_halt_safeguard",
        "live_provider_flags_closed",
        "no_sending_during_enrichment_validation",
    }
    assert "this_phase_does_not_execute" in gate.refusal_reason_codes
    assert "explicit_owner_approval" in gate.refusal_reason_codes
    assert "one_target_state" in gate.refusal_reason_codes
    assert "one_target_specialty" in gate.refusal_reason_codes
    assert {item.code for item in gate.compliance_prerequisites} >= {
        "suppression_controls",
        "opt_out_unsubscribe",
    }
    assert {item.code for item in gate.validation_run_constraints} == {
        "max_practices",
        "one_target_state",
        "one_target_specialty",
        "no_sending_during_enrichment_validation",
    }
    codes = {action.code for action in gate.next_actions}
    assert NextActionCode.SUPERVISED_VALIDATION_RUN_GATE_IS_NOT_EXECUTION.value in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    assert CLI_COMMAND in gate.related_commands
    assert HTTP_ROUTE in gate.related_routes
    assert read_operator_halt(db_session) is before_halt
    assert _row_counts(db_session) == before
    _assert_no_sensitive_output(rendered)
    assert "email" not in payload
    assert "phone" not in payload
    assert "npi" not in payload


def test_configured_segment_and_owner_code_still_refuse_execution(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(
        decision_maker_api_key="present-key",
        email_verification_api_key="present-key",
        internal_api_key="present-key",
    )
    before = _row_counts(db_session)
    before_halt = read_operator_halt(db_session)
    filters = ContactValidationFilters(state="TX", specialty="Family Medicine", max_cohort_size=200)
    options = SupervisedValidationRunGateOptions(
        dry_run=True,
        execute_requested=False,
        owner_approval_code_present=owner_approval_code_present(OWNER_CODE),
        confirm_operator_halt_unchanged=True,
    )

    gate = SupervisedValidationRunGateService().evaluate(db_session, settings, filters, options)
    payload = supervised_validation_run_gate_payload(gate)

    _assert_no_execution(payload)
    assert gate.segment_state == "TX"
    assert gate.segment_specialty == "Family Medicine"
    assert gate.max_cohort_size == 200
    assert gate.owner_approval_code_present is True
    assert gate.confirm_operator_halt_unchanged is True
    assert gate.owner_approved is False
    assert gate.supervised_validation_run_permitted is False
    assert gate.gate_passed is False
    by_code = {item.code: item for item in gate.gates}
    assert by_code["one_target_state"].passed is True
    assert by_code["one_target_specialty"].passed is True
    assert by_code["explicit_owner_approval"].passed is True
    assert by_code["this_phase_does_not_execute"].passed is False
    assert by_code["this_phase_does_not_execute"].blocking is True
    assert OWNER_CODE not in json.dumps(payload)
    assert _row_counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt


def test_execute_request_is_refused_without_provider_http_or_writes(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(decision_maker_live_enabled=True, decision_maker_api_key=SECRET_VALUE)
    before = _row_counts(db_session)
    before_halt = read_operator_halt(db_session)

    def _forbid_http(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("live provider HTTP is forbidden")

    monkeypatch.setattr(httpx, "Client", _forbid_http)
    monkeypatch.setattr(httpx, "AsyncClient", _forbid_http)

    gate = SupervisedValidationRunGateService().evaluate(
        db_session,
        settings,
        ContactValidationFilters(state="TX", specialty="Family Medicine"),
        SupervisedValidationRunGateOptions(
            dry_run=False,
            execute_requested=True,
            owner_approval_code_present=True,
            confirm_operator_halt_unchanged=True,
        ),
    )
    payload = supervised_validation_run_gate_payload(gate)

    _assert_no_execution(payload)
    assert gate.execute_requested is True
    assert gate.requested_mode == "execute_requested"
    assert gate.run_requested is True
    assert gate.run_executed is False
    assert gate.run_refused is True
    assert "execute_requested_refused_in_this_phase" in gate.refusal_reason_codes
    assert "live_provider_flags_closed" in gate.refusal_reason_codes
    assert gate.live_provider_calls_attempted is False
    assert gate.owner_approved is False
    assert settings.outbound_enabled is False
    assert _row_counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt


def test_gate_does_not_leak_prospect_details_or_secret_values(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    _service(
        [
            candidate(
                full_name=PROSPECT_NAME,
                title="Practice Manager",
                business_email=PROSPECT_EMAIL,
                business_phone=PROSPECT_PHONE,
                verification_status=ContactVerificationStatus.PROVIDER_VERIFIED,
            )
        ]
    ).enrich_organization(db_session, organization.id)
    settings = _settings(
        openai_api_key=SECRET_VALUE,
        decision_maker_api_key=SECRET_VALUE,
        email_verification_api_key=SECRET_VALUE,
        database_url=DB_SECRET_URL,
    )
    before = _row_counts(db_session)
    before_halt = read_operator_halt(db_session)

    gate = SupervisedValidationRunGateService().evaluate(
        db_session,
        settings,
        ContactValidationFilters(state="TX", specialty="Family Medicine"),
        SupervisedValidationRunGateOptions(
            owner_approval_code_present=owner_approval_code_present(OWNER_CODE)
        ),
    )
    payload = supervised_validation_run_gate_payload(gate)
    dumped = json.dumps(payload)
    markdown = format_supervised_validation_run_gate(gate)

    _assert_no_execution(payload)
    _assert_no_sensitive_output(dumped)
    _assert_no_sensitive_output(markdown)
    assert SECRET_VALUE not in dumped
    assert DB_SECRET_URL not in dumped
    assert OWNER_CODE not in dumped
    assert OWNER_CODE not in markdown
    assert any(
        item.name == "DECISION_MAKER_API_KEY" and item.present is True
        for item in gate.required_credentials
    )
    assert _row_counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert settings.outbound_enabled is False


def test_gate_is_deterministic_aside_from_timestamps_and_git(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    first = SupervisedValidationRunGateService().evaluate(db_session, settings)
    second = SupervisedValidationRunGateService().evaluate(db_session, settings)
    assert first.generated_at != datetime(1999, 1, 1, tzinfo=UTC)
    assert _strip_volatile(supervised_validation_run_gate_payload(first)) == _strip_volatile(
        supervised_validation_run_gate_payload(second)
    )
    markdown = format_supervised_validation_run_gate(first)
    assert "cli_command: supervised-validation-run" in markdown
    assert "http_route: /internal/supervised-validation-run" in markdown
    assert "Supervised validation run gate" in markdown
    json_text = format_supervised_validation_run_gate(first, as_json=True)
    parsed = json.loads(json_text)
    assert parsed["packet_kind"] == PACKET_KIND
    assert parsed["cli_command"] == CLI_COMMAND


def test_invalid_cohort_size_is_rejected(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    with pytest.raises(ContactValidationError) as exc:
        SupervisedValidationRunGateService().evaluate(
            db_session,
            _settings(),
            ContactValidationFilters(max_cohort_size=201),
        )
    assert exc.value.code == "invalid_cohort_size"


def test_unsafe_owner_approval_code_is_treated_as_missing() -> None:
    assert owner_approval_code_present(OWNER_CODE) is True
    assert owner_approval_code_present("") is False
    assert owner_approval_code_present(None) is False
    assert owner_approval_code_present("sk-live-secret") is False
    assert owner_approval_code_present("owner@example.com") is False


def test_cli_supervised_validation_run_dry_run_is_sanitized(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(voice_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    before = _row_counts(db_session)
    before_halt = read_operator_halt(db_session)

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    def _forbid_http(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("live provider HTTP is forbidden")

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)
    monkeypatch.setattr(httpx, "Client", _forbid_http)
    monkeypatch.setattr(httpx, "AsyncClient", _forbid_http)

    first_code = main(["supervised-validation-run", "--dry-run", "--json"])
    first_output = capsys.readouterr().out
    second_code = main(["supervised-validation-run", "--json"])
    second_output = capsys.readouterr().out
    payload = _json_from_cli(first_output)
    md_code = main(["supervised-validation-run", "--dry-run"])
    markdown = capsys.readouterr().out

    assert first_code == 0
    assert second_code == 0
    assert md_code == 0
    _assert_no_execution(payload)
    assert _strip_volatile(_json_from_cli(first_output)) == _strip_volatile(
        _json_from_cli(second_output)
    )
    assert payload["requested_mode"] == "dry_run"
    assert payload["execute_requested"] is False
    _assert_no_sensitive_output(first_output)
    _assert_no_sensitive_output(markdown)
    assert "cli_command: supervised-validation-run" in markdown
    assert _row_counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt


def test_cli_execute_exits_nonzero_and_does_not_run(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    before = _row_counts(db_session)
    before_halt = read_operator_halt(db_session)

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    def _forbid_http(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("live provider HTTP is forbidden")

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)
    monkeypatch.setattr(httpx, "Client", _forbid_http)
    monkeypatch.setattr(httpx, "AsyncClient", _forbid_http)

    code = main(
        [
            "supervised-validation-run",
            "--execute",
            "--json",
            "--state",
            "TX",
            "--specialty",
            "Family Medicine",
            "--max-cohort-size",
            "200",
            "--owner-approval-code",
            OWNER_CODE,
            "--confirm-operator-halt-unchanged",
        ]
    )
    output = capsys.readouterr().out
    payload = _json_from_cli(output)

    assert code == 1
    _assert_no_execution(payload)
    assert payload["execute_requested"] is True
    assert payload["run_executed"] is False
    assert payload["owner_approved"] is False
    assert payload["owner_approval_code_present"] is True
    assert OWNER_CODE not in output
    assert SECRET_VALUE not in output
    assert _row_counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
