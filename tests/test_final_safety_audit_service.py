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
    PROSPECT_PHONE,
    SECRET_VALUE,
)
from tests.test_dashboard_service import PHI_SNIPPET
from tests.test_launch_readiness_service import _assert_no_leakage
from vyro_growth.cli import main
from vyro_growth.config import Settings
from vyro_growth.domain import ContactVerificationStatus
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
    PLAN_CLI_COMMAND,
    REPORT_CLI_COMMAND,
    ContactValidationService,
)
from vyro_growth.services.final_safety_audit import (
    CLI_COMMAND,
    HTTP_ROUTE,
    PACKET_KIND,
    PACKET_PURPOSE,
    FinalSafetyAuditService,
    final_safety_audit_payload,
    format_final_safety_audit,
)
from vyro_growth.services.launch_readiness import LaunchReadinessService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

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
    assert payload["export_only"] is True
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
    assert payload["no_migrations"] is True
    assert payload["no_github_actions"] is True
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
    assert payload["github_actions_called"] is False
    assert payload["git_provider_called"] is False
    assert payload["outbound_enabled"] is False
    assert payload["supervised_validation_run_permitted"] is False
    assert payload["export_is_not_permission_to_validate"] is True
    assert payload["final_safety_audit_is_not_execution"] is True
    assert payload["launch_readiness_is_not_execution"] is True
    assert payload["contact_validation_is_not_outbound"] is True
    assert payload["contact_validation_is_not_live_send"] is True
    assert payload["packet_kind"] == PACKET_KIND
    assert payload["purpose"] == PACKET_PURPOSE
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE
    assert all(item["granted"] is False for item in payload["owner_approvals_required"])
    assert payload["local_git"]["git_provider_called"] is False
    assert payload["local_git"]["github_actions_called"] is False


def _assert_no_sensitive_output(text: str) -> None:
    lowered = text.lower()
    _assert_no_leakage(text, SECRET_VALUE, DB_SECRET_URL)
    assert PHI_SNIPPET not in text
    assert PROSPECT_EMAIL not in text
    assert PROSPECT_PHONE not in text
    assert PRACTICE_NAME not in text
    assert NPI not in text
    assert UNSAFE_ERROR not in text
    assert "sk-" not in lowered
    assert "austin family" not in lowered
    assert "512-555-0199" not in text


def test_empty_audit_reuses_readiness_and_does_not_permit_validation(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _row_counts(db_session)
    settings = _settings()
    readiness = LaunchReadinessService().assess(db_session, settings)
    report = ContactValidationService().build_report(db_session, settings)
    before_halt = read_operator_halt(db_session)

    packet = FinalSafetyAuditService().build(db_session, settings)
    payload = final_safety_audit_payload(packet)
    rendered = format_final_safety_audit(packet, as_json=True)

    _assert_no_execution(payload)
    assert packet.overall_status == readiness.overall_status
    assert packet.source_launch_readiness_overall_status == readiness.overall_status
    assert packet.source_contact_validation_overall_status == report.overall_status
    assert packet.operator_halt_unchanged is True
    assert packet.operator_halt_before == HaltStatus.HALTED.value
    assert packet.operator_halt_after == HaltStatus.HALTED.value
    assert packet.kill_switch_outbound_disabled is True
    assert packet.dual_kill_switch_proof is True
    assert {item.code for item in packet.owner_approvals_required} >= {
        "permit_supervised_validation_run",
        "enable_outbound",
        "lift_operator_halt",
        "deploy_or_publish",
    }
    assert {item.name for item in packet.live_flag_inventory} >= {
        "OUTBOUND_ENABLED",
        "DECISION_MAKER_LIVE_ENABLED",
        "EMAIL_VERIFICATION_LIVE_ENABLED",
    }
    assert any(
        item.name == "OUTBOUND_ENABLED" and item.enabled is False
        for item in packet.live_flag_inventory
    )
    assert any(item.name == CLI_COMMAND for item in packet.commands)
    assert any(item.name == HTTP_ROUTE for item in packet.routes)
    assert any(item.filename.startswith("020_") for item in packet.migrations)
    assert {item.name for item in packet.ci_jobs} == {
        "test",
        "smoke-dry-run",
        "deploy-config",
    }
    assert all(item.present for item in packet.ci_jobs)
    assert packet.ci_smoke_gate_present is True
    assert packet.ci_smoke_gate_documented is True
    assert packet.blocked_code_count + packet.warning_code_count + packet.info_code_count > 0
    assert {item.issue_number for item in packet.open_issues} >= {"P75-001", "P75-008"}
    assert CLI_COMMAND in packet.related_commands
    assert PLAN_CLI_COMMAND in packet.related_commands
    assert REPORT_CLI_COMMAND in packet.related_commands
    assert HTTP_ROUTE in packet.related_routes
    assert read_operator_halt(db_session) is before_halt
    assert _row_counts(db_session) == before
    _assert_no_sensitive_output(rendered)
    assert "email" not in payload
    assert "phone" not in payload
    assert "npi" not in payload


def test_audit_reuses_stored_status_without_leaking_prospect_details(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    _service(
        [
            candidate(
                full_name="Jordan Example",
                title="Practice Manager",
                business_email=PROSPECT_EMAIL,
                business_phone=PROSPECT_PHONE,
                verification_status=ContactVerificationStatus.PROVIDER_VERIFIED,
            )
        ]
    ).enrich_organization(db_session, organization.id)
    settings = _settings()
    readiness = LaunchReadinessService().assess(db_session, settings)
    report = ContactValidationService().build_report(db_session, settings)
    before = _row_counts(db_session)

    packet = FinalSafetyAuditService().build(db_session, settings)
    payload = final_safety_audit_payload(packet)
    markdown = format_final_safety_audit(packet)

    assert packet.overall_status == readiness.overall_status
    assert packet.source_contact_validation_overall_status == report.overall_status
    assert _row_counts(db_session) == before
    _assert_no_sensitive_output(json.dumps(payload))
    _assert_no_sensitive_output(markdown)
    assert "## Kill-switch proof" in markdown
    assert "cli_command: final-safety-audit" in markdown
    assert "http_route: /internal/final-safety-audit" in markdown
    assert "owner_approved=false" in markdown
    assert "supervised_validation_run_permitted=false" in markdown


def test_packet_source_does_not_call_later_phase_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/final_safety_audit.py"),
        Path("src/vyro_growth/api/final_safety_audit.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "from vyro_growth.providers" not in source
    assert "linkedin" not in source
    assert "sales navigator" not in source
    assert "apollo" not in source
    assert "hunter" not in source
    assert "neverbounce" not in source
    assert "zerobounce" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    assert "smtplib" not in source


def test_output_is_deterministic_except_timestamps_and_git(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    _org(db_session)
    settings = _settings()
    first = FinalSafetyAuditService().build(db_session, settings)
    second = FinalSafetyAuditService().build(db_session, settings)
    assert _strip_volatile(final_safety_audit_payload(first)) == _strip_volatile(
        final_safety_audit_payload(second)
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

    packet = FinalSafetyAuditService().build(db_session, settings)
    payload = final_safety_audit_payload(packet)

    assert packet.overall_status == "blocked"
    assert packet.live_providers["decision_maker"] is True
    assert packet.live_provider_calls_attempted is False
    assert packet.supervised_validation_run_permitted is False
    assert packet.owner_approved is False
    assert packet.outbound_enabled is False
    assert read_operator_halt(db_session) is before_halt
    assert any(
        item["name"] == "DECISION_MAKER_LIVE_ENABLED" and item["enabled"] is True
        for item in payload["live_flag_inventory"]
    )


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

    json_code = main(["final-safety-audit", "--json"])
    json_output = capsys.readouterr().out
    md_code = main(["final-safety-audit"])
    md_output = capsys.readouterr().out
    payload = _json_from_cli(json_output)

    assert json_code == 0
    assert md_code == 0
    _assert_no_execution(payload)
    assert payload["outbound_enabled"] is False
    assert payload["owner_approved"] is False
    assert payload["supervised_validation_run_permitted"] is False
    assert payload["operator_halt_unchanged"] is True
    assert "phases" in payload
    assert "commands" in payload
    assert "routes" in payload
    assert "migrations" in payload
    assert "live_flag_inventory" in payload
    assert "owner_approvals_required" in payload
    assert "open_issues" in payload
    assert "documentation_coverage" in payload
    assert _row_counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    _assert_no_sensitive_output(json_output)
    _assert_no_sensitive_output(md_output)
    assert "owner_approved=false" in md_output
    assert "supervised_validation_run_permitted=false" in md_output
