from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyro_growth.domain import (
    ContactFactType,
    EmailCandidateOrigin,
    EmailVerificationOutcome,
    EmailVerificationVerdict,
    EnrichmentRunStatus,
)
from vyro_growth.models import (
    Activity,
    Contact,
    EmailPatternCandidate,
    EnrichmentRun,
    Organization,
    OutreachMessage,
    SourceEvidence,
)
from vyro_growth.providers.email_verification import (
    StaticEmailVerificationProvider,
    StubEmailVerificationProvider,
    build_email_verification_provider,
)
from vyro_growth.services.email_verification import (
    EmailVerificationError,
    EmailVerificationService,
    contact_is_verified_safe,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

PROSPECT_EMAIL = "jordan.blake@austinfamily.example"
INFERRED_EMAIL = "sam.rivera@austinfamily.example"


def _org(db: Session, **overrides: object) -> Organization:
    values: dict[str, object] = {
        "name": "AUSTIN FAMILY MEDICINE PLLC",
        "npi": "1487448189",
        "city": "AUSTIN",
        "state": "TX",
        "specialty": "Family Medicine",
        "website": "https://austinfamily.example",
        "website_match_status": "verified",
    }
    values.update(overrides)
    organization = Organization(**values)
    db.add(organization)
    db.flush()
    return organization


def _contact(db: Session, organization: Organization, **overrides: object) -> Contact:
    values: dict[str, object] = {
        "organization_id": organization.id,
        "full_name": "Jordan Blake",
        "title": "Practice Manager",
        "email": PROSPECT_EMAIL,
        "role_category": "practice_manager",
        "role_rank": 3,
        "email_verified": False,
        "dedupe_key": f"email:{overrides.get('email', PROSPECT_EMAIL)}",
    }
    values.update(overrides)
    contact = Contact(**values)
    db.add(contact)
    db.flush()
    return contact


def test_stub_marks_stored_email_as_no_verified_email_without_failing(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    contact = _contact(db_session, organization)
    result = EmailVerificationService(StubEmailVerificationProvider()).verify_organization(
        db_session, organization.id
    )

    assert result.status is EnrichmentRunStatus.COMPLETED
    assert result.verified_count == 0
    assert result.no_verified_email_count == 1
    assert result.promoted_count == 0
    assert result.items[0].outcome is EmailVerificationOutcome.NO_VERIFIED_EMAIL
    db_session.refresh(contact)
    assert contact.email_verification_verdict == EmailVerificationVerdict.UNVERIFIED.value
    assert contact.email_verified is False
    assert contact_is_verified_safe(contact) is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == 0
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "email_verification_completed")
    )
    assert activity is not None
    assert PROSPECT_EMAIL not in str(activity.details)
    evidence = db_session.scalar(select(SourceEvidence))
    assert evidence is not None
    assert evidence.claim_type == ContactFactType.EMAIL_VERIFICATION.value
    assert evidence.extracted_value == EmailVerificationVerdict.UNVERIFIED.value
    assert PROSPECT_EMAIL not in str(evidence.metadata_json)


def test_rerun_is_idempotent_and_does_not_recall_provider(db_session: Session) -> None:
    organization = _org(db_session)
    _contact(db_session, organization)
    provider = StubEmailVerificationProvider()
    service = EmailVerificationService(provider)
    first = service.verify_organization(db_session, organization.id)
    second = service.verify_organization(db_session, organization.id)

    assert first.items[0].reused is False
    assert second.items[0].reused is True
    assert len(provider.requests) == 1
    assert db_session.scalar(select(func.count()).select_from(EnrichmentRun)) == 2


def test_unverified_source_does_not_invent_candidates(db_session: Session) -> None:
    organization = _org(db_session)
    _contact(db_session, organization)
    unnamed = _contact(
        db_session,
        organization,
        full_name="Sam Rivera",
        email=None,
        dedupe_key="name:sam rivera",
    )
    result = EmailVerificationService(StubEmailVerificationProvider()).verify_organization(
        db_session, organization.id
    )

    assert result.inferred_count == 0
    assert result.promoted_count == 0
    db_session.refresh(unnamed)
    assert unnamed.email is None
    assert db_session.scalar(select(func.count()).select_from(EmailPatternCandidate)) == 0


def test_stub_does_not_promote_inferred_guess_from_verified_source(db_session: Session) -> None:
    organization = _org(db_session)
    _contact(
        db_session,
        organization,
        email_verified=True,
        email_origin="stored",
        email_verification_verdict=EmailVerificationVerdict.VALID.value,
        email_verification_checked_at=datetime.now(tz=UTC),
        email_verification_provider="static",
    )
    target = _contact(
        db_session,
        organization,
        full_name="Sam Rivera",
        email=None,
        dedupe_key="name:sam rivera",
    )
    result = EmailVerificationService(StubEmailVerificationProvider()).verify_organization(
        db_session, organization.id
    )

    assert result.inferred_count == 1
    assert result.promoted_count == 0
    assert result.items[-1].outcome is EmailVerificationOutcome.NO_VERIFIED_EMAIL
    db_session.refresh(target)
    assert target.email is None
    candidate = db_session.scalar(select(EmailPatternCandidate))
    assert candidate is not None
    assert candidate.promoted is False
    assert candidate.origin == EmailCandidateOrigin.INFERRED.value
    assert candidate.verification_verdict == EmailVerificationVerdict.UNVERIFIED.value
    assert candidate.details_json["invented_email"] is False


def test_promotes_inferred_email_only_after_valid_verdict(db_session: Session) -> None:
    organization = _org(db_session)
    _contact(db_session, organization)
    target = _contact(
        db_session,
        organization,
        full_name="Sam Rivera",
        email=None,
        dedupe_key="name:sam rivera",
    )
    provider = StaticEmailVerificationProvider(
        {
            PROSPECT_EMAIL: EmailVerificationVerdict.VALID,
            INFERRED_EMAIL: EmailVerificationVerdict.VALID,
        }
    )
    result = EmailVerificationService(provider).verify_organization(db_session, organization.id)

    assert result.verified_count == 2
    assert result.inferred_count == 1
    assert result.promoted_count == 1
    db_session.refresh(target)
    assert target.email == INFERRED_EMAIL
    assert target.email_origin == EmailCandidateOrigin.INFERRED.value
    assert target.email_verified is True
    assert target.email_verification_verdict == EmailVerificationVerdict.VALID.value
    assert contact_is_verified_safe(target) is True
    candidate = db_session.scalar(select(EmailPatternCandidate))
    assert candidate is not None
    assert candidate.promoted is True
    evidence = db_session.scalars(
        select(SourceEvidence).where(
            SourceEvidence.claim_type == ContactFactType.EMAIL_PATTERN_INFERENCE.value
        )
    ).all()
    assert evidence
    assert all(INFERRED_EMAIL not in str(row.metadata_json) for row in evidence)


def test_invalid_inferred_candidate_is_not_promoted(db_session: Session) -> None:
    organization = _org(db_session)
    _contact(db_session, organization)
    target = _contact(
        db_session,
        organization,
        full_name="Sam Rivera",
        email=None,
        dedupe_key="name:sam rivera",
    )
    provider = StaticEmailVerificationProvider(
        {
            PROSPECT_EMAIL: EmailVerificationVerdict.VALID,
            INFERRED_EMAIL: EmailVerificationVerdict.INVALID,
        }
    )
    result = EmailVerificationService(provider).verify_organization(db_session, organization.id)

    assert result.promoted_count == 0
    assert result.items[-1].outcome is EmailVerificationOutcome.NO_VERIFIED_EMAIL
    db_session.refresh(target)
    assert target.email is None
    candidate = db_session.scalar(select(EmailPatternCandidate))
    assert candidate is not None
    assert candidate.promoted is False
    assert candidate.verification_verdict == EmailVerificationVerdict.INVALID.value


def test_factory_default_is_stub(db_session: Session) -> None:
    organization = _org(db_session)
    _contact(db_session, organization)
    result = EmailVerificationService(build_email_verification_provider()).verify_organization(
        db_session, organization.id
    )
    assert result.provider_name == "stub"
    assert result.status is EnrichmentRunStatus.COMPLETED


def test_missing_organization_raises(db_session: Session) -> None:
    service = EmailVerificationService(StubEmailVerificationProvider())
    with pytest.raises(EmailVerificationError, match="not found"):
        service.verify_organization(db_session, uuid4())
