from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from vyro_growth.config import Settings
from vyro_growth.providers.decision_makers import clean_optional_text
from vyro_growth.providers.personalization import (
    PERSONALIZATION_JSON_SCHEMA,
    PROMPT_SYSTEM,
    MalformedPersonalizationOutput,
    NonRetryablePersonalizationError,
    PersonalizationProviderResult,
    PersonalizationRequest,
    ProviderAudit,
    RetryablePersonalizationError,
    ground_personalization_content,
    pack_to_prompt_payload,
    parse_personalization_content,
    prompt_hash,
)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 422}
PROVIDER_NAME = "openai_guarded"
CHAT_COMPLETIONS_PATH = "/chat/completions"


class OpenAIPersonalizationProvider:
    """Guarded OpenAI adapter. Makes no live call unless explicitly enabled with a key."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        api_key: str = "",
        api_base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
        max_output_tokens: int = 800,
        max_input_tokens: int = 4000,
        estimated_cost_usd_limit: float | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._enabled = enabled
        self._api_key = api_key
        self._api_base_url = api_base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._max_output_tokens = max_output_tokens
        self._max_input_tokens = max_input_tokens
        self._estimated_cost_usd_limit = estimated_cost_usd_limit
        self._client = client
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings) -> OpenAIPersonalizationProvider:
        return cls(
            enabled=settings.openai_personalization_enabled,
            api_key=settings.openai_api_key,
            api_base_url=settings.openai_api_base_url,
            model=settings.openai_personalization_model,
            timeout_seconds=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
            retry_backoff_seconds=settings.openai_retry_backoff_seconds,
            max_output_tokens=settings.openai_max_output_tokens,
            max_input_tokens=settings.openai_max_input_tokens,
            estimated_cost_usd_limit=settings.openai_estimated_cost_usd_limit,
        )

    def generate(self, request: PersonalizationRequest) -> PersonalizationProviderResult:
        if not self._enabled:
            raise NonRetryablePersonalizationError(
                "live openai personalization is disabled; using this adapter requires "
                "OPENAI_PERSONALIZATION_ENABLED=true"
            )
        if clean_optional_text(self._api_key) is None:
            raise NonRetryablePersonalizationError(
                "openai api key is not configured; live personalization cannot run"
            )

        payload = self._request_payload(request)
        body, retry_attempts = self._post_with_retry(payload)
        raw_content = _message_content(body)
        parsed = parse_personalization_content(raw_content)
        if parsed is None:
            raise MalformedPersonalizationOutput(
                "openai personalization output was not valid structured JSON"
            )
        grounded = ground_personalization_content(parsed, request.pack)
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        input_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        output_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
        return PersonalizationProviderResult(
            content=grounded,
            audit=ProviderAudit(
                prompt_version=request.prompt_version,
                schema_version=request.schema_version,
                prompt_hash=prompt_hash(),
                provider_name=PROVIDER_NAME,
                model=self._model,
                max_input_tokens=self._max_input_tokens,
                max_output_tokens=self._max_output_tokens,
                estimated_cost_usd_limit=self._estimated_cost_usd_limit,
                input_tokens=input_tokens if isinstance(input_tokens, int) else None,
                output_tokens=output_tokens if isinstance(output_tokens, int) else None,
                retry_attempts=retry_attempts,
                live_call_attempted=True,
            ),
        )

    def _request_payload(self, request: PersonalizationRequest) -> dict[str, object]:
        user_payload = pack_to_prompt_payload(request.pack)
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": PROMPT_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, sort_keys=True, default=str),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "personalization_draft",
                    "strict": True,
                    "schema": PERSONALIZATION_JSON_SCHEMA,
                },
            },
            "max_tokens": self._max_output_tokens,
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
                    raise RetryablePersonalizationError(
                        "openai personalization request timed out"
                    ) from exc
                self._backoff(attempt)
                continue
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == self._max_retries:
                    raise RetryablePersonalizationError(
                        "openai personalization request failed"
                    ) from exc
                self._backoff(attempt)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt == self._max_retries:
                    raise RetryablePersonalizationError(
                        f"openai personalization request failed with status {response.status_code}"
                    )
                self._backoff(attempt)
                continue
            if response.status_code in NON_RETRYABLE_STATUS_CODES:
                raise NonRetryablePersonalizationError(
                    f"openai personalization request failed with status {response.status_code}"
                )
            if response.status_code >= 400:
                raise NonRetryablePersonalizationError(
                    f"openai personalization request failed with status {response.status_code}"
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise MalformedPersonalizationOutput(
                    "openai personalization response was not valid JSON"
                ) from exc
            if not isinstance(body, dict):
                raise MalformedPersonalizationOutput(
                    "openai personalization response was not a JSON object"
                )
            return body, attempts

        raise RetryablePersonalizationError("openai personalization request failed") from last_error

    def _post(self, payload: dict[str, object]) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._api_base_url}{CHAT_COMPLETIONS_PATH}"
        if self._client is not None:
            return self._client.post(
                url,
                headers=headers,
                json=payload,
                timeout=self._timeout_seconds,
            )
        with httpx.Client() as client:
            return client.post(
                url,
                headers=headers,
                json=payload,
                timeout=self._timeout_seconds,
            )

    def _backoff(self, attempt: int) -> None:
        delay = self._retry_backoff_seconds * (2**attempt)
        if delay > 0:
            self._sleep(delay)


def _message_content(body: dict[str, Any]) -> object:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise MalformedPersonalizationOutput("openai personalization response had no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise MalformedPersonalizationOutput("openai personalization choice was malformed")
    message = first.get("message")
    if not isinstance(message, dict):
        raise MalformedPersonalizationOutput("openai personalization message was malformed")
    content = message.get("content")
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise MalformedPersonalizationOutput(
                "openai personalization content was not valid JSON"
            ) from exc
        return parsed
    raise MalformedPersonalizationOutput("openai personalization content was missing")
