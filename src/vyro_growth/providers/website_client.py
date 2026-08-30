from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import httpx

from vyro_growth.providers.website import (
    HostResolver,
    PublicPage,
    WebsiteFetchError,
    WebsiteUrlError,
    assert_public_http_url,
    default_host_resolver,
    normalize_url,
)

ALLOWED_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
)
DEFAULT_USER_AGENT = (
    "VyroGrowthEngine/0.1 (+https://github.com/haseebKhan537/vyro-growth-engine)"
)
SleepFn = Callable[[float], None]


class HttpPublicPageFetcher:
    """Fetches public HTML only. Timeout-bound, size-capped, and SSRF-resistant."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        max_bytes: int = 524_288,
        max_redirects: int = 3,
        rate_limit_seconds: float = 0.5,
        user_agent: str = DEFAULT_USER_AGENT,
        client: httpx.Client | None = None,
        resolver: HostResolver | None = None,
        sleeper: SleepFn | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._rate_limit_seconds = rate_limit_seconds
        self._user_agent = user_agent
        self._client = client
        self._resolver = resolver or default_host_resolver
        self._sleep = sleeper or time.sleep
        self._last_request_at: float | None = None

    def fetch(self, url: str) -> PublicPage:
        current = self._validate(url)
        self._respect_rate_limit()
        hops = 0
        while hops <= self._max_redirects:
            response = self._get(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise WebsiteFetchError("redirect missing Location header")
                hops += 1
                if hops > self._max_redirects:
                    raise WebsiteFetchError("too many redirects")
                current = self._validate(urljoin(current, location))
                continue
            if response.status_code != 200:
                raise WebsiteFetchError(f"public page returned status {response.status_code}")
            content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip()
            if content_type and not any(
                content_type.startswith(allowed) for allowed in ALLOWED_CONTENT_TYPES
            ):
                raise WebsiteFetchError(f"unsupported content type: {content_type}")
            body = self._read_body(response)
            return PublicPage(
                url=normalize_url(str(response.url) if response.url else current),
                status_code=response.status_code,
                content_type=content_type or "text/html",
                text=body,
                fetched_at=datetime.now(tz=UTC),
            )
        raise WebsiteFetchError("too many redirects")

    def _validate(self, url: str) -> str:
        try:
            return assert_public_http_url(url, resolver=self._resolver)
        except WebsiteUrlError as exc:
            raise WebsiteFetchError(str(exc)) from exc

    def _respect_rate_limit(self) -> None:
        if self._last_request_at is None or self._rate_limit_seconds <= 0:
            self._last_request_at = time.monotonic()
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._rate_limit_seconds - elapsed
        if remaining > 0:
            self._sleep(remaining)
        self._last_request_at = time.monotonic()

    def _get(self, url: str) -> httpx.Response:
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        }
        try:
            if self._client is not None:
                return self._client.get(
                    url,
                    headers=headers,
                    timeout=self._timeout_seconds,
                    follow_redirects=False,
                )
            with httpx.Client() as client:
                return client.get(
                    url,
                    headers=headers,
                    timeout=self._timeout_seconds,
                    follow_redirects=False,
                )
        except httpx.TimeoutException as exc:
            raise WebsiteFetchError("public page request timed out") from exc
        except httpx.TransportError as exc:
            raise WebsiteFetchError("public page request failed") from exc

    def _read_body(self, response: httpx.Response) -> str:
        content_length = response.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self._max_bytes:
            raise WebsiteFetchError("public page exceeds size limit")
        raw = response.content
        if len(raw) > self._max_bytes:
            raise WebsiteFetchError("public page exceeds size limit")
        try:
            return raw.decode(response.encoding or "utf-8", errors="replace")
        except LookupError:
            return raw.decode("utf-8", errors="replace")


def build_public_page_fetcher(
    *,
    timeout_seconds: float,
    max_bytes: int,
    max_redirects: int,
    rate_limit_seconds: float,
    user_agent: str,
) -> HttpPublicPageFetcher:
    return HttpPublicPageFetcher(
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
        rate_limit_seconds=rate_limit_seconds,
        user_agent=user_agent,
    )


def fetcher_audit_fields(url: str, error: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"url": url, "provider": "http_public_page"}
    if error:
        payload["error"] = error
    return payload
