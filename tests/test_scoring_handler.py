from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.models import Lead, LeadScore, Organization, SourceEvidence
from vyro_growth.services.lead_scoring import LeadScoringError
from vyro_growth.workers.base import Job
from vyro_growth.workers.scoring_handler import (
    SCORE_DISCOVERED_LEADS_JOB,
    ScoreDiscoveredLeadsHandler,
)


def _seed_organization(db: Session) -> Organization:
    organization = Organization(
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="1487448189",
        city="AUSTIN",
        state="TX",
        specialty="Family Medicine",
    )
    db.add(organization)
    db.flush()
    db.add(
        SourceEvidence(
            organization_id=organization.id,
            source_url="https://npiregistry.cms.hhs.gov/api/",
            claim_type="nppes_organization_record",
            extracted_value=organization.name,
            metadata_json={"business_record": {"status": "A"}},
        )
    )
    db.flush()
    return organization


def test_worker_handler_scores_organization(db_session: Session) -> None:
    organization = _seed_organization(db_session)
    handler = ScoreDiscoveredLeadsHandler(db=db_session)

    handler.handle(
        Job(
            name=SCORE_DISCOVERED_LEADS_JOB,
            payload={"organization_id": str(organization.id)},
        )
    )

    lead = db_session.scalar(select(Lead).where(Lead.organization_id == organization.id))
    score_row = db_session.scalar(select(LeadScore))
    assert lead is not None
    assert score_row is not None
    assert score_row.lead_id == lead.id


def test_worker_handler_scores_existing_lead(db_session: Session) -> None:
    organization = _seed_organization(db_session)
    lead = Lead(organization_id=organization.id, stage="discovered", source="nppes")
    db_session.add(lead)
    db_session.flush()
    handler = ScoreDiscoveredLeadsHandler(db=db_session)

    handler.handle(
        Job(
            name=SCORE_DISCOVERED_LEADS_JOB,
            payload={"lead_id": lead.id},
        )
    )

    score_row = db_session.scalar(select(LeadScore).where(LeadScore.lead_id == lead.id))
    assert score_row is not None


def test_worker_handler_batch_scores_with_limit(db_session: Session) -> None:
    _seed_organization(db_session)
    handler = ScoreDiscoveredLeadsHandler(db=db_session)

    handler.handle(Job(name=SCORE_DISCOVERED_LEADS_JOB, payload={"limit": 1}))

    assert db_session.scalar(select(LeadScore)) is not None


def test_worker_handler_rejects_both_ids(db_session: Session) -> None:
    handler = ScoreDiscoveredLeadsHandler(db=db_session)

    with pytest.raises(LeadScoringError, match="not both"):
        handler.handle(
            Job(
                name=SCORE_DISCOVERED_LEADS_JOB,
                payload={
                    "lead_id": "11111111-1111-1111-1111-111111111111",
                    "organization_id": "22222222-2222-2222-2222-222222222222",
                },
            )
        )
