from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.fixtures.website_pages import VERIFIED_HOME_HTML, page
from vyro_growth.models import Organization, SourceEvidence
from vyro_growth.providers.website import (
    StaticPublicPageFetcher,
    StaticWebsiteSearchProvider,
    WebsiteCandidate,
)
from vyro_growth.services.website_enrichment import WebsiteEnrichmentError
from vyro_growth.workers.base import Job
from vyro_growth.workers.website_enrichment_handler import (
    ENRICH_ORGANIZATION_WEBSITES_JOB,
    EnrichOrganizationWebsitesHandler,
)

VERIFIED_URL = "https://austinfamilymedicine.com"


def test_worker_enriches_one_organization(db_session: Session) -> None:
    organization = Organization(
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="1487448189",
        city="AUSTIN",
        state="TX",
        specialty="Family Medicine",
    )
    db_session.add(organization)
    db_session.flush()
    handler = EnrichOrganizationWebsitesHandler(
        db=db_session,
        search_provider=StaticWebsiteSearchProvider(
            (WebsiteCandidate(url=VERIFIED_URL, source="search"),)
        ),
        page_fetcher=StaticPublicPageFetcher(
            {VERIFIED_URL: page(VERIFIED_URL, VERIFIED_HOME_HTML)}
        ),
    )

    handler.handle(
        Job(
            name=ENRICH_ORGANIZATION_WEBSITES_JOB,
            payload={"organization_id": str(organization.id)},
        )
    )

    db_session.refresh(organization)
    assert organization.website == VERIFIED_URL
    assert db_session.scalar(select(SourceEvidence)) is not None


def test_worker_batch_uses_limit(db_session: Session) -> None:
    organization = Organization(
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="1487448189",
        city="AUSTIN",
        state="TX",
    )
    db_session.add(organization)
    db_session.flush()
    handler = EnrichOrganizationWebsitesHandler(
        db=db_session,
        search_provider=StaticWebsiteSearchProvider(
            (WebsiteCandidate(url=VERIFIED_URL, source="search"),)
        ),
        page_fetcher=StaticPublicPageFetcher(
            {VERIFIED_URL: page(VERIFIED_URL, VERIFIED_HOME_HTML)}
        ),
    )

    handler.handle(Job(name=ENRICH_ORGANIZATION_WEBSITES_JOB, payload={"limit": 1}))
    db_session.refresh(organization)
    assert organization.website_match_status == "verified"


def test_worker_requires_organization_for_candidate_url(db_session: Session) -> None:
    handler = EnrichOrganizationWebsitesHandler(db=db_session)
    with pytest.raises(WebsiteEnrichmentError, match="candidate_url requires"):
        handler.handle(
            Job(
                name=ENRICH_ORGANIZATION_WEBSITES_JOB,
                payload={"candidate_url": VERIFIED_URL},
            )
        )
