from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

import httpx

from vyro_growth.providers.nppes import (
    NormalizedNppesOrganization,
    NppesProvider,
    NppesSearchPage,
    NppesSearchQuery,
)
from vyro_growth.providers.nppes_normalize import normalize_nppes_record

RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


class NppesProviderError(RuntimeError):
    """Raised when the NPPES API cannot be queried successfully."""


class HttpNppesProvider:
    def __init__(
        self,
        *,
        base_url: str = "https://npiregistry.cms.hhs.gov/api/",
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._client = client

    def search_organizations(self, query: NppesSearchQuery) -> NppesSearchPage:
        if not query.has_targeting_filter():
            raise NppesProviderError(
                "NPPES search requires at least one targeting filter "
                "(state, city, taxonomy_description, or organization_name)"
            )

        params = query.to_params()
        source_url = f"{self._base_url}?{urlencode(params)}"
        payload = self._request(params)
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raw_results = []

        normalized: list[NormalizedNppesOrganization] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            record = normalize_nppes_record(item, source_url=source_url, query=query)
            if record is not None:
                normalized.append(record)

        result_count = payload.get("result_count")
        return NppesSearchPage(
            results=tuple(normalized),
            result_count=int(result_count) if isinstance(result_count, int) else len(normalized),
            page_size=len(raw_results),
            source_url=source_url,
        )

    def _request(self, params: dict[str, str | int]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._get(params)
                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt == self._max_retries:
                        raise NppesProviderError(
                            f"NPPES request failed with status {response.status_code}"
                        )
                    self._sleep(attempt)
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise NppesProviderError("NPPES response was not a JSON object")
                return payload
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt == self._max_retries:
                    raise NppesProviderError("NPPES request timed out") from exc
                self._sleep(attempt)
            except httpx.HTTPError as exc:
                raise NppesProviderError("NPPES request failed") from exc
            except ValueError as exc:
                raise NppesProviderError("NPPES response was not valid JSON") from exc

        raise NppesProviderError("NPPES request failed") from last_error

    def _get(self, params: dict[str, str | int]) -> httpx.Response:
        if self._client is not None:
            return self._client.get(self._base_url, params=params, timeout=self._timeout_seconds)
        with httpx.Client() as client:
            return client.get(self._base_url, params=params, timeout=self._timeout_seconds)

    def _sleep(self, attempt: int) -> None:
        delay = self._retry_backoff_seconds * (2**attempt)
        time.sleep(delay)


def build_nppes_provider(
    *,
    base_url: str,
    timeout_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
) -> NppesProvider:
    return HttpNppesProvider(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
