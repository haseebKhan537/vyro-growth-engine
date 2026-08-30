from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from tests.fixtures.personalization import sample_pack, stub_payload
from vyro_growth.providers.personalization import (
    MalformedPersonalizationOutput,
    NonRetryablePersonalizationError,
    PersonalizationRequest,
    RetryablePersonalizationError,
)
from vyro_growth.providers.personalization_openai import OpenAIPersonalizationProvider


class MockTransport(httpx.MockTransport):
    def __init__(self, handlers: list[Any]) -> None:
        self._handlers = handlers
        self._call_index = 0
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        handler = self._handlers[self._call_index]
        self._call_index += 1
        return handler(request)


def _provider(client: httpx.Client, **overrides: object) -> OpenAIPersonalizationProvider:
    values: dict[str, object] = {
        "enabled": True,
        "api_key": "test-placeholder-key",
        "client": client,
        "max_retries": 2,
        "retry_backoff_seconds": 0,
        "sleep": lambda _delay: None,
    }
    values.update(overrides)
    return OpenAIPersonalizationProvider(**values)  # type: ignore[arg-type]


def _completion(payload: dict[str, object]) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 34},
    }


def test_disabled_adapter_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json=_completion(stub_payload(sample_pack())))

    client = httpx.Client(transport=MockTransport([handler]))
    provider = OpenAIPersonalizationProvider(
        enabled=False,
        api_key="test-placeholder-key",
        client=client,
    )
    with pytest.raises(NonRetryablePersonalizationError, match="disabled"):
        pack = sample_pack()
        provider.generate(
            PersonalizationRequest(lead_id=pack.organization.organization_id, pack=pack)
        )
    assert calls["count"] == 0


def test_missing_key_is_non_retryable_and_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = OpenAIPersonalizationProvider(enabled=True, api_key="", client=client)
    pack = sample_pack()
    request = PersonalizationRequest(lead_id=pack.organization.organization_id, pack=pack)
    with pytest.raises(NonRetryablePersonalizationError, match="api key"):
        provider.generate(request)
    assert calls["count"] == 0


def test_success_parses_structured_json_and_logs_token_placeholders() -> None:
    pack = sample_pack()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-placeholder-key"
        body = json.loads(request.content.decode("utf-8"))
        assert body["response_format"]["type"] == "json_schema"
        assert "personalization_draft" in body["response_format"]["json_schema"]["name"]
        return httpx.Response(200, json=_completion(stub_payload(pack)))

    client = httpx.Client(transport=MockTransport([handler]))
    result = _provider(client, max_retries=0).generate(
        PersonalizationRequest(lead_id=pack.organization.organization_id, pack=pack)
    )
    assert result.audit.live_call_attempted is True
    assert result.audit.input_tokens == 12
    assert result.audit.output_tokens == 34
    assert result.audit.retry_attempts == 0
    assert result.content.suggested_offer


def test_retryable_status_is_retried_then_succeeds() -> None:
    pack = sample_pack()
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json=_completion(stub_payload(pack)))

    client = httpx.Client(transport=MockTransport([handler, handler]))
    result = _provider(client).generate(
        PersonalizationRequest(lead_id=pack.organization.organization_id, pack=pack)
    )
    assert calls["count"] == 2
    assert result.audit.retry_attempts == 1


def test_retryable_status_exhausted_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    client = httpx.Client(transport=MockTransport([handler, handler, handler, handler]))
    pack = sample_pack()
    with pytest.raises(RetryablePersonalizationError, match="429"):
        _provider(client).generate(
            PersonalizationRequest(lead_id=pack.organization.organization_id, pack=pack)
        )


def test_non_retryable_status_does_not_retry() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    client = httpx.Client(transport=MockTransport([handler, handler]))
    pack = sample_pack()
    with pytest.raises(NonRetryablePersonalizationError, match="401"):
        _provider(client).generate(
            PersonalizationRequest(lead_id=pack.organization.organization_id, pack=pack)
        )
    assert calls["count"] == 1


def test_malformed_json_content_is_non_retryable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    client = httpx.Client(transport=MockTransport([handler]))
    pack = sample_pack()
    with pytest.raises(MalformedPersonalizationOutput):
        _provider(client, max_retries=0).generate(
            PersonalizationRequest(lead_id=pack.organization.organization_id, pack=pack)
        )
