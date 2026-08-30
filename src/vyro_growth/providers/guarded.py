from __future__ import annotations

from sqlalchemy.orm import Session

from vyro_growth.providers.base import (
    CalendarProvider,
    CallResult,
    EmailProvider,
    SendResult,
    VoiceProvider,
)
from vyro_growth.services.outbound_guard import (
    OutboundAction,
    OutboundGuard,
    domain_from_email,
)


class GuardedEmailProvider:
    """Send-capable adapter that enforces outbound safety gates before delegating."""

    def __init__(
        self,
        inner: EmailProvider,
        guard: OutboundGuard,
        db: Session,
    ) -> None:
        self._inner = inner
        self._guard = guard
        self._db = db

    def send_email(self, *, to: str, subject: str, body: str) -> SendResult:
        self._guard.require_allowed(
            self._db,
            action=OutboundAction.EMAIL_SEND,
            email=to,
            domain=domain_from_email(to),
        )
        return self._inner.send_email(to=to, subject=subject, body=body)


class GuardedCalendarProvider:
    """Schedule-capable adapter that enforces outbound safety gates before delegating."""

    def __init__(
        self,
        inner: CalendarProvider,
        guard: OutboundGuard,
        db: Session,
    ) -> None:
        self._inner = inner
        self._guard = guard
        self._db = db

    def create_meeting(
        self,
        *,
        attendee_email: str,
        starts_at_iso: str,
        duration_minutes: int,
        title: str,
    ) -> str:
        self._guard.require_allowed(
            self._db,
            action=OutboundAction.CALENDAR_SCHEDULE,
            email=attendee_email,
            domain=domain_from_email(attendee_email),
        )
        return self._inner.create_meeting(
            attendee_email=attendee_email,
            starts_at_iso=starts_at_iso,
            duration_minutes=duration_minutes,
            title=title,
        )


class GuardedVoiceProvider:
    """Consent-callback adapter that enforces outbound safety gates before delegating."""

    def __init__(
        self,
        inner: VoiceProvider,
        guard: OutboundGuard,
        db: Session,
    ) -> None:
        self._inner = inner
        self._guard = guard
        self._db = db

    def place_consent_callback(self, *, phone: str, consent_to_call: bool) -> CallResult:
        self._guard.require_allowed(
            self._db,
            action=OutboundAction.PHONE_DIAL,
            phone=phone,
            consent_to_call=consent_to_call,
        )
        return self._inner.place_consent_callback(phone=phone, consent_to_call=consent_to_call)
