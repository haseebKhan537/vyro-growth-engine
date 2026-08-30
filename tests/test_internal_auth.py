from __future__ import annotations

from vyro_growth.api.internal_auth import (
    InternalTriggerDecision,
    evaluate_internal_http_trigger,
    internal_trigger_http_error,
    is_internal_http_trigger_allowed,
)
from vyro_growth.config import Settings


def test_development_allows_missing_configured_key() -> None:
    decision = evaluate_internal_http_trigger(
        Settings(environment="development", internal_api_key=""),
        provided_key=None,
    )

    assert decision is InternalTriggerDecision.DEVELOPMENT_OPEN
    assert is_internal_http_trigger_allowed(decision)
    assert internal_trigger_http_error(decision) is None


def test_non_development_fails_closed_without_configured_key() -> None:
    decision = evaluate_internal_http_trigger(
        Settings(environment="production", internal_api_key="   "),
        provided_key="any-value",
    )

    assert decision is InternalTriggerDecision.KEY_NOT_CONFIGURED
    assert not is_internal_http_trigger_allowed(decision)
    assert internal_trigger_http_error(decision) == (
        403,
        "Internal operator route requires INTERNAL_API_KEY",
    )


def test_missing_request_key_is_rejected_when_configured() -> None:
    settings = Settings(environment="development", internal_api_key="internal-secret")

    decision = evaluate_internal_http_trigger(settings, provided_key=None)

    assert decision is InternalTriggerDecision.MISSING_KEY
    assert internal_trigger_http_error(decision) == (
        401,
        "Invalid or missing internal API key",
    )


def test_invalid_request_key_is_rejected() -> None:
    settings = Settings(environment="staging", internal_api_key="internal-secret")

    decision = evaluate_internal_http_trigger(settings, provided_key="other-secret")

    assert decision is InternalTriggerDecision.INVALID_KEY
    assert internal_trigger_http_error(decision) == (
        401,
        "Invalid or missing internal API key",
    )


def test_valid_request_key_is_accepted_outside_development() -> None:
    settings = Settings(environment="production", internal_api_key="internal-secret")

    decision = evaluate_internal_http_trigger(settings, provided_key="internal-secret")

    assert decision is InternalTriggerDecision.ALLOWED
    assert is_internal_http_trigger_allowed(decision)
    assert internal_trigger_http_error(decision) is None


def test_whitespace_only_provided_key_is_missing() -> None:
    settings = Settings(environment="production", internal_api_key="internal-secret")

    decision = evaluate_internal_http_trigger(settings, provided_key="   ")

    assert decision is InternalTriggerDecision.MISSING_KEY
