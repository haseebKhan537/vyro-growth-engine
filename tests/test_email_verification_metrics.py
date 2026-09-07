from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_email_verification_service import INFERRED_EMAIL, PROSPECT_EMAIL, _contact, _org
from vyro_growth.config import Settings
from vyro_growth.domain import EmailVerificationVerdict, EnrichmentRunStatus
from vyro_growth.models import Activity, Contact, EnrichmentRun
from vyro_growth.observability import REDACTED
from vyro_growth.providers.email_verification import (
    EMAIL_VERIFICATION_SOURCE,
    NO_VERIFIED_EMAIL,
    StaticEmailVerificationProvider,
)
from vyro_growth.services.email_verification import EmailVerificationService
from vyro_growth.services.email_verification_metrics import (
    EmailVerificationMetricsService,
    format_email_verification_metrics,
    metrics_payload,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

SECRET_VALUE = "sk-testsecret-email-metrics"
UNSAFE_ERROR = "lookup failed for jordan.blake@austinfamily.example token=sk-testsecret"


def test_empty_metrics_are_sanitized_counts_only(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    metrics = EmailVerificationMetricsService().summarize(db_session, Settings())

    assert metrics.contacts_considered == 0
    assert metrics.contacts_with_verified_safe_email == 0
    assert metrics.no_verified_email_count == 0
    assert metrics.provider_error_count == 0
    assert metrics.verified_email_rate == 0.0
    assert metrics.read_only is True
    assert metrics.outbound_attempted is False
    assert metrics.live_call_attempted is False
    assert metrics.smtp_attempted is False
    assert metrics.execution_allowed is False
    assert metrics.owner_approved is False
    assert metrics.halt_changed is False
    assert metrics.outbound_enabled is False
    assert metrics.email_verification_live_enabled is False
    assert metrics.email_verification_smtp_enabled is False
    assert metrics.email_verification_is_not_outbound is True
    assert metrics.live_providers["email_verification"] is False
    assert metrics.operator_halt_before == HaltStatus.HALTED.value
    assert metrics.operator_halt_after == HaltStatus.HALTED.value
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_funnel_counts_verified_and_inferred_outcomes(db_session: Session) -> None:
    organization = _org(db_session)
    _contact(db_session, organization)
    _contact(
        db_session,
        organization,
        full_name="Sam Rivera",
        email=None,
        dedupe_key="name:sam rivera",
    )
    EmailVerificationService(
        StaticEmailVerificationProvider(
            {
                PROSPECT_EMAIL: EmailVerificationVerdict.VALID,
                INFERRED_EMAIL: EmailVerificationVerdict.UNVERIFIED,
            }
        )
    ).verify_organization(db_session, organization.id)

    metrics = EmailVerificationMetricsService().summarize(db_session, Settings())
    payload = metrics_payload(metrics)
    rendered = format_email_verification_metrics(metrics, as_json=True)

    assert metrics.contacts_considered == 2
    assert metrics.contacts_with_business_email == 1
    assert metrics.contacts_with_verified_safe_email == 1
    assert metrics.no_verified_email_count == 0
    assert metrics.inferred_candidate_count == 1
    assert metrics.inferred_unverified_count == 1
    assert metrics.inferred_promoted_count == 0
    assert metrics.verified_email_rate == 1.0
    assert metrics.skipped_by_reason[NO_VERIFIED_EMAIL] >= 1
    assert PROSPECT_EMAIL not in rendered
    assert INFERRED_EMAIL not in rendered
    assert "AUSTIN FAMILY MEDICINE" not in rendered
    assert "1487448189" not in rendered
    assert SECRET_VALUE not in rendered
    assert payload["live_call_attempted"] is False
    assert payload["smtp_attempted"] is False
    assert payload["outbound_attempted"] is False
    assert "email" not in payload
    assert "phone" not in payload


def test_no_verified_email_is_a_normal_outcome(db_session: Session) -> None:
    organization = _org(db_session)
    _contact(db_session, organization)
    EmailVerificationService(StaticEmailVerificationProvider()).verify_organization(
        db_session, organization.id
    )

    metrics = EmailVerificationMetricsService().summarize(db_session, Settings())

    assert metrics.contacts_considered == 1
    assert metrics.contacts_with_verified_safe_email == 0
    assert metrics.no_verified_email_count == 1
    assert metrics.no_verified_email_rate == 1.0
    assert metrics.skipped_by_reason[NO_VERIFIED_EMAIL] == 1
    assert metrics.provider_error_count == 0


def test_provider_errors_are_bucketed_without_raw_text(db_session: Session) -> None:
    organization = _org(db_session)
    db_session.add(
        EnrichmentRun(
            organization_id=organization.id,
            source=EMAIL_VERIFICATION_SOURCE,
            status=EnrichmentRunStatus.FAILED.value,
            error_message=UNSAFE_ERROR,
            started_at=datetime.now(tz=UTC),
            finished_at=datetime.now(tz=UTC),
        )
    )
    db_session.flush()

    metrics = EmailVerificationMetricsService().summarize(db_session, Settings())
    rendered = format_email_verification_metrics(metrics, as_json=True)

    assert metrics.provider_error_count == 1
    assert metrics.provider_errors_by_category["unknown"] == 1
    assert UNSAFE_ERROR not in rendered
    assert PROSPECT_EMAIL not in rendered
    assert SECRET_VALUE not in rendered
    assert REDACTED not in rendered or PROSPECT_EMAIL not in rendered


def test_metrics_do_not_create_activity_or_change_halt(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    activity_before = int(db_session.scalar(select(func.count()).select_from(Activity)) or 0)
    contact_before = int(db_session.scalar(select(func.count()).select_from(Contact)) or 0)

    EmailVerificationMetricsService().summarize(db_session, Settings())

    activity_after = int(db_session.scalar(select(func.count()).select_from(Activity)) or 0)
    contact_after = int(db_session.scalar(select(func.count()).select_from(Contact)) or 0)
    assert activity_after == activity_before
    assert contact_after == contact_before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
