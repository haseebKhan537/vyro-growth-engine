from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.decision_makers import candidate
from tests.test_contact_enrichment_service import _org, _service
from vyro_growth.cli import main
from vyro_growth.config import Settings
from vyro_growth.domain import (
    ContactDiscoveryCallStatus,
    ContactRoleCategory,
    ContactVerificationStatus,
    EnrichmentRunStatus,
    WebsiteFactType,
    WebsiteMatchStatus,
)
from vyro_growth.models import (
    Activity,
    Contact,
    ContactDiscoveryCall,
    DiscoveryRun,
    EnrichmentRun,
    Organization,
    SourceEvidence,
)
from vyro_growth.providers.decision_makers import DECISION_MAKER_SOURCE, NO_CONTACT_FOUND
from vyro_growth.providers.email_verification import (
    EMAIL_VERIFICATION_SOURCE,
)
from vyro_growth.providers.website import WEBSITE_ENRICHMENT_SOURCE
from vyro_growth.services.contact_validation import (
    MAX_COHORT_SIZE,
    ContactValidationError,
    ContactValidationFilters,
    ContactValidationService,
    format_contact_validation_plan,
    format_contact_validation_report,
    parse_contact_validation_filters,
    plan_payload,
    report_payload,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.phone_verification import PhoneVerificationService

SECRET_VALUE = "sk-testsecret-contact-validation"
PROSPECT_EMAIL = "owner@austinfamily.example"
PROSPECT_PHONE = "512-555-0199"
PROSPECT_NAME = "Jordan Blake"
NPI = "1487448189"
PRACTICE_NAME = "AUSTIN FAMILY MEDICINE"


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _counts(db: Session) -> tuple[int, int, int, int]:
    return (
        int(db.scalar(select(func.count()).select_from(Activity)) or 0),
        int(db.scalar(select(func.count()).select_from(Contact)) or 0),
        int(db.scalar(select(func.count()).select_from(ContactDiscoveryCall)) or 0),
        int(db.scalar(select(func.count()).select_from(EnrichmentRun)) or 0),
    )


def _strip_volatile(payload: dict[str, object]) -> dict[str, object]:
    copied = dict(payload)
    copied.pop("generated_at", None)
    git = copied.get("local_git")
    if isinstance(git, dict):
        git = dict(git)
        git.pop("current_sha", None)
        git.pop("current_branch", None)
        git.pop("working_tree_status", None)
        copied["local_git"] = git
    return copied


def _json_from_cli(output: str) -> dict[str, object]:
    return json.loads(output.strip().splitlines()[-1])


def _add_fact(
    db: Session,
    organization: Organization,
    claim_type: str,
    *,
    extracted_value: str = "redacted-test-value",
) -> None:
    db.add(
        SourceEvidence(
            organization_id=organization.id,
            source_url="https://austinfamily.example/about",
            claim_type=claim_type,
            extracted_value=extracted_value,
            confidence=0.9,
            evidence_snippet=f"{PROSPECT_NAME} at {PRACTICE_NAME}",
            metadata_json={"fabricated": False},
        )
    )
    db.flush()


def test_empty_plan_and_report_are_sanitized_and_read_only(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    before = _counts(db_session)
    service = ContactValidationService()
    settings = _settings()

    plan = service.build_plan(db_session, settings)
    report = service.build_report(db_session, settings)
    plan_json = format_contact_validation_plan(plan, as_json=True)
    report_json = format_contact_validation_report(report, as_json=True)

    assert plan.packet_kind == "contact_validation_plan"
    assert report.packet_kind == "contact_validation_report"
    assert plan.read_only is True
    assert report.dry_run_only is True
    assert plan.outbound_enabled is False
    assert report.outbound_enabled is False
    assert plan.execution_allowed is False
    assert report.owner_approved is False
    assert plan.halt_changed is False
    assert report.supervised_validation_run_permitted is False
    assert report.funnel_strong_enough_for_supervised_validation is False
    assert report.no_contact_found_is_normal_outcome is True
    assert report.no_contact_found_is_failure is False
    assert report.organizations_considered == 0
    assert report.overall_status == "info"
    assert plan.segment.max_cohort_size == MAX_COHORT_SIZE
    assert all(stage.executed is False for stage in plan.planned_stages)
    assert all(item.applied_to_live_settings is False for item in plan.owner_review_thresholds)
    assert plan.operator_halt_before == HaltStatus.HALTED.value
    assert report.operator_halt_after == HaltStatus.HALTED.value
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert _counts(db_session) == before
    assert SECRET_VALUE not in plan_json
    assert SECRET_VALUE not in report_json
    assert PROSPECT_EMAIL not in report_json
    assert "email" not in report_payload(report)
    assert "phone" not in report_payload(report)


def test_report_counts_funnel_without_leaking_prospect_details(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    _add_fact(db_session, organization, WebsiteFactType.STAFF_MEMBER.value)
    _add_fact(db_session, organization, WebsiteFactType.JOB_POSTING_SIGNAL.value)
    discovery = DiscoveryRun(
        source="nppes",
        status="completed",
        query_params={"state": "TX", "city": "AUSTIN"},
        records_fetched=1,
        records_upserted=1,
        started_at=datetime.now(tz=UTC),
        finished_at=datetime.now(tz=UTC),
    )
    db_session.add(discovery)
    db_session.flush()
    db_session.add(
        SourceEvidence(
            organization_id=organization.id,
            discovery_run_id=discovery.id,
            source_url="https://npiregistry.cms.hhs.gov/api/",
            claim_type="nppes_organization",
            extracted_value=PRACTICE_NAME,
            confidence=1.0,
            evidence_snippet=NPI,
            metadata_json={},
        )
    )
    db_session.flush()
    _service(
        [
            candidate(
                full_name=PROSPECT_NAME,
                title="Practice Manager",
                business_email=PROSPECT_EMAIL,
                business_phone=PROSPECT_PHONE,
                verification_status=ContactVerificationStatus.PROVIDER_VERIFIED,
            )
        ]
    ).enrich_organization(db_session, organization.id)
    before = _counts(db_session)

    report = ContactValidationService().build_report(
        db_session,
        _settings(),
        ContactValidationFilters(state="TX", city="Austin", specialty="Family Medicine"),
    )
    rendered = format_contact_validation_report(report, as_json=True)
    payload = report_payload(report)

    assert report.organizations_considered == 1
    assert report.official_website_verified_count == 1
    assert report.staff_facts_found_count == 1
    assert report.job_posting_intent_count == 1
    assert report.decision_maker_candidates_found_count == 1
    assert report.business_email_found_count == 1
    assert report.verified_email_count == 1
    assert report.verified_decision_maker_role_email_count == 1
    assert report.no_contact_found_count == 0
    assert report.queued_human_phone_verification_count == 0
    assert report.segment.state == "TX"
    assert report.segment.city == "AUSTIN"
    assert report.segment.specialty == "Family Medicine"
    assert report.segment.taxonomy_description == "Family Medicine"
    assert report.run_counts_by_source[DECISION_MAKER_SOURCE] == 1
    assert str(discovery.id) in report.run_ids_by_source["nppes"]
    assert report.no_contact_found_is_failure is False
    assert payload["outbound_attempted"] is False
    assert payload["live_call_attempted"] is False
    assert payload["live_provider_calls_attempted"] is False
    assert payload["supervised_validation_run_permitted"] is False
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert PROSPECT_EMAIL not in rendered
    assert PROSPECT_PHONE not in rendered
    assert PROSPECT_NAME not in rendered
    assert PRACTICE_NAME not in rendered
    assert NPI not in rendered
    assert SECRET_VALUE not in rendered
    assert "https://austinfamily.example" not in rendered


def test_no_contact_found_and_phone_queue_are_normal_outcomes(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    _service().enrich_organization(db_session, organization.id)

    report = ContactValidationService().build_report(db_session, _settings())
    rendered = format_contact_validation_report(report, as_json=True)

    assert report.organizations_considered == 1
    assert report.decision_maker_candidates_found_count == 0
    assert report.no_contact_found_count == 1
    assert report.no_contact_found_rate == 1.0
    assert report.queued_human_phone_verification_count == 1
    assert report.phone_verification_by_status[ContactDiscoveryCallStatus.QUEUED.value] == 1
    assert report.no_contact_found_is_normal_outcome is True
    assert report.no_contact_found_is_failure is False
    assert report.overall_status == "warning"
    assert NO_CONTACT_FOUND not in rendered or report.no_contact_found_count == 1
    assert PRACTICE_NAME not in rendered
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_no_verified_email_is_counted_without_being_a_job_failure(db_session: Session) -> None:
    organization = _org(db_session)
    db_session.add(
        Contact(
            organization_id=organization.id,
            full_name=PROSPECT_NAME,
            title="Practice Manager",
            email=PROSPECT_EMAIL,
            role_category=ContactRoleCategory.PRACTICE_MANAGER.value,
            verification_status=ContactVerificationStatus.UNVERIFIED.value,
            email_verification_verdict="unverified",
            dedupe_key="email:unverified",
        )
    )
    db_session.flush()

    report = ContactValidationService().build_report(db_session, _settings())

    assert report.business_email_found_count == 1
    assert report.verified_email_count == 0
    assert report.no_verified_email_count == 1
    assert report.no_contact_found_is_failure is False
    assert any(
        item.code == "min_verified_email_rate" and item.passed is False
        for item in report.threshold_comparisons
    )


def test_cohort_is_capped_and_filtered(db_session: Session) -> None:
    _org(db_session, npi="1111111111", state="TX", city="AUSTIN", specialty="Family Medicine")
    _org(
        db_session,
        npi="2222222222",
        name="DALLAS CARDIOLOGY",
        state="TX",
        city="DALLAS",
        specialty="Cardiology",
        website_match_status=WebsiteMatchStatus.AMBIGUOUS.value,
    )
    _org(
        db_session,
        npi="3333333333",
        name="AUSTIN DERM",
        state="TX",
        city="AUSTIN",
        specialty="Family Medicine",
        website_match_status=WebsiteMatchStatus.NO_MATCH.value,
    )
    _org(
        db_session,
        npi="4444444444",
        name="AUSTIN PEDS",
        state="TX",
        city="AUSTIN",
        specialty="Family Medicine",
        website_match_status=WebsiteMatchStatus.VERIFIED.value,
    )

    report = ContactValidationService().build_report(
        db_session,
        _settings(),
        ContactValidationFilters(
            state="tx",
            city="austin",
            taxonomy_description="family medicine",
            max_cohort_size=2,
        ),
    )

    assert report.segment.organizations_matching_filters == 3
    assert report.organizations_considered == 2
    assert report.segment.max_cohort_size == 2
    assert report.official_website_verified_count + report.official_website_no_match_count == 2


def test_invalid_filters_are_rejected(db_session: Session) -> None:
    service = ContactValidationService()
    try:
        service.build_plan(
            db_session,
            _settings(),
            ContactValidationFilters(max_cohort_size=201),
        )
        raise AssertionError("expected invalid cohort size to fail")
    except ContactValidationError as exc:
        assert exc.code == "invalid_cohort_size"

    try:
        parse_contact_validation_filters(ContactValidationFilters(state="Texas"))
        raise AssertionError("expected invalid state to fail")
    except ContactValidationError as exc:
        assert exc.code == "invalid_state_filter"

    try:
        parse_contact_validation_filters(
            ContactValidationFilters(specialty="owner@austinfamily.example")
        )
        raise AssertionError("expected unsafe specialty to fail")
    except ContactValidationError as exc:
        assert exc.code == "unsafe_filter"


def test_output_is_deterministic_except_timestamps_and_git(db_session: Session) -> None:
    _org(db_session)
    settings = _settings()
    first = ContactValidationService().build_report(db_session, settings)
    second = ContactValidationService().build_report(db_session, settings)
    assert _strip_volatile(report_payload(first)) == _strip_volatile(report_payload(second))
    plan_first = ContactValidationService().build_plan(db_session, settings)
    plan_second = ContactValidationService().build_plan(db_session, settings)
    assert _strip_volatile(plan_payload(plan_first)) == _strip_volatile(plan_payload(plan_second))


def test_live_provider_flags_block_ready_status_without_calling_providers(
    db_session: Session,
) -> None:
    settings = _settings(decision_maker_live_enabled=True, decision_maker_api_key="placeholder")
    report = ContactValidationService().build_report(db_session, settings)
    assert report.overall_status == "blocked"
    assert report.live_providers["decision_maker"] is True
    assert report.live_provider_calls_attempted is False
    assert report.supervised_validation_run_permitted is False


def test_cli_json_is_sanitized_and_has_no_side_effects(
    db_session: Session,
    monkeypatch: object,
    capsys: object,
) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    _service(
        [
            candidate(
                business_email=PROSPECT_EMAIL,
                verification_status=ContactVerificationStatus.PROVIDER_VERIFIED,
            )
        ]
    ).enrich_organization(db_session, organization.id)
    before = _counts(db_session)
    settings = _settings()

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)

    plan_code = main(
        ["contact-validation-plan", "--json", "--state", "TX", "--city", "Austin"]
    )
    plan_output = capsys.readouterr().out
    report_code = main(
        ["contact-validation-report", "--json", "--state", "TX", "--max-cohort-size", "200"]
    )
    report_output = capsys.readouterr().out
    plan_payload_json = _json_from_cli(plan_output)
    report_payload_json = _json_from_cli(report_output)

    assert plan_code == 0
    assert report_code == 0
    assert plan_payload_json["packet_kind"] == "contact_validation_plan"
    assert report_payload_json["packet_kind"] == "contact_validation_report"
    assert report_payload_json["outbound_enabled"] is False
    assert report_payload_json["halt_changed"] is False
    assert report_payload_json["no_contact_found_is_failure"] is False
    assert "owner_review_thresholds" in plan_payload_json
    assert "threshold_comparisons" in report_payload_json
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert PROSPECT_EMAIL not in plan_output
    assert PROSPECT_EMAIL not in report_output
    assert PRACTICE_NAME not in report_output
    assert NPI not in report_output


def test_website_and_email_verification_run_ids_are_counts_only(db_session: Session) -> None:
    organization = _org(
        db_session,
        website_match_status=WebsiteMatchStatus.AMBIGUOUS.value,
    )
    db_session.add(
        EnrichmentRun(
            organization_id=organization.id,
            source=WEBSITE_ENRICHMENT_SOURCE,
            status=EnrichmentRunStatus.COMPLETED.value,
            started_at=datetime.now(tz=UTC),
            finished_at=datetime.now(tz=UTC),
        )
    )
    db_session.add(
        EnrichmentRun(
            organization_id=organization.id,
            source=EMAIL_VERIFICATION_SOURCE,
            status=EnrichmentRunStatus.COMPLETED.value,
            started_at=datetime.now(tz=UTC),
            finished_at=datetime.now(tz=UTC),
        )
    )
    db_session.flush()

    report = ContactValidationService().build_report(db_session, _settings())
    assert report.official_website_ambiguous_count == 1
    assert report.run_counts_by_source[WEBSITE_ENRICHMENT_SOURCE] == 1
    assert report.run_counts_by_source[EMAIL_VERIFICATION_SOURCE] == 1
    rendered = format_contact_validation_report(report, as_json=True)
    assert PROSPECT_EMAIL not in rendered
    assert PRACTICE_NAME not in rendered


def test_phone_verification_queue_helper_does_not_change_halt(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    PhoneVerificationService().queue_for_organization(db_session, organization.id, commit=False)
    report = ContactValidationService().build_report(db_session, _settings())
    assert report.queued_human_phone_verification_count == 1
    assert read_operator_halt(db_session) is HaltStatus.HALTED
