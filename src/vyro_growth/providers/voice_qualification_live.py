from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from vyro_growth.config import Settings
from vyro_growth.providers.decision_makers import clean_optional_text
from vyro_growth.providers.voice_qualification import (
    LIVE_PROVIDER_NAME,
    PLAN_PATH_SUFFIX,
    LiveVoiceDisabledError,
    LiveVoiceNotImplementedError,
    MalformedVoicePlanOutput,
    NonRetryableVoiceQualificationError,
    RetryableVoiceQualificationError,
    VoiceQualificationRequest,
    VoiceQualificationResult,
    parse_voice_qualification_result,
)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 422}


class LiveVoiceQualificationProvider:
    """Guarded live voice boundary. Phase 9 opens no default HTTP session."""

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
    def from_settings(cls, settings: Settings) -> LiveVoiceQualificationProvider:
        return cls(
            enabled=settings.voice_live_enabled,
            api_key=settings.voice_api_key,
            api_base_url=settings.voice_api_base_url,
            timeout_seconds=settings.voice_timeout_seconds,
            max_retries=settings.voice_max_retries,
            retry_backoff_seconds=settings.voice_retry_backoff_seconds,
        )

    def plan_qualification(self, request: VoiceQualificationRequest) -> VoiceQualificationResult:
        if not self._enabled:
            raise LiveVoiceDisabledError(
                "live voice is disabled; using this adapter requires VOICE_LIVE_ENABLED=true"
            )
        if clean_optional_text(self._api_key) is None:
            raise NonRetryableVoiceQualificationError(
                "voice api key is not configured; live qualification cannot run"
            )
        if clean_optional_text(self._api_base_url) is None:
            raise NonRetryableVoiceQualificationError(
                "voice api base url is not configured; live qualification cannot run"
            )
        if self._client is None:
            raise LiveVoiceNotImplementedError(
                "Phase 9 does not perform live voice HTTP. "
                "A future owner-approved step must inject a live client."
            )

        body, retry_attempts = self._post_with_retry(self._request_payload(request))
        parsed = parse_voice_qualification_result(
            _normalize_live_body(body, retry_attempts),
            allowed_facts=request.stored_facts,
        )
        if not parsed.dry_run:
            raise MalformedVoicePlanOutput("live voice result was not a dry-run plan")
        if parsed.call_placed:
            raise MalformedVoicePlanOutput("live voice result claimed a placed call")
        return parsed

    def _request_payload(self, request: VoiceQualificationRequest) -> dict[str, object]:
        return {
            "idempotency_key": request.idempotency_key,
            "organization_name": request.organization_name,
            "consent": request.consent.to_audit(),
            "stored_facts": request.stored_facts,
            "dry_run": True,
            "place_call": False,
            "request_key": request.request_key,
        }

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
                    raise RetryableVoiceQualificationError("voice request timed out") from exc
                self._backoff(attempt)
                continue
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == self._max_retries:
                    raise RetryableVoiceQualificationError("voice request failed") from exc
                self._backoff(attempt)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt == self._max_retries:
                    raise RetryableVoiceQualificationError(
                        f"voice request failed with status {response.status_code}"
                    )
                self._backoff(attempt)
                continue
            if response.status_code in NON_RETRYABLE_STATUS_CODES:
                raise NonRetryableVoiceQualificationError(
                    f"voice request failed with status {response.status_code}"
                )
            if response.status_code >= 400:
                raise NonRetryableVoiceQualificationError(
                    f"voice request failed with status {response.status_code}"
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise MalformedVoicePlanOutput("voice response was not valid JSON") from exc
            if not isinstance(body, dict):
                raise MalformedVoicePlanOutput("voice response was not a JSON object")
            return body, attempts

        raise RetryableVoiceQualificationError("voice request failed") from last_error

    def _post(self, payload: dict[str, object]) -> httpx.Response:
        if self._client is None:
            raise LiveVoiceNotImplementedError("live voice HTTP client is not available")
        url = f"{self._api_base_url}{PLAN_PATH_SUFFIX}"
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


def _normalize_live_body(body: dict[str, Any], retry_attempts: int) -> dict[str, object]:
    accepted = body.get("accepted", True)
    dry_run = body.get("dry_run", False)
    call_placed = body.get("call_placed", False)
    plan_id = body.get("provider_plan_id") or body.get("id")
    facts = body.get("facts")
    return {
        "accepted": accepted if isinstance(accepted, bool) else False,
        "dry_run": dry_run if isinstance(dry_run, bool) else False,
        "live_call_attempted": True,
        "call_placed": call_placed if isinstance(call_placed, bool) else False,
        "provider_name": LIVE_PROVIDER_NAME,
        "provider_plan_id": plan_id if isinstance(plan_id, str) else None,
        "facts": facts if isinstance(facts, dict) else {},
        "raw": {
            **body,
            "retry_attempts": retry_attempts,
            "sent": body.get("sent", False),
            "call_placed": call_placed if isinstance(call_placed, bool) else False,
        },
    }
