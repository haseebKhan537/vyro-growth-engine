from __future__ import annotations

import os

import pytest

from vyro_growth.providers.nppes import NppesSearchQuery
from vyro_growth.providers.nppes_client import HttpNppesProvider


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("NPPES_INTEGRATION_TESTS") != "1",
    reason="Set NPPES_INTEGRATION_TESTS=1 to run live NPPES integration tests",
)
def test_live_nppes_search_returns_results() -> None:
    provider = HttpNppesProvider(max_retries=1, retry_backoff_seconds=0)
    page = provider.search_organizations(
        NppesSearchQuery(state="TX", city="Austin", limit=1),
    )

    assert page.result_count >= 1
    assert len(page.results) >= 1
    assert page.results[0].npi
    assert page.results[0].name
    assert page.results[0].query_metadata["query"]["enumeration_type"] == "NPI-2"
