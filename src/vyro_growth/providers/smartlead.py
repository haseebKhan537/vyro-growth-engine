from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from vyro_growth.config import Settings, get_settings
from vyro_growth.providers.decision_makers import clean_optional_text, clip_text

STUB_PROVIDER_NAME = "stub"
LIVE_PROVIDER_NAME = "smartlead_guarded"
EMAIL_MAX_LENGTH = 320
NAME_MAX_LENGTH = 255
CAMPAIGN_KEY_MAX_LENGTH = 255
CUSTOM_FIELD_MAX_LENGTH = 500
IDEMPOTENCY_KEY_MAX_LENGTH = 255


class SmartleadProviderError(RuntimeError):
    """Base error for Smartlead adapter failures."""

    retryable: bool = False


class RetryableSmartleadError(SmartleadProviderError):
    retryable = True


class NonRetryableSmartleadError(SmartleadProviderError):
    retryable = False


class MalformedSmartleadOutput(NonRetryableSmartleadError):
    """Raised when provider output cannot be parsed or violates dry-run rules."""


class LiveSmartleadDisabledError(NonRetryableSmartleadError):
    """Raised when the live Smartlead boundary is not explicitly enabled."""


class LiveSmartleadNotImplementedError(NonRetryableSmartleadError):
    """Raised when Phase 6 refuses to open a live Smartlead HTTP session."""


@dataclass(frozen=True)
class SmartleadLeadPayload:
    campaign_key: str
    email: str
    company_name: str
    idempotency_key: str
    organization_id: UUID
    first_name: str | None = None
    last_name: str | None = None
    custom_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SmartleadPlanResult:
    accepted: bool
    dry_run: bool
    live_call_attempted: bool
    provider_name: str
    provider_enrollment_id: str | None = None
    raw: dict[str, object] = field(default_factory=dict)


class SmartleadProvider(Protocol):
    live: bool

    def plan_enrollment(self, payload: SmartleadLeadPayload) -> SmartleadPlanResult: ...


def split_stored_name(full_name: str | None) -> tuple[str | None, str | None]:
    cleaned = clean_optional_text(full_name)
    if cleaned is None:
        return None, None
    parts = cleaned.split()
    first = clip_text(parts[0], NAME_MAX_LENGTH)
    last = clip_text(parts[-1], NAME_MAX_LENGTH) if len(parts) > 1 else None
    return first, last


def enrollment_idempotency_key(
    *,
    campaign_id: UUID,
    lead_id: UUID,
    contact_id: UUID | None,
) -> str:
    contact_part = str(contact_id) if contact_id is not None else "none"
    return clip_text(f"{campaign_id}:{lead_id}:{contact_part}", IDEMPOTENCY_KEY_MAX_LENGTH)


def stored_custom_fields(
    *,
    organization_name: str,
    city: str | None,
    state: str | None,
    specialty: str | None,
    website: str | None,
    npi: str | None,
    opening_line: str | None,
    outreach_angle: str | None,
    suggested_offer: str | None,
    personalization_draft_id: str | None,
) -> dict[str, str]:
    """Map only stored public/business and draft fields. Never invent facts."""
    values: dict[str, str | None] = {
        "organization_name": organization_name,
        "city": city,
        "state": state,
        "specialty": specialty,
        "website": website,
        "npi": npi,
        "opening_line": opening_line,
        "outreach_angle": outreach_angle,
        "suggested_offer": suggested_offer,
        "personalization_draft_id": personalization_draft_id,
    }
    fields: dict[str, str] = {}
    for key, value in values.items():
        cleaned = clean_optional_text(value)
        if cleaned:
            fields[key] = clip_text(cleaned, CUSTOM_FIELD_MAX_LENGTH)
    return fields


def parse_smartlead_plan_result(raw: object) -> SmartleadPlanResult:
    if isinstance(raw, SmartleadPlanResult):
        result = raw
    elif isinstance(raw, dict):
        accepted = raw.get("accepted")
        dry_run = raw.get("dry_run")
        live_call_attempted = raw.get("live_call_attempted")
        provider_name = clean_optional_text(
            raw.get("provider_name") if isinstance(raw.get("provider_name"), str) else None
        )
        enrollment_id = raw.get("provider_enrollment_id")
        if not isinstance(accepted, bool) or not isinstance(dry_run, bool):
            raise MalformedSmartleadOutput("smartlead result missing accepted/dry_run booleans")
        if not isinstance(live_call_attempted, bool):
            raise MalformedSmartleadOutput("smartlead result missing live_call_attempted boolean")
        if provider_name is None:
            raise MalformedSmartleadOutput("smartlead result missing provider_name")
        if enrollment_id is not None and not isinstance(enrollment_id, str):
            raise MalformedSmartleadOutput("smartlead provider_enrollment_id must be a string")
        extra = raw.get("raw")
        raw_payload = dict(extra) if isinstance(extra, dict) else dict(raw)
        result = SmartleadPlanResult(
            accepted=accepted,
            dry_run=dry_run,
            live_call_attempted=live_call_attempted,
            provider_name=clip_text(provider_name, 64),
            provider_enrollment_id=clean_optional_text(
                enrollment_id if isinstance(enrollment_id, str) else None
            ),
            raw=raw_payload,
        )
    else:
        raise MalformedSmartleadOutput("smartlead result was not an object")

    if result.raw.get("sent") is True:
        raise MalformedSmartleadOutput("smartlead result claimed a live send")
    if result.raw.get("enrolled_live") is True:
        raise MalformedSmartleadOutput("smartlead result claimed a live enrollment")
    return result


class StubSmartleadProvider:
    """CI/local default. Does not call Smartlead, send email, or enroll a live campaign."""

    live = False

    def __init__(self) -> None:
        self.requests: list[SmartleadLeadPayload] = []

    def plan_enrollment(self, payload: SmartleadLeadPayload) -> SmartleadPlanResult:
        self.requests.append(payload)
        return SmartleadPlanResult(
            accepted=True,
            dry_run=True,
            live_call_attempted=False,
            provider_name=STUB_PROVIDER_NAME,
            provider_enrollment_id=f"stub-enroll:{payload.idempotency_key}",
            raw={"dry_run": True, "sent": False, "enrolled_live": False},
        )


class StaticSmartleadProvider:
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
        self.requests: list[SmartleadLeadPayload] = []

    def plan_enrollment(self, payload: SmartleadLeadPayload) -> SmartleadPlanResult:
        self.requests.append(payload)
        if self._error is not None:
            raise self._error
        if self._result is None:
            return StubSmartleadProvider().plan_enrollment(payload)
        return parse_smartlead_plan_result(self._result)


def build_smartlead_provider(settings: Settings | None = None) -> SmartleadProvider:
    """Always the stub. Live Smartlead is not wired and must not be called in CI."""
    _ = settings or get_settings()
    return StubSmartleadProvider()
