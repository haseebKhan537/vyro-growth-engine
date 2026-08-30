from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest

from vyro_growth.providers.calendar_booking import (
    BookingPlanPayload,
    LiveGoogleCalendarDisabledError,
    LiveGoogleCalendarNotImplementedError,
    MalformedBookingPlanOutput,
    NonRetryableBookingCalendarError,
    RetryableBookingCalendarError,
)
from vyro_growth.providers.google_calendar import LiveGoogleCalendarProvider


class MockTransport(httpx.MockTransport):
    def __init__(self, handlers: list[Any]) -> None:
        self._handlers = handlers
        self._call_index = 0
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        handler = self._handlers[self._call_index]
        self._call_index += 1
        return handler(request)


def _payload_clean() -> BookingPlanPayload:
    return BookingPlanPayload(
        lead_id=uuid4(),
        organization_id=uuid4(),
        idempotency_key="key-1",
        request_source="meeting_request_reply",
        organization_name="AUSTIN FAMILY MEDICINE PLLC",
        attendee_email="jordan.blake@austinfamily.example",
    )


def _provider(client: httpx.Client, **overrides: object) -> LiveGoogleCalendarProvider:
    values: dict[str, object] = {
        "enabled": True,
        "api_key": "test-placeholder-key",
        "api_base_url": "https://calendar.test/api/v1",
        "client": client,
        "max_retries": 2,
        "retry_backoff_seconds": 0,
        "sleep": lambda _delay: None,
    }
    values.update(overrides)
    return LiveGoogleCalendarProvider(**values)  # type: ignore[arg-type]


def test_disabled_live_adapter_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"accepted": True, "dry_run": True})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = LiveGoogleCalendarProvider(
        enabled=False,
        api_key="test-placeholder-key",
        api_base_url="https://calendar.test/api/v1",
        client=client,
    )
    with pytest.raises(LiveGoogleCalendarDisabledError, match="disabled"):
        provider.plan_booking(_payload_clean())
    assert calls["count"] == 0


def test_missing_key_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = LiveGoogleCalendarProvider(
        enabled=True,
        api_key="",
        api_base_url="https://calendar.test/api/v1",
        client=client,
    )
    with pytest.raises(NonRetryableBookingCalendarError, match="api key"):
        provider.plan_booking(_payload_clean())
    assert calls["count"] == 0


def test_no_injected_client_never_opens_live_http() -> None:
    provider = LiveGoogleCalendarProvider(
        enabled=True,
        api_key="test-placeholder-key",
        api_base_url="https://calendar.test/api/v1",
    )
    with pytest.raises(LiveGoogleCalendarNotImplementedError, match="Phase 8"):
        provider.plan_booking(_payload_clean())


def test_injected_client_parses_dry_run_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-placeholder-key"
        assert b'"create_event":false' in request.content
        assert b'"create_meet":false' in request.content
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "dry_run": True,
                "event_created": False,
                "meet_link_created": False,
                "proposed_slots": [
                    {
                        "starts_at_iso": "2026-09-08T15:00:00+00:00",
                        "duration_minutes": 30,
                        "timezone": "UTC",
                    }
                ],
            },
        )

    client = httpx.Client(transport=MockTransport([handler]))
    result = _provider(client, max_retries=0).plan_booking(_payload_clean())
    assert result.dry_run is True
    assert result.live_call_attempted is True
    assert result.event_created is False
    assert result.meet_link_created is False


def test_retryable_status_is_retried_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "dry_run": True,
                "event_created": False,
                "meet_link_created": False,
            },
        )

    client = httpx.Client(transport=MockTransport([handler, handler]))
    result = _provider(client).plan_booking(_payload_clean())
    assert calls["count"] == 2
    assert result.dry_run is True


def test_retryable_status_exhausted_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    client = httpx.Client(transport=MockTransport([handler, handler, handler, handler]))
    with pytest.raises(RetryableBookingCalendarError, match="429"):
        _provider(client).plan_booking(_payload_clean())


def test_non_retryable_status_does_not_retry() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    client = httpx.Client(transport=MockTransport([handler, handler]))
    with pytest.raises(NonRetryableBookingCalendarError, match="401"):
        _provider(client).plan_booking(_payload_clean())
    assert calls["count"] == 1


def test_malformed_event_creation_response_is_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "dry_run": True,
                "event_created": True,
                "meet_link_created": False,
                "provider_event_id": "evt-1",
            },
        )

    client = httpx.Client(transport=MockTransport([handler]))
    with pytest.raises(MalformedBookingPlanOutput):
        _provider(client, max_retries=0).plan_booking(_payload_clean())
