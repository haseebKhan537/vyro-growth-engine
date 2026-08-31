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
    SecretName,
    SettingsChangeDecisionStatus,
    SettingsChangeRequestType,
    SettingsExecutionBlockerCode,
    SettingsExecutionGateCode,
    SettingsExecutionPreflightStatus,
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
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService
from vyro_growth.services.settings_execution_preflight import (
    SettingsExecutionPreflightFilters,
    SettingsExecutionPreflightService,
    format_settings_execution_preflight,
    preflight_payload,
)

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
    requests = cloned.get("requests")
    if isinstance(requests, list):
        stripped: list[object] = []
        for item in requests:
            if isinstance(item, dict):
                row = dict(item)
                row.pop("simulated_at", None)
                row.pop("requested_at", None)
                stripped.append(row)
            else:
                stripped.append(item)
        cloned["requests"] = stripped
    return cloned


def test_empty_preflight_is_blocked_without_side_effects(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    before_flags = _flags(settings)
    before = _counts(db_session)

    result = SettingsExecutionPreflightService().simulate(db_session, settings)
    text = format_settings_execution_preflight(result, as_json=True)

    assert result.overall_status == SettingsExecutionPreflightStatus.BLOCKED.value
    assert result.request_count == 0
    assert result.executable_count == 0
    assert result.executed == 0
    assert result.dry_run_only is True
    assert result.no_execution is True
    assert result.execution_allowed is False
    assert result.future_execution_phase_exists is False
    assert result.settings_applied is False
    assert result.halt_changed is False
    assert result.owner_approved is False
    assert result.live_action is False
    assert result.outbound_enabled is False
    assert (
        SettingsExecutionBlockerCode.EXECUTION_DISABLED_IN_THIS_PHASE.value in result.blocker_codes
    )
    assert SettingsExecutionBlockerCode.OUTBOUND_DISABLED.value in result.blocker_codes
    assert SettingsExecutionBlockerCode.OPERATOR_HALT_ACTIVE.value in result.blocker_codes
    assert SettingsExecutionGateCode.EXECUTION_PHASE_GATE.value in result.missing_gate_codes
    assert SecretName.OPENAI_API_KEY.value in result.missing_credential_names
    assert _counts(db_session) == before
    assert _flags(settings) == before_flags
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    _assert_no_leakage(text)


def test_pending_and_non_approved_decisions_are_reported(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    service = SettingsChangeRequestService()
    pending = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="preflight-pending",
    )
    rejected = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OPERATOR_HALT_REVIEW.value,
        requested_setting_names=["OPERATOR_HALT"],
        idempotency_key="preflight-rejected",
    )
    service.record_decision(
        db_session,
        settings,
        request_id=rejected.request_id,
        decision="rejected",
        reviewer="owner",
    )
    needs_changes = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_SAFE_DEFAULT.value,
        requested_setting_names=["VOICE_LIVE_ENABLED"],
        idempotency_key="preflight-needs-changes",
    )
    service.record_decision(
        db_session,
        settings,
        request_id=needs_changes.request_id,
        decision="needs_changes",
        reviewer="owner",
    )

    result = SettingsExecutionPreflightService().simulate(db_session, settings)
    by_id = {item.request_id: item for item in result.requests}

    assert by_id[pending.request_id].execution_status == (
        SettingsExecutionPreflightStatus.PENDING_DECISION.value
    )
    assert SettingsExecutionBlockerCode.PENDING_DECISION.value in by_id[
        pending.request_id
    ].blocker_codes
    assert by_id[rejected.request_id].execution_status == (
        SettingsExecutionPreflightStatus.DECISION_NOT_APPROVED.value
    )
    assert SettingsExecutionBlockerCode.REJECTED_DECISION.value in by_id[
        rejected.request_id
    ].blocker_codes
    assert by_id[needs_changes.request_id].execution_status == (
        SettingsExecutionPreflightStatus.DECISION_NOT_APPROVED.value
    )
    assert SettingsExecutionBlockerCode.NEEDS_CHANGES_DECISION.value in by_id[
        needs_changes.request_id
    ].blocker_codes
    assert result.executable_count == 0
    assert all(item.execution_allowed is False for item in result.requests)


def test_approved_request_stays_dry_run_and_does_not_apply(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE, smartlead_api_key=SECRET_VALUE)
    before_flags = _flags(settings)
    service = SettingsChangeRequestService()
    created = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="preflight-approved-outbound",
    )
    service.record_decision(
        db_session,
        settings,
        request_id=created.request_id,
        decision="approved",
        reviewer="owner",
        reviewer_notes=f"record only {PHI_SNIPPET}",
    )
    before = _counts(db_session)

    result = SettingsExecutionPreflightService().simulate(db_session, settings)
    text = format_settings_execution_preflight(result, as_json=True)
    plain = format_settings_execution_preflight(result, as_json=False)
    item = result.requests[0]

    assert item.decision_status == SettingsChangeDecisionStatus.APPROVED.value
    assert item.execution_status == SettingsExecutionPreflightStatus.EXECUTION_GATES_CLOSED.value
    assert item.executed is False
    assert item.settings_applied is False
    assert item.owner_approved is False
    assert item.execution_allowed is False
    assert SettingsExecutionBlockerCode.OPERATOR_HALT_ACTIVE.value in item.blocker_codes
    assert SettingsExecutionBlockerCode.OUTBOUND_DISABLED.value in item.blocker_codes
    assert SettingsExecutionBlockerCode.PROVIDER_LIVE_FLAG_FALSE.value in item.blocker_codes
    assert SettingsExecutionBlockerCode.MISSING_EXPLICIT_OWNER_APPROVAL.value in (
        item.missing_approval_codes
    )
    assert SettingsExecutionBlockerCode.MISSING_OWNER_APPROVAL_PACKET_DECISION.value in (
        item.missing_approval_codes
    )
    assert SettingsExecutionGateCode.OPERATOR_HALT_GATE.value in item.missing_gate_codes
    assert "SMARTLEAD_LIVE_ENABLED" in item.closed_provider_flag_names
    assert SecretName.GOOGLE_CALENDAR_API_KEY.value in item.missing_credential_names
    assert SECRET_VALUE not in text
    assert SECRET_VALUE not in plain
    _assert_no_leakage(text, SECRET_VALUE, DB_SECRET_URL)
    _assert_no_leakage(plain, SECRET_VALUE)
    assert PROSPECT_EMAIL not in text
    assert PHI_SNIPPET not in text
    assert UNSAFE_ERROR not in text
    assert "reviewer_notes" not in text
    assert _counts(db_session) == before
    assert _flags(settings) == before_flags
    assert settings.outbound_enabled is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_missing_credentials_are_named_without_values(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(
        openai_api_key=SECRET_VALUE,
        smartlead_api_key="",
        google_calendar_api_key="",
        voice_api_key="",
        database_url=DB_SECRET_URL,
    )
    SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_CREDENTIAL_CONFIGURATION_REVIEW.value,
        requested_setting_names=["SMARTLEAD_API_KEY", "OPENAI_API_KEY"],
        idempotency_key="preflight-credentials",
    )

    result = SettingsExecutionPreflightService().simulate(db_session, settings)
    text = format_settings_execution_preflight(result, as_json=True)
    item = result.requests[0]

    assert SecretName.SMARTLEAD_API_KEY.value in item.missing_credential_names
    assert SecretName.OPENAI_API_KEY.value not in item.missing_credential_names
    assert SettingsExecutionBlockerCode.MISSING_CREDENTIAL.value in item.blocker_codes
    assert SecretName.SMARTLEAD_API_KEY.value in text
    assert SECRET_VALUE not in text
    assert "super-db-password" not in text
    _assert_no_leakage(text, SECRET_VALUE, DB_SECRET_URL)


def test_missing_packet_decision_and_provider_flag_blockers(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    _seed_plans_and_packets(db_session)
    SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_PROVIDER_LIVE_FLAG_REVIEW.value,
        requested_setting_names=["SMARTLEAD_LIVE_ENABLED"],
        idempotency_key="preflight-provider-flag",
    )

    result = SettingsExecutionPreflightService().simulate(db_session, settings)
    item = result.requests[0]

    assert result.pending_owner_approval_packet_count > 0
    assert result.approved_owner_approval_packet_count == 0
    assert SettingsExecutionBlockerCode.MISSING_OWNER_APPROVAL_PACKET_DECISION.value in (
        item.blocker_codes
    )
    assert SettingsExecutionBlockerCode.PROVIDER_LIVE_FLAG_FALSE.value in item.blocker_codes
    assert "SMARTLEAD_LIVE_ENABLED" in item.closed_provider_flag_names
    assert item.desired_boolean is True


def test_preflight_is_deterministic_and_idempotent(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    service = SettingsChangeRequestService()
    first = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="preflight-idempotent-a",
    )
    second = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="preflight-idempotent-b",
    )
    service.record_decision(
        db_session,
        settings,
        request_id=second.request_id,
        decision="approved",
    )
    simulator = SettingsExecutionPreflightService()
    before = _counts(db_session)

    one = simulator.simulate(db_session, settings)
    two = simulator.simulate(db_session, settings)
    payload_one = _without_timestamps(preflight_payload(one))
    payload_two = _without_timestamps(preflight_payload(two))

    assert payload_one == payload_two
    assert {item.request_id for item in one.requests} == {first.request_id, second.request_id}
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False


def test_filters_and_unavailable_halt(db_session: Session) -> None:
    settings = _settings()
    service = SettingsChangeRequestService()
    service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="preflight-filter-keep",
    )
    enable = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="preflight-filter-enable",
    )
    service.record_decision(db_session, settings, request_id=enable.request_id, decision="approved")

    filtered = SettingsExecutionPreflightService().simulate(
        db_session,
        settings,
        filters=SettingsExecutionPreflightFilters(
            request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
            decision_status=SettingsChangeDecisionStatus.APPROVED.value,
        ),
    )
    ignored = SettingsExecutionPreflightService().simulate(
        db_session,
        settings,
        filters=SettingsExecutionPreflightFilters(request_type="not-a-type"),
    )

    assert filtered.request_count == 1
    assert filtered.requests[0].request_id == enable.request_id
    assert ignored.request_count == 2
    assert filtered.operator_halt_status == HaltStatus.UNAVAILABLE.value
    assert SettingsExecutionBlockerCode.OPERATOR_HALT_UNAVAILABLE.value in (
        filtered.requests[0].blocker_codes
    )


def test_cli_settings_execution_preflight_json(
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
    SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="cli-preflight",
    )
    before = _counts(db_session)

    code = main(["settings-execution-preflight", "--json"])
    output = capsys.readouterr().out
    payload = _json_from_cli(output)

    assert code == 0
    assert payload["no_execution"] is True
    assert payload["execution_allowed"] is False
    assert payload["executed"] == 0
    assert payload["settings_applied"] is False
    assert payload["owner_approved"] is False
    assert payload["request_count"] == 1
    _assert_no_leakage(output, SECRET_VALUE)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False
