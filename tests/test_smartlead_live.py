from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest

from vyro_growth.providers.smartlead import (
    LiveSmartleadDisabledError,
    LiveSmartleadNotImplementedError,
    MalformedSmartleadOutput,
    NonRetryableSmartleadError,
    RetryableSmartleadError,
    SmartleadLeadPayload,
)
from vyro_growth.providers.smartlead_live import LiveSmartleadProvider


class MockTransport(httpx.MockTransport):
    def __init__(self, handlers: list[Any]) -> None:
        self._handlers = handlers
        self._call_index = 0
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        handler = self._handlers[self._call_index]
        self._call_index += 1
        return handler(request)


def _payload() -> SmartleadLeadPayload:
    return SmartleadLeadPayload(
        campaign_key="camp-1",
        email="jordan.blake@austinfamily.example",
        company_name="AUSTIN FAMILY MEDICINE PLLC",
        idempotency_key="key-1",
        organization_id=uuid4(),
        first_name="Jordan",
        last_name="Blake",
        custom_fields={"organization_name": "AUSTIN FAMILY MEDICINE PLLC"},
    )


def _provider(client: httpx.Client, **overrides: object) -> LiveSmartleadProvider:
    values: dict[str, object] = {
        "enabled": True,
        "api_key": "test-placeholder-key",
        "api_base_url": "https://smartlead.test/api/v1",
        "client": client,
        "max_retries": 2,
        "retry_backoff_seconds": 0,
        "sleep": lambda _delay: None,
    }
    values.update(overrides)
    return LiveSmartleadProvider(**values)  # type: ignore[arg-type]


def test_disabled_live_adapter_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"accepted": True, "dry_run": True})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = LiveSmartleadProvider(
        enabled=False,
        api_key="test-placeholder-key",
        api_base_url="https://smartlead.test/api/v1",
        client=client,
    )
    with pytest.raises(LiveSmartleadDisabledError, match="disabled"):
        provider.plan_enrollment(_payload())
    assert calls["count"] == 0


def test_missing_key_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = LiveSmartleadProvider(
        enabled=True,
        api_key="",
        api_base_url="https://smartlead.test/api/v1",
        client=client,
    )
    with pytest.raises(NonRetryableSmartleadError, match="api key"):
        provider.plan_enrollment(_payload())
    assert calls["count"] == 0


def test_no_injected_client_never_opens_live_http() -> None:
    provider = LiveSmartleadProvider(
        enabled=True,
        api_key="test-placeholder-key",
        api_base_url="https://smartlead.test/api/v1",
    )
    with pytest.raises(LiveSmartleadNotImplementedError, match="Phase 6"):
        provider.plan_enrollment(_payload())


def test_injected_client_parses_dry_run_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-placeholder-key"
        assert b'"dry_run":true' in request.content
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "dry_run": True,
                "provider_enrollment_id": "enroll-1",
                "sent": False,
            },
        )

    client = httpx.Client(transport=MockTransport([handler]))
    result = _provider(client, max_retries=0).plan_enrollment(_payload())
    assert result.dry_run is True
    assert result.live_call_attempted is True
    assert result.provider_enrollment_id == "enroll-1"


def test_retryable_status_is_retried_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(
            200,
            json={"accepted": True, "dry_run": True, "provider_enrollment_id": "ok"},
        )

    client = httpx.Client(transport=MockTransport([handler, handler]))
    result = _provider(client).plan_enrollment(_payload())
    assert calls["count"] == 2
    assert result.dry_run is True


def test_retryable_status_exhausted_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    client = httpx.Client(transport=MockTransport([handler, handler, handler, handler]))
    with pytest.raises(RetryableSmartleadError, match="429"):
        _provider(client).plan_enrollment(_payload())


def test_non_retryable_status_does_not_retry() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    client = httpx.Client(transport=MockTransport([handler, handler]))
    with pytest.raises(NonRetryableSmartleadError, match="401"):
        _provider(client).plan_enrollment(_payload())
    assert calls["count"] == 1


def test_malformed_non_dry_run_response_is_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"accepted": True, "dry_run": False, "sent": True})

    client = httpx.Client(transport=MockTransport([handler]))
    with pytest.raises(MalformedSmartleadOutput):
        _provider(client, max_retries=0).plan_enrollment(_payload())
