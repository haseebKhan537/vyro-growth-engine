from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from vyro_growth.config import Settings
from vyro_growth.providers.calendar_booking import (
    LIVE_PROVIDER_NAME,
    PLAN_PATH_SUFFIX,
    BookingPlanPayload,
    BookingPlanProviderResult,
    LiveGoogleCalendarDisabledError,
    LiveGoogleCalendarNotImplementedError,
    MalformedBookingPlanOutput,
    NonRetryableBookingCalendarError,
    RetryableBookingCalendarError,
    parse_booking_plan_result,
)
from vyro_growth.providers.decision_makers import clean_optional_text

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 422}


class LiveGoogleCalendarProvider:
    """Guarded live Google Calendar/Meet boundary. Phase 8 opens no default HTTP."""

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
    def from_settings(cls, settings: Settings) -> LiveGoogleCalendarProvider:
        return cls(
            enabled=settings.google_calendar_live_enabled,
            api_key=settings.google_calendar_api_key,
            api_base_url=settings.google_calendar_api_base_url,
            timeout_seconds=settings.google_calendar_timeout_seconds,
            max_retries=settings.google_calendar_max_retries,
            retry_backoff_seconds=settings.google_calendar_retry_backoff_seconds,
        )

    def plan_booking(self, payload: BookingPlanPayload) -> BookingPlanProviderResult:
        if not self._enabled:
            raise LiveGoogleCalendarDisabledError(
                "live google calendar is disabled; using this adapter requires "
                "GOOGLE_CALENDAR_LIVE_ENABLED=true"
            )
        if clean_optional_text(self._api_key) is None:
            raise NonRetryableBookingCalendarError(
                "google calendar api key is not configured; live booking cannot run"
            )
        if clean_optional_text(self._api_base_url) is None:
            raise NonRetryableBookingCalendarError(
                "google calendar api base url is not configured; live booking cannot run"
            )
        if self._client is None:
            raise LiveGoogleCalendarNotImplementedError(
                "Phase 8 does not perform live Google Calendar or Meet HTTP. "
                "A future owner-approved step must inject a live client."
            )

        body, retry_attempts = self._post_with_retry(self._request_payload(payload))
        parsed = parse_booking_plan_result(_normalize_live_body(body, retry_attempts))
        if not parsed.dry_run:
            raise MalformedBookingPlanOutput("live google calendar result was not a dry-run plan")
        return parsed

    def _request_payload(self, payload: BookingPlanPayload) -> dict[str, object]:
        return {
            "idempotency_key": payload.idempotency_key,
            "organization_name": payload.organization_name,
            "requested_window": payload.requested_window,
            "dry_run": True,
            "create_event": False,
            "create_meet": False,
            "request_source": payload.request_source,
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
                    raise RetryableBookingCalendarError(
                        "google calendar request timed out"
                    ) from exc
                self._backoff(attempt)
                continue
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == self._max_retries:
                    raise RetryableBookingCalendarError(
                        "google calendar request failed"
                    ) from exc
                self._backoff(attempt)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt == self._max_retries:
                    raise RetryableBookingCalendarError(
                        f"google calendar request failed with status {response.status_code}"
                    )
                self._backoff(attempt)
                continue
            if response.status_code in NON_RETRYABLE_STATUS_CODES:
                raise NonRetryableBookingCalendarError(
                    f"google calendar request failed with status {response.status_code}"
                )
            if response.status_code >= 400:
                raise NonRetryableBookingCalendarError(
                    f"google calendar request failed with status {response.status_code}"
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise MalformedBookingPlanOutput(
                    "google calendar response was not valid JSON"
                ) from exc
            if not isinstance(body, dict):
                raise MalformedBookingPlanOutput(
                    "google calendar response was not a JSON object"
                )
            return body, attempts

        raise RetryableBookingCalendarError("google calendar request failed") from last_error

    def _post(self, payload: dict[str, object]) -> httpx.Response:
        if self._client is None:
            raise LiveGoogleCalendarNotImplementedError(
                "live google calendar HTTP client is not available"
            )
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
    event_created = body.get("event_created", False)
    meet_link_created = body.get("meet_link_created", False)
    event_id = body.get("provider_event_id") or body.get("id")
    meeting_url = body.get("meeting_url")
    return {
        "accepted": accepted if isinstance(accepted, bool) else False,
        "dry_run": dry_run if isinstance(dry_run, bool) else False,
        "live_call_attempted": True,
        "event_created": event_created if isinstance(event_created, bool) else False,
        "meet_link_created": meet_link_created if isinstance(meet_link_created, bool) else False,
        "provider_name": LIVE_PROVIDER_NAME,
        "provider_event_id": event_id if isinstance(event_id, str) else None,
        "meeting_url": meeting_url if isinstance(meeting_url, str) else None,
        "proposed_slots": body.get("proposed_slots"),
        "raw": {
            **body,
            "retry_attempts": retry_attempts,
            "sent": body.get("sent", False),
        },
    }
