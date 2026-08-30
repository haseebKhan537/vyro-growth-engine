from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.fixtures.nppes_records import (
    INACTIVE_ORG_RECORD,
    SAMPLE_ORG_RECORD,
    SAMPLE_ORG_RECORD_2,
)
from vyro_growth.providers.nppes import NppesSearchQuery
from vyro_growth.providers.nppes_client import HttpNppesProvider, NppesProviderError


class MockTransport(httpx.MockTransport):
    def __init__(self, handlers: list[Any]) -> None:
        self._handlers = handlers
        self._call_index = 0
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        handler = self._handlers[self._call_index]
        self._call_index += 1
        return handler(request)


def test_search_organizations_returns_normalized_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["version"] == "2.1"
        assert request.url.params["enumeration_type"] == "NPI-2"
        assert request.url.params["state"] == "TX"
        return httpx.Response(
            200,
            json={"result_count": 1, "results": [SAMPLE_ORG_RECORD]},
        )

    client = httpx.Client(transport=MockTransport([handler]))
    provider = HttpNppesProvider(client=client, max_retries=0)

    page = provider.search_organizations(NppesSearchQuery(state="TX", city="Austin"))

    assert page.result_count == 1
    assert page.page_size == 1
    assert len(page.results) == 1
    assert page.results[0].npi == "1487448189"


def test_search_organizations_uses_raw_page_size_when_records_are_filtered() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result_count": 2,
                "results": [SAMPLE_ORG_RECORD, INACTIVE_ORG_RECORD],
            },
        )

    client = httpx.Client(transport=MockTransport([handler]))
    provider = HttpNppesProvider(client=client, max_retries=0)

    page = provider.search_organizations(NppesSearchQuery(state="TX"))

    assert page.page_size == 2
    assert len(page.results) == 1


def test_search_organizations_paginates_with_skip() -> None:
    seen_skips: list[int] = []

    def page_one(request: httpx.Request) -> httpx.Response:
        assert request.url.params["skip"] == "0"
        seen_skips.append(int(request.url.params["skip"]))
        return httpx.Response(
            200,
            json={"result_count": 2, "results": [SAMPLE_ORG_RECORD]},
        )

    def page_two(request: httpx.Request) -> httpx.Response:
        assert request.url.params["skip"] == "1"
        seen_skips.append(int(request.url.params["skip"]))
        return httpx.Response(
            200,
            json={"result_count": 2, "results": [SAMPLE_ORG_RECORD_2]},
        )

    client = httpx.Client(transport=MockTransport([page_one, page_two]))
    provider = HttpNppesProvider(client=client, max_retries=0)

    first = provider.search_organizations(NppesSearchQuery(state="TX", skip=0))
    second = provider.search_organizations(NppesSearchQuery(state="TX", skip=1))

    assert first.results[0].npi == "1487448189"
    assert second.results[0].npi == "1234567890"
    assert seen_skips == [0, 1]


def test_search_organizations_retries_retryable_status() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(
            200,
            json={"result_count": 1, "results": [SAMPLE_ORG_RECORD]},
        )

    client = httpx.Client(transport=MockTransport([handler, handler]))
    provider = HttpNppesProvider(
        client=client,
        max_retries=2,
        retry_backoff_seconds=0,
    )

    page = provider.search_organizations(NppesSearchQuery(state="TX"))

    assert calls["count"] == 2
    assert len(page.results) == 1


def test_search_organizations_raises_after_retry_exhaustion() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    client = httpx.Client(transport=MockTransport([handler, handler, handler, handler]))
    provider = HttpNppesProvider(
        client=client,
        max_retries=2,
        retry_backoff_seconds=0,
    )

    with pytest.raises(NppesProviderError, match="503"):
        provider.search_organizations(NppesSearchQuery(state="TX"))


def test_search_organizations_requires_a_targeting_filter() -> None:
    provider = HttpNppesProvider(max_retries=0)

    with pytest.raises(NppesProviderError, match="targeting filter"):
        provider.search_organizations(NppesSearchQuery())
