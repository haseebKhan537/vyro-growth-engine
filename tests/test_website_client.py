from __future__ import annotations

from typing import Any

import httpx
import pytest

from vyro_growth.providers.website import WebsiteFetchError
from vyro_growth.providers.website_client import HttpPublicPageFetcher


class MockTransport(httpx.MockTransport):
    def __init__(self, handlers: list[Any]) -> None:
        self._handlers = handlers
        self._call_index = 0
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        handler = self._handlers[self._call_index]
        self._call_index += 1
        return handler(request)


def _fetcher(handlers: list[Any], **kwargs: object) -> HttpPublicPageFetcher:
    client = httpx.Client(transport=MockTransport(handlers))
    return HttpPublicPageFetcher(
        client=client,
        resolver=lambda _host: ("8.8.8.8",),
        sleeper=lambda _seconds: None,
        rate_limit_seconds=0.0,
        **kwargs,  # type: ignore[arg-type]
    )


def test_fetcher_returns_html_for_public_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"].startswith("VyroGrowthEngine/")
        assert request.url.path == "/"
        return httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html"})

    page = _fetcher([handler]).fetch("https://clinic.example")
    assert page.status_code == 200
    assert page.text == "<html>ok</html>"
    assert page.url == "https://clinic.example"


def test_fetcher_follows_safe_redirects_only() -> None:
    def redirect(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://clinic.example/about"})

    def destination(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>about</html>", headers={"content-type": "text/html"})

    page = _fetcher([redirect, destination]).fetch("https://clinic.example")
    assert "about" in page.text


def test_fetcher_rejects_redirect_to_private_ip() -> None:
    def redirect(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    with pytest.raises(WebsiteFetchError, match="private"):
        _fetcher([redirect]).fetch("https://clinic.example")


def test_fetcher_rejects_non_html_and_oversize_bodies() -> None:
    def pdf(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})

    with pytest.raises(WebsiteFetchError, match="unsupported content type"):
        _fetcher([pdf]).fetch("https://clinic.example")

    def huge(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"x" * 200,
            headers={"content-type": "text/html", "content-length": "200"},
        )

    with pytest.raises(WebsiteFetchError, match="size limit"):
        _fetcher([huge], max_bytes=50).fetch("https://clinic.example")


def test_fetcher_rejects_timeouts_and_non_200() -> None:
    def missing(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="gone")

    with pytest.raises(WebsiteFetchError, match="status 404"):
        _fetcher([missing]).fetch("https://clinic.example")


def test_fetcher_blocks_portal_urls_before_request() -> None:
    called = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        called["count"] += 1
        return httpx.Response(200, text="secret")

    with pytest.raises(WebsiteFetchError, match="public business page"):
        _fetcher([handler]).fetch("https://clinic.example/patient-portal")
    assert called["count"] == 0
