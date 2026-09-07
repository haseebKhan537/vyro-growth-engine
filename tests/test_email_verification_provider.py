from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vyro_growth.config import Settings
from vyro_growth.domain import (
    EmailCandidateOrigin,
    EmailVerificationOutcome,
    EmailVerificationVerdict,
)
from vyro_growth.providers.email_verification import (
    EmailVerificationRequest,
    EmailVerificationResult,
    LiveEmailVerificationNotImplementedError,
    MalformedEmailVerificationOutput,
    StaticEmailVerificationProvider,
    StubEmailVerificationProvider,
    build_email_verification_provider,
    parse_email_verification_result,
    sanitize_verification_details,
)


def test_stub_never_returns_valid_and_never_calls_smtp() -> None:
    provider = StubEmailVerificationProvider()
    result = provider.verify_email(
        EmailVerificationRequest(email="owner@austinfamily.example")
    )
    assert result.verdict is EmailVerificationVerdict.UNVERIFIED
    assert result.outcome is EmailVerificationOutcome.NO_VERIFIED_EMAIL
    assert result.dry_run is True
    assert result.live_call_attempted is False
    assert result.smtp_attempted is False
    assert result.provider_name == "stub"


def test_stub_rejects_smtp_recipient_validation() -> None:
    provider = StubEmailVerificationProvider()
    with pytest.raises(LiveEmailVerificationNotImplementedError, match="SMTP"):
        provider.verify_email(
            EmailVerificationRequest(email="owner@austinfamily.example", allow_smtp=True)
        )


def test_factory_always_returns_stub_even_when_live_flag_is_true() -> None:
    provider = build_email_verification_provider(
        Settings(
            email_verification_live_enabled=True,
            email_verification_api_key="placeholder",
            email_verification_api_base_url="https://verifier.test",
        )
    )
    assert isinstance(provider, StubEmailVerificationProvider)
    assert provider.live is False


def test_static_adapter_returns_configured_verdicts_without_network() -> None:
    provider = StaticEmailVerificationProvider(
        {"owner@austinfamily.example": EmailVerificationVerdict.VALID}
    )
    valid = provider.verify_email(
        EmailVerificationRequest(email="owner@austinfamily.example")
    )
    unknown = provider.verify_email(
        EmailVerificationRequest(email="other@austinfamily.example")
    )
    assert valid.verdict is EmailVerificationVerdict.VALID
    assert valid.outcome is EmailVerificationOutcome.VERIFIED
    assert unknown.verdict is EmailVerificationVerdict.UNVERIFIED
    assert unknown.outcome is EmailVerificationOutcome.NO_VERIFIED_EMAIL
    assert valid.live_call_attempted is False
    assert valid.smtp_attempted is False


def test_parse_rejects_smtp_and_live_dry_run_combinations() -> None:
    now = datetime.now(tz=UTC)
    with pytest.raises(MalformedEmailVerificationOutput, match="smtp"):
        parse_email_verification_result(
            EmailVerificationResult(
                email="owner@austinfamily.example",
                verdict=EmailVerificationVerdict.VALID,
                outcome=EmailVerificationOutcome.VERIFIED,
                dry_run=True,
                live_call_attempted=False,
                smtp_attempted=True,
                provider_name="stub",
                checked_at=now,
            )
        )
    with pytest.raises(MalformedEmailVerificationOutput, match="live_call_attempted"):
        parse_email_verification_result(
            EmailVerificationResult(
                email="owner@austinfamily.example",
                verdict=EmailVerificationVerdict.VALID,
                outcome=EmailVerificationOutcome.VERIFIED,
                dry_run=True,
                live_call_attempted=True,
                smtp_attempted=False,
                provider_name="stub",
                checked_at=now,
            )
        )


def test_sanitize_details_drop_secret_and_email_keys() -> None:
    payload = sanitize_verification_details(
        verdict=EmailVerificationVerdict.VALID,
        outcome=EmailVerificationOutcome.VERIFIED,
        origin=EmailCandidateOrigin.STORED,
        extra={
            "email": "owner@austinfamily.example",
            "api_key": "secret-key",
            "token": "tok",
            "secret": "shh",
            "phone": "512-555-0100",
            "pattern_safe": True,
        },
    )
    assert payload["verdict"] == "valid"
    assert payload["invented_email"] is False
    assert payload["smtp_attempted"] is False
    assert "email" not in payload
    assert "api_key" not in payload
    assert "token" not in payload
    assert "secret" not in payload
    assert "phone" not in payload
    assert payload["pattern_safe"] is True
