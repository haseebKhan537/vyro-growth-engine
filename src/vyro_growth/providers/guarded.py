from __future__ import annotations

from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.providers.base import (
    CalendarProvider,
    CallResult,
    EmailProvider,
    SendResult,
    VoiceProvider,
)
from vyro_growth.providers.calendar_booking import (
    BookingCalendarProvider,
    BookingPlanPayload,
    BookingPlanProviderResult,
    LiveGoogleCalendarDisabledError,
)
from vyro_growth.providers.smartlead import (
    LiveSmartleadDisabledError,
    SmartleadLeadPayload,
    SmartleadPlanResult,
    SmartleadProvider,
)
from vyro_growth.providers.voice_qualification import (
    LiveVoiceDisabledError,
    VoiceQualificationProvider,
    VoiceQualificationRequest,
    VoiceQualificationResult,
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


class GuardedSmartleadProvider:
    """Live Smartlead boundary that enforces outbound and live-enablement gates."""

    live = True

    def __init__(
        self,
        inner: SmartleadProvider,
        guard: OutboundGuard,
        db: Session,
        settings: Settings,
    ) -> None:
        self._inner = inner
        self._guard = guard
        self._db = db
        self._settings = settings

    def plan_enrollment(self, payload: SmartleadLeadPayload) -> SmartleadPlanResult:
        if not self._settings.smartlead_live_enabled:
            raise LiveSmartleadDisabledError("smartlead_live_disabled")
        self._guard.require_allowed(
            self._db,
            action=OutboundAction.CAMPAIGN_ENROLL,
            email=payload.email,
            domain=domain_from_email(payload.email),
            organization_id=payload.organization_id,
        )
        return self._inner.plan_enrollment(payload)


class GuardedGoogleCalendarProvider:
    """Live Google Calendar boundary that enforces outbound and live-enablement gates."""

    live = True

    def __init__(
        self,
        inner: BookingCalendarProvider,
        guard: OutboundGuard,
        db: Session,
        settings: Settings,
    ) -> None:
        self._inner = inner
        self._guard = guard
        self._db = db
        self._settings = settings

    def plan_booking(self, payload: BookingPlanPayload) -> BookingPlanProviderResult:
        if not self._settings.google_calendar_live_enabled:
            raise LiveGoogleCalendarDisabledError("google_calendar_live_disabled")
        self._guard.require_allowed(
            self._db,
            action=OutboundAction.CALENDAR_SCHEDULE,
            email=payload.attendee_email,
            domain=domain_from_email(payload.attendee_email),
            organization_id=payload.organization_id,
        )
        return self._inner.plan_booking(payload)


class GuardedVoiceQualificationProvider:
    """Live voice boundary that enforces outbound, consent, and live-enablement gates."""

    live = True

    def __init__(
        self,
        inner: VoiceQualificationProvider,
        guard: OutboundGuard,
        db: Session,
        settings: Settings,
    ) -> None:
        self._inner = inner
        self._guard = guard
        self._db = db
        self._settings = settings

    def plan_qualification(self, request: VoiceQualificationRequest) -> VoiceQualificationResult:
        if not self._settings.voice_live_enabled:
            raise LiveVoiceDisabledError("voice_live_disabled")
        self._guard.require_allowed(
            self._db,
            action=OutboundAction.PHONE_DIAL,
            phone=request.consent.permitted_phone,
            organization_id=request.organization_id,
            consent_to_call=True,
        )
        return self._inner.plan_qualification(request)
