"""Guarded live email-verification boundary.

Hunter / NeverBounce / ZeroBounce-style HTTP lives here. Phase 69 never opens
a default HTTP session and never contacts SMTP recipient servers.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from vyro_growth.config import Settings
from vyro_growth.domain import EmailCandidateOrigin, EmailVerificationVerdict
from vyro_growth.providers.decision_makers import clean_optional_text
from vyro_growth.providers.email_verification import (
    LIVE_PROVIDER_NAME,
    EmailVerificationRequest,
    EmailVerificationResult,
    LiveEmailVerificationDisabledError,
    LiveEmailVerificationNotImplementedError,
    MalformedEmailVerificationOutput,
    NonRetryableEmailVerificationError,
    RetryableEmailVerificationError,
    parse_email_verification_result,
)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 422}
VERIFY_PATH = "/v1/verify"


class LiveEmailVerificationProvider:
    """Guarded live verifier. Phase 69 opens no default HTTP or SMTP session."""

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
        smtp_enabled: bool = False,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._enabled = enabled
        self._api_key = api_key
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._smtp_enabled = smtp_enabled
        self._client = client
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings) -> LiveEmailVerificationProvider:
        return cls(
            enabled=settings.email_verification_live_enabled,
            api_key=settings.email_verification_api_key,
            api_base_url=settings.email_verification_api_base_url,
            timeout_seconds=settings.email_verification_timeout_seconds,
            max_retries=settings.email_verification_max_retries,
            retry_backoff_seconds=settings.email_verification_retry_backoff_seconds,
            smtp_enabled=settings.email_verification_smtp_enabled,
        )

    def verify_email(self, request: EmailVerificationRequest) -> EmailVerificationResult:
        if not self._enabled:
            raise LiveEmailVerificationDisabledError(
                "live email verification is disabled; using this adapter "
                "requires EMAIL_VERIFICATION_LIVE_ENABLED=true"
            )
        if self._smtp_enabled or request.allow_smtp:
            raise LiveEmailVerificationNotImplementedError(
                "Phase 69 does not perform SMTP recipient-server validation"
            )
        if clean_optional_text(self._api_key) is None:
            raise NonRetryableEmailVerificationError(
                "email-verification api key is not configured; live verification cannot run"
            )
        if clean_optional_text(self._api_base_url) is None:
            raise NonRetryableEmailVerificationError(
                "email-verification api base url is not configured; live verification cannot run"
            )
        if self._client is None:
            raise LiveEmailVerificationNotImplementedError(
                "Phase 69 does not perform live email-verification HTTP. "
                "A future owner-approved step must inject a live client."
            )

        body, retry_attempts = self._post_with_retry(self._request_payload(request))
        parsed = parse_email_verification_result(
            _normalize_live_body(body, retry_attempts, request)
        )
        if parsed.smtp_attempted:
            raise MalformedEmailVerificationOutput("live email verifier attempted SMTP")
        return parsed

    def _request_payload(self, request: EmailVerificationRequest) -> dict[str, object]:
        return {
            "email": request.email,
            "dry_run": True,
            "smtp": False,
            "allow_smtp": False,
            "origin": request.origin.value,
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
                    raise RetryableEmailVerificationError(
                        "email-verification request timed out"
                    ) from exc
                self._backoff(attempt)
                continue
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == self._max_retries:
                    raise RetryableEmailVerificationError(
                        "email-verification request failed"
                    ) from exc
                self._backoff(attempt)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt == self._max_retries:
                    raise RetryableEmailVerificationError(
                        f"email-verification retryable status {response.status_code}"
                    )
                self._backoff(attempt)
                continue
            if response.status_code in NON_RETRYABLE_STATUS_CODES:
                raise NonRetryableEmailVerificationError(
                    f"email-verification non-retryable status {response.status_code}"
                )
            if response.status_code >= 400:
                raise NonRetryableEmailVerificationError(
                    f"email-verification unexpected status {response.status_code}"
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise MalformedEmailVerificationOutput(
                    "email-verification response is not valid JSON"
                ) from exc
            if not isinstance(body, dict):
                raise MalformedEmailVerificationOutput(
                    "email-verification response is not a JSON object"
                )
            return body, attempts
        raise RetryableEmailVerificationError("email-verification request failed") from last_error

    def _post(self, payload: dict[str, object]) -> httpx.Response:
        assert self._client is not None
        return self._client.post(
            f"{self._api_base_url}{VERIFY_PATH}",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._timeout_seconds,
        )

    def _backoff(self, attempt: int) -> None:
        self._sleep(self._retry_backoff_seconds * (2**attempt))


def _normalize_live_body(
    body: dict[str, Any],
    retry_attempts: int,
    request: EmailVerificationRequest,
) -> dict[str, object]:
    verdict = body.get("verdict") or body.get("result") or body.get("status")
    email = body.get("email") or request.email
    return {
        "email": email,
        "verdict": verdict if isinstance(verdict, str) else EmailVerificationVerdict.UNKNOWN.value,
        "dry_run": False,
        "live_call_attempted": True,
        "smtp_attempted": False,
        "provider_name": LIVE_PROVIDER_NAME,
        "origin": request.origin.value
        if isinstance(request.origin, EmailCandidateOrigin)
        else EmailCandidateOrigin.STORED.value,
        "raw": {"retry_attempts": retry_attempts, "dry_run": True},
    }
