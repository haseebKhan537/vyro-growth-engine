from __future__ import annotations

import json
from copy import deepcopy

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_action_readiness_service import _seed_plans_and_packets
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from tests.test_monitoring_service import UNSAFE_ERROR
from vyro_growth.cli import main
from vyro_growth.config import Settings
from vyro_growth.domain import (
    NextActionCode,
    SecretName,
    SettingsChangeRequestType,
)
from vyro_growth.models import (
    Activity,
    Campaign,
    CampaignEnrollment,
    LiveSettingsChangeRequest,
    LiveSettingsChangeRequestDecision,
    Meeting,
    OutreachMessage,
    OwnerApprovalPacket,
    OwnerApprovalPacketDecision,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.owner_handoff import (
    OwnerHandoffPacketService,
    format_owner_handoff,
    handoff_payload,
)
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

DB_SECRET_URL = "postgresql+psycopg://vyro:super-db-password@localhost:5432/vyro_growth"


def _json_from_cli(output: str) -> dict[str, object]:
    start = output.find("{")
    assert start != -1
    payload = json.loads(output[start:])
    assert isinstance(payload, dict)
    return payload


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _counts(db: Session) -> dict[str, int]:
    return {
        "activities": int(db.scalar(select(func.count()).select_from(Activity)) or 0),
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
        "packets": int(db.scalar(select(func.count()).select_from(OwnerApprovalPacket)) or 0),
        "packet_decisions": int(
            db.scalar(select(func.count()).select_from(OwnerApprovalPacketDecision)) or 0
        ),
        "campaigns": int(db.scalar(select(func.count()).select_from(Campaign)) or 0),
        "requests": int(
            db.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) or 0
        ),
        "decisions": int(
            db.scalar(select(func.count()).select_from(LiveSettingsChangeRequestDecision)) or 0
        ),
    }


def _flags(settings: Settings) -> dict[str, bool]:
    return {
        "outbound_enabled": settings.outbound_enabled,
        "openai_personalization_enabled": settings.openai_personalization_enabled,
        "smartlead_live_enabled": settings.smartlead_live_enabled,
        "openai_reply_classification_enabled": settings.openai_reply_classification_enabled,
        "google_calendar_live_enabled": settings.google_calendar_live_enabled,
        "voice_live_enabled": settings.voice_live_enabled,
        "outbound_halted": settings.outbound_halted,
    }


def _without_timestamps(payload: dict[str, object]) -> dict[str, object]:
    cloned = deepcopy(payload)
    cloned.pop("generated_at", None)

    def _strip(value: object) -> object:
        if isinstance(value, dict):
            row = {
                key: _strip(item)
                for key, item in value.items()
                if key not in {"generated_at", "requested_at", "simulated_at"}
            }
            return row
        if isinstance(value, list):
            return [_strip(item) for item in value]
        return value

    return _strip(cloned)  # type: ignore[return-value]


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
    assert payload["go_live_permitted"] is False
    assert payload["manual_review_only"] is True
    assert payload["packet_kind"] == "owner_go_live_handoff"
    assert payload["purpose"] == "manual_owner_review_only"


def test_empty_handoff_is_read_only_without_side_effects(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    before_flags = _flags(settings)
    before = _counts(db_session)

    packet = OwnerHandoffPacketService().build(db_session, settings)
    text = format_owner_handoff(packet, as_json=True)
    markdown = format_owner_handoff(packet, as_json=False)
    payload = json.loads(text)

    assert packet.overall_status in {"blocked", "warning", "ready_for_owner_review"}
    assert packet.go_live_permitted is False
    assert packet.execution_allowed is False
    assert packet.settings_applied is False
    assert packet.halt_changed is False
    assert packet.owner_approved is False
    assert packet.live_action is False
    assert packet.outbound_enabled is False
    assert packet.launch_readiness.no_execution is True
    assert packet.settings_change_requests.request_count == 0
    assert packet.settings_execution_preflight.executable_count == 0
    assert packet.owner_approval_packets.packet_count == 0
    assert packet.approved_action_readiness.candidate_count == 0
    codes = {item.code for item in packet.remaining_manual_owner_checklist}
    assert NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.INSPECT_OPERATOR_AUDIT_TIMELINE.value in codes
    assert "execution_disabled_in_this_phase" in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    assert "/internal/operator-audit-timeline" in markdown
    assert "/internal/operator-compliance-evidence-binder" in markdown
    assert "/internal/operator-release-candidate-runbook" in markdown
    assert "/internal/release-artifact-manifest" in markdown
    assert "## Launch readiness summary" in markdown
    assert "## Settings change request summary" in markdown
    assert "## Settings execution preflight summary" in markdown
    assert "## Owner approval packet summary" in markdown
    assert "## Approved action readiness summary" in markdown
    assert "## Remaining manual owner checklist" in markdown
    assert "not permission or machinery for going live" in markdown
    _assert_no_execution(payload)
    assert _counts(db_session) == before
    assert _flags(settings) == before_flags
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    _assert_no_leakage(text)
    _assert_no_leakage(markdown)


def test_handoff_consolidates_existing_safe_summaries(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE)
    _seed_plans_and_packets(db_session)
    service = SettingsChangeRequestService()
    pending = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="handoff-pending",
        reviewer_notes=f"record only {PHI_SNIPPET}",
    )
    approved = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        desired_boolean=True,
        idempotency_key="handoff-approved",
    )
    service.record_decision(
        db_session,
        settings,
        request_id=approved.request_id,
        decision="approved",
        reviewer="owner",
            reviewer_notes=PHI_SNIPPET,
    )
    before = _counts(db_session)
    before_flags = _flags(settings)

    packet = OwnerHandoffPacketService().build(db_session, settings)
    text = format_owner_handoff(packet, as_json=True)
    markdown = format_owner_handoff(packet, as_json=False)

    assert packet.settings_change_requests.request_count == 2
    assert packet.settings_change_requests.pending_count == 1
    assert packet.settings_change_requests.approved_count == 1
    assert str(pending.request_id) in packet.settings_change_requests.request_ids
    assert str(approved.request_id) in packet.settings_change_requests.request_ids
    assert "OUTBOUND_ENABLED" in packet.settings_change_requests.setting_names
    assert packet.settings_execution_preflight.request_count == 2
    assert packet.settings_execution_preflight.execution_allowed is False
    assert packet.owner_approval_packets.packet_count > 0
    assert packet.owner_approval_packets.pending_count == packet.owner_approval_packets.packet_count
    assert packet.approved_action_readiness.candidate_count > 0
    assert packet.approved_action_readiness.candidate_ids
    assert all(
        item.execution_allowed is False
        for item in packet.approved_action_readiness.candidates
    )
    assert all(item.owner_approved is False for item in packet.owner_approval_packets.packets)
    assert SecretName.SMARTLEAD_API_KEY.value in packet.missing_credential_names
    assert "reviewer_notes" not in text
    assert "sanitized_label" not in text
    assert "proposed_action" not in text
    assert "preflight_checklist" not in text
    _assert_no_leakage(text, SECRET_VALUE, DB_SECRET_URL)
    _assert_no_leakage(markdown, SECRET_VALUE)
    assert PROSPECT_EMAIL not in text
    assert PHI_SNIPPET not in text
    assert UNSAFE_ERROR not in text
    assert _counts(db_session) == before
    assert _flags(settings) == before_flags
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False


def test_handoff_is_deterministic_and_idempotent(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="handoff-idempotent",
    )
    builder = OwnerHandoffPacketService()
    before = _counts(db_session)

    one = builder.build(db_session, settings)
    two = builder.build(db_session, settings)
    payload_one = _without_timestamps(handoff_payload(one))
    payload_two = _without_timestamps(handoff_payload(two))

    assert payload_one == payload_two
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False
    assert one.go_live_permitted is False
    assert two.execution_allowed is False


def test_cli_owner_handoff_packet_json_is_sanitized(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)

    code = main(["owner-handoff-packet", "--json"])
    output = capsys.readouterr().out
    payload = _json_from_cli(output)

    assert code == 0
    _assert_no_execution(payload)
    assert payload["outbound_enabled"] is False
    assert "launch_readiness" in payload
    assert "remaining_manual_owner_checklist" in payload
    _assert_no_leakage(output, SECRET_VALUE, DB_SECRET_URL)
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_cli_owner_handoff_packet_markdown_is_sanitized(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE)

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)

    code = main(["owner-handoff-packet"])
    output = capsys.readouterr().out

    assert code == 0
    assert "# Owner go-live handoff packet" in output
    assert "go_live_permitted: false" in output
    assert "execution_allowed: false" in output
    assert "## Remaining manual owner checklist" in output
    _assert_no_leakage(output, SECRET_VALUE)
    assert read_operator_halt(db_session) is HaltStatus.HALTED
