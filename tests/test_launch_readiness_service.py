from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_action_readiness_service import _seed_plans_and_packets
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_monitoring_service import UNSAFE_ERROR
from vyro_growth.cli import main
from vyro_growth.config import Settings
from vyro_growth.domain import (
    FindingCode,
    LaunchReadinessStatus,
    NextActionCode,
    SecretName,
    SecretPresenceStatus,
)
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    Meeting,
    OutreachMessage,
    OwnerApprovalPacket,
)
from vyro_growth.services.launch_readiness import (
    LaunchReadinessService,
    format_launch_readiness,
    inspect_ci_smoke_gate,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

SECRET_VALUE = "sk-test-secret-value-12345"
DB_SECRET_URL = "postgresql+psycopg://vyro:super-db-password@localhost:5432/vyro_growth"


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _payload(checklist: object) -> str:
    return json.dumps(checklist, default=str)


def _counts(db: Session) -> dict[str, int]:
    return {
        "activities": int(db.scalar(select(func.count()).select_from(Activity)) or 0),
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
        "packets": int(db.scalar(select(func.count()).select_from(OwnerApprovalPacket)) or 0),
    }


def _assert_no_leakage(text: str, *secrets: str) -> None:
    lowered = text.lower()
    assert SECRET_VALUE not in text
    assert "super-db-password" not in text
    assert "sk-" not in lowered
    assert PROSPECT_EMAIL not in text
    assert PHI_SNIPPET not in text
    assert UNSAFE_ERROR not in text
    assert "5551112222" not in text
    for secret in secrets:
        assert secret not in text


def test_missing_secrets_are_named_without_values(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(
        openai_api_key="",
        smartlead_api_key="",
        google_calendar_api_key="",
        voice_api_key="",
        internal_api_key="",
    )

    checklist = LaunchReadinessService().assess(db_session, settings)
    text = format_launch_readiness(checklist, as_json=True)

    by_name = {item.name: item for item in checklist.secret_inventory}
    assert by_name[SecretName.OPENAI_API_KEY.value].present is False
    assert by_name[SecretName.OPENAI_API_KEY.value].status == SecretPresenceStatus.MISSING.value
    assert by_name[SecretName.SMARTLEAD_API_KEY.value].status == SecretPresenceStatus.MISSING.value
    assert SecretName.OPENAI_API_KEY.value in text
    _assert_no_leakage(text)
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_present_secrets_are_redacted_and_never_printed(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(
        openai_api_key=SECRET_VALUE,
        smartlead_api_key=SECRET_VALUE,
        google_calendar_api_key=SECRET_VALUE,
        voice_api_key=SECRET_VALUE,
        internal_api_key=SECRET_VALUE,
        database_url=DB_SECRET_URL,
    )

    checklist = LaunchReadinessService().assess(db_session, settings)
    json_text = format_launch_readiness(checklist, as_json=True)
    plain_text = format_launch_readiness(checklist, as_json=False)

    by_name = {item.name: item for item in checklist.secret_inventory}
    for name in SecretName:
        assert by_name[name.value].present is True
        assert by_name[name.value].status == SecretPresenceStatus.REDACTED.value
    _assert_no_leakage(json_text, SECRET_VALUE, DB_SECRET_URL)
    _assert_no_leakage(plain_text, SECRET_VALUE, DB_SECRET_URL)
    assert "postgresql+" not in json_text
    assert "postgresql+" not in plain_text
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_operator_halt_is_a_warning_and_is_unchanged(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)

    checklist = LaunchReadinessService().assess(db_session, _settings())

    assert checklist.overall_status == LaunchReadinessStatus.WARNING.value
    assert checklist.operator_halt_status == HaltStatus.HALTED.value
    assert checklist.operator_halt_before == HaltStatus.HALTED.value
    assert checklist.operator_halt_after == HaltStatus.HALTED.value
    assert FindingCode.OPERATOR_HALT_ACTIVE.value in {item.code for item in checklist.findings}
    assert NextActionCode.KEEP_OPERATOR_HALT.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_unavailable_operator_halt_is_blocked(db_session: Session) -> None:
    checklist = LaunchReadinessService().assess(db_session, _settings())

    assert checklist.overall_status == LaunchReadinessStatus.BLOCKED.value
    assert checklist.operator_halt_status == HaltStatus.UNAVAILABLE.value
    assert FindingCode.OPERATOR_HALT_UNAVAILABLE.value in {
        item.code for item in checklist.findings
    }
    assert read_operator_halt(db_session) is HaltStatus.UNAVAILABLE


def test_outbound_enabled_is_blocked(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(outbound_enabled=True)

    checklist = LaunchReadinessService().assess(db_session, settings)
    text = format_launch_readiness(checklist, as_json=True)

    assert checklist.overall_status == LaunchReadinessStatus.BLOCKED.value
    assert checklist.outbound_enabled is True
    assert FindingCode.OUTBOUND_ENABLED.value in {item.code for item in checklist.findings}
    assert NextActionCode.DISABLE_OUTBOUND.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert checklist.live_action is False
    assert checklist.executed == 0
    _assert_no_leakage(text)
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_live_provider_flag_enabled_is_blocked(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_personalization_enabled=True, openai_api_key=SECRET_VALUE)

    checklist = LaunchReadinessService().assess(db_session, settings)
    text = format_launch_readiness(checklist, as_json=True)

    assert checklist.overall_status == LaunchReadinessStatus.BLOCKED.value
    assert checklist.live_providers_enabled is True
    assert FindingCode.LIVE_PROVIDER_ENABLED.value in {item.code for item in checklist.findings}
    assert NextActionCode.DISABLE_LIVE_PROVIDERS.value in {
        item.next_action_code for item in checklist.next_actions
    }
    openai_secret = next(
        item
        for item in checklist.secret_inventory
        if item.name == SecretName.OPENAI_API_KEY.value
    )
    assert openai_secret.required is True
    assert openai_secret.status == SecretPresenceStatus.REDACTED.value
    _assert_no_leakage(text, SECRET_VALUE)
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_missing_required_credential_with_live_flag_is_blocked(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(smartlead_live_enabled=True, smartlead_api_key="")

    checklist = LaunchReadinessService().assess(db_session, settings)
    text = format_launch_readiness(checklist, as_json=True)

    assert checklist.overall_status == LaunchReadinessStatus.BLOCKED.value
    assert FindingCode.MISSING_REQUIRED_CREDENTIAL.value in {
        item.code for item in checklist.findings
    }
    assert SecretName.SMARTLEAD_API_KEY.value in text
    _assert_no_leakage(text)
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_pending_approval_packets_are_a_warning(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    _seed_plans_and_packets(db_session)
    before = _counts(db_session)

    checklist = LaunchReadinessService().assess(db_session, _settings())

    assert checklist.pending_owner_approval_packets > 0
    assert FindingCode.PENDING_OWNER_APPROVAL_PACKETS.value in {
        item.code for item in checklist.findings
    }
    assert checklist.overall_status == LaunchReadinessStatus.WARNING.value
    assert checklist.executed == 0
    assert checklist.live_action is False
    assert checklist.owner_approved is False
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_action_readiness_blockers_are_a_warning(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    _seed_plans_and_packets(db_session)

    checklist = LaunchReadinessService().assess(db_session, _settings())

    assert checklist.action_readiness_candidate_count > 0
    assert checklist.action_readiness_blocked_count > 0
    assert FindingCode.ACTION_READINESS_BLOCKED.value in {
        item.code for item in checklist.findings
    }
    assert NextActionCode.INSPECT_ACTION_READINESS.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_missing_smoke_gate_is_blocked(db_session: Session, tmp_path: Path) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    checklist = LaunchReadinessService().assess(
        db_session,
        _settings(),
        repo_root=tmp_path,
    )

    assert checklist.ci_smoke_gate.present is False
    assert checklist.ci_smoke_gate.documented is False
    assert checklist.overall_status == LaunchReadinessStatus.BLOCKED.value
    assert FindingCode.SMOKE_GATE_MISSING.value in {item.code for item in checklist.findings}
    assert inspect_ci_smoke_gate(tmp_path).documented is False


def test_documented_smoke_gate_and_cleared_halt_is_ready_for_owner_review(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=False, reason="test_clear")

    checklist = LaunchReadinessService().assess(db_session, _settings())
    text = format_launch_readiness(checklist, as_json=True)

    assert checklist.overall_status == LaunchReadinessStatus.READY_FOR_OWNER_REVIEW.value
    assert checklist.ci_smoke_gate.documented is True
    assert checklist.ci_smoke_gate.job_name == "smoke-dry-run"
    assert checklist.outbound_enabled is False
    assert checklist.live_providers_enabled is False
    assert checklist.pending_owner_approval_packets == 0
    assert checklist.action_readiness_blocked_count == 0
    assert checklist.read_only is True
    assert checklist.no_execution is True
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert NextActionCode.INSPECT_SETTINGS_EXECUTION_PREFLIGHT.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert NextActionCode.INSPECT_OPERATOR_AUDIT_TIMELINE.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert NextActionCode.LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert NextActionCode.OWNER_LAUNCH_DOSSIER_IS_NOT_GO_LIVE.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert NextActionCode.PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value in {
        item.next_action_code for item in checklist.next_actions
    }
    assert checklist.pending_settings_change_request_count == 0
    assert any(
        item.request_type == "keep_outbound_disabled"
        for item in checklist.proposed_settings_change_requests
    )
    assert all(
        item.settings_applied is False for item in checklist.proposed_settings_change_requests
    )
    _assert_no_leakage(text)
    assert read_operator_halt(db_session) is HaltStatus.CLEARED


def test_output_sanitizes_and_does_not_write_rows(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)
    settings = _settings(openai_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)

    checklist = LaunchReadinessService().assess(db_session, settings)
    dumped = _payload(checklist) + format_launch_readiness(checklist, as_json=True)

    assert checklist.executed == 0
    assert checklist.live_action is False
    assert checklist.outbound_attempted is False
    assert checklist.owner_approved is False
    _assert_no_leakage(dumped, SECRET_VALUE, DB_SECRET_URL)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_missing_schema_fails_closed_without_secret_leakage(tmp_path: Path) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'empty.db'}", future=True)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    settings = _settings(openai_api_key=SECRET_VALUE)
    try:
        checklist = LaunchReadinessService().assess(session, settings)
        text = format_launch_readiness(checklist, as_json=True)
        assert checklist.overall_status == LaunchReadinessStatus.BLOCKED.value
        assert checklist.database == "unavailable"
        assert FindingCode.DATABASE_UNAVAILABLE.value in {item.code for item in checklist.findings}
        _assert_no_leakage(text, SECRET_VALUE)
    finally:
        session.close()
        engine.dispose()


def test_cli_launch_readiness_json_exits_nonzero_when_blocked(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings(outbound_enabled=True, openai_api_key=SECRET_VALUE)

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)

    exit_code = main(["launch-readiness", "--json"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert '"overall_status": "blocked"' in output
    assert '"outbound_enabled": true' in output
    _assert_no_leakage(output, SECRET_VALUE)


def test_cli_launch_readiness_text_is_sanitized(
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

    exit_code = main(["launch-readiness"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Launch readiness:" in output
    assert "overall=warning" in output
    assert "name=OPENAI_API_KEY" in output
    assert "status=redacted" in output
    assert "name=DATABASE_URL" in output
    _assert_no_leakage(output, SECRET_VALUE, DB_SECRET_URL)
    assert read_operator_halt(db_session) is HaltStatus.HALTED
