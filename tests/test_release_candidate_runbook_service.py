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
from vyro_growth.domain import NextActionCode, SecretName, SettingsChangeRequestType
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
from vyro_growth.services.release_candidate_runbook import (
    ReleaseCandidateRunbookService,
    format_release_candidate_runbook,
    runbook_payload,
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

    def _strip(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: _strip(item)
                for key, item in value.items()
                if key not in {"generated_at", "occurred_at", "requested_at", "simulated_at"}
            }
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
    assert payload["future_deployment_phase_exists"] is False
    assert payload["go_live_permitted"] is False
    assert payload["deployment_allowed"] is False
    assert payload["deployment_attempted"] is False
    assert payload["deployed"] is False
    assert payload["manual_review_only"] is True
    assert payload["runbook_is_not_deployment"] is True
    assert payload["packet_kind"] == "release_candidate_deployment_runbook"
    assert payload["purpose"] == "future_manual_owner_review_only"
    assert payload["cli_command"] == "release-candidate-runbook"
    assert payload["http_route"] == "/internal/release-candidate-runbook"


def test_empty_runbook_is_read_only_without_side_effects(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    before_flags = _flags(settings)
    before = _counts(db_session)

    runbook = ReleaseCandidateRunbookService().build(db_session, settings)
    text = format_release_candidate_runbook(runbook, as_json=True)
    markdown = format_release_candidate_runbook(runbook, as_json=False)
    payload = json.loads(text)

    assert runbook.overall_status in {"blocked", "warning", "ready_for_owner_review"}
    assert runbook.go_live_permitted is False
    assert runbook.execution_allowed is False
    assert runbook.deployment_allowed is False
    assert runbook.deployment_attempted is False
    assert runbook.deployed is False
    assert runbook.settings_applied is False
    assert runbook.halt_changed is False
    assert runbook.owner_approved is False
    assert runbook.live_action is False
    assert runbook.outbound_enabled is False
    assert runbook.runbook_is_not_deployment is True
    assert runbook.release_candidate_identity.expected_base_branch == "main"
    assert runbook.release_candidate_identity.git_provider_called is False
    assert runbook.release_candidate_identity.deployment_from_runbook is False
    assert runbook.ci_gates_and_local_verification.github_actions_called is False
    assert "smoke-dry-run" in runbook.ci_gates_and_local_verification.required_ci_job_names
    assert "deploy-config" in runbook.ci_gates_and_local_verification.required_ci_job_names
    assert runbook.ci_gates_and_local_verification.smoke_gate.documented is True
    assert runbook.ci_gates_and_local_verification.deploy_config_gate.documented is True
    assert runbook.safe_environment_defaults.outbound_enabled_required is False
    assert runbook.safe_environment_defaults.secret_values_included is False
    assert runbook.operator_halt_and_outbound.keep_outbound_disabled is True
    assert runbook.manual_deployment_sequence
    assert runbook.rollback_checklist
    assert runbook.post_deploy_verification
    assert "/internal/operator-release-candidate-runbook" in runbook.related_routes
    codes = {item.code for item in runbook.remaining_manual_owner_checklist}
    assert NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT.value in codes
    assert "execution_disabled_in_this_phase" in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    assert "## Release candidate identity and repo branch expectations" in markdown
    assert "## Required CI gates and local dry-run verification commands" in markdown
    assert "## Required safe environment defaults" in markdown
    assert "## Operator halt and outbound-disabled verification" in markdown
    assert "## Manual deployment sequence (instructions only)" in markdown
    assert "## Rollback checklist (instructions only)" in markdown
    assert "## Post-deploy read-only verification" in markdown
    assert "## Remaining unresolved blockers and manual owner checklist" in markdown
    assert "not a deployment mechanism or permission to go live" in markdown
    _assert_no_execution(payload)
    assert _counts(db_session) == before
    assert _flags(settings) == before_flags
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    _assert_no_leakage(text)
    _assert_no_leakage(markdown)


def test_populated_runbook_consolidates_safe_evidence(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(voice_api_key=SECRET_VALUE)
    _seed_plans_and_packets(db_session)
    activity = Activity(
        lead_id=None,
        actor="cli",
        action="nppes_discovery_completed",
        details={
            "body": PHI_SNIPPET,
            "email": PROSPECT_EMAIL,
            "status": "completed",
            "source": "cli",
        },
    )
    db_session.add(activity)
    db_session.flush()
    service = SettingsChangeRequestService()
    service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="runbook-pending",
        reviewer_notes=f"record only {PHI_SNIPPET}",
    )
    approved = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        desired_boolean=True,
        idempotency_key="runbook-approved",
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

    runbook = ReleaseCandidateRunbookService().build(db_session, settings)
    text = format_release_candidate_runbook(runbook, as_json=True)
    markdown = format_release_candidate_runbook(runbook, as_json=False)

    assert runbook.reused_summaries.settings_preflight_blocked_count >= 1
    assert runbook.reused_summaries.settings_preflight_execution_allowed is False
    assert runbook.reused_summaries.owner_handoff_go_live_permitted is False
    assert runbook.reused_summaries.binder_is_not_go_live is True
    assert runbook.reused_summaries.audit_timeline_matching_count >= 1
    assert SecretName.SMARTLEAD_API_KEY.value in runbook.missing_credential_names
    assert runbook.safe_environment_defaults.secret_values_included is False
    assert "reviewer_notes" not in text
    _assert_no_leakage(text, SECRET_VALUE, DB_SECRET_URL)
    _assert_no_leakage(markdown, SECRET_VALUE)
    assert PROSPECT_EMAIL not in text
    assert PHI_SNIPPET not in text
    assert UNSAFE_ERROR not in text
    assert _counts(db_session) == before
    assert _flags(settings) == before_flags
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False


def test_runbook_is_deterministic_and_idempotent(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="runbook-idempotent",
    )
    builder = ReleaseCandidateRunbookService()
    before = _counts(db_session)

    one = builder.build(db_session, settings)
    two = builder.build(db_session, settings)
    payload_one = _without_timestamps(runbook_payload(one))
    payload_two = _without_timestamps(runbook_payload(two))

    assert payload_one == payload_two
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False
    assert one.go_live_permitted is False
    assert two.deployment_allowed is False
    assert one.runbook_is_not_deployment is True


def test_cli_release_candidate_runbook_json_is_sanitized(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(voice_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)

    code = main(["release-candidate-runbook", "--json"])
    output = capsys.readouterr().out
    payload = _json_from_cli(output)

    assert code == 0
    _assert_no_execution(payload)
    assert payload["outbound_enabled"] is False
    assert payload["cli_command"] == "release-candidate-runbook"
    assert "release_candidate_identity" in payload
    assert "manual_deployment_sequence" in payload
    assert "rollback_checklist" in payload
    assert "post_deploy_verification" in payload
    assert "remaining_manual_owner_checklist" in payload
    _assert_no_leakage(output, SECRET_VALUE, DB_SECRET_URL)
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_cli_release_candidate_runbook_markdown_is_sanitized(
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

    code = main(["release-candidate-runbook"])
    output = capsys.readouterr().out

    assert code == 0
    assert "# Release-candidate deployment runbook" in output
    assert "go_live_permitted: false" in output
    assert "execution_allowed: false" in output
    assert "deployment_allowed: false" in output
    assert "runbook_is_not_deployment: true" in output
    assert "## Remaining unresolved blockers and manual owner checklist" in output
    _assert_no_leakage(output, SECRET_VALUE)
    assert read_operator_halt(db_session) is HaltStatus.HALTED
