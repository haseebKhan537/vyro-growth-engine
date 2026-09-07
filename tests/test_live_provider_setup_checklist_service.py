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
from vyro_growth.services.compliance_evidence_binder import (
    CLI_COMMAND as BINDER_CLI_COMMAND,
)
from vyro_growth.services.compliance_evidence_binder import (
    HTTP_ROUTE as BINDER_HTTP_ROUTE,
)
from vyro_growth.services.launch_readiness import LaunchReadinessService
from vyro_growth.services.live_provider_setup_checklist import (
    CLI_COMMAND,
    HTTP_ROUTE,
    PACKET_KIND,
    PACKET_PURPOSE,
    PROVIDER_KEYS,
    LiveProviderSetupChecklistService,
    format_live_provider_setup_checklist,
    live_provider_setup_checklist_payload,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.provider_setup_checklist import (
    CLI_COMMAND as PROVIDER_SETUP_CLI_COMMAND,
)
from vyro_growth.services.provider_setup_checklist import (
    HTTP_ROUTE as PROVIDER_SETUP_HTTP_ROUTE,
)
from vyro_growth.services.provider_setup_checklist import ProviderSetupChecklistService
from vyro_growth.services.settings_execution_preflight import SettingsExecutionPreflightService
from vyro_growth.services.supervised_validation_run_packet import (
    CLI_COMMAND as VALIDATION_CLI_COMMAND,
)
from vyro_growth.services.supervised_validation_run_packet import (
    HTTP_ROUTE as VALIDATION_HTTP_ROUTE,
)
from vyro_growth.services.supervised_validation_run_packet import (
    SupervisedValidationRunPacketService,
)

DB_SECRET_URL = "postgresql+psycopg://vyro:super-db-password@localhost:5432/vyro_growth"
UNSAFE_ERROR = "Traceback (most recent call last): secret=sk-live-error-token"
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
    assert payload["no_credential_verification"] is True
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
    assert payload["credential_verification_attempted"] is False
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
    assert payload["live_provider_setup_checklist_is_not_go_live"] is True
    assert payload["checklist_is_not_permission_to_go_live"] is True
    assert payload["checklist_is_not_execution"] is True
    assert payload["credential_values_included"] is False
    assert payload["packet_kind"] == PACKET_KIND
    assert payload["purpose"] == PACKET_PURPOSE
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE
    assert payload["source_provider_setup_command"] == PROVIDER_SETUP_CLI_COMMAND
    assert payload["source_provider_setup_route"] == PROVIDER_SETUP_HTTP_ROUTE
    assert payload["source_launch_readiness_command"] == "launch-readiness"
    assert payload["source_launch_readiness_route"] == "/internal/launch-readiness"
    assert payload["source_validation_packet_command"] == VALIDATION_CLI_COMMAND
    assert payload["source_validation_packet_route"] == VALIDATION_HTTP_ROUTE
    assert payload["source_preflight_command"] == "settings-execution-preflight"
    assert payload["source_preflight_route"] == "/internal/settings-execution-preflight"
    assert payload["source_binder_command"] == BINDER_CLI_COMMAND
    assert payload["source_binder_route"] == BINDER_HTTP_ROUTE
    assert all(item["granted"] is False for item in payload["owner_decisions"])
    assert all(item["live_execution_allowed"] is False for item in payload["provider_accounts"])


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
    assert "sk-" not in lowered
    assert "austin family" not in lowered
    assert "512-555-0199" not in text
    assert "super-db-password" not in text


def test_empty_checklist_reuses_sources_and_does_not_permit_validation(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _row_counts(db_session)
    settings = _settings()
    before_halt = read_operator_halt(db_session)
    launch = LaunchReadinessService().assess(db_session, settings)
    provider_setup = ProviderSetupChecklistService().build(db_session, settings)
    validation = SupervisedValidationRunPacketService().build(db_session, settings)
    preflight = SettingsExecutionPreflightService().simulate(db_session, settings)

    checklist = LiveProviderSetupChecklistService().build(db_session, settings)
    payload = live_provider_setup_checklist_payload(checklist)
    rendered = format_live_provider_setup_checklist(checklist, as_json=True)

    _assert_no_execution(payload)
    assert checklist.source_launch_readiness_overall_status == launch.overall_status
    assert checklist.source_provider_setup_overall_status == provider_setup.overall_status
    assert checklist.source_validation_packet_overall_status == validation.overall_status
    assert checklist.source_preflight_overall_status == preflight.overall_status
    assert checklist.operator_halt_unchanged is True
    assert checklist.operator_halt_before == HaltStatus.HALTED.value
    assert checklist.operator_halt_after == HaltStatus.HALTED.value
    assert checklist.outbound_enabled is False
    assert checklist.owner_approved is False
    assert checklist.validation_permitted is False
    assert checklist.supervised_validation_run_permitted is False
    assert tuple(item.key for item in checklist.provider_accounts) == PROVIDER_KEYS
    assert {item.code for item in checklist.compliance_prerequisites} >= {
        "suppression_controls",
        "opt_out_unsubscribe",
        "no_phi",
        "consent_only_voice",
        "no_linkedin_automation",
        "no_restricted_job_board_scraping",
        "keep_outbound_disabled",
    }
    assert {item.code for item in checklist.validation_run_constraints} == {
        "max_practices",
        "one_target_state",
        "one_target_specialty",
        "no_sending_during_enrichment_validation",
    }
    assert any(item.limit == 200 for item in checklist.validation_run_constraints)
    assert {item.code for item in checklist.owner_decisions} >= {
        "permit_supervised_validation_run",
        "enable_outbound",
        "lift_operator_halt",
        "approve_live_provider_credentials",
    }
    assert any(item.name == "DECISION_MAKER_API_KEY" for item in checklist.required_credentials)
    assert any(item.name == "EMAIL_VERIFICATION_API_KEY" for item in checklist.required_credentials)
    assert any(
        item.name == "OUTBOUND_ENABLED" and item.present is False
        for item in checklist.required_configs
    )
    codes = {action.code for action in checklist.next_actions}
    assert NextActionCode.LIVE_PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    assert CLI_COMMAND in checklist.related_commands
    assert HTTP_ROUTE in checklist.related_routes
    assert VALIDATION_HTTP_ROUTE in checklist.related_routes
    assert read_operator_halt(db_session) is before_halt
    assert _row_counts(db_session) == before
    _assert_no_sensitive_output(rendered)
    assert "email" not in payload
    assert "phone" not in payload
    assert "npi" not in payload


def test_checklist_does_not_leak_prospect_details_or_secret_values(
    db_session: Session,
) -> None:
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

    checklist = LiveProviderSetupChecklistService().build(db_session, settings)
    payload = live_provider_setup_checklist_payload(checklist)
    dumped = json.dumps(payload)
    markdown = format_live_provider_setup_checklist(checklist)

    _assert_no_execution(payload)
    _assert_no_sensitive_output(dumped)
    _assert_no_sensitive_output(markdown)
    assert SECRET_VALUE not in dumped
    assert DB_SECRET_URL not in dumped
    assert any(
        item.name == "DECISION_MAKER_API_KEY" and item.present is True
        for item in checklist.required_credentials
    )
    assert any(
        item.name == "OPENAI_API_KEY" and item.present is True
        for item in checklist.required_credentials
    )
    assert _row_counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert settings.outbound_enabled is False


def test_checklist_is_deterministic_aside_from_timestamps_and_git(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    first = LiveProviderSetupChecklistService().build(db_session, settings)
    second = LiveProviderSetupChecklistService().build(db_session, settings)
    assert first.generated_at != datetime(1999, 1, 1, tzinfo=UTC)
    assert _strip_volatile(live_provider_setup_checklist_payload(first)) == _strip_volatile(
        live_provider_setup_checklist_payload(second)
    )
    markdown = format_live_provider_setup_checklist(first)
    assert "cli_command: live-provider-setup-checklist" in markdown
    assert "http_route: /internal/live-provider-setup-checklist" in markdown
    assert "Owner live-provider setup checklist" in markdown
    json_text = format_live_provider_setup_checklist(first, as_json=True)
    parsed = json.loads(json_text)
    assert parsed["packet_kind"] == PACKET_KIND
    assert parsed["cli_command"] == CLI_COMMAND


def test_cli_live_provider_setup_checklist_json_is_sanitized(
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

    first_code = main(["live-provider-setup-checklist", "--json"])
    first_output = capsys.readouterr().out
    second_code = main(["live-provider-setup-checklist", "--json"])
    second_output = capsys.readouterr().out
    payload = _json_from_cli(first_output)
    md_code = main(["live-provider-setup-checklist"])
    markdown = capsys.readouterr().out

    assert first_code == 0
    assert second_code == 0
    assert md_code == 0
    _assert_no_execution(payload)
    assert _strip_volatile(_json_from_cli(first_output)) == _strip_volatile(
        _json_from_cli(second_output)
    )
    assert payload["outbound_enabled"] is False
    assert payload["owner_approved"] is False
    assert payload["validation_permitted"] is False
    assert "provider_accounts" in payload
    assert "owner_decisions" in payload
    assert "budget_rate_limits" in payload
    assert "compliance_prerequisites" in payload
    assert "validation_run_constraints" in payload
    _assert_no_sensitive_output(first_output)
    _assert_no_sensitive_output(markdown)
    assert "cli_command: live-provider-setup-checklist" in markdown
    assert _row_counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
