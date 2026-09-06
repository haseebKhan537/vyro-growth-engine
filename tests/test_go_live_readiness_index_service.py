from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_action_readiness_service import _seed_plans_and_packets
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
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
from vyro_growth.services.go_live_readiness_index import (
    CLI_COMMAND,
    HTML_ROUTE,
    HTTP_ROUTE,
    GoLiveReadinessIndexService,
    format_go_live_readiness_index,
    index_payload,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

DB_SECRET_URL = "postgresql+psycopg://vyro:super-db-password@localhost:5432/vyro_growth"
VOLATILE_KEYS = {
    "generated_at",
    "current_sha",
    "current_branch",
    "working_tree_status",
    "available",
}


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
    assert payload["build_allowed"] is False
    assert payload["artifact_publish_allowed"] is False
    assert payload["container_build_attempted"] is False
    assert payload["artifact_publish_attempted"] is False
    assert payload["manual_review_only"] is True
    assert payload["index_is_not_permission_to_go_live"] is True
    assert payload["handoff_is_not_go_live"] is True
    assert payload["binder_is_not_go_live"] is True
    assert payload["runbook_is_not_deployment"] is True
    assert payload["manifest_is_not_a_build_or_deploy"] is True
    assert payload["packet_kind"] == "operator_go_live_readiness_index"
    assert payload["purpose"] == "manual_owner_review_index_only"
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE


def test_empty_index_is_read_only_and_not_permission_to_go_live(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)
    settings = _settings()
    before_halt = read_operator_halt(db_session)

    index = GoLiveReadinessIndexService().build(db_session, settings)
    payload = index_payload(index)

    assert index.read_only is True
    assert index.no_execution is True
    assert index.execution_allowed is False
    assert index.go_live_permitted is False
    assert index.deployment_allowed is False
    assert index.build_allowed is False
    assert index.artifact_publish_allowed is False
    assert index.index_is_not_permission_to_go_live is True
    assert index.handoff_is_not_go_live is True
    assert index.binder_is_not_go_live is True
    assert index.runbook_is_not_deployment is True
    assert index.manifest_is_not_a_build_or_deploy is True
    assert index.owner_approved is False
    assert index.settings_applied is False
    assert index.halt_changed is False
    assert index.live_action is False
    assert index.outbound_enabled is False
    assert index.executed == 0
    keys = {card.key for card in index.surfaces}
    assert keys == {
        "operator-dashboard",
        "launch-readiness",
        "settings-execution-preflight",
        "owner-handoff-packet",
        "compliance-evidence-binder",
        "release-candidate-runbook",
        "release-artifact-manifest",
        "operator-audit-timeline",
    }
    assert HTML_ROUTE in index.related_routes
    assert HTTP_ROUTE in index.related_routes
    assert CLI_COMMAND in index.related_commands
    codes = {item.code for item in index.remaining_manual_owner_checklist}
    assert NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value in codes
    assert NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value in codes
    assert NextActionCode.PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.GO_LIVE_REHEARSAL_CHECKLIST_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.REHEARSAL_OUTCOME_REPORT_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.SUPERVISED_PILOT_PLAN_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.SUPERVISED_PILOT_CANDIDATES_IS_NOT_GO_LIVE.value in codes
    assert "provider-setup-checklist" in index.related_commands
    assert "go-live-rehearsal-checklist" in index.related_commands
    assert "rehearsal-outcome-report" in index.related_commands
    assert "supervised-pilot-plan" in index.related_commands
    assert "/internal/operator-provider-setup-checklist" in index.related_routes
    assert "/internal/provider-setup-checklist" in index.related_routes
    assert "/internal/operator-go-live-rehearsal-checklist" in index.related_routes
    assert "/internal/operator-rehearsal-outcome-report" in index.related_routes
    assert "/internal/go-live-rehearsal-checklist" in index.related_routes
    assert "/internal/rehearsal-outcome-report" in index.related_routes
    assert "/internal/operator-supervised-pilot-plan" in index.related_routes
    assert "/internal/supervised-pilot-plan" in index.related_routes
    assert "/internal/operator-supervised-pilot-candidates" in index.related_routes
    assert "/internal/supervised-pilot-candidates" in index.related_routes
    assert payload["go_live_permitted"] is False
    assert payload["execution_allowed"] is False
    _assert_no_execution(payload)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_index_reuses_summaries_and_does_not_leak_or_write(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    _seed_plans_and_packets(db_session)
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="index-service",
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

    first = GoLiveReadinessIndexService().build(db_session, settings)
    second = GoLiveReadinessIndexService().build(db_session, settings)

    launch = next(card for card in first.surfaces if card.key == "launch-readiness")
    preflight = next(card for card in first.surfaces if card.key == "settings-execution-preflight")
    handoff = next(card for card in first.surfaces if card.key == "owner-handoff-packet")
    assert launch.overall_status
    assert any(item.label == "Requests" for item in preflight.counts)
    assert any(item.label == "Packets" for item in handoff.counts)
    payload = index_payload(first)
    _assert_no_execution(payload)
    _assert_no_leakage(str(payload), SECRET_VALUE)
    assert PHI_SNIPPET not in str(payload)
    assert PROSPECT_EMAIL not in str(payload)
    assert SECRET_VALUE not in str(payload)
    assert DB_SECRET_URL not in str(payload)
    assert _strip_volatile(index_payload(first)) == _strip_volatile(index_payload(second))
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert settings.outbound_enabled is False
    assert first.local_git.git_provider_called is False
    assert first.local_git.github_actions_called is False


def test_index_is_deterministic_aside_from_timestamps_and_git(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    first = GoLiveReadinessIndexService().build(db_session, settings)
    second = GoLiveReadinessIndexService().build(db_session, settings)
    assert first.generated_at != datetime(1999, 1, 1, tzinfo=UTC)
    assert _strip_volatile(index_payload(first)) == _strip_volatile(index_payload(second))
    assert first.packet_kind == "operator_go_live_readiness_index"
    assert first.purpose == "manual_owner_review_index_only"
    assert first.cli_command == CLI_COMMAND
    assert first.http_route == HTTP_ROUTE


def test_cli_go_live_readiness_index_json_is_sanitized(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(voice_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    before = _counts(db_session)
    before_halt = read_operator_halt(db_session)

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)

    first_code = main(["go-live-readiness-index", "--json"])
    first_output = capsys.readouterr().out
    second_code = main(["go-live-readiness-index", "--json"])
    second_output = capsys.readouterr().out
    payload = _json_from_cli(first_output)

    assert first_code == 0
    assert second_code == 0
    _assert_no_execution(payload)
    assert _strip_volatile(_json_from_cli(first_output)) == _strip_volatile(
        _json_from_cli(second_output)
    )
    assert payload["outbound_enabled"] is False
    assert "surfaces" in payload
    assert "remaining_manual_owner_checklist" in payload
    assert "local_git" in payload
    surfaces = payload["surfaces"]
    assert isinstance(surfaces, list)
    surface_keys = {card["key"] for card in surfaces if isinstance(card, dict)}
    assert "operator-dashboard" in surface_keys
    assert "launch-readiness" in surface_keys
    assert "settings-execution-preflight" in surface_keys
    assert "owner-handoff-packet" in surface_keys
    assert "compliance-evidence-binder" in surface_keys
    assert "release-candidate-runbook" in surface_keys
    assert "release-artifact-manifest" in surface_keys
    assert "operator-audit-timeline" in surface_keys
    _assert_no_leakage(first_output, SECRET_VALUE, DB_SECRET_URL)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False


def test_cli_go_live_readiness_index_markdown_is_sanitized(
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

    markdown = format_go_live_readiness_index(
        GoLiveReadinessIndexService().build(db_session, settings),
        as_json=False,
    )
    json_text = format_go_live_readiness_index(
        GoLiveReadinessIndexService().build(db_session, settings),
        as_json=True,
    )
    code = main(["go-live-readiness-index"])
    output = capsys.readouterr().out

    assert code == 0
    assert "# Go-live readiness index" in output
    assert "go_live_permitted: false" in output
    assert "execution_allowed: false" in output
    assert "deployment_allowed: false" in output
    assert "build_allowed: false" in output
    assert "artifact_publish_allowed: false" in output
    assert "index_is_not_permission_to_go_live: true" in output
    assert "OUTBOUND_ENABLED=false" in output
    assert "## Live-blocking flags" in output
    assert "## Readiness surfaces" in output
    assert "### Operator dashboard / command center" in output
    assert "### Launch readiness" in output
    assert "### Settings execution preflight" in output
    assert "### Owner handoff packet" in output
    assert "### Compliance evidence binder" in output
    assert "### Release-candidate runbook" in output
    assert "### Release artifact manifest" in output
    assert "### Operator audit timeline" in output
    assert "## Remaining unresolved blockers and manual owner checklist" in output
    assert "cli_command: go-live-readiness-index" in output
    assert "http_route: /internal/go-live-readiness-index" in output
    _assert_no_leakage(output, SECRET_VALUE)
    _assert_no_leakage(markdown, SECRET_VALUE)
    _assert_no_leakage(json_text, SECRET_VALUE)
    assert read_operator_halt(db_session) is HaltStatus.HALTED
