from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest

from vyro_growth.domain import VoiceConsentChannel, VoiceConsentSource
from vyro_growth.providers.voice_qualification import (
    LiveVoiceDisabledError,
    LiveVoiceNotImplementedError,
    NonRetryableVoiceQualificationError,
    VoiceConsentProof,
    VoiceQualificationRequest,
)
from vyro_growth.providers.voice_qualification_live import LiveVoiceQualificationProvider


class MockTransport(httpx.MockTransport):
    def __init__(self, handlers: list[Any]) -> None:
        self._handlers = handlers
        self._call_index = 0
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        handler = self._handlers[self._call_index]
        self._call_index += 1
        return handler(request)


def _request() -> VoiceQualificationRequest:
    return VoiceQualificationRequest(
        lead_id=uuid4(),
        organization_id=uuid4(),
        idempotency_key="key-1",
        request_key="ops-1",
        consent=VoiceConsentProof(
            source=VoiceConsentSource.OPERATOR_REQUEST,
            channel=VoiceConsentChannel.OPERATOR,
            consented_at=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
            permitted_phone="5551112222",
        ),
        organization_name="AUSTIN FAMILY MEDICINE PLLC",
        stored_facts={"specialty": "Family Medicine"},
    )


def _provider(client: httpx.Client, **overrides: object) -> LiveVoiceQualificationProvider:
    values: dict[str, object] = {
        "enabled": True,
        "api_key": "test-placeholder-key",
        "api_base_url": "https://voice.test/api/v1",
        "client": client,
        "max_retries": 2,
        "retry_backoff_seconds": 0,
        "sleep": lambda _delay: None,
    }
    values.update(overrides)
    return LiveVoiceQualificationProvider(**values)  # type: ignore[arg-type]


def test_disabled_live_adapter_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"accepted": True, "dry_run": True, "call_placed": False})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = LiveVoiceQualificationProvider(
        enabled=False,
        api_key="test-placeholder-key",
        api_base_url="https://voice.test/api/v1",
        client=client,
    )
    with pytest.raises(LiveVoiceDisabledError, match="disabled"):
        provider.plan_qualification(_request())
    assert calls["count"] == 0


def test_missing_key_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"accepted": True, "dry_run": True})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = _provider(client, api_key="")
    with pytest.raises(NonRetryableVoiceQualificationError, match="api key"):
        provider.plan_qualification(_request())
    assert calls["count"] == 0


def test_live_adapter_without_client_is_not_implemented() -> None:
    provider = LiveVoiceQualificationProvider(
        enabled=True,
        api_key="test-placeholder-key",
        api_base_url="https://voice.test/api/v1",
    )
    with pytest.raises(LiveVoiceNotImplementedError, match="Phase 9"):
        provider.plan_qualification(_request())


def test_injected_client_keeps_dry_run_and_does_not_place_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read()
        assert b'"place_call": false' in payload
        assert b'"dry_run": true' in payload
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "dry_run": True,
                "call_placed": False,
                "facts": {"specialty": "Family Medicine"},
                "provider_plan_id": "plan-1",
            },
        )

    client = httpx.Client(transport=MockTransport([handler]))
    result = _provider(client).plan_qualification(_request())
    assert result.dry_run is True
    assert result.call_placed is False
    assert result.live_call_attempted is True
