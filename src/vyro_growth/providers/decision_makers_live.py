from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

from vyro_growth.config import Settings
from vyro_growth.domain import ContactVerificationStatus
from vyro_growth.providers.decision_makers import (
    LIVE_PROVIDER_NAME,
    DecisionMakerCandidate,
    DecisionMakerEnrichmentRequest,
    DecisionMakerEnrichmentResult,
    LiveDecisionMakerDisabledError,
    LiveDecisionMakerNotImplementedError,
    MalformedDecisionMakerOutput,
    NonRetryableDecisionMakerError,
    RetryableDecisionMakerError,
    clean_optional_text,
    parse_decision_maker_candidate,
)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 422}
PEOPLE_SEARCH_PATH = "/people/search"
PROVIDER_RECORD_MAX_LENGTH = 128
VERIFIED_EMAIL_STATUSES = frozenset({"verified", "valid", "verified_email", "provider_verified"})
UNVERIFIED_EMAIL_STATUSES = frozenset(
    {"unverified", "catch_all", "guessed", "extrapolated", "unavailable"}
)


class LiveDecisionMakerProvider:
    """Guarded live people-search boundary. Phase 66 opens no default HTTP session."""

    live = True

    def __init__(
        self,
        *,
        enabled: bool = False,
        api_key: str = "",
        api_base_url: str = "",
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._enabled = enabled
        self._api_key = api_key
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._client = client
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings) -> LiveDecisionMakerProvider:
        return cls(
            enabled=settings.decision_maker_live_enabled,
            api_key=settings.decision_maker_api_key,
            api_base_url=settings.decision_maker_api_base_url,
            timeout_seconds=settings.decision_maker_timeout_seconds,
            max_retries=settings.decision_maker_max_retries,
            retry_backoff_seconds=settings.decision_maker_retry_backoff_seconds,
        )

    def enrich_decision_makers(
        self, request: DecisionMakerEnrichmentRequest
    ) -> DecisionMakerEnrichmentResult:
        if not self._enabled:
            raise LiveDecisionMakerDisabledError(
                "live decision-maker enrichment is disabled; using this adapter "
                "requires DECISION_MAKER_LIVE_ENABLED=true"
            )
        if clean_optional_text(self._api_key) is None:
            raise NonRetryableDecisionMakerError(
                "decision-maker api key is not configured; live enrichment cannot run"
            )
        if clean_optional_text(self._api_base_url) is None:
            raise NonRetryableDecisionMakerError(
                "decision-maker api base url is not configured; live enrichment cannot run"
            )
        if self._client is None:
            raise LiveDecisionMakerNotImplementedError(
                "Phase 66 does not perform live people-search HTTP. "
                "A future owner-approved step must inject a live client."
            )

        body, _retry_attempts = self._post_with_retry(self._request_payload(request))
        fetched_at = _timestamp_from_body(body) or datetime.now(tz=UTC)
        candidates, raw_count = parse_people_search_result(body, fetched_at=fetched_at)
        return DecisionMakerEnrichmentResult(
            candidates=candidates,
            provider_name=LIVE_PROVIDER_NAME,
            fetched_at=fetched_at,
            raw_count=raw_count,
        )

    def _request_payload(self, request: DecisionMakerEnrichmentRequest) -> dict[str, object]:
        organization = request.organization
        payload: dict[str, object] = {
            "max_candidates": request.max_candidates,
            "dry_run": True,
            "invent_contacts": False,
        }
        name = clean_optional_text(organization.name)
        if name is not None:
            payload["organization_name"] = name
        website = clean_optional_text(organization.website)
        if website is not None:
            payload["website"] = website
        city = clean_optional_text(organization.city)
        if city is not None:
            payload["city"] = city
        state = clean_optional_text(organization.state)
        if state is not None:
            payload["state"] = state
        specialty = clean_optional_text(organization.specialty)
        if specialty is not None:
            payload["specialty"] = specialty
        return payload

    def _post_with_retry(self, payload: dict[str, object]) -> tuple[dict[str, Any], int]:
        last_error: Exception | None = None
        attempts = 0
        for attempt in range(self._max_retries + 1):
            attempts = attempt
            try:
                response = self._post(payload)
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt == self._max_retries:
                    raise RetryableDecisionMakerError("decision-maker request timed out") from exc
                self._backoff(attempt)
                continue
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == self._max_retries:
                    raise RetryableDecisionMakerError("decision-maker request failed") from exc
                self._backoff(attempt)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt == self._max_retries:
                    raise RetryableDecisionMakerError(
                        f"decision-maker request failed with status {response.status_code}"
                    )
                self._backoff(attempt)
                continue
            if response.status_code in NON_RETRYABLE_STATUS_CODES:
                raise NonRetryableDecisionMakerError(
                    f"decision-maker request failed with status {response.status_code}"
                )
            if response.status_code >= 400:
                raise NonRetryableDecisionMakerError(
                    f"decision-maker request failed with status {response.status_code}"
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise MalformedDecisionMakerOutput(
                    "decision-maker response was not valid JSON"
                ) from exc
            if not isinstance(body, dict):
                raise MalformedDecisionMakerOutput(
                    "decision-maker response was not a JSON object"
                )
            return body, attempts

        raise RetryableDecisionMakerError("decision-maker request failed") from last_error

    def _post(self, payload: dict[str, object]) -> httpx.Response:
        if self._client is None:
            raise LiveDecisionMakerNotImplementedError(
                "live decision-maker HTTP client is not available"
            )
        url = f"{self._api_base_url}{PEOPLE_SEARCH_PATH}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        return self._client.post(
            url,
            headers=headers,
            json=payload,
            timeout=self._timeout_seconds,
        )

    def _backoff(self, attempt: int) -> None:
        delay = self._retry_backoff_seconds * (2**attempt)
        if delay > 0:
            self._sleep(delay)


def parse_people_search_result(
    raw: object,
    *,
    fetched_at: datetime | None = None,
) -> tuple[tuple[DecisionMakerCandidate, ...], int]:
    """Parse structured people-search JSON into DecisionMakerCandidate values.

    Unknown or malformed records are dropped. Missing people is a valid empty
    result, not an invented contact list.
    """
    if not isinstance(raw, dict):
        raise MalformedDecisionMakerOutput("decision-maker response was not a JSON object")
    records = _people_records(raw)
    timestamp = fetched_at or _timestamp_from_body(raw) or datetime.now(tz=UTC)
    parsed: list[DecisionMakerCandidate] = []
    for item in records:
        candidate = parse_decision_maker_candidate(
            _person_record_to_candidate_payload(item, fetched_at=timestamp)
        )
        if candidate is not None:
            parsed.append(candidate)
    return tuple(parsed), len(records)


def _people_records(body: Mapping[str, object]) -> list[object]:
    for key in ("people", "contacts", "candidates", "results"):
        value = body.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            raise MalformedDecisionMakerOutput(
                "decision-maker people search result was not a list"
            )
        return list(value)
    return []


def _timestamp_from_body(body: Mapping[str, object]) -> datetime | None:
    for key in ("fetched_at", "source_timestamp", "updated_at"):
        value = body.get(key)
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value
        if isinstance(value, str) and value.strip():
            raw = value.strip().replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(raw)
            except ValueError:
                continue
            if parsed.tzinfo is not None:
                return parsed
    return None


def _person_record_to_candidate_payload(
    raw: object,
    *,
    fetched_at: datetime,
) -> dict[str, object] | None:
    if isinstance(raw, DecisionMakerCandidate):
        return {
            "full_name": raw.full_name,
            "title": raw.title,
            "role_category": raw.role_category,
            "business_email": raw.business_email,
            "business_phone": raw.business_phone,
            "source_provider": raw.source_provider,
            "source_timestamp": raw.source_timestamp,
            "confidence": raw.confidence,
            "verification_status": raw.verification_status,
            "provenance": {
                "source_url": raw.provenance.source_url,
                "evidence_snippet": raw.provenance.evidence_snippet,
                "metadata": raw.provenance.metadata,
            },
            "provider_record_id": raw.provider_record_id,
            "owner_operator_evidence": raw.owner_operator_evidence,
        }
    if not isinstance(raw, dict):
        return None
    full_name = _person_full_name(raw)
    if full_name is None:
        return None
    timestamp = _timestamp_from_body(raw) or fetched_at
    payload: dict[str, object] = {
        "full_name": full_name,
        "source_provider": LIVE_PROVIDER_NAME,
        "source_timestamp": timestamp,
        "verification_status": _verification_status(raw),
    }
    title = _optional_text(raw, "title") or _optional_text(raw, "headline")
    if title is not None:
        payload["title"] = title
    email = _optional_text(raw, "business_email") or _optional_text(raw, "email")
    if email is not None:
        payload["business_email"] = email
    phone = _person_phone(raw)
    if phone is not None:
        payload["business_phone"] = phone
    confidence = raw.get("confidence")
    if isinstance(confidence, int | float) and not isinstance(confidence, bool):
        payload["confidence"] = confidence
    record_id = _person_record_id(raw)
    if record_id is not None:
        payload["provider_record_id"] = record_id
    provenance = _person_provenance(raw)
    if provenance:
        payload["provenance"] = provenance
    owner_evidence = _optional_text(raw, "owner_operator_evidence")
    if owner_evidence is not None:
        payload["owner_operator_evidence"] = owner_evidence
    role = raw.get("role_category")
    if isinstance(role, str) and role.strip():
        payload["role_category"] = role
    return payload


def _person_full_name(raw: Mapping[str, object]) -> str | None:
    direct = _optional_text(raw, "full_name") or _optional_text(raw, "name")
    if direct is not None:
        return direct
    first = _optional_text(raw, "first_name")
    last = _optional_text(raw, "last_name")
    if first is None and last is None:
        return None
    return " ".join(part for part in (first, last) if part)


def _person_phone(raw: Mapping[str, object]) -> str | None:
    direct = _optional_text(raw, "business_phone") or _optional_text(raw, "phone")
    if direct is not None:
        return direct
    numbers = raw.get("phone_numbers")
    if not isinstance(numbers, Sequence) or isinstance(numbers, str | bytes):
        return None
    for item in numbers:
        if isinstance(item, str):
            cleaned = clean_optional_text(item)
            if cleaned is not None:
                return cleaned
        if isinstance(item, dict):
            nested = (
                _optional_text(item, "sanitized_number")
                or _optional_text(item, "raw_number")
                or _optional_text(item, "number")
            )
            if nested is not None:
                return nested
    return None


def _person_record_id(raw: Mapping[str, object]) -> str | None:
    value = raw.get("provider_record_id") or raw.get("id")
    if isinstance(value, str):
        return clean_optional_text(value[:PROVIDER_RECORD_MAX_LENGTH])
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)[:PROVIDER_RECORD_MAX_LENGTH]
    return None


def _person_provenance(raw: Mapping[str, object]) -> dict[str, object]:
    existing = raw.get("provenance")
    if isinstance(existing, dict):
        return dict(existing)
    provenance: dict[str, object] = {}
    source_url = _optional_text(raw, "source_url")
    if source_url is not None:
        provenance["source_url"] = source_url
    snippet = _optional_text(raw, "evidence_snippet")
    if snippet is not None:
        provenance["evidence_snippet"] = snippet
    return provenance


def _verification_status(raw: Mapping[str, object]) -> str:
    explicit = raw.get("verification_status")
    if isinstance(explicit, ContactVerificationStatus):
        return explicit.value
    if isinstance(explicit, str) and explicit.strip():
        cleaned = explicit.strip().lower().replace(" ", "_").replace("-", "_")
        for status in ContactVerificationStatus:
            if status.value == cleaned:
                return status.value
        if cleaned in VERIFIED_EMAIL_STATUSES:
            return ContactVerificationStatus.PROVIDER_VERIFIED.value
        if cleaned in UNVERIFIED_EMAIL_STATUSES:
            return ContactVerificationStatus.UNVERIFIED.value
    email_status = _optional_text(raw, "email_status")
    if email_status is not None:
        cleaned = email_status.lower().replace(" ", "_").replace("-", "_")
        if cleaned in VERIFIED_EMAIL_STATUSES:
            return ContactVerificationStatus.PROVIDER_VERIFIED.value
        if cleaned in UNVERIFIED_EMAIL_STATUSES:
            return ContactVerificationStatus.UNVERIFIED.value
    return ContactVerificationStatus.UNKNOWN.value


def _optional_text(raw: Mapping[str, object], key: str) -> str | None:
    value = raw.get(key)
    if isinstance(value, str):
        return clean_optional_text(value)
    return None
