from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from vyro_growth.config import Settings, get_settings
from vyro_growth.domain import VoiceConsentChannel, VoiceConsentSource
from vyro_growth.providers.decision_makers import clean_optional_text, clip_text
from vyro_growth.services.outbound_guard import normalize_phone

STUB_PROVIDER_NAME = "stub"
LIVE_PROVIDER_NAME = "voice_guarded"
IDEMPOTENCY_KEY_MAX_LENGTH = 255
FACT_VALUE_MAX_LENGTH = 240
PLAN_PATH_SUFFIX = "/voice/plans"
DEFAULT_OPERATOR_REQUEST_KEY = "operator"

SAFE_FACT_KEYS = frozenset(
    {
        "provider_count",
        "specialty",
        "billing_setup",
        "denial_ar_pain",
        "decision_maker_status",
        "urgency",
        "current_vendor_status",
        "preferred_follow_up",
    }
)

CALL_REQUEST_PHRASES = (
    "please call",
    "call me",
    "give me a call",
    "hop on a call",
    "you can call",
    "ok to call",
    "okay to call",
    "permission to call",
    "call us",
    "call back",
    "callback",
    "request a call",
    "requested a call",
    "approve a call",
    "approved a call",
    "available for a call",
    "schedule a call",
    "set up a call",
    "happy to hop on a call",
)

PHI_PHRASES = (
    "patient name",
    "patient diagnosis",
    "patient portal",
    "medical record",
    "date of birth",
    "social security",
    "protected health",
    "prescription",
    "diagnosed with",
    "my patient",
    "our patient",
    "the patient",
    "insurance member",
    "member id",
    "hipaa",
)

PHI_PATTERNS = (
    re.compile(r"\bphi\b", re.I),
    re.compile(r"\bssn\b", re.I),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\bmrn\b", re.I),
    re.compile(r"\bdob\b", re.I),
    re.compile(r"\bpatients?\b", re.I),
    re.compile(r"\bpatient's\b", re.I),
)


class VoiceQualificationError(RuntimeError):
    """Base error for voice qualification adapter failures."""

    retryable: bool = False


class RetryableVoiceQualificationError(VoiceQualificationError):
    retryable = True


class NonRetryableVoiceQualificationError(VoiceQualificationError):
    retryable = False


class MalformedVoicePlanOutput(NonRetryableVoiceQualificationError):
    """Raised when provider output cannot be parsed or violates dry-run rules."""


class LiveVoiceDisabledError(NonRetryableVoiceQualificationError):
    """Raised when the live voice boundary is not explicitly enabled."""


class LiveVoiceNotImplementedError(NonRetryableVoiceQualificationError):
    """Raised when Phase 9 refuses to open a live voice HTTP session."""


@dataclass(frozen=True)
class VoiceConsentProof:
    source: VoiceConsentSource
    channel: VoiceConsentChannel
    consented_at: datetime
    permitted_phone: str
    evidence_reference_id: str | None = None

    def to_audit(self) -> dict[str, object]:
        phone = normalize_phone(self.permitted_phone) or self.permitted_phone
        return {
            "source": self.source.value,
            "channel": self.channel.value,
            "timestamp": self.consented_at.isoformat(),
            "evidence_reference_id": self.evidence_reference_id,
            "permitted_phone": phone,
        }


@dataclass(frozen=True)
class VoiceQualificationRequest:
    lead_id: UUID
    organization_id: UUID
    idempotency_key: str
    request_key: str
    consent: VoiceConsentProof
    organization_name: str
    contact_id: UUID | None = None
    stored_facts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class VoiceQualificationResult:
    accepted: bool
    dry_run: bool
    live_call_attempted: bool
    call_placed: bool
    provider_name: str
    provider_plan_id: str | None = None
    facts: dict[str, str] = field(default_factory=dict)
    raw: dict[str, object] = field(default_factory=dict)


class VoiceQualificationProvider(Protocol):
    live: bool

    def plan_qualification(
        self, request: VoiceQualificationRequest
    ) -> VoiceQualificationResult: ...


def voice_idempotency_key(
    *,
    lead_id: UUID,
    contact_id: UUID | None,
    consent_source: VoiceConsentSource | str,
    request_key: str,
) -> str:
    source = (
        consent_source.value
        if isinstance(consent_source, VoiceConsentSource)
        else consent_source
    )
    contact_part = str(contact_id) if contact_id is not None else "none"
    return clip_text(
        f"{lead_id}:{contact_part}:{source}:{request_key}",
        IDEMPOTENCY_KEY_MAX_LENGTH,
    )


def message_requests_call(text: str | None) -> bool:
    cleaned = clean_optional_text(text)
    if cleaned is None:
        return False
    lowered = cleaned.lower()
    return any(phrase in lowered for phrase in CALL_REQUEST_PHRASES)


def contains_suspected_phi(*values: object) -> bool:
    for value in values:
        if _value_has_phi(value):
            return True
    return False


def sanitize_stored_facts(raw: dict[str, object] | None) -> dict[str, str]:
    """Keep only allowlisted B2B facts that were actually supplied. Never invent."""
    facts: dict[str, str] = {}
    if not raw:
        return facts
    for key in SAFE_FACT_KEYS:
        value = raw.get(key)
        cleaned = clean_optional_text(value if isinstance(value, str) else None)
        if cleaned is None:
            continue
        if contains_suspected_phi(cleaned):
            continue
        facts[key] = clip_text(cleaned, FACT_VALUE_MAX_LENGTH)
    return facts


def parse_consent_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_voice_qualification_result(
    raw: object,
    *,
    allowed_facts: dict[str, str] | None = None,
) -> VoiceQualificationResult:
    if isinstance(raw, VoiceQualificationResult):
        result = raw
    elif isinstance(raw, dict):
        accepted = raw.get("accepted")
        dry_run = raw.get("dry_run")
        live_call_attempted = raw.get("live_call_attempted")
        call_placed = raw.get("call_placed")
        provider_name = clean_optional_text(
            raw.get("provider_name") if isinstance(raw.get("provider_name"), str) else None
        )
        if not isinstance(accepted, bool) or not isinstance(dry_run, bool):
            raise MalformedVoicePlanOutput("voice result missing accepted/dry_run booleans")
        if not isinstance(live_call_attempted, bool):
            raise MalformedVoicePlanOutput("voice result missing live_call_attempted boolean")
        if not isinstance(call_placed, bool):
            raise MalformedVoicePlanOutput("voice result missing call_placed boolean")
        if provider_name is None:
            raise MalformedVoicePlanOutput("voice result missing provider_name")
        plan_id = raw.get("provider_plan_id")
        if plan_id is not None and not isinstance(plan_id, str):
            raise MalformedVoicePlanOutput("voice provider_plan_id must be a string")
        extra = raw.get("raw")
        raw_payload = dict(extra) if isinstance(extra, dict) else dict(raw)
        facts_raw = raw.get("facts")
        facts = sanitize_stored_facts(facts_raw if isinstance(facts_raw, dict) else None)
        result = VoiceQualificationResult(
            accepted=accepted,
            dry_run=dry_run,
            live_call_attempted=live_call_attempted,
            call_placed=call_placed,
            provider_name=clip_text(provider_name, 64),
            provider_plan_id=clean_optional_text(plan_id if isinstance(plan_id, str) else None),
            facts=facts,
            raw=raw_payload,
        )
    else:
        raise MalformedVoicePlanOutput("voice result was not an object")

    if result.raw.get("sent") is True:
        raise MalformedVoicePlanOutput("voice result claimed an outbound send")
    if result.raw.get("enrolled_live") is True:
        raise MalformedVoicePlanOutput("voice result claimed a live enrollment")
    if result.raw.get("meeting_url"):
        raise MalformedVoicePlanOutput("voice result included a meeting URL")
    if result.raw.get("event_created") is True:
        raise MalformedVoicePlanOutput("voice result claimed a calendar event")
    if result.call_placed or result.raw.get("call_placed") is True:
        raise MalformedVoicePlanOutput("voice result claimed a live call")
    if allowed_facts is not None:
        for key, value in result.facts.items():
            if key not in allowed_facts or allowed_facts[key] != value:
                raise MalformedVoicePlanOutput("voice result invented a qualification fact")
    return result


def _value_has_phi(value: object) -> bool:
    if isinstance(value, dict):
        return any(_value_has_phi(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_value_has_phi(item) for item in value)
    if not isinstance(value, str):
        return False
    cleaned = clean_optional_text(value)
    if cleaned is None:
        return False
    lowered = cleaned.lower()
    if any(phrase in lowered for phrase in PHI_PHRASES):
        return True
    return any(pattern.search(cleaned) is not None for pattern in PHI_PATTERNS)


class StubVoiceQualificationProvider:
    """CI/local default. Does not place calls or contact a live voice provider."""

    live = False

    def __init__(self) -> None:
        self.requests: list[VoiceQualificationRequest] = []

    def plan_qualification(self, request: VoiceQualificationRequest) -> VoiceQualificationResult:
        self.requests.append(request)
        facts = sanitize_stored_facts(dict(request.stored_facts))
        return VoiceQualificationResult(
            accepted=True,
            dry_run=True,
            live_call_attempted=False,
            call_placed=False,
            provider_name=STUB_PROVIDER_NAME,
            provider_plan_id=f"stub-voice:{request.idempotency_key}",
            facts=facts,
            raw={
                "dry_run": True,
                "call_placed": False,
                "sent": False,
                "enrolled_live": False,
                "event_created": False,
            },
        )


class StaticVoiceQualificationProvider:
    """Test adapter that returns a configured payload or raises a configured error."""

    live = False

    def __init__(
        self,
        result: object | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.requests: list[VoiceQualificationRequest] = []

    def plan_qualification(self, request: VoiceQualificationRequest) -> VoiceQualificationResult:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        if self._result is None:
            return StubVoiceQualificationProvider().plan_qualification(request)
        return parse_voice_qualification_result(
            self._result,
            allowed_facts=request.stored_facts,
        )


def build_voice_qualification_provider(
    settings: Settings | None = None,
) -> VoiceQualificationProvider:
    """Always the stub. Live voice is not wired and must not be called in CI."""
    _ = settings or get_settings()
    return StubVoiceQualificationProvider()
