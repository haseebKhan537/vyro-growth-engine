from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.decision_makers import candidate
from tests.test_contact_enrichment_service import _org, _service
from vyro_growth.config import Settings
from vyro_growth.domain import (
    ContactRoleCategory,
    ContactVerificationStatus,
    EnrichmentRunStatus,
)
from vyro_growth.models import Activity, Contact, EnrichmentRun
from vyro_growth.observability import REDACTED
from vyro_growth.providers.decision_makers import DECISION_MAKER_SOURCE, NO_CONTACT_FOUND
from vyro_growth.services.contact_enrichment_metrics import (
    ContactEnrichmentMetricsService,
    format_contact_enrichment_metrics,
    metrics_payload,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

SECRET_VALUE = "sk-testsecret-contact-metrics"
PROSPECT_EMAIL = "owner@austinfamily.example"
PROSPECT_PHONE = "512-555-0199"
UNSAFE_ERROR = "lookup failed for owner@austinfamily.example token=sk-testsecret"


def test_empty_metrics_are_sanitized_counts_only(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    metrics = ContactEnrichmentMetricsService().summarize(db_session, Settings())

    assert metrics.organizations_considered == 0
    assert metrics.organizations_with_candidate == 0
    assert metrics.no_contact_found_count == 0
    assert metrics.provider_error_count == 0
    assert metrics.organizations_with_verified_decision_maker_email_rate == 0.0
    assert metrics.read_only is True
    assert metrics.outbound_attempted is False
    assert metrics.live_call_attempted is False
    assert metrics.execution_allowed is False
    assert metrics.owner_approved is False
    assert metrics.halt_changed is False
    assert metrics.outbound_enabled is False
    assert metrics.decision_maker_live_enabled is False
    assert metrics.contact_enrichment_is_not_outbound is True
    assert metrics.live_providers["decision_maker"] is False
    assert metrics.operator_halt_before == HaltStatus.HALTED.value
    assert metrics.operator_halt_after == HaltStatus.HALTED.value
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_hit_rate_counts_verified_decision_maker_email(db_session: Session) -> None:
    organization = _org(db_session)
    service = _service(
        [
            candidate(
                full_name="Jordan Blake",
                title="Practice Manager",
                business_email=PROSPECT_EMAIL,
                business_phone=PROSPECT_PHONE,
                verification_status=ContactVerificationStatus.PROVIDER_VERIFIED,
            )
        ]
    )
    service.enrich_organization(db_session, organization.id)

    metrics = ContactEnrichmentMetricsService().summarize(db_session, Settings())
    payload = metrics_payload(metrics)
    rendered = format_contact_enrichment_metrics(metrics, as_json=True)

    assert metrics.organizations_considered == 1
    assert metrics.organizations_with_candidate == 1
    assert metrics.organizations_with_business_email == 1
    assert metrics.organizations_with_provider_verified_email == 1
    assert metrics.organizations_with_decision_maker_role == 1
    assert metrics.organizations_with_verified_decision_maker_email == 1
    assert metrics.no_contact_found_count == 0
    assert metrics.candidates_by_role_category[
        ContactRoleCategory.PRACTICE_MANAGER.value
    ] == 1
    assert (
        metrics.candidates_by_verification_status[
            ContactVerificationStatus.PROVIDER_VERIFIED.value
        ]
        == 1
    )
    assert PROSPECT_EMAIL not in rendered
    assert PROSPECT_PHONE not in rendered
    assert "AUSTIN FAMILY MEDICINE" not in rendered
    assert "1487448189" not in rendered
    assert SECRET_VALUE not in rendered
    assert payload["live_call_attempted"] is False
    assert payload["outbound_attempted"] is False
    assert "email" not in payload
    assert "phone" not in payload


def test_no_contact_found_is_a_normal_outcome(db_session: Session) -> None:
    organization = _org(db_session)
    _service().enrich_organization(db_session, organization.id)

    metrics = ContactEnrichmentMetricsService().summarize(db_session, Settings())

    assert metrics.organizations_considered == 1
    assert metrics.organizations_with_candidate == 0
    assert metrics.no_contact_found_count == 1
    assert metrics.no_contact_found_rate == 1.0
    assert metrics.skipped_by_reason[NO_CONTACT_FOUND] == 1
    assert metrics.provider_error_count == 0


def test_provider_errors_are_bucketed_without_raw_text(db_session: Session) -> None:
    organization = _org(db_session)
    db_session.add(
        EnrichmentRun(
            organization_id=organization.id,
            source=DECISION_MAKER_SOURCE,
            status=EnrichmentRunStatus.FAILED.value,
            error_message=UNSAFE_ERROR,
            started_at=datetime.now(tz=UTC),
            finished_at=datetime.now(tz=UTC),
        )
    )
    db_session.flush()

    metrics = ContactEnrichmentMetricsService().summarize(db_session, Settings())
    rendered = format_contact_enrichment_metrics(metrics, as_json=True)

    assert metrics.organizations_considered == 1
    assert metrics.provider_error_count == 1
    assert metrics.provider_errors_by_category["unknown"] == 1
    assert metrics.no_contact_found_count == 0
    assert UNSAFE_ERROR not in rendered
    assert PROSPECT_EMAIL not in rendered
    assert SECRET_VALUE not in rendered
    assert REDACTED not in rendered or PROSPECT_EMAIL not in rendered


def test_skipped_reasons_are_generic_only(db_session: Session) -> None:
    organization = _org(db_session)
    service = _service(
        [
            candidate(full_name="Sam Rivera", title="Family Physician, MD"),
        ]
    )
    service.enrich_organization(db_session, organization.id)

    metrics = ContactEnrichmentMetricsService().summarize(db_session, Settings())
    rendered = format_contact_enrichment_metrics(metrics, as_json=True)

    assert metrics.skipped_by_reason["irrelevant_clinical"] == 1
    assert metrics.organizations_with_candidate == 0
    assert "Sam Rivera" not in rendered
    assert "Family Physician" not in rendered


def test_metrics_do_not_create_activity_or_change_halt(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    activity_before = int(db_session.scalar(select(func.count()).select_from(Activity)) or 0)
    contact_before = int(db_session.scalar(select(func.count()).select_from(Contact)) or 0)

    ContactEnrichmentMetricsService().summarize(db_session, Settings())

    assert int(db_session.scalar(select(func.count()).select_from(Activity)) or 0) == activity_before
    assert int(db_session.scalar(select(func.count()).select_from(Contact)) or 0) == contact_before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
