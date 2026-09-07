from __future__ import annotations

import json
from pathlib import Path

import httpx
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
    _add_fact,
    _counts,
)
from tests.test_dashboard_service import PHI_SNIPPET
from tests.test_launch_readiness_service import _assert_no_leakage
from vyro_growth.cli import main
from vyro_growth.config import Settings
from vyro_growth.domain import ContactVerificationStatus, WebsiteFactType
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    Contact,
    ContactDiscoveryCall,
    EnrichmentRun,
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
    ContactValidationService,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.supervised_validation_run_packet import (
    CLI_COMMAND,
    HTML_ROUTE,
    HTTP_ROUTE,
    PACKET_KIND,
    PACKET_PURPOSE,
    SupervisedValidationRunPacketService,
    format_supervised_validation_run_packet,
    supervised_validation_run_packet_payload,
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
        "phone": int(db.scalar(select(func.count()).select_from(ContactDiscoveryCall)) or 0),
        "runs": int(db.scalar(select(func.count()).select_from(EnrichmentRun)) or 0),
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
    return json.loads(output.strip().splitlines()[-1])


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
    assert payload["spend_attempted"] is False
    assert payload["campaign_launched"] is False
    assert payload["halt_changed"] is False
    assert payload["settings_applied"] is False
    assert payload["scoring_thresholds_changed"] is False
    assert payload["outbound_enabled"] is False
    assert payload["supervised_validation_run_permitted"] is False
    assert payload["export_is_not_permission_to_run"] is True
    assert payload["supervised_validation_run_packet_is_not_execution"] is True
    assert payload["contact_validation_is_not_outbound"] is True
    assert payload["contact_validation_is_not_live_send"] is True
    assert payload["packet_kind"] == PACKET_KIND
    assert payload["purpose"] == PACKET_PURPOSE
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE
    assert payload["html_route"] == HTML_ROUTE
    assert payload["source_plan_command"] == PLAN_CLI_COMMAND
    assert payload["source_plan_route"] == PLAN_HTTP_ROUTE
    assert payload["source_report_command"] == REPORT_CLI_COMMAND
    assert payload["source_report_route"] == REPORT_HTTP_ROUTE
    assert payload["source_html_route"] == CONTACT_VALIDATION_HTML_ROUTE
    assert all(item["granted"] is False for item in payload["required_owner_decisions"])
    assert all(stage["executed"] is False for stage in payload["planned_stages"])
    assert all(stage["live_provider_called"] is False for stage in payload["planned_stages"])


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


def test_empty_packet_reuses_phase_71_and_does_not_permit_the_run(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _row_counts(db_session)
    settings = _settings()
    report = ContactValidationService().build_report(db_session, settings)
    before_halt = read_operator_halt(db_session)

    packet = SupervisedValidationRunPacketService().build(db_session, settings)
    payload = supervised_validation_run_packet_payload(packet)
    rendered = format_supervised_validation_run_packet(packet, as_json=True)

    _assert_no_execution(payload)
    assert packet.overall_status == report.overall_status
    assert packet.source_report_overall_status == report.overall_status
    assert packet.funnel.organizations_considered == report.organizations_considered
    assert packet.funnel.no_contact_found_count == report.no_contact_found_count
    assert packet.no_contact_found_is_normal_outcome is True
    assert packet.no_contact_found_is_failure is False
    assert packet.no_verified_email_is_normal_outcome is True
    assert packet.no_verified_email_is_failure is False
    assert packet.operator_halt_unchanged is True
    assert packet.operator_halt_before == HaltStatus.HALTED.value
    assert packet.operator_halt_after == HaltStatus.HALTED.value
    assert packet.max_cohort_size == 200
    assert packet.planned_cohort_size == 200
    assert {item.code for item in packet.prerequisites} >= {
        "keep_outbound_disabled",
        "later_owner_approval_required_before_supervised_run",
        "supervised_validation_run_not_permitted",
        "no_contact_found_is_normal_outcome",
        "no_verified_email_is_normal_outcome",
        "review_operator_contact_validation_ui",
        "review_operator_supervised_validation_run_packet_ui",
    }
    assert {item.code for item in packet.required_owner_decisions} >= {
        "permit_supervised_validation_run",
        "enable_outbound",
        "lift_operator_halt",
    }
    assert any(item.name == "DECISION_MAKER_API_KEY" for item in packet.required_credentials)
    assert {item.name for item in packet.required_configs} == {
        "OUTBOUND_ENABLED",
        "DECISION_MAKER_LIVE_ENABLED",
        "EMAIL_VERIFICATION_LIVE_ENABLED",
        "EMAIL_VERIFICATION_SMTP_ENABLED",
    }
    assert any(
        item.name == "OUTBOUND_ENABLED" and item.present is False
        for item in packet.required_configs
    )
    assert packet.blocked_code_count + packet.warning_code_count + packet.info_code_count > 0
    assert HTML_ROUTE in packet.related_routes
    assert CONTACT_VALIDATION_HTML_ROUTE in packet.related_routes
    assert CLI_COMMAND in packet.related_commands
    assert PLAN_CLI_COMMAND in packet.related_commands
    assert read_operator_halt(db_session) is before_halt
    assert _row_counts(db_session) == before
    _assert_no_sensitive_output(rendered)
    assert "email" not in payload
    assert "phone" not in payload
    assert "npi" not in payload


def test_packet_reuses_funnel_counts_without_leaking_prospect_details(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    _add_fact(db_session, organization, WebsiteFactType.STAFF_MEMBER.value)
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
    settings = _settings()
    report = ContactValidationService().build_report(
        db_session,
        settings,
        ContactValidationFilters(state="TX", city="Austin", specialty="Family Medicine"),
    )
    before = _row_counts(db_session)

    packet = SupervisedValidationRunPacketService().build(
        db_session,
        settings,
        ContactValidationFilters(state="TX", city="Austin", specialty="Family Medicine"),
    )
    payload = supervised_validation_run_packet_payload(packet)
    markdown = format_supervised_validation_run_packet(packet)

    assert packet.funnel.organizations_considered == report.organizations_considered
    assert packet.funnel.decision_maker_candidates_found_count == (
        report.decision_maker_candidates_found_count
    )
    assert packet.funnel.verified_email_count == report.verified_email_count
    assert packet.segment_state == "TX"
    assert packet.segment_city == "AUSTIN"
    assert packet.threshold_comparisons == report.threshold_comparisons
    assert all(item.applied_to_live_settings is False for item in packet.owner_review_thresholds)
    assert _row_counts(db_session) == before
    _assert_no_sensitive_output(json.dumps(payload))
    _assert_no_sensitive_output(markdown)
    assert "## Prerequisite checklist" in markdown
    assert "cli_command: supervised-validation-run-packet" in markdown
    assert "http_route: /internal/supervised-validation-run-packet" in markdown
    assert "html_route: /internal/operator-supervised-validation-run-packet" in markdown


def test_packet_source_does_not_call_later_phase_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/supervised_validation_run_packet.py"),
        Path("src/vyro_growth/api/supervised_validation_run_packet.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "linkedin" not in source
    assert "sales navigator" not in source
    assert "apollo" not in source
    assert "hunter" not in source
    assert "neverbounce" not in source
    assert "zerobounce" not in source
    assert "smartlead" not in source
    assert "openai" not in source
    assert "google_calendar" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    assert "smtplib" not in source


def test_output_is_deterministic_except_timestamps_and_git(db_session: Session) -> None:
    _org(db_session)
    settings = _settings()
    first = SupervisedValidationRunPacketService().build(db_session, settings)
    second = SupervisedValidationRunPacketService().build(db_session, settings)
    assert _strip_volatile(supervised_validation_run_packet_payload(first)) == _strip_volatile(
        supervised_validation_run_packet_payload(second)
    )


def test_live_provider_flags_do_not_permit_run_or_call_providers(
    db_session: Session,
    monkeypatch: object,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(decision_maker_live_enabled=True, decision_maker_api_key="placeholder")
    before_halt = read_operator_halt(db_session)

    def _forbid_http(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("live provider HTTP is forbidden")

    monkeypatch.setattr(httpx, "Client", _forbid_http)
    monkeypatch.setattr(httpx, "AsyncClient", _forbid_http)

    packet = SupervisedValidationRunPacketService().build(db_session, settings)
    payload = supervised_validation_run_packet_payload(packet)

    assert packet.overall_status == "blocked"
    assert packet.live_providers["decision_maker"] is True
    assert packet.live_provider_calls_attempted is False
    assert packet.supervised_validation_run_permitted is False
    assert packet.owner_approved is False
    assert packet.outbound_enabled is False
    assert read_operator_halt(db_session) is before_halt
    assert payload["required_configs"]
    assert any(
        item["name"] == "DECISION_MAKER_LIVE_ENABLED" and item["present"] is True
        for item in payload["required_configs"]
    )


def test_invalid_filters_are_rejected_without_side_effects(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)
    before_halt = read_operator_halt(db_session)
    try:
        SupervisedValidationRunPacketService().build(
            db_session,
            _settings(),
            ContactValidationFilters(max_cohort_size=201),
        )
    except ContactValidationError as exc:
        assert exc.code == "invalid_cohort_size"
    else:
        raise AssertionError("expected invalid cohort size")
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt


def test_cli_json_and_markdown_are_sanitized_and_have_no_side_effects(
    db_session: Session,
    monkeypatch: object,
    capsys: object,
) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    _service(
        [
            candidate(
                business_email=PROSPECT_EMAIL,
                verification_status=ContactVerificationStatus.PROVIDER_VERIFIED,
            )
        ]
    ).enrich_organization(db_session, organization.id)
    before = _row_counts(db_session)
    settings = _settings()

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)

    json_code = main(
        ["supervised-validation-run-packet", "--json", "--state", "TX", "--max-cohort-size", "200"]
    )
    json_output = capsys.readouterr().out
    md_code = main(["supervised-validation-run-packet", "--state", "TX"])
    md_output = capsys.readouterr().out
    payload = _json_from_cli(json_output)

    assert json_code == 0
    assert md_code == 0
    _assert_no_execution(payload)
    assert payload["outbound_enabled"] is False
    assert payload["owner_approved"] is False
    assert payload["supervised_validation_run_permitted"] is False
    assert payload["operator_halt_unchanged"] is True
    assert "prerequisites" in payload
    assert "required_owner_decisions" in payload
    assert "required_credentials" in payload
    assert "threshold_comparisons" in payload
    assert _row_counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    _assert_no_sensitive_output(json_output)
    _assert_no_sensitive_output(md_output)
    assert "owner_approved=false" in md_output
    assert "supervised_validation_run_permitted=false" in md_output
