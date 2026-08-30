from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from vyro_growth.config import Settings, get_settings
from vyro_growth.domain import BookingRequestSource
from vyro_growth.providers.decision_makers import clean_optional_text, clip_text

STUB_PROVIDER_NAME = "stub"
LIVE_PROVIDER_NAME = "google_calendar_guarded"
IDEMPOTENCY_KEY_MAX_LENGTH = 255
SLOT_TIMEZONE = "UTC"
DEFAULT_DURATION_MINUTES = 30
DEFAULT_SLOT_ORIGIN = datetime(2026, 9, 8, 15, 0, tzinfo=UTC)
PLAN_PATH_SUFFIX = "/calendar/bookings/plan"


class BookingCalendarError(RuntimeError):
    """Base error for booking calendar adapter failures."""

    retryable: bool = False


class RetryableBookingCalendarError(BookingCalendarError):
    retryable = True


class NonRetryableBookingCalendarError(BookingCalendarError):
    retryable = False


class MalformedBookingPlanOutput(NonRetryableBookingCalendarError):
    """Raised when provider output cannot be parsed or violates dry-run rules."""


class LiveGoogleCalendarDisabledError(NonRetryableBookingCalendarError):
    """Raised when the live Google Calendar boundary is not explicitly enabled."""


class LiveGoogleCalendarNotImplementedError(NonRetryableBookingCalendarError):
    """Raised when Phase 8 refuses to open a live Google Calendar HTTP session."""


@dataclass(frozen=True)
class ProposedSlot:
    starts_at_iso: str
    duration_minutes: int
    timezone: str

    def to_dict(self) -> dict[str, object]:
        return {
            "starts_at_iso": self.starts_at_iso,
            "duration_minutes": self.duration_minutes,
            "timezone": self.timezone,
            "proposed_only": True,
        }


@dataclass(frozen=True)
class BookingPlanPayload:
    lead_id: UUID
    organization_id: UUID
    idempotency_key: str
    request_source: str
    organization_name: str
    contact_id: UUID | None = None
    attendee_email: str | None = None
    requested_window: dict[str, object] | None = None


@dataclass(frozen=True)
class BookingPlanProviderResult:
    accepted: bool
    dry_run: bool
    live_call_attempted: bool
    event_created: bool
    meet_link_created: bool
    provider_name: str
    provider_event_id: str | None = None
    meeting_url: str | None = None
    proposed_slots: tuple[ProposedSlot, ...] = ()
    raw: dict[str, object] = field(default_factory=dict)


class BookingCalendarProvider(Protocol):
    live: bool

    def plan_booking(self, payload: BookingPlanPayload) -> BookingPlanProviderResult: ...


def booking_idempotency_key(
    *,
    lead_id: UUID,
    contact_id: UUID | None,
    request_source: BookingRequestSource | str,
    request_key: str,
) -> str:
    source = (
        request_source.value
        if isinstance(request_source, BookingRequestSource)
        else request_source
    )
    contact_part = str(contact_id) if contact_id is not None else "none"
    return clip_text(
        f"{lead_id}:{contact_part}:{source}:{request_key}",
        IDEMPOTENCY_KEY_MAX_LENGTH,
    )


def default_proposed_slots(
    requested_window: dict[str, object] | None = None,
) -> tuple[ProposedSlot, ...]:
    """Return deterministic proposed-only placeholders. Never live availability."""
    origin = DEFAULT_SLOT_ORIGIN
    if requested_window is not None:
        start_raw = requested_window.get("starts_at")
        if isinstance(start_raw, str) and start_raw.strip():
            parsed = _parse_iso(start_raw)
            if parsed is not None:
                origin = parsed
    return tuple(
        ProposedSlot(
            starts_at_iso=(origin + timedelta(days=offset)).isoformat(),
            duration_minutes=DEFAULT_DURATION_MINUTES,
            timezone=SLOT_TIMEZONE,
        )
        for offset in range(3)
    )


def parse_booking_plan_result(raw: object) -> BookingPlanProviderResult:
    if isinstance(raw, BookingPlanProviderResult):
        result = raw
    elif isinstance(raw, dict):
        accepted = raw.get("accepted")
        dry_run = raw.get("dry_run")
        live_call_attempted = raw.get("live_call_attempted")
        event_created = raw.get("event_created")
        meet_link_created = raw.get("meet_link_created")
        provider_name = clean_optional_text(
            raw.get("provider_name") if isinstance(raw.get("provider_name"), str) else None
        )
        if not isinstance(accepted, bool) or not isinstance(dry_run, bool):
            raise MalformedBookingPlanOutput("booking result missing accepted/dry_run booleans")
        if not isinstance(live_call_attempted, bool):
            raise MalformedBookingPlanOutput("booking result missing live_call_attempted boolean")
        if not isinstance(event_created, bool) or not isinstance(meet_link_created, bool):
            raise MalformedBookingPlanOutput(
                "booking result missing event_created/meet_link_created booleans"
            )
        if provider_name is None:
            raise MalformedBookingPlanOutput("booking result missing provider_name")
        event_id = raw.get("provider_event_id")
        meeting_url = raw.get("meeting_url")
        if event_id is not None and not isinstance(event_id, str):
            raise MalformedBookingPlanOutput("booking provider_event_id must be a string")
        if meeting_url is not None and not isinstance(meeting_url, str):
            raise MalformedBookingPlanOutput("booking meeting_url must be a string")
        extra = raw.get("raw")
        raw_payload = dict(extra) if isinstance(extra, dict) else dict(raw)
        result = BookingPlanProviderResult(
            accepted=accepted,
            dry_run=dry_run,
            live_call_attempted=live_call_attempted,
            event_created=event_created,
            meet_link_created=meet_link_created,
            provider_name=clip_text(provider_name, 64),
            provider_event_id=clean_optional_text(event_id if isinstance(event_id, str) else None),
            meeting_url=clean_optional_text(
                meeting_url if isinstance(meeting_url, str) else None
            ),
            proposed_slots=_parse_slots(raw.get("proposed_slots")),
            raw=raw_payload,
        )
    else:
        raise MalformedBookingPlanOutput("booking result was not an object")

    if result.raw.get("sent") is True:
        raise MalformedBookingPlanOutput("booking result claimed an outbound send")
    if result.meeting_url:
        raise MalformedBookingPlanOutput("booking result included a meeting URL")
    if result.provider_event_id:
        raise MalformedBookingPlanOutput("booking result included a provider event id")
    return result


def _parse_slots(raw: object) -> tuple[ProposedSlot, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise MalformedBookingPlanOutput("booking proposed_slots must be a list")
    slots: list[ProposedSlot] = []
    for item in raw:
        if not isinstance(item, dict):
            raise MalformedBookingPlanOutput("booking proposed slot must be an object")
        starts = item.get("starts_at_iso")
        duration = item.get("duration_minutes")
        timezone = item.get("timezone")
        if not isinstance(starts, str) or not starts.strip():
            raise MalformedBookingPlanOutput("booking proposed slot missing starts_at_iso")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            raise MalformedBookingPlanOutput("booking proposed slot has invalid duration")
        if not isinstance(timezone, str) or not timezone.strip():
            raise MalformedBookingPlanOutput("booking proposed slot missing timezone")
        slots.append(
            ProposedSlot(
                starts_at_iso=starts.strip(),
                duration_minutes=duration,
                timezone=timezone.strip(),
            )
        )
    return tuple(slots)


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class StubBookingCalendarProvider:
    """CI/local default. Does not call Google, create events, or create Meet links."""

    live = False

    def __init__(self) -> None:
        self.requests: list[BookingPlanPayload] = []

    def plan_booking(self, payload: BookingPlanPayload) -> BookingPlanProviderResult:
        self.requests.append(payload)
        slots = default_proposed_slots(payload.requested_window)
        return BookingPlanProviderResult(
            accepted=True,
            dry_run=True,
            live_call_attempted=False,
            event_created=False,
            meet_link_created=False,
            provider_name=STUB_PROVIDER_NAME,
            provider_event_id=None,
            meeting_url=None,
            proposed_slots=slots,
            raw={
                "dry_run": True,
                "event_created": False,
                "meet_link_created": False,
                "sent": False,
                "proposed_only": True,
            },
        )


class StaticBookingCalendarProvider:
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
        self.requests: list[BookingPlanPayload] = []

    def plan_booking(self, payload: BookingPlanPayload) -> BookingPlanProviderResult:
        self.requests.append(payload)
        if self._error is not None:
            raise self._error
        if self._result is None:
            return StubBookingCalendarProvider().plan_booking(payload)
        return parse_booking_plan_result(self._result)


def build_booking_calendar_provider(
    settings: Settings | None = None,
) -> BookingCalendarProvider:
    """Always the stub. Live Google Calendar is not wired and must not be called in CI."""
    _ = settings or get_settings()
    return StubBookingCalendarProvider()
