from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.fixtures.decision_makers import candidate
from vyro_growth.models import Contact, Organization
from vyro_growth.providers.decision_makers import StaticDecisionMakerEnrichmentProvider
from vyro_growth.workers.base import Job
from vyro_growth.workers.contact_enrichment_handler import (
    ENRICH_DECISION_MAKERS_JOB,
    EnrichDecisionMakersHandler,
)


def test_worker_enriches_one_organization(db_session: Session) -> None:
    organization = Organization(
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="1487448189",
        city="AUSTIN",
        state="TX",
        specialty="Family Medicine",
        website="https://austinfamily.example",
    )
    db_session.add(organization)
    db_session.flush()
    handler = EnrichDecisionMakersHandler(
        db=db_session,
        provider=StaticDecisionMakerEnrichmentProvider((candidate(),)),
    )

    handler.handle(
        Job(
            name=ENRICH_DECISION_MAKERS_JOB,
            payload={"organization_id": str(organization.id)},
        )
    )

    contact = db_session.scalar(select(Contact))
    assert contact is not None
    assert contact.organization_id == organization.id
    assert contact.title == "Practice Manager"


def test_worker_batch_uses_limit(db_session: Session) -> None:
    organization = Organization(
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="1487448189",
        city="AUSTIN",
        state="TX",
    )
    db_session.add(organization)
    db_session.flush()
    handler = EnrichDecisionMakersHandler(
        db=db_session,
        provider=StaticDecisionMakerEnrichmentProvider((candidate(),)),
    )

    handler.handle(Job(name=ENRICH_DECISION_MAKERS_JOB, payload={"limit": 1}))
    assert db_session.scalar(select(Contact)) is not None
