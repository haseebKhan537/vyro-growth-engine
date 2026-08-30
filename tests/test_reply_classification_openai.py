from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
import pytest

from tests.fixtures.replies import classified_payload
from vyro_growth.domain import ReplyIntent
from vyro_growth.providers.reply_classification import (
    MalformedReplyClassificationOutput,
    NonRetryableReplyClassifierError,
    ReplyClassificationRequest,
    RetryableReplyClassifierError,
)
from vyro_growth.providers.reply_classification_openai import OpenAIReplyClassifier


class MockTransport(httpx.MockTransport):
    def __init__(self, handlers: list[Any]) -> None:
        self._handlers = handlers
        self._call_index = 0
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        handler = self._handlers[self._call_index]
        self._call_index += 1
        return handler(request)


def _provider(client: httpx.Client, **overrides: object) -> OpenAIReplyClassifier:
    values: dict[str, object] = {
        "enabled": True,
        "api_key": "test-placeholder-key",
        "client": client,
        "max_retries": 2,
        "retry_backoff_seconds": 0,
        "sleep": lambda _delay: None,
    }
    values.update(overrides)
    return OpenAIReplyClassifier(**values)  # type: ignore[arg-type]


def _completion(payload: dict[str, object]) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 12},
    }


def _request() -> ReplyClassificationRequest:
    return ReplyClassificationRequest(
        lead_id=uuid4(),
        subject="Re: billing",
        body="We are interested.",
        sender_email="owner@clinic.example",
    )


def test_disabled_adapter_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json=_completion(classified_payload(ReplyIntent.INTERESTED)))

    client = httpx.Client(transport=MockTransport([handler]))
    provider = OpenAIReplyClassifier(
        enabled=False,
        api_key="test-placeholder-key",
        client=client,
    )
    with pytest.raises(NonRetryableReplyClassifierError, match="disabled"):
        provider.classify(_request())
    assert calls["count"] == 0


def test_missing_key_is_non_retryable_and_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = OpenAIReplyClassifier(enabled=True, api_key="", client=client)
    with pytest.raises(NonRetryableReplyClassifierError, match="api key"):
        provider.classify(_request())
    assert calls["count"] == 0


def test_success_parses_structured_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-placeholder-key"
        body = json.loads(request.content.decode("utf-8"))
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["name"] == "reply_classification"
        return httpx.Response(200, json=_completion(classified_payload(ReplyIntent.INTERESTED)))

    client = httpx.Client(transport=MockTransport([handler]))
    result = _provider(client, max_retries=0).classify(_request())
    assert result.audit.live_call_attempted is True
    assert result.content.intent is ReplyIntent.INTERESTED
    assert result.audit.input_tokens == 8


def test_retryable_status_is_retried_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json=_completion(classified_payload(ReplyIntent.UNKNOWN)))

    client = httpx.Client(transport=MockTransport([handler, handler]))
    result = _provider(client).classify(_request())
    assert calls["count"] == 2
    assert result.audit.retry_attempts == 1


def test_retryable_status_exhausted_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    client = httpx.Client(transport=MockTransport([handler, handler, handler, handler]))
    with pytest.raises(RetryableReplyClassifierError, match="429"):
        _provider(client).classify(_request())


def test_non_retryable_status_does_not_retry() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    client = httpx.Client(transport=MockTransport([handler, handler]))
    with pytest.raises(NonRetryableReplyClassifierError, match="401"):
        _provider(client).classify(_request())
    assert calls["count"] == 1


def test_malformed_json_content_is_non_retryable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    client = httpx.Client(transport=MockTransport([handler]))
    with pytest.raises(MalformedReplyClassificationOutput):
        _provider(client, max_retries=0).classify(_request())
