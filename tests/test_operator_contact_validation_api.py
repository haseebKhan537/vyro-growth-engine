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
from vyro_growth.api.operator_contact_validation import (
    render_operator_contact_validation,
    render_operator_contact_validation_error,
)
from vyro_growth.api.operator_ui import OPERATOR_CONTACT_VALIDATION_PATH
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
    HTML_ROUTE,
    PLAN_HTTP_ROUTE,
    REPORT_HTTP_ROUTE,
    ContactValidationFilters,
    ContactValidationPlan,
    ContactValidationReport,
    ContactValidationSegment,
    ContactValidationService,
    ContactValidationStage,
    OwnerReviewThreshold,
    ThresholdComparison,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata

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
    "validation-flags",
    "live-provider-flags",
    "target-segment",
    "planned-stages",
    "funnel-counts",
    "threshold-comparisons",
    "owner-review-thresholds",
    "outcome-summaries",
    "related-routes",
    "related-commands",
    "local-git",
    "owner-next-steps",
    "side-effects",
)
LINKED_SURFACES = (
    "/internal/operator-dashboard",
    "/internal/contact-validation/plan",
    "/internal/contact-validation/report",
    "/internal/contact-enrichment/metrics",
    "/internal/email-verification/metrics",
    "/internal/phone-verification/tasks",
    "/internal/operator-supervised-pilot-launch-rehearsal-control-map",
    "/internal/operator-contact-validation",
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


def _segment(**overrides: object) -> ContactValidationSegment:
    payload: dict[str, object] = {
        "state": "TX",
        "city": "AUSTIN",
        "specialty": "Family Medicine",
        "taxonomy_description": "Family Medicine",
        "max_cohort_size": 200,
        "organizations_matching_filters": 0,
        "planned_cohort_size": 200,
    }
    payload.update(overrides)
    return ContactValidationSegment(**payload)  # type: ignore[arg-type]


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


def _safety_fields() -> dict[str, object]:
    return {
        "read_only": True,
        "dry_run_only": True,
        "no_execution": True,
        "no_outbound": True,
        "no_provider_calls": True,
        "no_spend": True,
        "no_deployment": True,
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
        "live_providers_enabled": False,
        "live_providers": {"decision_maker": False, "email_verification": False},
        "decision_maker_live_enabled": False,
        "email_verification_live_enabled": False,
        "email_verification_smtp_enabled": False,
        "contact_validation_is_not_outbound": True,
        "contact_validation_is_not_live_send": True,
        "supervised_validation_run_permitted": False,
        "no_contact_found_is_normal_outcome": True,
        "no_contact_found_is_failure": False,
        "segment": _segment(),
        "planned_stages": (_stage(),),
        "owner_review_thresholds": (_threshold(),),
        "related_commands": ("contact-validation-plan", "contact-validation-report"),
        "related_routes": LINKED_SURFACES,
        "local_git": _git(),
    }


def _plan(**overrides: object) -> ContactValidationPlan:
    payload: dict[str, object] = {
        "generated_at": datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        "packet_kind": "contact_validation_plan",
        "purpose": "contact_enrichment_validation_measurement_only",
        "overall_status": "info",
        "funnel_strong_enough_for_supervised_validation": False,
        "cli_command": "contact-validation-plan",
        "http_route": PLAN_HTTP_ROUTE,
        **_safety_fields(),
    }
    payload.update(overrides)
    return ContactValidationPlan(**payload)  # type: ignore[arg-type]


def _report(**overrides: object) -> ContactValidationReport:
    payload: dict[str, object] = {
        "generated_at": datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        "packet_kind": "contact_validation_report",
        "purpose": "contact_enrichment_validation_measurement_only",
        "overall_status": "info",
        "funnel_strong_enough_for_supervised_validation": False,
        "threshold_comparisons": (_comparison(),),
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
        "website_match_counts": {},
        "phone_verification_by_status": {},
        "run_ids_by_source": {},
        "run_counts_by_source": {},
        "cli_command": "contact-validation-report",
        "http_route": REPORT_HTTP_ROUTE,
        **_safety_fields(),
    }
    payload.update(overrides)
    return ContactValidationReport(**payload)  # type: ignore[arg-type]


def test_renderer_escapes_and_omits_executable_controls() -> None:
    html = render_operator_contact_validation(
        _plan(purpose=XSS_LABEL),
        _report(
            purpose=XSS_LABEL,
            related_commands=(XSS_LABEL, "contact-validation-report"),
            live_providers={"decision_maker": False},
        ),
    )
    error = render_operator_contact_validation_error()

    assert 'id="operator-contact-validation"' in html
    assert OPERATOR_CONTACT_VALIDATION_PATH == HTML_ROUTE
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert SECRET_VALUE not in html
    assert 'id="operator-contact-validation-error"' in error
    assert "sk-testsecret" not in error
    lowered = html.lower()
    error_lowered = error.lower()
    for marker in ACTION_MARKERS + FORM_MARKERS + CONTACT_MARKERS:
        assert marker not in lowered
        assert marker not in error_lowered


def test_renderer_is_deterministic_aside_from_timestamps_and_git_metadata() -> None:
    first = render_operator_contact_validation(_plan(), _report())
    second = render_operator_contact_validation(
        _plan(generated_at=datetime(2026, 9, 8, 8, 30, tzinfo=UTC)),
        _report(generated_at=datetime(2026, 9, 8, 8, 30, tzinfo=UTC)),
    )
    git_variant = render_operator_contact_validation(
        _plan(),
        _report(
            local_git=_git(
                available=True,
                current_branch="cursor/phase-72-contact-validation-ui-2f19",
                current_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )
        ),
    )

    assert _strip_volatile(first) == _strip_volatile(second)
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in git_variant
    assert "cursor/phase-72-contact-validation-ui-2f19" in git_variant
    assert TIMESTAMP_RE.search(first)
    assert TIMESTAMP_RE.search(second)


def test_operator_contact_validation_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_CONTACT_VALIDATION_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    body = response.text
    assert "Operator contact validation" in body
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
    assert "contact_validation_is_not_outbound=true" in body
    assert "contact_validation_is_not_live_send=true" in body
    assert "NO_CONTACT_FOUND is a normal outcome" in body
    assert "Non-executable owner next steps" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    lowered = body.lower()
    for marker in FORM_MARKERS + CONTACT_MARKERS:
        assert marker not in lowered


def test_operator_contact_validation_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_CONTACT_VALIDATION_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_CONTACT_VALIDATION_PATH)
    invalid = api_client.get(
        OPERATOR_CONTACT_VALIDATION_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_CONTACT_VALIDATION_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    put = api_client.put(
        OPERATOR_CONTACT_VALIDATION_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    delete = api_client.delete(
        OPERATOR_CONTACT_VALIDATION_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    patch = api_client.patch(
        OPERATOR_CONTACT_VALIDATION_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405
    assert put.status_code == 405
    assert delete.status_code == 405
    assert patch.status_code == 405


def test_operator_contact_validation_populated_no_side_effects_and_no_live_traffic(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="production",
        internal_api_key="internal-secret",
        voice_api_key=SECRET_VALUE,
        openai_api_key=SECRET_VALUE,
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
        OPERATOR_CONTACT_VALIDATION_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
        params={"state": "TX", "city": "Austin", "max_cohort_size": 200},
    )
    second = api_client.get(
        OPERATOR_CONTACT_VALIDATION_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
        params={"state": "TX", "city": "Austin", "max_cohort_size": 200},
    )
    report_json = api_client.get(
        REPORT_HTTP_ROUTE,
        headers={"X-Internal-Api-Key": "internal-secret"},
        params={"state": "TX", "city": "Austin", "max_cohort_size": 200},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert report_json.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    body = first.text
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    assert "OUTBOUND_ENABLED" in body
    assert "supervised_validation_run_not_permitted" in body
    assert "NO_CONTACT_FOUND" in body
    assert "NO_VERIFIED_EMAIL" in body
    assert "Halt unchanged" in body
    assert "Funnel counts and rates" in body
    assert "Threshold comparison rows" in body
    payload = report_json.json()
    assert payload["read_only"] is True
    assert payload["no_execution"] is True
    assert payload["no_outbound"] is True
    assert payload["no_provider_calls"] is True
    assert payload["outbound_attempted"] is False
    assert payload["live_provider_calls_attempted"] is False
    assert payload["owner_approved"] is False
    assert payload["supervised_validation_run_permitted"] is False
    assert payload["outbound_enabled"] is False
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


def test_operator_contact_validation_rejects_unsafe_filters(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    oversized = api_client.get(
        OPERATOR_CONTACT_VALIDATION_PATH,
        params={"max_cohort_size": 201},
    )
    unsafe = api_client.get(
        OPERATOR_CONTACT_VALIDATION_PATH,
        params={"specialty": "owner@example.com"},
    )
    invalid_state = api_client.get(
        OPERATOR_CONTACT_VALIDATION_PATH,
        params={"state": "TEXAS"},
    )

    assert oversized.status_code == 422
    assert unsafe.status_code == 400
    assert invalid_state.status_code == 400
    assert unsafe.headers["cache-control"] == "no-store"
    assert "owner@example.com" not in unsafe.text
    assert "TEXAS" not in invalid_state.text
    assert "<form" not in unsafe.text.lower()


def test_operator_contact_validation_escapes_safe_filter_text(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(
        OPERATOR_CONTACT_VALIDATION_PATH,
        params={"specialty": XSS_LABEL, "max_cohort_size": 50},
    )

    assert response.status_code == 200
    assert XSS_LABEL not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "max 50" in response.text


def test_operator_contact_validation_failure_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(
        self: ContactValidationService,
        *_args: object,
        **_kwargs: object,
    ) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(ContactValidationService, "build_plan", _boom)
    response = api_client.get(OPERATOR_CONTACT_VALIDATION_PATH)

    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the operator contact validation view" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()


def test_operator_contact_validation_reuses_phase_71_filters() -> None:
    filters = ContactValidationFilters(
        state="tx",
        city="Austin",
        specialty="Family Medicine",
        max_cohort_size=50,
    )
    assert filters.max_cohort_size == 50
    assert HTML_ROUTE == "/internal/operator-contact-validation"
