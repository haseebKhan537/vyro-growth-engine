from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.outreach import sample_contact, sample_lead, sample_organization, sample_score
from tests.test_action_readiness_service import _seed_plans_and_packets
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from vyro_growth.cli import main
from vyro_growth.config import Settings
from vyro_growth.domain import (
    EnrichmentRunStatus,
    LeadStage,
    NextActionCode,
    SettingsChangeRequestType,
    WebsiteMatchStatus,
)
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    EnrichmentRun,
    LiveSettingsChangeRequest,
    Meeting,
    OutreachMessage,
    SourceEvidence,
)
from vyro_growth.providers.website import WEBSITE_ENRICHMENT_SOURCE
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService
from vyro_growth.services.supervised_pilot_candidates import (
    CLI_COMMAND,
    HTTP_ROUTE,
    SupervisedPilotCandidateService,
    format_supervised_pilot_candidates,
    supervised_pilot_candidates_payload,
)
from vyro_growth.services.supervised_pilot_plan import (
    CLI_COMMAND as PILOT_CLI_COMMAND,
)
from vyro_growth.services.supervised_pilot_plan import (
    HTTP_ROUTE as PILOT_HTTP_ROUTE,
)
from vyro_growth.services.supervised_pilot_plan import SupervisedPilotPlanService

DB_SECRET_URL = "postgresql+psycopg://vyro:super-db-password@localhost:5432/vyro_growth"
VOLATILE_KEYS = {
    "generated_at",
    "current_sha",
    "current_branch",
    "working_tree_status",
    "available",
}
UNSAFE_ERROR = "Traceback (most recent call last): secret=sk-live-error-token"
PRACTICE_NAME = "AUSTIN FAMILY MEDICINE PLLC"
PROVIDER_NAME = "Jordan Blake"
NPI_NUMBER = "1487448189"
STREET_HINT = "AUSTIN"
WEBSITE = "https://austinfamily.example"


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


def _count_map(items: object) -> dict[str, int]:
    assert isinstance(items, list)
    mapped: dict[str, int] = {}
    for item in items:
        assert isinstance(item, dict)
        key = item["key"]
        count = item["count"]
        assert isinstance(key, str)
        assert isinstance(count, int)
        mapped[key] = count
    return mapped


def _assert_no_execution(payload: dict[str, object]) -> None:
    assert payload["read_only"] is True
    assert payload["no_execution"] is True
    assert payload["no_go_live"] is True
    assert payload["no_deployment"] is True
    assert payload["no_outbound"] is True
    assert payload["no_provider_calls"] is True
    assert payload["no_spend"] is True
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
    assert payload["spend_allowed"] is False
    assert payload["spend_attempted"] is False
    assert payload["manual_review_only"] is True
    assert payload["supervised_pilot_candidates_is_not_go_live"] is True
    assert payload["export_is_not_permission_to_go_live"] is True
    assert payload["export_is_not_execution"] is True
    assert payload["packet_kind"] == "supervised_pilot_candidates"
    assert payload["purpose"] == "manual_owner_supervised_pilot_candidate_review_only"
    assert payload["cli_command"] == CLI_COMMAND
    assert payload["http_route"] == HTTP_ROUTE
    assert payload["source_pilot_plan_command"] == PILOT_CLI_COMMAND
    assert payload["source_pilot_plan_route"] == PILOT_HTTP_ROUTE
    assert payload["source_outcome_command"] == "rehearsal-outcome-report"
    assert payload["source_rehearsal_command"] == "go-live-rehearsal-checklist"
    assert payload["source_launch_readiness_command"] == "launch-readiness"
    assert payload["source_index_command"] == "go-live-readiness-index"
    assert payload["source_provider_setup_command"] == "provider-setup-checklist"


def _assert_no_sensitive_leakage(text: str) -> None:
    lowered = text.lower()
    _assert_no_leakage(text, SECRET_VALUE, DB_SECRET_URL)
    assert PHI_SNIPPET not in text
    assert PROSPECT_EMAIL not in text
    assert PRACTICE_NAME not in text
    assert PROVIDER_NAME not in text
    assert NPI_NUMBER not in text
    assert WEBSITE not in text
    assert "austin family" not in lowered
    assert STREET_HINT.lower() not in lowered or "family medicine" not in lowered
    assert UNSAFE_ERROR not in text
    assert "sk-" not in lowered
    assert "please call me" not in lowered
    assert "this opening line" not in lowered


def _seed_candidate(
    db: Session,
    *,
    verified_contact: bool = False,
    add_evidence: bool = False,
    add_enrichment: bool = False,
    score_band: str | None = "hot",
    stage: LeadStage = LeadStage.READY_FOR_OUTREACH,
) -> None:
    organization = sample_organization(db)
    lead = sample_lead(db, organization, stage=stage)
    sample_contact(
        db,
        organization,
        email=PROSPECT_EMAIL,
        email_verified=verified_contact,
        full_name=PROVIDER_NAME,
    )
    if score_band is not None:
        sample_score(db, lead, band=score_band)
    if add_enrichment:
        db.add(
            EnrichmentRun(
                organization_id=organization.id,
                source=WEBSITE_ENRICHMENT_SOURCE,
                status=EnrichmentRunStatus.COMPLETED.value,
                match_status=WebsiteMatchStatus.VERIFIED.value,
                official_website=organization.website,
                facts_extracted=1,
            )
        )
    if add_evidence:
        db.add(
            SourceEvidence(
                organization_id=organization.id,
                source_url="https://example.test/public-listing",
                claim_type="official_website",
                extracted_value="public listing",
                evidence_snippet=f"Do not leak this snippet. {PHI_SNIPPET}",
            )
        )
    db.flush()


def test_empty_candidate_export_reuses_plan_and_is_not_permission_to_go_live(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)
    settings = _settings()
    before_halt = read_operator_halt(db_session)
    plan = SupervisedPilotPlanService().build(db_session, settings)

    export = SupervisedPilotCandidateService().build(db_session, settings)
    payload = supervised_pilot_candidates_payload(export)

    assert export.read_only is True
    assert export.no_execution is True
    assert export.no_go_live is True
    assert export.no_outbound is True
    assert export.no_provider_calls is True
    assert export.no_spend is True
    assert export.execution_allowed is False
    assert export.go_live_permitted is False
    assert export.owner_approved is False
    assert export.supervised_pilot_candidates_is_not_go_live is True
    assert export.outbound_enabled is False
    assert export.executed == 0
    assert export.source_pilot_plan_overall_status == plan.overall_status
    assert export.source_outcome_overall_status == plan.source_outcome_overall_status
    assert export.candidate_scope.total_candidate_count == 0
    assert export.candidate_scope.ready_for_review_count == 0
    assert export.candidate_scope.suggested_max_manually_reviewed_sends == 0
    assert export.candidate_scope.suggested_candidate_count == 0
    assert set(plan.blocker_codes) <= set(export.blocker_codes)
    codes = {action.code for action in export.next_actions}
    assert NextActionCode.SUPERVISED_PILOT_CANDIDATES_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.SUPERVISED_PILOT_PLAN_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    assert CLI_COMMAND in export.related_commands
    assert PILOT_CLI_COMMAND in export.related_commands
    assert HTTP_ROUTE in export.related_routes
    assert PILOT_HTTP_ROUTE in export.related_routes
    assert export.kill_switch_outbound_disabled is True
    assert export.kill_switch_operator_halt_active is True
    _assert_no_execution(payload)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_candidate_export_counts_ready_and_blocked_without_leaking(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    _seed_candidate(
        db_session,
        verified_contact=True,
        add_evidence=True,
        add_enrichment=True,
        score_band="hot",
    )
    _seed_candidate(
        db_session,
        verified_contact=False,
        add_evidence=False,
        add_enrichment=False,
        score_band=None,
        stage=LeadStage.DISCOVERED,
    )
    before = _counts(db_session)
    before_halt = read_operator_halt(db_session)

    first = SupervisedPilotCandidateService().build(db_session, settings)
    second = SupervisedPilotCandidateService().build(db_session, settings)
    payload = supervised_pilot_candidates_payload(first)
    dumped = json.dumps(payload)

    assert first.candidate_scope.total_candidate_count == 2
    blocked = _count_map(payload["blocked_counts"])
    assert blocked["missing_website"] >= 0
    assert blocked["missing_enrichment"] >= 1
    assert blocked["missing_evidence"] >= 1
    assert blocked["missing_score"] >= 1
    assert blocked["consent"] >= 1
    assert "target" in _count_map(payload["candidate_counts_by_specialty"])
    assert "TX" in _count_map(payload["candidate_counts_by_state"])
    assert "nppes" in _count_map(payload["candidate_counts_by_source"])
    assert "hot" in _count_map(payload["scoring_distribution"])
    assert first.candidate_scope.suggested_max_leads == 10
    _assert_no_execution(payload)
    _assert_no_sensitive_leakage(dumped)
    assert "Family Medicine" not in dumped
    assert _strip_volatile(supervised_pilot_candidates_payload(first)) == _strip_volatile(
        supervised_pilot_candidates_payload(second)
    )
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert settings.outbound_enabled is False
    assert first.local_git.git_provider_called is False
    assert first.local_git.github_actions_called is False


def test_candidate_export_is_deterministic_aside_from_timestamps_and_git(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    first = SupervisedPilotCandidateService().build(db_session, settings)
    second = SupervisedPilotCandidateService().build(db_session, settings)
    assert first.generated_at != datetime(1999, 1, 1, tzinfo=UTC)
    assert _strip_volatile(supervised_pilot_candidates_payload(first)) == _strip_volatile(
        supervised_pilot_candidates_payload(second)
    )
    assert first.packet_kind == "supervised_pilot_candidates"
    assert first.purpose == "manual_owner_supervised_pilot_candidate_review_only"
    assert first.cli_command == CLI_COMMAND
    assert first.http_route == HTTP_ROUTE


def test_cli_supervised_pilot_candidates_json_is_sanitized(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(voice_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    _seed_plans_and_packets(db_session)
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="supervised-pilot-candidates-service",
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

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)

    first_code = main(["supervised-pilot-candidates", "--json"])
    first_output = capsys.readouterr().out
    second_code = main(["supervised-pilot-candidates", "--json"])
    second_output = capsys.readouterr().out
    payload = _json_from_cli(first_output)

    assert first_code == 0
    assert second_code == 0
    _assert_no_execution(payload)
    assert _strip_volatile(_json_from_cli(first_output)) == _strip_volatile(
        _json_from_cli(second_output)
    )
    assert payload["outbound_enabled"] is False
    assert "candidate_scope" in payload
    assert "blocked_counts" in payload
    assert "scoring_distribution" in payload
    assert "local_git" in payload
    _assert_no_sensitive_leakage(first_output)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False


def test_cli_supervised_pilot_candidates_markdown_is_sanitized(
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

    markdown = format_supervised_pilot_candidates(
        SupervisedPilotCandidateService().build(db_session, settings),
        as_json=False,
    )
    json_text = format_supervised_pilot_candidates(
        SupervisedPilotCandidateService().build(db_session, settings),
        as_json=True,
    )
    code = main(["supervised-pilot-candidates"])
    output = capsys.readouterr().out

    assert code == 0
    assert "# Supervised pilot candidate readiness" in output
    assert "go_live_permitted: false" in output
    assert "execution_allowed: false" in output
    assert "no_outbound: true" in output
    assert "no_provider_calls: true" in output
    assert "no_spend: true" in output
    assert "supervised_pilot_candidates_is_not_go_live: true" in output
    assert "export_is_not_permission_to_go_live: true" in output
    assert "OUTBOUND_ENABLED=false" in output
    assert "## Live-blocking flags" in output
    assert "## Pilot candidate scope recommendation" in output
    assert "## Candidate counts by readiness" in output
    assert "## Scoring distribution" in output
    assert "## Blocked-count reasons" in output
    assert "## Owner next actions" in output
    assert "cli_command: supervised-pilot-candidates" in output
    assert "http_route: /internal/supervised-pilot-candidates" in output
    assert "source_pilot_plan_command: supervised-pilot-plan" in output
    assert "suggested_max_manually_reviewed_sends: 0" in output
    _assert_no_sensitive_leakage(output)
    _assert_no_sensitive_leakage(markdown)
    _assert_no_sensitive_leakage(json_text)
    assert read_operator_halt(db_session) is HaltStatus.HALTED
