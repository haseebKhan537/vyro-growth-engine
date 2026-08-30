from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.fixtures.website_pages import (
    NAME_ONLY_HTML,
    NO_OPTIONAL_FACTS_HTML,
    UNRELATED_HTML,
    VERIFIED_HOME_HTML,
    WRONG_CITY_HTML,
    page,
)
from vyro_growth.domain import EnrichmentRunStatus, WebsiteFactType, WebsiteMatchStatus
from vyro_growth.models import Activity, Contact, EnrichmentRun, Organization, SourceEvidence
from vyro_growth.providers.website import (
    StaticPublicPageFetcher,
    StaticWebsiteSearchProvider,
    WebsiteCandidate,
    WebsiteFetchError,
)
from vyro_growth.services.website_enrichment import (
    WebsiteEnrichmentError,
    WebsiteEnrichmentService,
)

VERIFIED_URL = "https://austinfamilymedicine.com"
WRONG_CITY_URL = "https://dallas.example.com"
UNRELATED_URL = "https://sunrisecoffee.example"
NAME_ONLY_URL = "https://name-only.example"


def _org(db: Session, **overrides: object) -> Organization:
    values: dict[str, object] = {
        "name": "AUSTIN FAMILY MEDICINE PLLC",
        "npi": "1487448189",
        "city": "AUSTIN",
        "state": "TX",
        "specialty": "Family Medicine",
    }
    values.update(overrides)
    organization = Organization(**values)
    db.add(organization)
    db.flush()
    return organization


def _service(
    pages: dict[str, object],
    candidates: list[WebsiteCandidate] | None = None,
) -> WebsiteEnrichmentService:
    return WebsiteEnrichmentService(
        StaticWebsiteSearchProvider(candidates or ()),
        StaticPublicPageFetcher(pages),  # type: ignore[arg-type]
        max_pages_per_org=5,
    )


def test_verified_enrichment_sets_website_and_evidence(db_session: Session) -> None:
    organization = _org(db_session)
    service = _service(
        {VERIFIED_URL: page(VERIFIED_URL, VERIFIED_HOME_HTML)},
        [WebsiteCandidate(url=VERIFIED_URL, source="search")],
    )

    result = service.enrich_organization(db_session, organization.id)

    db_session.refresh(organization)
    assert result.match_status is WebsiteMatchStatus.VERIFIED
    assert result.status is EnrichmentRunStatus.COMPLETED
    assert organization.website == VERIFIED_URL
    assert organization.website_match_status == WebsiteMatchStatus.VERIFIED.value
    assert result.facts_extracted >= 6

    evidence = db_session.scalars(
        select(SourceEvidence).where(SourceEvidence.organization_id == organization.id)
    ).all()
    claim_types = {row.claim_type for row in evidence}
    assert WebsiteFactType.WEBSITE_MATCH.value in claim_types
    assert WebsiteFactType.OFFICIAL_WEBSITE.value in claim_types
    assert WebsiteFactType.BUSINESS_PHONE.value in claim_types
    assert WebsiteFactType.BILLING_SIGNAL.value in claim_types
    for row in evidence:
        assert row.source_url
        assert row.confidence is not None
        assert row.evidence_snippet is not None or row.claim_type == WebsiteFactType.WEBSITE_MATCH.value
        assert row.metadata_json.get("fabricated") is False
        assert row.enrichment_run_id == result.enrichment_run_id

    activity = db_session.scalar(
        select(Activity).where(Activity.action == "website_enrichment_completed")
    )
    assert activity is not None
    assert activity.details["fabricated_facts"] is False
    assert db_session.scalar(select(Contact)) is None


def test_ambiguous_and_no_match_do_not_set_website(db_session: Session) -> None:
    ambiguous_org = _org(db_session, npi="1111111111")
    missing_org = Organization(
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="2222222222",
        city="AUSTIN",
        state="TX",
        specialty="Family Medicine",
    )
    db_session.add(missing_org)
    db_session.flush()

    ambiguous = _service(
        {NAME_ONLY_URL: page(NAME_ONLY_URL, NAME_ONLY_HTML)},
        [WebsiteCandidate(url=NAME_ONLY_URL, source="search")],
    ).enrich_organization(db_session, ambiguous_org.id)
    missing = _service(
        {UNRELATED_URL: page(UNRELATED_URL, UNRELATED_HTML)},
        [WebsiteCandidate(url=UNRELATED_URL, source="search")],
    ).enrich_organization(db_session, missing_org.id)

    db_session.refresh(ambiguous_org)
    db_session.refresh(missing_org)
    assert ambiguous.match_status is WebsiteMatchStatus.AMBIGUOUS
    assert missing.match_status is WebsiteMatchStatus.NO_MATCH
    assert ambiguous_org.website is None
    assert missing_org.website is None
    assert ambiguous_org.website_match_status == WebsiteMatchStatus.AMBIGUOUS.value
    assert missing_org.website_match_status == WebsiteMatchStatus.NO_MATCH.value


def test_wrong_city_is_ambiguous(db_session: Session) -> None:
    organization = _org(db_session)
    result = _service(
        {WRONG_CITY_URL: page(WRONG_CITY_URL, WRONG_CITY_HTML)},
        [WebsiteCandidate(url=WRONG_CITY_URL, source="search")],
    ).enrich_organization(db_session, organization.id)
    db_session.refresh(organization)
    assert result.match_status is WebsiteMatchStatus.AMBIGUOUS
    assert organization.website is None


def test_blocked_and_failed_candidates_become_no_match(db_session: Session) -> None:
    organization = _org(db_session)
    result = _service(
        {},
        [
            WebsiteCandidate(url="https://clinic.example/patient-portal", source="search"),
            WebsiteCandidate(url="https://www.healthgrades.com/x", source="search"),
            WebsiteCandidate(url="https://missing.example", source="search"),
        ],
    ).enrich_organization(db_session, organization.id)
    assert result.match_status is WebsiteMatchStatus.NO_MATCH
    assert result.pages_fetched == 0
    run = db_session.get(EnrichmentRun, result.enrichment_run_id)
    assert run is not None
    match_row = db_session.scalar(
        select(SourceEvidence).where(SourceEvidence.claim_type == "website_match")
    )
    assert match_row is not None
    errors = match_row.metadata_json["fetch_errors"]
    assert any(item["error"] == "blocked_public_path" for item in errors)
    assert any(item["error"] == "directory_host" for item in errors)


def test_does_not_invent_facts_or_wipe_existing_website(db_session: Session) -> None:
    organization = _org(db_session, website="https://already-set.example")
    result = _service(
        {UNRELATED_URL: page(UNRELATED_URL, UNRELATED_HTML)},
        [WebsiteCandidate(url=UNRELATED_URL, source="search")],
    ).enrich_organization(db_session, organization.id)
    db_session.refresh(organization)
    assert result.match_status is WebsiteMatchStatus.NO_MATCH
    assert organization.website == "https://already-set.example"
    fact_rows = db_session.scalars(
        select(SourceEvidence).where(
            SourceEvidence.claim_type.in_(
                [
                    WebsiteFactType.BUSINESS_PHONE.value,
                    WebsiteFactType.BUSINESS_EMAIL.value,
                    WebsiteFactType.BILLING_SIGNAL.value,
                ]
            )
        )
    ).all()
    assert fact_rows == []


def test_operator_candidate_is_preferred_and_skip_verified(db_session: Session) -> None:
    organization = _org(db_session)
    service = _service(
        {
            VERIFIED_URL: page(VERIFIED_URL, VERIFIED_HOME_HTML),
            NAME_ONLY_URL: page(NAME_ONLY_URL, NAME_ONLY_HTML),
        },
        [WebsiteCandidate(url=NAME_ONLY_URL, source="search")],
    )
    first = service.enrich_organization(
        db_session,
        organization.id,
        candidate_url=VERIFIED_URL,
    )
    assert first.match_status is WebsiteMatchStatus.VERIFIED
    skipped = service.enrich_organization(db_session, organization.id, skip_verified=True)
    assert skipped.facts_extracted == 0
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "website_enrichment_skipped")
    )
    assert activity is not None


def test_fetch_error_on_all_pages_is_no_match(db_session: Session) -> None:
    organization = _org(db_session)
    result = _service(
        {VERIFIED_URL: WebsiteFetchError("timed out")},
        [WebsiteCandidate(url=VERIFIED_URL, source="search")],
    ).enrich_organization(db_session, organization.id)
    assert result.match_status is WebsiteMatchStatus.NO_MATCH
    assert result.pages_fetched == 0


def test_missing_organization_raises(db_session: Session) -> None:
    service = _service({})
    with pytest.raises(WebsiteEnrichmentError, match="not found"):
        service.enrich_organization(db_session, uuid4())


def test_batch_skips_verified_and_respects_limit(db_session: Session) -> None:
    first = _org(db_session, npi="1000000001")
    second = Organization(
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="1000000002",
        city="AUSTIN",
        state="TX",
        specialty="Family Medicine",
        website_match_status=WebsiteMatchStatus.VERIFIED.value,
        website=VERIFIED_URL,
    )
    db_session.add(second)
    db_session.flush()
    results = _service(
        {VERIFIED_URL: page(VERIFIED_URL, NO_OPTIONAL_FACTS_HTML)},
        [WebsiteCandidate(url=VERIFIED_URL, source="search")],
    ).enrich_batch(db_session, limit=10)
    ids = {item.organization_id for item in results}
    assert first.id in ids
    assert second.id not in ids
