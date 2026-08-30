from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.models import Organization, PersonalizationDraft, SourceEvidence
from vyro_growth.providers.personalization import StubPersonalizationProvider
from vyro_growth.workers.base import Job
from vyro_growth.workers.personalization_handler import (
    PERSONALIZE_SCORED_LEADS_JOB,
    PersonalizeScoredLeadsHandler,
)


def test_worker_personalizes_one_organization(db_session: Session) -> None:
    organization = Organization(
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="1487448189",
        city="AUSTIN",
        state="TX",
        specialty="Family Medicine",
    )
    db_session.add(organization)
    db_session.flush()
    db_session.add(
        SourceEvidence(
            organization_id=organization.id,
            source_url="https://npiregistry.cms.hhs.gov/api/",
            claim_type="nppes_organization_record",
            extracted_value=organization.name,
            metadata_json={"business_record": {"status": "A"}},
        )
    )
    db_session.flush()
    handler = PersonalizeScoredLeadsHandler(
        db=db_session,
        provider=StubPersonalizationProvider(),
    )

    handler.handle(
        Job(
            name=PERSONALIZE_SCORED_LEADS_JOB,
            payload={"organization_id": str(organization.id)},
        )
    )

    draft = db_session.scalar(select(PersonalizationDraft))
    assert draft is not None
    assert draft.organization_id == organization.id


def test_worker_batch_uses_limit(db_session: Session) -> None:
    organization = Organization(
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="1487448189",
        city="AUSTIN",
        state="TX",
        specialty="Family Medicine",
    )
    db_session.add(organization)
    db_session.flush()
    handler = PersonalizeScoredLeadsHandler(
        db=db_session,
        provider=StubPersonalizationProvider(),
    )

    handler.handle(Job(name=PERSONALIZE_SCORED_LEADS_JOB, payload={"limit": 1}))
    assert db_session.scalar(select(PersonalizationDraft)) is not None
