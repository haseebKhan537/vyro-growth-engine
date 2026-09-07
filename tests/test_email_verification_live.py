from __future__ import annotations

from typing import Any

import httpx
import pytest

from vyro_growth.config import Settings
from vyro_growth.domain import EmailVerificationOutcome, EmailVerificationVerdict
from vyro_growth.providers.email_verification import (
    LIVE_PROVIDER_NAME,
    EmailVerificationRequest,
    LiveEmailVerificationDisabledError,
    LiveEmailVerificationNotImplementedError,
    MalformedEmailVerificationOutput,
    NonRetryableEmailVerificationError,
    RetryableEmailVerificationError,
)
from vyro_growth.providers.email_verification_live import LiveEmailVerificationProvider


class MockTransport(httpx.MockTransport):
    def __init__(self, handlers: list[Any]) -> None:
        self._handlers = handlers
        self._call_index = 0
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        handler = self._handlers[self._call_index]
        self._call_index += 1
        return handler(request)


def _request() -> EmailVerificationRequest:
    return EmailVerificationRequest(email="owner@austinfamily.example")


def _provider(client: httpx.Client, **overrides: object) -> LiveEmailVerificationProvider:
    values: dict[str, object] = {
        "enabled": True,
        "api_key": "test-placeholder-key",
        "api_base_url": "https://verifier.test",
        "client": client,
        "max_retries": 2,
        "retry_backoff_seconds": 0,
        "sleep": lambda _delay: None,
    }
    values.update(overrides)
    return LiveEmailVerificationProvider(**values)  # type: ignore[arg-type]


def test_disabled_live_adapter_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"verdict": "valid", "email": "owner@austinfamily.example"})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = LiveEmailVerificationProvider(
        enabled=False,
        api_key="test-placeholder-key",
        api_base_url="https://verifier.test",
        client=client,
    )
    with pytest.raises(LiveEmailVerificationDisabledError, match="disabled"):
        provider.verify_email(_request())
    assert calls["count"] == 0


def test_missing_key_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = LiveEmailVerificationProvider(
        enabled=True,
        api_key="",
        api_base_url="https://verifier.test",
        client=client,
    )
    with pytest.raises(NonRetryableEmailVerificationError, match="api key"):
        provider.verify_email(_request())
    assert calls["count"] == 0


def test_smtp_flag_never_opens_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = LiveEmailVerificationProvider(
        enabled=True,
        api_key="test-placeholder-key",
        api_base_url="https://verifier.test",
        smtp_enabled=True,
        client=client,
    )
    with pytest.raises(LiveEmailVerificationNotImplementedError, match="SMTP"):
        provider.verify_email(_request())
    assert calls["count"] == 0


def test_no_injected_client_never_opens_live_http() -> None:
    provider = LiveEmailVerificationProvider(
        enabled=True,
        api_key="test-placeholder-key",
        api_base_url="https://verifier.test",
    )
    with pytest.raises(LiveEmailVerificationNotImplementedError, match="Phase 69"):
        provider.verify_email(_request())


def test_from_settings_stays_disabled_by_default() -> None:
    provider = LiveEmailVerificationProvider.from_settings(Settings())
    with pytest.raises(LiveEmailVerificationDisabledError):
        provider.verify_email(_request())


def test_injected_client_parses_verifier_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-placeholder-key"
        assert b'"smtp":false' in request.content
        assert request.url.path.endswith("/v1/verify")
        return httpx.Response(
            200,
            json={"verdict": "deliverable", "email": "owner@austinfamily.example"},
        )

    client = httpx.Client(transport=MockTransport([handler]))
    result = _provider(client, max_retries=0).verify_email(_request())
    assert result.provider_name == LIVE_PROVIDER_NAME
    assert result.verdict is EmailVerificationVerdict.VALID
    assert result.outcome is EmailVerificationOutcome.VERIFIED
    assert result.smtp_attempted is False
    assert result.live_call_attempted is True
    assert result.dry_run is False


def test_retryable_status_is_retried_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"verdict": "valid", "email": "owner@austinfamily.example"})

    client = httpx.Client(transport=MockTransport([handler, handler]))
    result = _provider(client).verify_email(_request())
    assert calls["count"] == 2
    assert result.verdict is EmailVerificationVerdict.VALID


def test_retryable_status_exhausted_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    client = httpx.Client(transport=MockTransport([handler, handler, handler, handler]))
    with pytest.raises(RetryableEmailVerificationError, match="429"):
        _provider(client).verify_email(_request())


def test_non_retryable_status_does_not_retry() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    client = httpx.Client(transport=MockTransport([handler, handler]))
    with pytest.raises(NonRetryableEmailVerificationError, match="401"):
        _provider(client).verify_email(_request())
    assert calls["count"] == 1


def test_malformed_non_object_response_is_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["verdict"])

    client = httpx.Client(transport=MockTransport([handler]))
    with pytest.raises(MalformedEmailVerificationOutput):
        _provider(client, max_retries=0).verify_email(_request())
