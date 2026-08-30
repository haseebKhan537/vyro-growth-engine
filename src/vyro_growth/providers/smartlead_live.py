from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from vyro_growth.config import Settings
from vyro_growth.providers.decision_makers import clean_optional_text
from vyro_growth.providers.smartlead import (
    LIVE_PROVIDER_NAME,
    LiveSmartleadDisabledError,
    LiveSmartleadNotImplementedError,
    MalformedSmartleadOutput,
    NonRetryableSmartleadError,
    RetryableSmartleadError,
    SmartleadLeadPayload,
    SmartleadPlanResult,
    parse_smartlead_plan_result,
)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 422}
LEADS_PATH_SUFFIX = "/leads"


class LiveSmartleadProvider:
    """Guarded live Smartlead boundary. Phase 6 does not open a default HTTP session."""

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
    def from_settings(cls, settings: Settings) -> LiveSmartleadProvider:
        return cls(
            enabled=settings.smartlead_live_enabled,
            api_key=settings.smartlead_api_key,
            api_base_url=settings.smartlead_api_base_url,
            timeout_seconds=settings.smartlead_timeout_seconds,
            max_retries=settings.smartlead_max_retries,
            retry_backoff_seconds=settings.smartlead_retry_backoff_seconds,
        )

    def plan_enrollment(self, payload: SmartleadLeadPayload) -> SmartleadPlanResult:
        if not self._enabled:
            raise LiveSmartleadDisabledError(
                "live smartlead is disabled; using this adapter requires "
                "SMARTLEAD_LIVE_ENABLED=true"
            )
        if clean_optional_text(self._api_key) is None:
            raise NonRetryableSmartleadError(
                "smartlead api key is not configured; live enrollment cannot run"
            )
        if clean_optional_text(self._api_base_url) is None:
            raise NonRetryableSmartleadError(
                "smartlead api base url is not configured; live enrollment cannot run"
            )
        if self._client is None:
            raise LiveSmartleadNotImplementedError(
                "Phase 6 does not perform live Smartlead enrollment HTTP. "
                "A future owner-approved step must inject a live client."
            )

        body, retry_attempts = self._post_with_retry(self._request_payload(payload))
        parsed = parse_smartlead_plan_result(_normalize_live_body(body, retry_attempts))
        if not parsed.dry_run:
            raise MalformedSmartleadOutput("live smartlead result was not a dry-run plan")
        return parsed

    def _request_payload(self, payload: SmartleadLeadPayload) -> dict[str, object]:
        return {
            "email": payload.email,
            "first_name": payload.first_name,
            "last_name": payload.last_name,
            "company_name": payload.company_name,
            "custom_fields": payload.custom_fields,
            "idempotency_key": payload.idempotency_key,
            "dry_run": True,
            "campaign_key": payload.campaign_key,
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
                    raise RetryableSmartleadError("smartlead request timed out") from exc
                self._backoff(attempt)
                continue
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == self._max_retries:
                    raise RetryableSmartleadError("smartlead request failed") from exc
                self._backoff(attempt)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt == self._max_retries:
                    raise RetryableSmartleadError(
                        f"smartlead request failed with status {response.status_code}"
                    )
                self._backoff(attempt)
                continue
            if response.status_code in NON_RETRYABLE_STATUS_CODES:
                raise NonRetryableSmartleadError(
                    f"smartlead request failed with status {response.status_code}"
                )
            if response.status_code >= 400:
                raise NonRetryableSmartleadError(
                    f"smartlead request failed with status {response.status_code}"
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise MalformedSmartleadOutput("smartlead response was not valid JSON") from exc
            if not isinstance(body, dict):
                raise MalformedSmartleadOutput("smartlead response was not a JSON object")
            return body, attempts

        raise RetryableSmartleadError("smartlead request failed") from last_error

    def _post(self, payload: dict[str, object]) -> httpx.Response:
        if self._client is None:
            raise LiveSmartleadNotImplementedError("live smartlead HTTP client is not available")
        campaign_key = payload.get("campaign_key")
        campaign_part = campaign_key if isinstance(campaign_key, str) else "unknown"
        url = f"{self._api_base_url}/campaigns/{campaign_part}{LEADS_PATH_SUFFIX}"
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
    enrollment_id = body.get("provider_enrollment_id") or body.get("id")
    return {
        "accepted": accepted if isinstance(accepted, bool) else False,
        "dry_run": dry_run if isinstance(dry_run, bool) else False,
        "live_call_attempted": True,
        "provider_name": LIVE_PROVIDER_NAME,
        "provider_enrollment_id": enrollment_id if isinstance(enrollment_id, str) else None,
        "raw": {**body, "retry_attempts": retry_attempts, "sent": body.get("sent", False)},
    }
