from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyro_growth.cli import build_parser, main
from vyro_growth.config import Settings
from vyro_growth.domain import (
    ActionReadinessStatus,
    ExecutionReadinessStatus,
    LeadStage,
    MessageDirection,
    PersonalizationReadiness,
)
from vyro_growth.models import (
    Activity,
    Campaign,
    CampaignEnrollment,
    Lead,
    Meeting,
    OperatorControl,
    Organization,
    OutreachMessage,
    OwnerApprovalPacket,
    OwnerApprovalPacketDecision,
    PersonalizationDraft,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.smoke_dry_run import (
    SMOKE_CONTACT_EMAIL,
    SMOKE_INBOUND_BODY,
    SMOKE_NPI,
    SMOKE_ORG_NAME,
    SMOKE_VOICE_PHONE,
    SmokeDryRunRefused,
    SmokeDryRunResult,
    SmokeRefusalCode,
    format_smoke_summary,
    isolated_demo_session,
    refuse_unsafe_smoke_run,
    run_smoke_dry_run,
)

UNSAFE_TOKENS = (
    SMOKE_CONTACT_EMAIL,
    SMOKE_INBOUND_BODY,
    SMOKE_VOICE_PHONE,
    "555-010",
    "sk-testsecret",
    "patient diagnosis",
    "Bearer secret",
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"environment": "development", "outbound_enabled": False}
    values.update(overrides)
    return Settings(**values)


def _counts(db: Session) -> dict[str, int]:
    return {
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "outbound_messages": int(
            db.scalar(
                select(func.count())
                .select_from(OutreachMessage)
                .where(OutreachMessage.direction == MessageDirection.OUTBOUND.value)
            )
            or 0
        ),
        "owner_approved_packets": int(
            db.scalar(
                select(func.count())
                .select_from(OwnerApprovalPacket)
                .where(OwnerApprovalPacket.owner_approved.is_(True))
            )
            or 0
        ),
        "owner_approved_decisions": int(
            db.scalar(
                select(func.count())
                .select_from(OwnerApprovalPacketDecision)
                .where(OwnerApprovalPacketDecision.owner_approved.is_(True))
            )
            or 0
        ),
    }


def test_parser_accepts_smoke_dry_run() -> None:
    parser = build_parser()
    args = parser.parse_args(["smoke-dry-run", "--local-only", "--json"])
    demo = parser.parse_args(["smoke-dry-run", "--dev-demo"])

    assert args.command == "smoke-dry-run"
    assert args.local_only is True
    assert args.json is True
    assert demo.dev_demo is True


def test_production_without_local_only_is_refused() -> None:
    with pytest.raises(SmokeDryRunRefused) as exc:
        refuse_unsafe_smoke_run(_settings(environment="production"), local_only=False)

    assert exc.value.code is SmokeRefusalCode.PRODUCTION_ENVIRONMENT
    assert "--local-only" in str(exc.value)


def test_outbound_enabled_is_refused_even_with_local_only() -> None:
    with pytest.raises(SmokeDryRunRefused) as exc:
        refuse_unsafe_smoke_run(
            _settings(outbound_enabled=True),
            local_only=True,
        )

    assert exc.value.code is SmokeRefusalCode.OUTBOUND_ENABLED


def test_live_provider_flag_is_refused() -> None:
    with pytest.raises(SmokeDryRunRefused) as exc:
        refuse_unsafe_smoke_run(
            _settings(voice_live_enabled=True, voice_api_key="placeholder"),
            local_only=True,
        )

    assert exc.value.code is SmokeRefusalCode.LIVE_PROVIDERS_ENABLED


def test_successful_smoke_run_is_dry_run_only(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    result = run_smoke_dry_run(db_session, _settings(), local_only=True)

    assert result.status == "completed"
    assert result.executed == 0
    assert result.live_action is False
    assert result.outbound_attempted is False
    assert result.owner_approved is False
    assert result.dry_run_only is True
    assert result.no_execution is True
    assert result.recommendation_applied is False
    assert result.spend_attempted is False
    assert result.campaign_launched is False
    assert result.pages_published is False
    assert result.ads_launched is False
    assert result.operator_halt_before == HaltStatus.HALTED.value
    assert result.operator_halt_after == HaltStatus.HALTED.value
    assert "execution_disabled_in_this_phase" in result.blocker_codes
    assert result.counts["execution_plans"] >= 1
    assert result.counts["approval_packets"] >= 1
    assert result.counts["action_readiness_candidates"] >= 1
    assert result.action_readiness["live_action"] is False
    assert result.action_readiness["executed"] == 0
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    after = _counts(db_session)
    assert after["outbound_messages"] == 0
    assert after["owner_approved_packets"] == 0
    assert after["owner_approved_decisions"] == 0
    lead = db_session.scalar(select(Lead))
    assert lead is not None
    assert lead.stage != LeadStage.MEETING_BOOKED.value
    enrollment = db_session.scalar(select(CampaignEnrollment))
    assert enrollment is None or enrollment.status != "enrolled"
    campaign = db_session.scalar(select(Campaign).where(Campaign.name == "phase-25-dry-run"))
    if campaign is not None:
        assert campaign.active is False
        assert campaign.dry_run_only is True
    draft = db_session.scalar(select(PersonalizationDraft))
    assert draft is None or draft.readiness_status == PersonalizationReadiness.READY.value
    meeting = db_session.scalar(select(Meeting))
    assert meeting is None
    assert (
        db_session.scalar(select(Activity).where(Activity.action == "smoke_dry_run_completed"))
        is not None
    )


def test_readiness_summary_reports_blocked_statuses(db_session: Session) -> None:
    result = run_smoke_dry_run(db_session, _settings(), local_only=True)

    assert result.blocker_codes
    assert "execution_disabled_in_this_phase" in result.blocker_codes
    assert result.steps["execution_plans"]["executed"] == 0
    assert ExecutionReadinessStatus.BLOCKED.value in result.steps["execution_plans"]["readiness"]
    assert result.action_readiness["explicit_live_owner_action_required"] is True
    assert result.live_action is False
    readiness_keys = set(result.readiness_statuses)
    allowed = {item.value for item in ActionReadinessStatus}
    assert readiness_keys <= allowed


def test_output_sanitization_redacts_unsafe_values(db_session: Session) -> None:
    result = run_smoke_dry_run(db_session, _settings(), local_only=True)
    text = format_smoke_summary(result, as_json=False)
    payload = format_smoke_summary(result, as_json=True)

    for token in UNSAFE_TOKENS:
        assert token not in text
        assert token not in payload
    assert SMOKE_ORG_NAME not in text
    assert SMOKE_ORG_NAME not in payload
    parsed = json.loads(payload)
    assert parsed["executed"] == 0
    assert parsed["live_action"] is False
    assert parsed["outbound_attempted"] is False
    assert "practice_summary" not in payload
    assert "opening_line" not in payload
    assert "evidence_snippet" not in payload
    assert isinstance(result, SmokeDryRunResult)


def test_no_side_effects_on_halt_outbound_or_live_flags(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="runtime-halt")
    settings = _settings()

    result = run_smoke_dry_run(db_session, settings, local_only=True)

    assert settings.outbound_enabled is False
    assert result.outbound_enabled is False
    assert result.live_providers_enabled is False
    assert all(flag is False for flag in result.live_providers.values())
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    control = db_session.get(OperatorControl, "global")
    assert control is not None
    assert control.outbound_halted is True
    assert control.reason == "runtime-halt"
    org = db_session.scalar(select(Organization).where(Organization.npi == SMOKE_NPI))
    assert org is not None
    inbound = db_session.scalar(
        select(OutreachMessage).where(OutreachMessage.direction == MessageDirection.INBOUND.value)
    )
    assert inbound is not None
    assert (
        db_session.scalar(
            select(OutreachMessage).where(
                OutreachMessage.direction == MessageDirection.OUTBOUND.value
            )
        )
        is None
    )


def test_cli_smoke_dry_run_uses_isolated_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = {"session_local": False}

    class Boom:
        def __call__(self) -> None:
            called["session_local"] = True
            raise AssertionError("smoke-dry-run must not use SessionLocal")

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", Boom())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: _settings())

    exit_code = main(["smoke-dry-run", "--local-only"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert called["session_local"] is False
    assert "executed=0" in captured.out
    assert "live_action=false" in captured.out
    assert "outbound_attempted=false" in captured.out
    assert "dry_run_only=true" in captured.out
    for token in UNSAFE_TOKENS:
        assert token not in captured.out
        assert token not in captured.err


def test_cli_production_refusal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "vyro_growth.cli.get_settings",
        lambda: _settings(environment="production", internal_api_key="internal-secret"),
    )

    exit_code = main(["smoke-dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "production/live environment" in captured.err
    assert captured.out == ""


def test_cli_production_with_local_only_still_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "vyro_growth.cli.get_settings",
        lambda: _settings(environment="production", internal_api_key="internal-secret"),
    )

    exit_code = main(["smoke-dry-run", "--dev-demo", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["executed"] == 0
    assert payload["live_action"] is False
    assert payload["outbound_attempted"] is False
    assert payload["isolated_demo_database"] is True
    assert payload["local_only"] is True


def test_cli_live_outbound_refusal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "vyro_growth.cli.get_settings",
        lambda: _settings(outbound_enabled=True),
    )

    exit_code = main(["smoke-dry-run", "--local-only"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "OUTBOUND_ENABLED" in captured.err


def test_isolated_demo_session_does_not_share_state(db_session: Session) -> None:
    run_smoke_dry_run(db_session, _settings(), local_only=True)
    with isolated_demo_session() as isolated:
        assert isolated.scalar(select(Organization)) is None
        result = run_smoke_dry_run(
            isolated,
            _settings(),
            local_only=True,
            isolated_demo_database=True,
        )
        assert result.isolated_demo_database is True
        assert result.executed == 0


def test_smoke_source_does_not_call_live_providers() -> None:
    source = Path("src/vyro_growth/services/smoke_dry_run.py").read_text(encoding="utf-8").lower()
    forbidden = (
        "httpx",
        "openai",
        "smartlead",
        "google.calendar",
        "google_calendar",
        "apollo",
        "nppes_client",
        "twilio",
        "vapi",
        "retell",
        "firecrawl",
    )
    for token in forbidden:
        assert token not in source, token
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example
