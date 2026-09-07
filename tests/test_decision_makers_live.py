from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest

from vyro_growth.config import Settings
from vyro_growth.domain import ContactVerificationStatus
from vyro_growth.providers.decision_makers import (
    LIVE_PROVIDER_NAME,
    DecisionMakerEnrichmentRequest,
    LiveDecisionMakerDisabledError,
    LiveDecisionMakerNotImplementedError,
    MalformedDecisionMakerOutput,
    NonRetryableDecisionMakerError,
    OrganizationContactContext,
    RetryableDecisionMakerError,
)
from vyro_growth.providers.decision_makers_live import (
    LiveDecisionMakerProvider,
    parse_people_search_result,
)


class MockTransport(httpx.MockTransport):
    def __init__(self, handlers: list[Any]) -> None:
        self._handlers = handlers
        self._call_index = 0
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        handler = self._handlers[self._call_index]
        self._call_index += 1
        return handler(request)


def _org() -> OrganizationContactContext:
    return OrganizationContactContext(
        organization_id=uuid4(),
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="1487448189",
        city="AUSTIN",
        state="TX",
        specialty="Family Medicine",
        website="https://austinfamily.example",
        website_match_status="verified",
        website_facts=(),
    )


def _request() -> DecisionMakerEnrichmentRequest:
    return DecisionMakerEnrichmentRequest(organization=_org(), max_candidates=5)


def _provider(client: httpx.Client, **overrides: object) -> LiveDecisionMakerProvider:
    values: dict[str, object] = {
        "enabled": True,
        "api_key": "test-placeholder-key",
        "api_base_url": "https://people-search.test/v1",
        "client": client,
        "max_retries": 2,
        "retry_backoff_seconds": 0,
        "sleep": lambda _delay: None,
    }
    values.update(overrides)
    return LiveDecisionMakerProvider(**values)  # type: ignore[arg-type]


def _person_payload() -> dict[str, object]:
    return {
        "id": "person-1",
        "first_name": "Jordan",
        "last_name": "Blake",
        "title": "Practice Manager",
        "email": "jblake@austinfamily.example",
        "email_status": "verified",
        "phone_numbers": [{"sanitized_number": "512-555-0100"}],
        "source_url": "https://provider.example/people/jblake",
    }


def test_disabled_live_adapter_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"people": [_person_payload()]})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = LiveDecisionMakerProvider(
        enabled=False,
        api_key="test-placeholder-key",
        api_base_url="https://people-search.test/v1",
        client=client,
    )
    with pytest.raises(LiveDecisionMakerDisabledError, match="disabled"):
        provider.enrich_decision_makers(_request())
    assert calls["count"] == 0


def test_missing_key_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = LiveDecisionMakerProvider(
        enabled=True,
        api_key="",
        api_base_url="https://people-search.test/v1",
        client=client,
    )
    with pytest.raises(NonRetryableDecisionMakerError, match="api key"):
        provider.enrich_decision_makers(_request())
    assert calls["count"] == 0


def test_missing_base_url_does_not_call_http() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={})

    client = httpx.Client(transport=MockTransport([handler]))
    provider = LiveDecisionMakerProvider(
        enabled=True,
        api_key="test-placeholder-key",
        api_base_url="  ",
        client=client,
    )
    with pytest.raises(NonRetryableDecisionMakerError, match="base url"):
        provider.enrich_decision_makers(_request())
    assert calls["count"] == 0


def test_no_injected_client_never_opens_live_http() -> None:
    provider = LiveDecisionMakerProvider(
        enabled=True,
        api_key="test-placeholder-key",
        api_base_url="https://people-search.test/v1",
    )
    with pytest.raises(LiveDecisionMakerNotImplementedError, match="Phase 66"):
        provider.enrich_decision_makers(_request())


def test_from_settings_stays_disabled_by_default() -> None:
    provider = LiveDecisionMakerProvider.from_settings(Settings())
    with pytest.raises(LiveDecisionMakerDisabledError):
        provider.enrich_decision_makers(_request())


def test_injected_client_parses_people_search_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-placeholder-key"
        assert b'"dry_run":true' in request.content
        assert b'"invent_contacts":false' in request.content
        assert request.url.path.endswith("/people/search")
        return httpx.Response(200, json={"people": [_person_payload()]})

    client = httpx.Client(transport=MockTransport([handler]))
    result = _provider(client, max_retries=0).enrich_decision_makers(_request())
    assert result.provider_name == LIVE_PROVIDER_NAME
    assert result.raw_count == 1
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.full_name == "Jordan Blake"
    assert candidate.title == "Practice Manager"
    assert candidate.business_email == "jblake@austinfamily.example"
    assert candidate.verification_status is ContactVerificationStatus.PROVIDER_VERIFIED
    assert candidate.source_provider == LIVE_PROVIDER_NAME


def test_empty_people_list_is_no_contact_not_invented() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"people": []})

    client = httpx.Client(transport=MockTransport([handler]))
    result = _provider(client, max_retries=0).enrich_decision_makers(_request())
    assert result.candidates == ()
    assert result.raw_count == 0


def test_malformed_records_are_dropped() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "people": [
                    {"title": "Office Manager"},
                    _person_payload(),
                    "not-an-object",
                ]
            },
        )

    client = httpx.Client(transport=MockTransport([handler]))
    result = _provider(client, max_retries=0).enrich_decision_makers(_request())
    assert result.raw_count == 3
    assert len(result.candidates) == 1
    assert result.candidates[0].full_name == "Jordan Blake"


def test_retryable_status_is_retried_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"people": [_person_payload()]})

    client = httpx.Client(transport=MockTransport([handler, handler]))
    result = _provider(client).enrich_decision_makers(_request())
    assert calls["count"] == 2
    assert len(result.candidates) == 1


def test_retryable_status_exhausted_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    client = httpx.Client(transport=MockTransport([handler, handler, handler, handler]))
    with pytest.raises(RetryableDecisionMakerError, match="429"):
        _provider(client).enrich_decision_makers(_request())


def test_non_retryable_status_does_not_retry() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    client = httpx.Client(transport=MockTransport([handler, handler]))
    with pytest.raises(NonRetryableDecisionMakerError, match="401"):
        _provider(client).enrich_decision_makers(_request())
    assert calls["count"] == 1


def test_malformed_non_object_response_is_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["people"])

    client = httpx.Client(transport=MockTransport([handler]))
    with pytest.raises(MalformedDecisionMakerOutput):
        _provider(client, max_retries=0).enrich_decision_makers(_request())


def test_parse_people_search_result_maps_verification_aliases() -> None:
    fetched_at = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    candidates, raw_count = parse_people_search_result(
        {
            "people": [
                {
                    "name": "Alex Nguyen",
                    "title": "Office Manager",
                    "email": "alex@clinic.example",
                    "email_status": "valid",
                }
            ]
        },
        fetched_at=fetched_at,
    )
    assert raw_count == 1
    assert candidates[0].verification_status is ContactVerificationStatus.PROVIDER_VERIFIED
    assert candidates[0].full_name == "Alex Nguyen"
