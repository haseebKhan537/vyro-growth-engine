from __future__ import annotations

import re
from collections.abc import Generator
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.decision_makers import candidate
from tests.test_contact_enrichment_service import _org, _service
from tests.test_contact_validation_service import SECRET_VALUE, _add_fact
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import _assert_no_leakage
from vyro_growth.api.operator_supervised_validation_run_packet import (
    render_operator_supervised_validation_run_packet,
    render_operator_supervised_validation_run_packet_error,
)
from vyro_growth.api.operator_ui import OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import ContactVerificationStatus, WebsiteFactType
from vyro_growth.main import app
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    Contact,
    ContactDiscoveryCall,
    Meeting,
    OutreachMessage,
)
from vyro_growth.services.contact_validation import (
    ContactValidationFilters,
    ContactValidationStage,
    OwnerReviewThreshold,
    ThresholdComparison,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.supervised_validation_run_packet import (
    CLI_COMMAND,
    HTML_ROUTE,
    HTTP_ROUTE,
    FunnelAggregate,
    NamedPresence,
    OwnerDecisionItem,
    OwnerNextStep,
    PrerequisiteItem,
    StatusCount,
    SupervisedValidationRunPacket,
    SupervisedValidationRunPacketService,
)

XSS_LABEL = "<script>alert(1)</script>"
ACTION_MARKERS = ("javascript:", "onclick=", "onerror=")
FORM_MARKERS = ("<form", "<button", "<input", "<select", "<textarea")
CONTACT_MARKERS = (
    "mailto:",
    "tel:",
    'href="sms:',
    "contact this candidate",
    "email this candidate",
    "call this candidate",
)
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
PRACTICE_NAME = "AUSTIN FAMILY MEDICINE"
NPI_NUMBER = "1487448189"
WEBSITE = "https://austinfamily.example"
PROSPECT_PHONE = "512-555-0199"
SECTION_IDS = (
    "live-blocking-flags",
    "packet-flags",
    "live-provider-flags",
    "target-segment",
    "prerequisite-checklist",
    "required-owner-decisions",
    "required-credentials",
    "required-configs",
    "planned-stages",
    "funnel-counts",
    "threshold-comparisons",
    "owner-review-thresholds",
    "outcome-summaries",
    "status-code-counts",
    "source-references",
    "related-routes",
    "related-commands",
    "local-git",
    "owner-next-steps",
    "side-effects",
)
LINKED_SURFACES = (
    "/internal/operator-dashboard",
    "/internal/supervised-validation-run-packet",
    "/internal/operator-contact-validation",
    "/internal/contact-validation/plan",
    "/internal/contact-validation/report",
    "/internal/contact-enrichment/metrics",
    "/internal/email-verification/metrics",
    "/internal/phone-verification/tasks",
    "/internal/operator-supervised-pilot-launch-rehearsal-control-map",
    "/internal/operator-supervised-validation-run-packet",
)
FORBIDDEN_PROVIDER_HOSTS = (
    "api.apollo.io",
    "api.hunter.io",
    "api.neverbounce.com",
    "api.zerobounce.net",
    "api.openai.com",
    "npiregistry.cms.hhs.gov",
    "smartlead.ai",
)


@pytest.fixture
def api_client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr("vyro_growth.main.get_settings", lambda: settings)


def _strip_volatile(html: str) -> str:
    cleaned = TIMESTAMP_RE.sub("TIMESTAMP", html)
    cleaned = re.sub(r"\b[0-9a-f]{7,40}\b", "GITSHA", cleaned)
    cleaned = re.sub(r"cursor/[A-Za-z0-9._/\-]+", "GITBRANCH", cleaned)
    return cleaned


def _git(**overrides: object) -> LocalGitMetadata:
    payload: dict[str, object] = {
        "available": False,
        "current_branch": "unavailable",
        "current_sha": "unavailable",
        "working_tree_status": "not_inspected",
        "git_provider_called": False,
        "github_actions_called": False,
    }
    payload.update(overrides)
    return LocalGitMetadata(**payload)  # type: ignore[arg-type]


def _stage(**overrides: object) -> ContactValidationStage:
    payload: dict[str, object] = {
        "code": "nppes_discovery",
        "command_name": "discover-nppes",
        "json_route": "/internal/discovery/nppes",
        "mode": "existing_safe_stage_review_only",
        "executed": False,
        "live_provider_called": False,
    }
    payload.update(overrides)
    return ContactValidationStage(**payload)  # type: ignore[arg-type]


def _threshold(**overrides: object) -> OwnerReviewThreshold:
    payload: dict[str, object] = {
        "code": "min_organizations_considered",
        "metric": "organizations_considered",
        "comparator": "gte",
        "threshold": 50.0,
        "applied_to_live_settings": False,
        "scoring_thresholds_changed": False,
    }
    payload.update(overrides)
    return OwnerReviewThreshold(**payload)  # type: ignore[arg-type]


def _comparison(**overrides: object) -> ThresholdComparison:
    payload: dict[str, object] = {
        "code": "min_organizations_considered",
        "metric": "organizations_considered",
        "observed": 0.0,
        "threshold": 50.0,
        "comparator": "gte",
        "passed": False,
        "blocking": False,
        "no_contact_found_is_failure": False,
    }
    payload.update(overrides)
    return ThresholdComparison(**payload)  # type: ignore[arg-type]


def _funnel(**overrides: object) -> FunnelAggregate:
    payload: dict[str, object] = {
        "organizations_considered": 0,
        "official_website_verified_count": 0,
        "official_website_ambiguous_count": 0,
        "official_website_no_match_count": 0,
        "official_website_unknown_count": 0,
        "staff_facts_found_count": 0,
        "job_posting_intent_count": 0,
        "decision_maker_candidates_found_count": 0,
        "business_email_found_count": 0,
        "verified_email_count": 0,
        "verified_decision_maker_role_email_count": 0,
        "no_contact_found_count": 0,
        "no_verified_email_count": 0,
        "queued_human_phone_verification_count": 0,
        "provider_error_count": 0,
        "official_website_verified_rate": 0.0,
        "staff_facts_found_rate": 0.0,
        "job_posting_intent_rate": 0.0,
        "decision_maker_candidates_found_rate": 0.0,
        "business_email_found_rate": 0.0,
        "verified_email_rate": 0.0,
        "verified_decision_maker_role_email_rate": 0.0,
        "no_contact_found_rate": 0.0,
        "no_verified_email_rate": 0.0,
        "queued_human_phone_verification_rate": 0.0,
        "provider_error_rate": 0.0,
    }
    payload.update(overrides)
    return FunnelAggregate(**payload)  # type: ignore[arg-type]


def _packet(**overrides: object) -> SupervisedValidationRunPacket:
    payload: dict[str, object] = {
        "generated_at": datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        "packet_kind": "supervised_validation_run_packet",
        "purpose": "manual_owner_supervised_validation_run_review_only",
        "overall_status": "info",
        "read_only": True,
        "dry_run_only": True,
        "no_execution": True,
        "no_outbound": True,
        "no_provider_calls": True,
        "no_send": True,
        "no_call": True,
        "no_book": True,
        "no_spend": True,
        "no_deploy": True,
        "no_autodial": True,
        "no_ai_voice": True,
        "manual_review_only": True,
        "outbound_attempted": False,
        "live_call_attempted": False,
        "live_provider_calls_attempted": False,
        "smtp_attempted": False,
        "autodial_attempted": False,
        "campaign_enrolled": False,
        "booking_attempted": False,
        "meet_link_created": False,
        "ads_launched": False,
        "execution_allowed": False,
        "owner_approved": False,
        "spend_attempted": False,
        "campaign_launched": False,
        "halt_changed": False,
        "settings_applied": False,
        "scoring_thresholds_changed": False,
        "outbound_enabled": False,
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "operator_halt_unchanged": True,
        "live_providers_enabled": False,
        "live_providers": {"decision_maker": False, "email_verification": False},
        "decision_maker_live_enabled": False,
        "email_verification_live_enabled": False,
        "email_verification_smtp_enabled": False,
        "contact_validation_is_not_outbound": True,
        "contact_validation_is_not_live_send": True,
        "supervised_validation_run_packet_is_not_execution": True,
        "export_is_not_permission_to_run": True,
        "supervised_validation_run_permitted": False,
        "funnel_strong_enough_for_supervised_validation": False,
        "no_contact_found_is_normal_outcome": True,
        "no_contact_found_is_failure": False,
        "no_verified_email_is_normal_outcome": True,
        "no_verified_email_is_failure": False,
        "source_plan_overall_status": "info",
        "source_report_overall_status": "info",
        "source_plan_command": "contact-validation-plan",
        "source_plan_route": "/internal/contact-validation/plan",
        "source_report_command": "contact-validation-report",
        "source_report_route": "/internal/contact-validation/report",
        "source_html_route": "/internal/operator-contact-validation",
        "segment_state": "TX",
        "segment_city": "AUSTIN",
        "segment_specialty": "Family Medicine",
        "segment_taxonomy_description": "Family Medicine",
        "max_cohort_size": 200,
        "planned_cohort_size": 200,
        "organizations_matching_filters": 0,
        "funnel": _funnel(),
        "planned_stages": (_stage(),),
        "owner_review_thresholds": (_threshold(),),
        "threshold_comparisons": (_comparison(),),
        "prerequisites": (
            PrerequisiteItem(
                code="keep_outbound_disabled",
                status="info",
                label="Keep OUTBOUND_ENABLED=false.",
                blocking=False,
                command_name=CLI_COMMAND,
                json_route=HTTP_ROUTE,
                html_route=HTML_ROUTE,
            ),
        ),
        "required_owner_decisions": (
            OwnerDecisionItem(
                code="permit_supervised_validation_run",
                name="Permit a later owner-supervised validation run.",
                granted=False,
            ),
        ),
        "required_credentials": (
            NamedPresence(name="DECISION_MAKER_API_KEY", present=False),
        ),
        "required_configs": (NamedPresence(name="OUTBOUND_ENABLED", present=False),),
        "missing_credential_names": ("DECISION_MAKER_API_KEY",),
        "missing_config_names": ("OUTBOUND_ENABLED",),
        "blocked_code_count": 0,
        "warning_code_count": 0,
        "info_code_count": 1,
        "status_counts": (StatusCount(key="info", count=1),),
        "related_commands": (CLI_COMMAND, "contact-validation-report"),
        "related_routes": LINKED_SURFACES,
        "local_git": _git(),
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "html_route": HTML_ROUTE,
        "next_actions": (
            OwnerNextStep(
                code="supervised_validation_run_not_permitted",
                status="info",
                label="supervised_validation_run_permitted=false.",
                command_name=CLI_COMMAND,
                json_route=HTTP_ROUTE,
                html_route=HTML_ROUTE,
                config_name=None,
            ),
        ),
    }
    payload.update(overrides)
    return SupervisedValidationRunPacket(**payload)  # type: ignore[arg-type]


def test_renderer_escapes_and_omits_executable_controls() -> None:
    html = render_operator_supervised_validation_run_packet(
        _packet(
            purpose=XSS_LABEL,
            related_commands=(XSS_LABEL, "contact-validation-report"),
            live_providers={"decision_maker": False},
        )
    )
    error = render_operator_supervised_validation_run_packet_error()

    assert 'id="operator-supervised-validation-run-packet"' in html
    assert OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH == HTML_ROUTE
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert SECRET_VALUE not in html
    assert 'id="operator-supervised-validation-run-packet-error"' in error
    assert "sk-testsecret" not in error
    lowered = html.lower()
    error_lowered = error.lower()
    for marker in ACTION_MARKERS + FORM_MARKERS + CONTACT_MARKERS:
        assert marker not in lowered
        assert marker not in error_lowered


def test_renderer_is_deterministic_aside_from_timestamps_and_git_metadata() -> None:
    first = render_operator_supervised_validation_run_packet(_packet())
    second = render_operator_supervised_validation_run_packet(
        _packet(generated_at=datetime(2026, 9, 8, 8, 30, tzinfo=UTC))
    )
    git_variant = render_operator_supervised_validation_run_packet(
        _packet(
            local_git=_git(
                available=True,
                current_branch="cursor/phase-74-supervised-validation-run-packet-ui-f1d9",
                current_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )
        )
    )

    assert _strip_volatile(first) == _strip_volatile(second)
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in git_variant
    assert "cursor/phase-74-supervised-validation-run-packet-ui-f1d9" in git_variant
    assert TIMESTAMP_RE.search(first)
    assert TIMESTAMP_RE.search(second)


def test_operator_supervised_validation_run_packet_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    body = response.text
    assert "Operator supervised validation run packet" in body
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for href in LINKED_SURFACES:
        assert href in body
    assert "OUTBOUND_ENABLED=false" in body
    assert "execution_allowed=false" in body
    assert "owner_approved=false" in body
    assert "supervised_validation_run_permitted=false" in body
    assert "no_outbound=true" in body
    assert "no_provider_calls=true" in body
    assert "no_send=true" in body
    assert "no_call=true" in body
    assert "no_book=true" in body
    assert "no_spend=true" in body
    assert "no_deploy=true" in body
    assert "contact_validation_is_not_outbound=true" in body
    assert "contact_validation_is_not_live_send=true" in body
    assert "NO_CONTACT_FOUND is a normal outcome" in body
    assert "NO_VERIFIED_EMAIL is a normal outcome" in body
    assert "Non-executable owner next steps" in body
    assert "granted" in body.lower()
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    lowered = body.lower()
    for marker in FORM_MARKERS + CONTACT_MARKERS:
        assert marker not in lowered


def test_operator_supervised_validation_run_packet_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH)
    invalid = api_client.get(
        OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    put = api_client.put(
        OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    delete = api_client.delete(
        OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    patch = api_client.patch(
        OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405
    assert put.status_code == 405
    assert delete.status_code == 405
    assert patch.status_code == 405


def test_operator_supervised_validation_run_packet_populated_no_side_effects(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="production",
        internal_api_key="internal-secret",
        voice_api_key=SECRET_VALUE,
        openai_api_key=SECRET_VALUE,
        decision_maker_api_key=SECRET_VALUE,
    )
    _patch_settings(monkeypatch, settings)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    organization = _org(db_session)
    _add_fact(db_session, organization, WebsiteFactType.STAFF_MEMBER.value)
    _service(
        [
            candidate(
                business_email=PROSPECT_EMAIL,
                verification_status=ContactVerificationStatus.PROVIDER_VERIFIED,
            )
        ]
    ).enrich_organization(db_session, organization.id)

    def _forbid_http(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("live provider HTTP is forbidden")

    monkeypatch.setattr(httpx, "Client", _forbid_http)
    monkeypatch.setattr(httpx, "AsyncClient", _forbid_http)

    before_activities = int(db_session.scalar(select(func.count()).select_from(Activity)) or 0)
    before_contacts = int(db_session.scalar(select(func.count()).select_from(Contact)) or 0)
    before_phone = int(
        db_session.scalar(select(func.count()).select_from(ContactDiscoveryCall)) or 0
    )
    before_meetings = int(db_session.scalar(select(func.count()).select_from(Meeting)) or 0)
    before_enrollments = int(
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0
    )
    before_messages = int(db_session.scalar(select(func.count()).select_from(OutreachMessage)) or 0)
    before_halt = read_operator_halt(db_session)

    first = api_client.get(
        OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
        params={"state": "TX", "city": "Austin", "max_cohort_size": 200},
    )
    second = api_client.get(
        OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
        params={"state": "TX", "city": "Austin", "max_cohort_size": 200},
    )
    packet_json = api_client.get(
        HTTP_ROUTE,
        headers={"X-Internal-Api-Key": "internal-secret"},
        params={"state": "TX", "city": "Austin", "max_cohort_size": 200},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert packet_json.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    body = first.text
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    assert "OUTBOUND_ENABLED" in body
    assert "supervised_validation_run_not_permitted" in body
    assert "NO_CONTACT_FOUND" in body
    assert "NO_VERIFIED_EMAIL" in body
    assert "Halt unchanged" in body
    assert "Phase 71 funnel counts and rates" in body
    assert "Threshold comparison statuses" in body
    assert "Prerequisite checklist" in body
    assert "Required owner decisions" in body
    payload = packet_json.json()
    assert payload["read_only"] is True
    assert payload["no_execution"] is True
    assert payload["no_outbound"] is True
    assert payload["no_provider_calls"] is True
    assert payload["no_send"] is True
    assert payload["no_call"] is True
    assert payload["no_book"] is True
    assert payload["no_spend"] is True
    assert payload["no_deploy"] is True
    assert payload["outbound_attempted"] is False
    assert payload["live_provider_calls_attempted"] is False
    assert payload["owner_approved"] is False
    assert payload["supervised_validation_run_permitted"] is False
    assert payload["outbound_enabled"] is False
    assert payload["html_route"] == OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH
    assert all(item["granted"] is False for item in payload["required_owner_decisions"])
    _assert_no_leakage(body, SECRET_VALUE)
    assert PHI_SNIPPET not in body
    assert PROSPECT_EMAIL not in body
    assert PRACTICE_NAME not in body
    assert NPI_NUMBER not in body
    assert WEBSITE not in body
    assert PROSPECT_PHONE not in body
    for host in FORBIDDEN_PROVIDER_HOSTS:
        assert host not in body.lower()
    lowered = body.lower()
    for marker in FORM_MARKERS + CONTACT_MARKERS:
        assert marker not in lowered
    assert _strip_volatile(first.text) == _strip_volatile(second.text)
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert db_session.scalar(select(func.count()).select_from(Contact)) == before_contacts
    assert db_session.scalar(select(func.count()).select_from(ContactDiscoveryCall)) == before_phone
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False
    assert settings.decision_maker_live_enabled is False
    assert settings.email_verification_live_enabled is False


def test_operator_supervised_validation_run_packet_rejects_unsafe_filters(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    oversized = api_client.get(
        OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH,
        params={"max_cohort_size": 201},
    )
    unsafe = api_client.get(
        OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH,
        params={"specialty": "owner@example.com"},
    )
    invalid_state = api_client.get(
        OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH,
        params={"state": "TEXAS"},
    )

    assert oversized.status_code == 422
    assert unsafe.status_code == 400
    assert invalid_state.status_code == 400
    assert unsafe.headers["cache-control"] == "no-store"
    assert "owner@example.com" not in unsafe.text
    assert "TEXAS" not in invalid_state.text
    assert "<form" not in unsafe.text.lower()


def test_operator_supervised_validation_run_packet_escapes_safe_filter_text(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(
        OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH,
        params={"specialty": XSS_LABEL, "max_cohort_size": 50},
    )

    assert response.status_code == 200
    assert XSS_LABEL not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "max 50" in response.text


def test_operator_supervised_validation_run_packet_failure_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(
        self: SupervisedValidationRunPacketService,
        *_args: object,
        **_kwargs: object,
    ) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(SupervisedValidationRunPacketService, "build", _boom)
    response = api_client.get(OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH)

    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the operator supervised validation run packet" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()


def test_operator_supervised_validation_run_packet_reuses_phase_73_filters() -> None:
    filters = ContactValidationFilters(
        state="tx",
        city="Austin",
        specialty="Family Medicine",
        max_cohort_size=50,
    )
    assert filters.max_cohort_size == 50
    assert HTML_ROUTE == "/internal/operator-supervised-validation-run-packet"
    assert OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH == HTML_ROUTE
