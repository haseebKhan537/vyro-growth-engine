from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.fixtures.nppes_records import SAMPLE_ORG_RECORD, SAMPLE_ORG_RECORD_2
from vyro_growth.domain import DiscoveryRunStatus
from vyro_growth.models import DiscoveryRun, Organization, SourceEvidence
from vyro_growth.providers.nppes import (
    NormalizedNppesOrganization,
    NppesSearchPage,
    NppesSearchQuery,
)
from vyro_growth.services.discovery import NppesDiscoveryService


class FakeNppesProvider:
    def __init__(self, pages: list[NppesSearchPage]) -> None:
        self._pages = pages
        self.calls: list[NppesSearchQuery] = []

    def search_organizations(self, query: NppesSearchQuery) -> NppesSearchPage:
        self.calls.append(query)
        if not self._pages:
            return NppesSearchPage(results=(), result_count=0, source_url="https://example.test")
        return self._pages.pop(0)


def _normalized(record: dict[str, Any], npi: str, name: str) -> NormalizedNppesOrganization:
    return NormalizedNppesOrganization(
        npi=npi,
        name=name,
        city="AUSTIN",
        state="TX",
        specialty="Chiropractor",
        source_url="https://example.test",
        query_metadata={"query": {"state": "TX"}, "npi": npi},
        raw_record=record,
    )


def test_discovery_service_paginates_and_persists(db_session: Session) -> None:
    provider = FakeNppesProvider(
        [
            NppesSearchPage(
                results=(_normalized(SAMPLE_ORG_RECORD, "1487448189", "100 CHIRO CORONA LLC"),),
                result_count=2,
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


def test_discovery_service_deduplicates_duplicate_npis(db_session: Session) -> None:
    duplicate = _normalized(SAMPLE_ORG_RECORD, "1487448189", "100 CHIRO CORONA LLC")
    provider = FakeNppesProvider(
        [
            NppesSearchPage(
                results=(duplicate, duplicate),
                result_count=2,
                source_url="https://example.test",
            )
        ]
    )
    service = NppesDiscoveryService(provider, max_records_per_run=500)

    result = service.run(db_session, query=NppesSearchQuery(state="TX"))

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
                source_url="https://example.test",
            )
        ]
    )
    service = NppesDiscoveryService(provider, max_records_per_run=500)

    result = service.run(
        db_session,
        query=NppesSearchQuery(state="TX"),
        max_records=1,
    )

    assert result.records_fetched == 1
    assert len(db_session.scalars(select(Organization)).all()) == 1


def test_discovery_service_is_idempotent_on_rerun(db_session: Session) -> None:
    provider = FakeNppesProvider(
        [
            NppesSearchPage(
                results=(_normalized(SAMPLE_ORG_RECORD, "1487448189", "100 CHIRO CORONA LLC"),),
                result_count=1,
                source_url="https://example.test/run-1",
            )
        ]
    )
    service = NppesDiscoveryService(provider, max_records_per_run=500)
    first = service.run(db_session, query=NppesSearchQuery(state="TX"))

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
            source_url="https://example.test/run-2",
        )
    )
    second = service.run(db_session, query=NppesSearchQuery(state="TX"))

    organization = db_session.scalar(
        select(Organization).where(Organization.npi == "1487448189")
    )
    evidence_count = len(db_session.scalars(select(SourceEvidence)).all())

    assert first.records_upserted == 1
    assert second.records_upserted == 1
    assert organization is not None
    assert organization.name == "100 CHIRO CORONA LLC UPDATED"
    assert evidence_count == 2


def test_discovery_service_records_failed_run(db_session: Session) -> None:
    class FailingProvider:
        def search_organizations(self, query: NppesSearchQuery) -> NppesSearchPage:
            raise RuntimeError("nppes unavailable")

    service = NppesDiscoveryService(FailingProvider(), max_records_per_run=500)

    with pytest.raises(RuntimeError, match="nppes unavailable"):
        service.run(db_session, query=NppesSearchQuery(state="TX"))

    run = db_session.scalar(select(DiscoveryRun))
    assert run is not None
    assert run.status == DiscoveryRunStatus.FAILED.value
    assert run.error_message == "nppes unavailable"
    assert run.finished_at is not None
