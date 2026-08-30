from __future__ import annotations

import hmac
from enum import StrEnum
from typing import Never

from vyro_growth.config import Settings


class InternalTriggerDecision(StrEnum):
    ALLOWED = "allowed"
    DEVELOPMENT_OPEN = "development_open"
    KEY_NOT_CONFIGURED = "internal_api_key_not_configured"
    MISSING_KEY = "missing_internal_api_key"
    INVALID_KEY = "invalid_internal_api_key"


def _unreachable(value: object) -> Never:
    raise RuntimeError(f"unhandled internal trigger decision: {value!r}")


def configured_internal_api_key(settings: Settings) -> str:
    return settings.internal_api_key.strip()


def is_development_environment(settings: Settings) -> bool:
    return settings.environment == "development"


def internal_api_keys_match(configured: str, provided: str | None) -> bool:
    if not configured or provided is None:
        return False
    provided_key = provided.strip()
    if not provided_key or len(configured) != len(provided_key):
        return False
    return hmac.compare_digest(configured, provided_key)


def evaluate_internal_http_trigger(
    settings: Settings,
    provided_key: str | None,
) -> InternalTriggerDecision:
    """Authorize an internal HTTP trigger. CLI and worker jobs do not use this gate.

    Development may run without a configured key. Every other environment is
    fail-closed until INTERNAL_API_KEY is set and the request presents a match.
    """

    configured = configured_internal_api_key(settings)
    if not configured:
        if is_development_environment(settings):
            return InternalTriggerDecision.DEVELOPMENT_OPEN
        return InternalTriggerDecision.KEY_NOT_CONFIGURED
    if internal_api_keys_match(configured, provided_key):
        return InternalTriggerDecision.ALLOWED
    if provided_key is None or not provided_key.strip():
        return InternalTriggerDecision.MISSING_KEY
    return InternalTriggerDecision.INVALID_KEY


def is_internal_http_trigger_allowed(decision: InternalTriggerDecision) -> bool:
    match decision:
        case InternalTriggerDecision.ALLOWED | InternalTriggerDecision.DEVELOPMENT_OPEN:
            return True
        case (
            InternalTriggerDecision.KEY_NOT_CONFIGURED
            | InternalTriggerDecision.MISSING_KEY
            | InternalTriggerDecision.INVALID_KEY
        ):
            return False
        case _:
            return _unreachable(decision)


def internal_trigger_http_error(decision: InternalTriggerDecision) -> tuple[int, str] | None:
    match decision:
        case InternalTriggerDecision.ALLOWED | InternalTriggerDecision.DEVELOPMENT_OPEN:
            return None
        case InternalTriggerDecision.KEY_NOT_CONFIGURED:
            return (403, "Internal operator route requires INTERNAL_API_KEY")
        case InternalTriggerDecision.MISSING_KEY | InternalTriggerDecision.INVALID_KEY:
            return (401, "Invalid or missing internal API key")
        case _:
            return _unreachable(decision)
