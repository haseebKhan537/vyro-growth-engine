from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.fixtures.nppes_records import SAMPLE_ORG_RECORD, SAMPLE_ORG_RECORD_2
from vyro_growth.domain import DiscoveryRunStatus
from vyro_growth.models import Activity, DiscoveryRun, Organization, SourceEvidence
from vyro_growth.providers.nppes import (
    NPPES_MAX_SKIP,
    NormalizedNppesOrganization,
    NppesSearchPage,
    NppesSearchQuery,
)
from vyro_growth.providers.nppes_normalize import normalize_nppes_record
from vyro_growth.services.discovery import DiscoveryQueryError, NppesDiscoveryService


class FakeNppesProvider:
    def __init__(self, pages: list[NppesSearchPage]) -> None:
        self._pages = pages
        self.calls: list[NppesSearchQuery] = []

    def search_organizations(self, query: NppesSearchQuery) -> NppesSearchPage:
        self.calls.append(query)
        if not self._pages:
            return NppesSearchPage(
                results=(),
                result_count=0,
                page_size=0,
                source_url="https://example.test",
            )
        return self._pages.pop(0)


def _normalized(
    record: dict[str, Any],
    npi: str,
    name: str,
    *,
    city: str | None = "AUSTIN",
    state: str | None = "TX",
    specialty: str | None = "Chiropractor",
) -> NormalizedNppesOrganization:
    return NormalizedNppesOrganization(
        npi=npi,
        name=name,
        city=city,
        state=state,
        specialty=specialty,
        source_url="https://example.test",
        query_metadata={"query": {"state": "TX", "city": "Austin"}, "npi": npi},
        business_record={
            "npi": npi,
            "organization_name": name,
            "city": city,
            "state": state,
            "specialty": specialty,
        },
    )


def test_discovery_service_paginates_and_persists(db_session: Session) -> None:
    provider = FakeNppesProvider(
        [
            NppesSearchPage(
                results=(_normalized(SAMPLE_ORG_RECORD, "1487448189", "100 CHIRO CORONA LLC"),),
                result_count=2,
                page_size=1,
                source_url="https://example.test?page=1",
            ),
            NppesSearchPage(
                results=(
                    _normalized(
                        SAMPLE_ORG_RECORD_2,
                        "1234567890",
                        "AUSTIN FAMILY MEDICINE PLLC",
                    ),
                ),
                result_count=2,
                page_size=1,
                source_url="https://example.test?page=2",
            ),
        ]
    )
    service = NppesDiscoveryService(provider, max_records_per_run=500)

    result = service.run(
        db_session,
        query=NppesSearchQuery(state="TX", city="Austin", limit=1),
        max_records=10,
    )

    assert result.records_fetched == 2
    assert result.records_upserted == 2
    assert result.status == DiscoveryRunStatus.COMPLETED
    assert len(provider.calls) == 3
    assert provider.calls[1].skip == 1

    organizations = db_session.scalars(select(Organization)).all()
    assert len(organizations) == 2
    evidence = db_session.scalars(select(SourceEvidence)).all()
    assert len(evidence) == 2
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "nppes_discovery_completed")
    )
    assert activity is not None
    assert activity.details["records_fetched"] == 2


def test_discovery_service_deduplicates_duplicate_npis(db_session: Session) -> None:
    duplicate = _normalized(SAMPLE_ORG_RECORD, "1487448189", "100 CHIRO CORONA LLC")
    provider = FakeNppesProvider(
        [
            NppesSearchPage(
                results=(duplicate, duplicate),
                result_count=2,
                page_size=2,
                source_url="https://example.test",
            )
        ]
    )
    service = NppesDiscoveryService(provider, max_records_per_run=500)

    result = service.run(db_session, query=NppesSearchQuery(state="TX", city="Austin"))

    assert result.records_fetched == 1
    assert result.records_skipped == 1
    assert db_session.scalar(select(Organization).where(Organization.npi == "1487448189"))


def test_discovery_service_enforces_run_limit(db_session: Session) -> None:
    provider = FakeNppesProvider(
        [
            NppesSearchPage(
                results=(
                    _normalized(SAMPLE_ORG_RECORD, "1487448189", "100 CHIRO CORONA LLC"),
                    _normalized(SAMPLE_ORG_RECORD_2, "1234567890", "AUSTIN FAMILY MEDICINE PLLC"),
                ),
                result_count=2,
                page_size=2,
                source_url="https://example.test",
            )
        ]
    )
    service = NppesDiscoveryService(provider, max_records_per_run=500)

    result = service.run(
        db_session,
        query=NppesSearchQuery(state="TX", city="Austin"),
        max_records=1,
    )

    assert result.records_fetched == 1
    assert len(db_session.scalars(select(Organization)).all()) == 1
    assert provider.calls[0].limit == 200


def test_discovery_service_is_idempotent_on_rerun(db_session: Session) -> None:
    provider = FakeNppesProvider(
        [
            NppesSearchPage(
                results=(_normalized(SAMPLE_ORG_RECORD, "1487448189", "100 CHIRO CORONA LLC"),),
                result_count=1,
                page_size=1,
                source_url="https://example.test/run-1",
            )
        ]
    )
    service = NppesDiscoveryService(provider, max_records_per_run=500)
    first = service.run(db_session, query=NppesSearchQuery(state="TX", city="Austin"))

    provider._pages.append(
        NppesSearchPage(
            results=(
                _normalized(
                    SAMPLE_ORG_RECORD,
                    "1487448189",
                    "100 CHIRO CORONA LLC UPDATED",
                ),
            ),
            result_count=1,
            page_size=1,
            source_url="https://example.test/run-2",
        )
    )
    second = service.run(db_session, query=NppesSearchQuery(state="TX", city="Austin"))

    organization = db_session.scalar(select(Organization).where(Organization.npi == "1487448189"))
    evidence_count = len(db_session.scalars(select(SourceEvidence)).all())

    assert first.records_upserted == 1
    assert second.records_upserted == 1
    assert organization is not None
    assert organization.name == "100 CHIRO CORONA LLC UPDATED"
    assert evidence_count == 2
    assert len(db_session.scalars(select(DiscoveryRun)).all()) == 2


def test_discovery_service_records_failed_run(db_session: Session) -> None:
    class FailingProvider:
        def search_organizations(self, query: NppesSearchQuery) -> NppesSearchPage:
            raise RuntimeError("nppes unavailable")

    service = NppesDiscoveryService(FailingProvider(), max_records_per_run=500)

    with pytest.raises(RuntimeError, match="nppes unavailable"):
        service.run(db_session, query=NppesSearchQuery(state="TX", city="Austin"))

    run = db_session.scalar(select(DiscoveryRun))
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "nppes_discovery_failed")
    )
    assert run is not None
    assert run.status == DiscoveryRunStatus.FAILED.value
    assert run.error_message == "nppes unavailable"
    assert run.finished_at is not None
    assert activity is not None


def test_discovery_service_requires_targeting_filter(db_session: Session) -> None:
    service = NppesDiscoveryService(FakeNppesProvider([]), max_records_per_run=500)

    with pytest.raises(DiscoveryQueryError, match="narrow filter"):
        service.run(db_session, query=NppesSearchQuery())


def test_discovery_service_rejects_state_only_query(db_session: Session) -> None:
    service = NppesDiscoveryService(FakeNppesProvider([]), max_records_per_run=500)

    with pytest.raises(DiscoveryQueryError, match="state alone is not sufficient"):
        service.run(db_session, query=NppesSearchQuery(state="TX"))


def test_discovery_service_rejects_whitespace_only_narrow_filters(db_session: Session) -> None:
    service = NppesDiscoveryService(FakeNppesProvider([]), max_records_per_run=500)

    with pytest.raises(DiscoveryQueryError, match="state alone is not sufficient"):
        service.run(db_session, query=NppesSearchQuery(state="TX", city="   "))


def test_discovery_service_does_not_persist_authorized_official_pii(
    db_session: Session,
) -> None:
    query = NppesSearchQuery(state="TX", city="Austin")
    normalized = normalize_nppes_record(
        SAMPLE_ORG_RECORD,
        source_url="https://example.test",
        query=query,
    )
    assert normalized is not None
    assert SAMPLE_ORG_RECORD["basic"]["authorized_official_first_name"] == "CHRIS"
    assert SAMPLE_ORG_RECORD["basic"]["authorized_official_telephone_number"] == "5126388544"
    assert "CHRIS" not in str(normalized.business_record)
    assert "5126388544" not in str(normalized.business_record)
    assert "authorized_official" not in str(normalized.business_record)
    assert "CHRIS" not in str(normalized.query_metadata)

    provider = FakeNppesProvider(
        [
            NppesSearchPage(
                results=(normalized,),
                result_count=1,
                page_size=1,
                source_url="https://example.test",
            )
        ]
    )
    service = NppesDiscoveryService(provider, max_records_per_run=500)
    service.run(db_session, query=query)

    evidence = db_session.scalar(select(SourceEvidence))
    organization = db_session.scalar(select(Organization).where(Organization.npi == "1487448189"))
    assert evidence is not None
    assert organization is not None
    dumped = str(evidence.metadata_json)
    assert "authorized_official" not in dumped
    assert "CHRIS" not in dumped
    assert "5126388544" not in dumped
    assert "Owner" not in dumped
    assert evidence.metadata_json["npi"] == "1487448189"
    assert evidence.metadata_json["business_record"]["organization_name"] == "100 CHIRO CORONA LLC"
    assert evidence.source_url == "https://example.test"
    assert organization.name == "100 CHIRO CORONA LLC"


def test_discovery_continues_when_raw_page_has_no_kept_rows(db_session: Session) -> None:
    provider = FakeNppesProvider(
        [
            NppesSearchPage(
                results=(),
                result_count=3,
                page_size=2,
                source_url="https://example.test?page=1",
            ),
            NppesSearchPage(
                results=(_normalized(SAMPLE_ORG_RECORD, "1487448189", "100 CHIRO CORONA LLC"),),
                result_count=3,
                page_size=1,
                source_url="https://example.test?page=2",
            ),
        ]
    )
    service = NppesDiscoveryService(provider, max_records_per_run=500)

    result = service.run(
        db_session,
        query=NppesSearchQuery(state="TX", city="Austin", limit=2),
        max_records=10,
    )

    assert result.records_fetched == 1
    assert result.status == DiscoveryRunStatus.COMPLETED
    assert len(provider.calls) == 2
    assert provider.calls[1].skip == 2
    assert db_session.scalar(select(Organization).where(Organization.npi == "1487448189"))


def test_discovery_stops_cleanly_at_skip_ceiling(db_session: Session) -> None:
    provider = FakeNppesProvider(
        [
            NppesSearchPage(
                results=(_normalized(SAMPLE_ORG_RECORD, "1487448189", "100 CHIRO CORONA LLC"),),
                result_count=400,
                page_size=200,
                source_url="https://example.test",
            ),
            NppesSearchPage(
                results=(_normalized(SAMPLE_ORG_RECORD_2, "1234567890", "SHOULD NOT FETCH"),),
                result_count=400,
                page_size=200,
                source_url="https://example.test?unexpected",
            ),
        ]
    )
    service = NppesDiscoveryService(provider, max_records_per_run=500)

    result = service.run(
        db_session,
        query=NppesSearchQuery(state="TX", city="Austin", skip=NPPES_MAX_SKIP, limit=200),
        max_records=500,
    )

    assert result.status == DiscoveryRunStatus.COMPLETED
    assert len(provider.calls) == 1
    assert provider.calls[0].skip == NPPES_MAX_SKIP
    assert result.records_fetched == 1


def test_discovery_does_not_request_beyond_skip_ceiling(db_session: Session) -> None:
    provider = FakeNppesProvider(
        [
            NppesSearchPage(
                results=(_normalized(SAMPLE_ORG_RECORD, "1487448189", "SHOULD NOT FETCH"),),
                result_count=1,
                page_size=1,
                source_url="https://example.test",
            )
        ]
    )
    service = NppesDiscoveryService(provider, max_records_per_run=500)

    result = service.run(
        db_session,
        query=NppesSearchQuery(state="TX", city="Austin", skip=NPPES_MAX_SKIP + 1),
        max_records=10,
    )

    assert result.status == DiscoveryRunStatus.COMPLETED
    assert result.records_fetched == 0
    assert provider.calls == []


def test_discovery_upsert_preserves_existing_fields_on_sparse_rerun(
    db_session: Session,
) -> None:
    provider = FakeNppesProvider(
        [
            NppesSearchPage(
                results=(_normalized(SAMPLE_ORG_RECORD, "1487448189", "100 CHIRO CORONA LLC"),),
                result_count=1,
                page_size=1,
                source_url="https://example.test/run-1",
            )
        ]
    )
    service = NppesDiscoveryService(provider, max_records_per_run=500)
    service.run(db_session, query=NppesSearchQuery(state="TX", city="Austin"))

    provider._pages.append(
        NppesSearchPage(
            results=(
                _normalized(
                    SAMPLE_ORG_RECORD,
                    "1487448189",
                    "100 CHIRO CORONA LLC UPDATED",
                    city=None,
                    state=None,
                    specialty=None,
                ),
            ),
            result_count=1,
            page_size=1,
            source_url="https://example.test/run-2",
        )
    )
    service.run(db_session, query=NppesSearchQuery(state="TX", city="Austin"))

    organization = db_session.scalar(select(Organization).where(Organization.npi == "1487448189"))
    assert organization is not None
    assert organization.name == "100 CHIRO CORONA LLC UPDATED"
    assert organization.city == "AUSTIN"
    assert organization.state == "TX"
    assert organization.specialty == "Chiropractor"


def test_discovery_upsert_truncates_fields_to_db_lengths(db_session: Session) -> None:
    long_name = "N" * 400
    long_city = "C" * 200
    long_specialty = "S" * 400
    provider = FakeNppesProvider(
        [
            NppesSearchPage(
                results=(
                    _normalized(
                        SAMPLE_ORG_RECORD,
                        "1487448189",
                        long_name,
                        city=long_city,
                        state="TEXAS",
                        specialty=long_specialty,
                    ),
                ),
                result_count=1,
                page_size=1,
                source_url="https://example.test",
            )
        ]
    )
    service = NppesDiscoveryService(provider, max_records_per_run=500)
    service.run(db_session, query=NppesSearchQuery(state="TX", city="Austin"))

    organization = db_session.scalar(select(Organization).where(Organization.npi == "1487448189"))
    assert organization is not None
    assert len(organization.name) == 255
    assert organization.city is not None
    assert len(organization.city) == 120
    assert organization.state == "TE"
    assert organization.specialty is not None
    assert len(organization.specialty) == 255
