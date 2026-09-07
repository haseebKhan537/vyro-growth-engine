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
    CLI_COMMAND as INDEX_CLI_COMMAND,
)
from vyro_growth.services.go_live_readiness_index import (
    HTTP_ROUTE as INDEX_HTTP_ROUTE,
)
from vyro_growth.services.launch_blockers_plan import (
    CLI_COMMAND as BLOCKERS_CLI_COMMAND,
)
from vyro_growth.services.launch_blockers_plan import (
    HTTP_ROUTE as BLOCKERS_HTTP_ROUTE,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.owner_launch_dossier import (
    CLI_COMMAND as DOSSIER_CLI_COMMAND,
)
from vyro_growth.services.owner_launch_dossier import (
    HTTP_ROUTE as DOSSIER_HTTP_ROUTE,
)
from vyro_growth.services.owner_launch_dossier import OwnerLaunchDossierService
from vyro_growth.services.provider_setup_checklist import (
    CATEGORY_KEYS,
    CLI_COMMAND,
    HTML_ROUTE,
    HTTP_ROUTE,
    ProviderSetupChecklistService,
    checklist_payload,
    format_provider_setup_checklist,
)
from vyro_growth.services.release_candidate_runbook import (
    CLI_COMMAND as RUNBOOK_CLI_COMMAND,
)
from vyro_growth.services.release_candidate_runbook import (
    HTTP_ROUTE as RUNBOOK_HTTP_ROUTE,
)
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService
from vyro_growth.services.staged_rollout_plan import (
    CLI_COMMAND as STAGED_CLI_COMMAND,
)
from vyro_growth.services.staged_rollout_plan import (
    HTTP_ROUTE as STAGED_HTTP_ROUTE,
)

DB_SECRET_URL = "postgresql+psycopg://vyro:super-db-password@localhost:5432/vyro_growth"
VOLATILE_KEYS = {
    "generated_at",
    "current_sha",
    "current_branch",
    "working_tree_status",
    "available",
}
UNSAFE_ERROR = "Traceback (most recent call last): secret=sk-live-error-token"


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
    assert payload["no_go_live"] is True
    assert payload["no_deployment"] is True
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
    assert payload["provider_setup_checklist_is_not_go_live"] is True
    assert payload["checklist_is_not_permission_to_go_live"] is True
    assert payload["checklist_is_not_execution"] is True
    assert payload["index_is_not_permission_to_go_live"] is True
    assert payload["dossier_is_not_permission_to_go_live"] is True
    assert payload["staged_rollout_plan_is_not_go_live"] is True
    assert payload["runbook_is_not_deployment"] is True
    assert payload["packet_kind"] == "provider_setup_checklist"
    assert payload["purpose"] == "manual_owner_provider_setup_review_only"
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE
    assert payload["source_launch_readiness_command"] == "launch-readiness"
    assert payload["source_launch_readiness_route"] == "/internal/launch-readiness"
    assert payload["source_index_command"] == INDEX_CLI_COMMAND
    assert payload["source_index_route"] == INDEX_HTTP_ROUTE
    assert payload["source_blockers_plan_command"] == BLOCKERS_CLI_COMMAND
    assert payload["source_blockers_plan_route"] == BLOCKERS_HTTP_ROUTE
    assert payload["source_staged_rollout_command"] == STAGED_CLI_COMMAND
    assert payload["source_staged_rollout_route"] == STAGED_HTTP_ROUTE
    assert payload["source_dossier_command"] == DOSSIER_CLI_COMMAND
    assert payload["source_dossier_route"] == DOSSIER_HTTP_ROUTE
    assert payload["source_preflight_command"] == "settings-execution-preflight"
    assert payload["source_preflight_route"] == "/internal/settings-execution-preflight"
    assert payload["source_runbook_command"] == RUNBOOK_CLI_COMMAND
    assert payload["source_runbook_route"] == RUNBOOK_HTTP_ROUTE


def test_empty_checklist_reuses_sources_and_is_not_permission_to_go_live(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)
    settings = _settings()
    before_halt = read_operator_halt(db_session)
    dossier = OwnerLaunchDossierService().build(db_session, settings)

    checklist = ProviderSetupChecklistService().build(db_session, settings)
    payload = checklist_payload(checklist)

    assert checklist.read_only is True
    assert checklist.no_execution is True
    assert checklist.no_go_live is True
    assert checklist.no_deployment is True
    assert checklist.execution_allowed is False
    assert checklist.go_live_permitted is False
    assert checklist.deployment_allowed is False
    assert checklist.settings_applied is False
    assert checklist.halt_changed is False
    assert checklist.owner_approved is False
    assert checklist.provider_setup_checklist_is_not_go_live is True
    assert checklist.checklist_is_not_permission_to_go_live is True
    assert checklist.checklist_is_not_execution is True
    assert checklist.outbound_enabled is False
    assert checklist.executed == 0
    assert checklist.source_index_overall_status == dossier.source_index_overall_status
    assert (
        checklist.source_blockers_plan_overall_status
        == dossier.source_blockers_plan_overall_status
    )
    assert (
        checklist.source_staged_rollout_overall_status
        == dossier.source_staged_rollout_overall_status
    )
    assert checklist.source_dossier_overall_status == dossier.overall_status
    assert INDEX_HTTP_ROUTE in checklist.related_routes
    assert BLOCKERS_HTTP_ROUTE in checklist.related_routes
    assert STAGED_HTTP_ROUTE in checklist.related_routes
    assert DOSSIER_HTTP_ROUTE in checklist.related_routes
    assert HTML_ROUTE in checklist.related_routes
    assert HTTP_ROUTE in checklist.related_routes
    assert CLI_COMMAND in checklist.related_commands
    assert tuple(category.key for category in checklist.categories) == CATEGORY_KEYS
    codes = {action.code for action in checklist.next_actions}
    assert NextActionCode.PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    for category in checklist.categories:
        assert category.read_only is True
        assert category.no_execution is True
        assert category.go_live_permitted is False
        assert category.deployment_allowed is False
        assert category.required_owner_approval_type
        for item in category.credential_statuses:
            assert item.status in {"redacted", "missing"}
    _assert_no_execution(payload)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_checklist_reuses_sources_and_does_not_leak_or_write(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    _seed_plans_and_packets(db_session)
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="provider-setup-checklist-service",
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
    dossier = OwnerLaunchDossierService().build(db_session, settings)

    first = ProviderSetupChecklistService().build(db_session, settings)
    second = ProviderSetupChecklistService().build(db_session, settings)

    assert set(dossier.blocker_codes) <= set(first.blocker_codes)
    assert first.source_index_overall_status == dossier.source_index_overall_status
    payload = checklist_payload(first)
    _assert_no_execution(payload)
    _assert_no_leakage(str(payload), SECRET_VALUE)
    assert PHI_SNIPPET not in str(payload)
    assert PROSPECT_EMAIL not in str(payload)
    assert SECRET_VALUE not in str(payload)
    assert DB_SECRET_URL not in str(payload)
    assert UNSAFE_ERROR not in str(payload)
    assert "sk-" not in str(payload).lower()
    dumped = json.dumps(payload)
    for action in first.next_actions:
        assert action.label
        assert PHI_SNIPPET not in action.label
        assert PROSPECT_EMAIL not in action.label
        assert SECRET_VALUE not in action.label
        assert UNSAFE_ERROR not in action.label
    assert "categories" in payload
    assert "next_actions" in payload
    assert "local_verification_gates" in payload
    categories = payload["categories"]
    assert isinstance(categories, list)
    keys = {item["key"] for item in categories if isinstance(item, dict)}
    assert keys == set(CATEGORY_KEYS)
    email = next(
        item for item in categories if isinstance(item, dict) and item["key"] == "email_outreach"
    )
    assert "OPENAI_API_KEY" in email["config_names"]
    assert "SMARTLEAD_API_KEY" in email["config_names"]
    assert "OUTBOUND_ENABLED" in email["config_names"]
    assert email["required_owner_approval_type"]
    enrichment = next(
        item for item in categories if isinstance(item, dict) and item["key"] == "enrichment"
    )
    assert "DECISION_MAKER_API_KEY" in enrichment["config_names"]
    assert "DECISION_MAKER_LIVE_ENABLED" in enrichment["config_names"]
    assert "EMAIL_VERIFICATION_API_KEY" in enrichment["config_names"]
    assert "EMAIL_VERIFICATION_LIVE_ENABLED" in enrichment["config_names"]
    assert SECRET_VALUE not in str(enrichment)
    assert _strip_volatile(checklist_payload(first)) == _strip_volatile(checklist_payload(second))
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert settings.outbound_enabled is False
    assert first.local_git.git_provider_called is False
    assert first.local_git.github_actions_called is False
    assert dumped


def test_checklist_is_deterministic_aside_from_timestamps_and_git(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    first = ProviderSetupChecklistService().build(db_session, settings)
    second = ProviderSetupChecklistService().build(db_session, settings)
    assert first.generated_at != datetime(1999, 1, 1, tzinfo=UTC)
    assert _strip_volatile(checklist_payload(first)) == _strip_volatile(checklist_payload(second))
    assert first.packet_kind == "provider_setup_checklist"
    assert first.purpose == "manual_owner_provider_setup_review_only"
    assert first.cli_command == CLI_COMMAND
    assert first.http_route == HTTP_ROUTE


def test_cli_provider_setup_checklist_json_is_sanitized(
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

    first_code = main(["provider-setup-checklist", "--json"])
    first_output = capsys.readouterr().out
    second_code = main(["provider-setup-checklist", "--json"])
    second_output = capsys.readouterr().out
    payload = _json_from_cli(first_output)

    assert first_code == 0
    assert second_code == 0
    _assert_no_execution(payload)
    assert _strip_volatile(_json_from_cli(first_output)) == _strip_volatile(
        _json_from_cli(second_output)
    )
    assert payload["outbound_enabled"] is False
    assert "categories" in payload
    assert "local_git" in payload
    categories = payload["categories"]
    assert isinstance(categories, list)
    keys = {item["key"] for item in categories if isinstance(item, dict)}
    assert keys == set(CATEGORY_KEYS)
    _assert_no_leakage(first_output, SECRET_VALUE, DB_SECRET_URL)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False


def test_cli_provider_setup_checklist_markdown_is_sanitized(
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

    markdown = format_provider_setup_checklist(
        ProviderSetupChecklistService().build(db_session, settings),
        as_json=False,
    )
    json_text = format_provider_setup_checklist(
        ProviderSetupChecklistService().build(db_session, settings),
        as_json=True,
    )
    code = main(["provider-setup-checklist"])
    output = capsys.readouterr().out

    assert code == 0
    assert "# Provider setup checklist" in output
    assert "go_live_permitted: false" in output
    assert "execution_allowed: false" in output
    assert "deployment_allowed: false" in output
    assert "settings_applied: false" in output
    assert "halt_changed: false" in output
    assert "owner_approved: false" in output
    assert "provider_setup_checklist_is_not_go_live: true" in output
    assert "checklist_is_not_permission_to_go_live: true" in output
    assert "OUTBOUND_ENABLED=false" in output
    assert "## Live-blocking flags" in output
    assert "## Provider setup categories" in output
    assert "## Owner next actions" in output
    assert "cli_command: provider-setup-checklist" in output
    assert "http_route: /internal/provider-setup-checklist" in output
    assert "source_launch_readiness_command: launch-readiness" in output
    assert "source_index_command: go-live-readiness-index" in output
    assert "source_blockers_plan_command: launch-blockers-plan" in output
    assert "source_staged_rollout_command: staged-rollout-plan" in output
    assert "source_dossier_command: owner-launch-dossier" in output
    assert "source_runbook_command: release-candidate-runbook" in output
    _assert_no_leakage(output, SECRET_VALUE)
    _assert_no_leakage(markdown, SECRET_VALUE)
    _assert_no_leakage(json_text, SECRET_VALUE)
    assert read_operator_halt(db_session) is HaltStatus.HALTED
