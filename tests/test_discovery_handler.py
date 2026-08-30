from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.models import DiscoveryRun, Organization
from vyro_growth.providers.nppes import (
    NormalizedNppesOrganization,
    NppesSearchPage,
    NppesSearchQuery,
)
from vyro_growth.workers.base import Job
from vyro_growth.workers.discovery_handler import (
    DISCOVER_NPPES_PRACTICES_JOB,
    DiscoverNppesPracticesHandler,
)


class HandlerFakeProvider:
    def search_organizations(self, query: NppesSearchQuery) -> NppesSearchPage:
        return NppesSearchPage(
            results=(
                NormalizedNppesOrganization(
                    npi="1487448189",
                    name="100 CHIRO CORONA LLC",
                    city="AUSTIN",
                    state="TX",
                    specialty="Chiropractor",
                    source_url="https://example.test",
                    query_metadata={"query": query.to_params(), "npi": "1487448189"},
                ),
            ),
            result_count=1,
            page_size=1,
            source_url="https://example.test",
        )


def test_worker_handler_runs_discovery_job(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        nppes_api_base_url="https://example.test/",
        discovery_max_records_per_run=100,
    )
    monkeypatch.setattr(
        "vyro_growth.workers.discovery_handler.build_nppes_provider",
        lambda **_kwargs: HandlerFakeProvider(),
    )
    handler = DiscoverNppesPracticesHandler(db=db_session, settings=settings)

    handler.handle(
        Job(
            name=DISCOVER_NPPES_PRACTICES_JOB,
            payload={"state": "TX", "city": "Austin", "max_records": 5},
        )
    )

    run = db_session.scalar(select(DiscoveryRun))
    organization = db_session.scalar(select(Organization).where(Organization.npi == "1487448189"))

    assert run is not None
    assert run.records_fetched == 1
    assert organization is not None
    assert organization.name == "100 CHIRO CORONA LLC"
