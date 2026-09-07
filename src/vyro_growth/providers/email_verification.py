"""Email verification provider boundary.

Hunter / NeverBounce / ZeroBounce-style adapters implement this protocol.
CI and local defaults use a deterministic stub that never calls a live
verifier and never contacts SMTP recipient servers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from vyro_growth.config import Settings, get_settings
from vyro_growth.domain import (
    ContactVerificationStatus,
    EmailCandidateOrigin,
    EmailVerificationOutcome,
    EmailVerificationVerdict,
)
from vyro_growth.providers.decision_makers import (
    EMAIL_MAX_LENGTH,
    EMAIL_RE,
    clean_optional_text,
    clip_text,
)

EMAIL_VERIFICATION_SOURCE = "email_verification"
STUB_PROVIDER_NAME = "stub"
LIVE_PROVIDER_NAME = "email_verification_guarded"
NO_VERIFIED_EMAIL = "no_verified_email"
VERIFIED_SAFE_VERDICTS = frozenset({EmailVerificationVerdict.VALID})
RISKY_VERDICTS = frozenset(
    {
        EmailVerificationVerdict.CATCH_ALL,
        EmailVerificationVerdict.RISKY,
        EmailVerificationVerdict.DISPOSABLE,
        EmailVerificationVerdict.ROLE,
        EmailVerificationVerdict.UNKNOWN,
    }
)
INVALID_VERDICTS = frozenset({EmailVerificationVerdict.INVALID})
PROVIDER_MAX_LENGTH = 64
VERDICT_ALIASES = {
    "deliverable": EmailVerificationVerdict.VALID,
    "valid": EmailVerificationVerdict.VALID,
    "ok": EmailVerificationVerdict.VALID,
    "verified": EmailVerificationVerdict.VALID,
    "undeliverable": EmailVerificationVerdict.INVALID,
    "invalid": EmailVerificationVerdict.INVALID,
    "bounce": EmailVerificationVerdict.INVALID,
    "hard_bounce": EmailVerificationVerdict.INVALID,
    "catch_all": EmailVerificationVerdict.CATCH_ALL,
    "accept_all": EmailVerificationVerdict.CATCH_ALL,
    "unknown": EmailVerificationVerdict.UNKNOWN,
    "risky": EmailVerificationVerdict.RISKY,
    "disposable": EmailVerificationVerdict.DISPOSABLE,
    "role": EmailVerificationVerdict.ROLE,
    "unverified": EmailVerificationVerdict.UNVERIFIED,
}


class EmailVerificationProviderError(RuntimeError):
    """Raised when an email verifier cannot complete a lookup."""

    retryable: bool = False


class RetryableEmailVerificationError(EmailVerificationProviderError):
    retryable = True


class NonRetryableEmailVerificationError(EmailVerificationProviderError):
    retryable = False


class MalformedEmailVerificationOutput(NonRetryableEmailVerificationError):
    """Raised when provider output cannot be parsed into a safe verdict."""


class LiveEmailVerificationDisabledError(NonRetryableEmailVerificationError):
    """Raised when the live email-verification boundary is not explicitly enabled."""


class LiveEmailVerificationNotImplementedError(NonRetryableEmailVerificationError):
    """Raised when Phase 69 refuses to open a live verifier or SMTP session."""


@dataclass(frozen=True)
class EmailVerificationRequest:
    email: str
    organization_id: UUID | None = None
    contact_id: UUID | None = None
    origin: EmailCandidateOrigin = EmailCandidateOrigin.STORED
    allow_smtp: bool = False


@dataclass(frozen=True)
class EmailVerificationResult:
    email: str
    verdict: EmailVerificationVerdict
    outcome: EmailVerificationOutcome
    dry_run: bool
    live_call_attempted: bool
    smtp_attempted: bool
    provider_name: str
    checked_at: datetime
    origin: EmailCandidateOrigin = EmailCandidateOrigin.STORED
    verification_status: ContactVerificationStatus = ContactVerificationStatus.UNVERIFIED
    raw: dict[str, object] = field(default_factory=dict)


class EmailVerificationProvider(Protocol):
    live: bool

    def verify_email(self, request: EmailVerificationRequest) -> EmailVerificationResult: ...


def is_verified_safe_verdict(verdict: EmailVerificationVerdict | str | None) -> bool:
    parsed = parse_email_verification_verdict(verdict)
    return parsed in VERIFIED_SAFE_VERDICTS


def verification_status_for_verdict(
    verdict: EmailVerificationVerdict,
    *,
    origin: EmailCandidateOrigin,
) -> ContactVerificationStatus:
    if verdict is EmailVerificationVerdict.VALID:
        return ContactVerificationStatus.VERIFIER_VALID
    if verdict is EmailVerificationVerdict.INVALID:
        return ContactVerificationStatus.VERIFIER_INVALID
    if verdict in RISKY_VERDICTS:
        return ContactVerificationStatus.VERIFIER_RISKY
    if origin is EmailCandidateOrigin.INFERRED:
        return ContactVerificationStatus.INFERRED
    return ContactVerificationStatus.UNVERIFIED


def outcome_for_verdict(verdict: EmailVerificationVerdict) -> EmailVerificationOutcome:
    if verdict in VERIFIED_SAFE_VERDICTS:
        return EmailVerificationOutcome.VERIFIED
    return EmailVerificationOutcome.NO_VERIFIED_EMAIL


def parse_email_verification_verdict(
    value: EmailVerificationVerdict | str | None,
) -> EmailVerificationVerdict | None:
    if isinstance(value, EmailVerificationVerdict):
        return value
    if value is None:
        return None
    cleaned = value.strip().lower().replace(" ", "_").replace("-", "_")
    for verdict in EmailVerificationVerdict:
        if verdict.value == cleaned:
            return verdict
    return VERDICT_ALIASES.get(cleaned)


def parse_email_verification_result(raw: object) -> EmailVerificationResult:
    if isinstance(raw, EmailVerificationResult):
        result = raw
    elif isinstance(raw, Mapping):
        result = _result_from_mapping(raw)
    else:
        raise MalformedEmailVerificationOutput("email verification result is not an object")
    if result.smtp_attempted:
        raise MalformedEmailVerificationOutput("smtp recipient validation is forbidden")
    if result.live_call_attempted and result.dry_run:
        raise MalformedEmailVerificationOutput("live_call_attempted cannot be true for a dry-run")
    email = clean_optional_text(result.email)
    if email is None or not EMAIL_RE.match(email.lower()):
        raise MalformedEmailVerificationOutput("email verification result missing a valid email")
    return result


def _result_from_mapping(raw: Mapping[str, object]) -> EmailVerificationResult:
    email_raw = raw.get("email")
    provider_raw = raw.get("provider_name")
    verdict_raw = raw.get("verdict")
    email = clean_optional_text(email_raw) if isinstance(email_raw, str) else None
    provider_name = (
        clean_optional_text(provider_raw) if isinstance(provider_raw, str) else None
    )
    verdict = parse_email_verification_verdict(
        verdict_raw if isinstance(verdict_raw, str) else None
    )
    dry_run = raw.get("dry_run")
    live_call_attempted = raw.get("live_call_attempted")
    smtp_attempted = raw.get("smtp_attempted")
    if email is None or provider_name is None or verdict is None:
        raise MalformedEmailVerificationOutput("email verification result missing required fields")
    if not isinstance(dry_run, bool) or not isinstance(live_call_attempted, bool):
        raise MalformedEmailVerificationOutput("email verification result missing dry-run flags")
    if not isinstance(smtp_attempted, bool):
        raise MalformedEmailVerificationOutput("email verification result missing smtp_attempted")
    origin_raw = raw.get("origin")
    origin = EmailCandidateOrigin.STORED
    if isinstance(origin_raw, EmailCandidateOrigin):
        origin = origin_raw
    elif isinstance(origin_raw, str):
        for item in EmailCandidateOrigin:
            if item.value == origin_raw:
                origin = item
                break
    extra = raw.get("raw")
    raw_payload = dict(extra) if isinstance(extra, dict) else dict(raw)
    checked_at = raw.get("checked_at")
    timestamp = checked_at if isinstance(checked_at, datetime) else datetime.now(tz=UTC)
    if timestamp.tzinfo is None:
        raise MalformedEmailVerificationOutput(
            "email verification timestamp must be timezone-aware"
        )
    return EmailVerificationResult(
        email=clip_text(email.lower(), EMAIL_MAX_LENGTH),
        verdict=verdict,
        outcome=outcome_for_verdict(verdict),
        dry_run=dry_run,
        live_call_attempted=live_call_attempted,
        smtp_attempted=smtp_attempted,
        provider_name=clip_text(provider_name, PROVIDER_MAX_LENGTH),
        checked_at=timestamp,
        origin=origin,
        verification_status=verification_status_for_verdict(verdict, origin=origin),
        raw=raw_payload,
    )


class StubEmailVerificationProvider:
    """CI/local default. Does not call live verifiers or SMTP servers."""

    live = False

    def __init__(self) -> None:
        self.requests: list[EmailVerificationRequest] = []

    def verify_email(self, request: EmailVerificationRequest) -> EmailVerificationResult:
        self.requests.append(request)
        if request.allow_smtp:
            raise LiveEmailVerificationNotImplementedError(
                "Phase 69 does not perform SMTP recipient-server validation"
            )
        email = clip_text(request.email.lower(), EMAIL_MAX_LENGTH)
        return EmailVerificationResult(
            email=email,
            verdict=EmailVerificationVerdict.UNVERIFIED,
            outcome=EmailVerificationOutcome.NO_VERIFIED_EMAIL,
            dry_run=True,
            live_call_attempted=False,
            smtp_attempted=False,
            provider_name=STUB_PROVIDER_NAME,
            checked_at=datetime.now(tz=UTC),
            origin=request.origin,
            verification_status=verification_status_for_verdict(
                EmailVerificationVerdict.UNVERIFIED,
                origin=request.origin,
            ),
            raw={"dry_run": True, "invented": False},
        )


class StaticEmailVerificationProvider:
    """Test adapter that returns configured verdicts. Does not call a network."""

    live = False

    def __init__(
        self,
        verdicts: Mapping[str, EmailVerificationVerdict] | None = None,
        *,
        default: EmailVerificationVerdict = EmailVerificationVerdict.UNVERIFIED,
    ) -> None:
        self._verdicts = {key.lower(): value for key, value in (verdicts or {}).items()}
        self._default = default
        self.requests: list[EmailVerificationRequest] = []

    def verify_email(self, request: EmailVerificationRequest) -> EmailVerificationResult:
        self.requests.append(request)
        if request.allow_smtp:
            raise LiveEmailVerificationNotImplementedError(
                "Phase 69 does not perform SMTP recipient-server validation"
            )
        email = clip_text(request.email.lower(), EMAIL_MAX_LENGTH)
        verdict = self._verdicts.get(email, self._default)
        return EmailVerificationResult(
            email=email,
            verdict=verdict,
            outcome=outcome_for_verdict(verdict),
            dry_run=True,
            live_call_attempted=False,
            smtp_attempted=False,
            provider_name="static",
            checked_at=datetime.now(tz=UTC),
            origin=request.origin,
            verification_status=verification_status_for_verdict(verdict, origin=request.origin),
            raw={"dry_run": True, "invented": False},
        )


def build_email_verification_provider(
    settings: Settings | None = None,
) -> EmailVerificationProvider:
    """Always the stub. Live adapters are never selected by this factory."""
    _ = settings or get_settings()
    return StubEmailVerificationProvider()


def sanitize_verification_details(
    *,
    verdict: EmailVerificationVerdict | None,
    outcome: EmailVerificationOutcome | None,
    origin: EmailCandidateOrigin | None,
    pattern_name: str | None = None,
    reused: bool = False,
    promoted: bool = False,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "dry_run": True,
        "live_call_attempted": False,
        "smtp_attempted": False,
        "outbound_attempted": False,
        "fabricated_facts": False,
        "invented_email": False,
        "reused": reused,
        "promoted": promoted,
    }
    if verdict is not None:
        payload["verdict"] = verdict.value
        payload["verified_safe"] = verdict in VERIFIED_SAFE_VERDICTS
    if outcome is not None:
        payload["outcome"] = outcome.value
    if origin is not None:
        payload["origin"] = origin.value
    if pattern_name:
        payload["pattern_name"] = pattern_name
    if extra:
        for key, value in extra.items():
            if key.lower() in {"email", "phone", "api_key", "token", "secret"}:
                continue
            payload[key] = value
    return payload


def known_verdicts() -> tuple[EmailVerificationVerdict, ...]:
    return tuple(EmailVerificationVerdict)


def known_outcomes() -> Sequence[EmailVerificationOutcome]:
    return tuple(EmailVerificationOutcome)
