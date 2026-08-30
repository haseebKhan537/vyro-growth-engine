from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import VoiceConsentChannel, VoiceConsentSource
from vyro_growth.models import Suppression
from vyro_growth.providers.calendar_booking import (
    BookingPlanPayload,
    LiveGoogleCalendarDisabledError,
    StubBookingCalendarProvider,
)
from vyro_growth.providers.guarded import (
    GuardedCalendarProvider,
    GuardedEmailProvider,
    GuardedGoogleCalendarProvider,
    GuardedSmartleadProvider,
    GuardedVoiceProvider,
    GuardedVoiceQualificationProvider,
)
from vyro_growth.providers.smartlead import (
    LiveSmartleadDisabledError,
    SmartleadLeadPayload,
    StubSmartleadProvider,
)
from vyro_growth.providers.stubs import StubCalendarProvider, StubEmailProvider, StubVoiceProvider
from vyro_growth.providers.voice_qualification import (
    LiveVoiceDisabledError,
    StubVoiceQualificationProvider,
    VoiceConsentProof,
    VoiceQualificationRequest,
)
from vyro_growth.services.operator_halt import set_operator_halt
from vyro_growth.services.outbound_guard import OutboundBlockedError, OutboundGuard


def _cleared_guard(db: Session) -> OutboundGuard:
    set_operator_halt(db, halted=False, reason="test_clear")
    return OutboundGuard(Settings(outbound_enabled=True, outbound_halted=False))


def test_guarded_email_provider_blocks_when_outbound_disabled(db_session: Session) -> None:
    guard = OutboundGuard(Settings(outbound_enabled=False))
    provider = GuardedEmailProvider(StubEmailProvider(), guard, db_session)

    with pytest.raises(OutboundBlockedError, match="global_outbound_disabled"):
        provider.send_email(to="owner@clinic.com", subject="Hello", body="Test")


def test_guarded_email_provider_blocks_when_halted(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    guard = OutboundGuard(Settings(outbound_enabled=True, outbound_halted=False))
    provider = GuardedEmailProvider(StubEmailProvider(), guard, db_session)

    with pytest.raises(OutboundBlockedError, match="operator_global_halt"):
        provider.send_email(to="owner@clinic.com", subject="Hello", body="Test")


def test_guarded_email_provider_blocks_when_suppressed(db_session: Session) -> None:
    guard = _cleared_guard(db_session)
    db_session.add(
        Suppression(email="blocked@clinic.com", reason="unsubscribe", permanent=True)
    )
    db_session.flush()
    provider = GuardedEmailProvider(StubEmailProvider(), guard, db_session)

    with pytest.raises(OutboundBlockedError, match="suppressed"):
        provider.send_email(to="blocked@clinic.com", subject="Hello", body="Test")


def test_guarded_email_provider_delegates_when_allowed(db_session: Session) -> None:
    provider = GuardedEmailProvider(StubEmailProvider(), _cleared_guard(db_session), db_session)

    result = provider.send_email(to="owner@clinic.com", subject="Hello", body="Test")

    assert result.accepted is True
    assert result.provider_message_id == "stub-email:owner@clinic.com"


def test_guarded_calendar_provider_fails_closed_when_disabled(db_session: Session) -> None:
    provider = GuardedCalendarProvider(
        StubCalendarProvider(),
        OutboundGuard(Settings(outbound_enabled=False)),
        db_session,
    )

    with pytest.raises(OutboundBlockedError, match="global_outbound_disabled"):
        provider.create_meeting(
            attendee_email="owner@clinic.com",
            starts_at_iso="2026-09-01T15:00:00+00:00",
            duration_minutes=30,
            title="Intro",
        )


def test_guarded_calendar_provider_fails_closed_when_halted(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    provider = GuardedCalendarProvider(
        StubCalendarProvider(),
        OutboundGuard(Settings(outbound_enabled=True, outbound_halted=False)),
        db_session,
    )

    with pytest.raises(OutboundBlockedError, match="operator_global_halt"):
        provider.create_meeting(
            attendee_email="owner@clinic.com",
            starts_at_iso="2026-09-01T15:00:00+00:00",
            duration_minutes=30,
            title="Intro",
        )


def test_guarded_voice_provider_fails_closed_without_consent(db_session: Session) -> None:
    provider = GuardedVoiceProvider(
        StubVoiceProvider(),
        _cleared_guard(db_session),
        db_session,
    )

    with pytest.raises(OutboundBlockedError, match="voice_consent_required"):
        provider.place_consent_callback(phone="5551112222", consent_to_call=False)


def test_guarded_voice_provider_fails_closed_when_suppressed(db_session: Session) -> None:
    guard = _cleared_guard(db_session)
    db_session.add(Suppression(phone="5551112222", reason="do_not_call", permanent=True))
    db_session.flush()
    provider = GuardedVoiceProvider(StubVoiceProvider(), guard, db_session)

    with pytest.raises(OutboundBlockedError, match="suppressed"):
        provider.place_consent_callback(phone="555-111-2222", consent_to_call=True)


def test_guarded_voice_provider_delegates_when_allowed(db_session: Session) -> None:
    provider = GuardedVoiceProvider(
        StubVoiceProvider(),
        _cleared_guard(db_session),
        db_session,
    )

    result = provider.place_consent_callback(phone="5551112222", consent_to_call=True)

    assert result.accepted is True
    assert result.provider_call_id == "stub-call:5551112222:True"


def _smartlead_payload() -> SmartleadLeadPayload:
    return SmartleadLeadPayload(
        campaign_key="phase-6-dry-run",
        email="owner@clinic.com",
        company_name="Clinic",
        idempotency_key="key",
        organization_id=uuid4(),
    )


def test_guarded_smartlead_blocks_when_live_disabled(db_session: Session) -> None:
    inner = StubSmartleadProvider()
    settings = Settings(outbound_enabled=True, smartlead_live_enabled=False)
    provider = GuardedSmartleadProvider(
        inner,
        _cleared_guard(db_session),
        db_session,
        settings,
    )
    with pytest.raises(LiveSmartleadDisabledError, match="smartlead_live_disabled"):
        provider.plan_enrollment(_smartlead_payload())
    assert inner.requests == []


def test_guarded_google_calendar_blocks_when_live_disabled(db_session: Session) -> None:
    inner = StubBookingCalendarProvider()
    settings = Settings(outbound_enabled=True, google_calendar_live_enabled=False)
    provider = GuardedGoogleCalendarProvider(
        inner,
        _cleared_guard(db_session),
        db_session,
        settings,
    )
    with pytest.raises(LiveGoogleCalendarDisabledError, match="google_calendar_live_disabled"):
        provider.plan_booking(
            BookingPlanPayload(
                lead_id=uuid4(),
                organization_id=uuid4(),
                idempotency_key="key",
                request_source="operator_request",
                organization_name="Clinic",
                attendee_email="owner@clinic.com",
            )
        )
    assert inner.requests == []


def test_guarded_google_calendar_blocks_when_outbound_disabled(db_session: Session) -> None:
    inner = StubBookingCalendarProvider()
    settings = Settings(outbound_enabled=False, google_calendar_live_enabled=True)
    provider = GuardedGoogleCalendarProvider(
        inner,
        OutboundGuard(settings),
        db_session,
        settings,
    )
    with pytest.raises(OutboundBlockedError, match="global_outbound_disabled"):
        provider.plan_booking(
            BookingPlanPayload(
                lead_id=uuid4(),
                organization_id=uuid4(),
                idempotency_key="key",
                request_source="operator_request",
                organization_name="Clinic",
                attendee_email="owner@clinic.com",
            )
        )
    assert inner.requests == []


def test_guarded_smartlead_blocks_when_outbound_disabled(db_session: Session) -> None:
    inner = StubSmartleadProvider()
    settings = Settings(outbound_enabled=False, smartlead_live_enabled=True)
    provider = GuardedSmartleadProvider(
        inner,
        OutboundGuard(settings),
        db_session,
        settings,
    )
    with pytest.raises(OutboundBlockedError, match="global_outbound_disabled"):
        provider.plan_enrollment(_smartlead_payload())
    assert inner.requests == []


def _voice_request() -> VoiceQualificationRequest:
    return VoiceQualificationRequest(
        lead_id=uuid4(),
        organization_id=uuid4(),
        idempotency_key="key",
        request_key="ops-1",
        consent=VoiceConsentProof(
            source=VoiceConsentSource.OPERATOR_REQUEST,
            channel=VoiceConsentChannel.OPERATOR,
            consented_at=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
            permitted_phone="5551112222",
        ),
        organization_name="Clinic",
    )


def test_guarded_voice_qualification_blocks_when_live_disabled(db_session: Session) -> None:
    inner = StubVoiceQualificationProvider()
    settings = Settings(outbound_enabled=True, voice_live_enabled=False)
    provider = GuardedVoiceQualificationProvider(
        inner,
        _cleared_guard(db_session),
        db_session,
        settings,
    )
    with pytest.raises(LiveVoiceDisabledError, match="voice_live_disabled"):
        provider.plan_qualification(_voice_request())
    assert inner.requests == []


def test_guarded_voice_qualification_blocks_when_outbound_disabled(db_session: Session) -> None:
    inner = StubVoiceQualificationProvider()
    settings = Settings(outbound_enabled=False, voice_live_enabled=True)
    provider = GuardedVoiceQualificationProvider(
        inner,
        OutboundGuard(settings),
        db_session,
        settings,
    )
    with pytest.raises(OutboundBlockedError, match="global_outbound_disabled"):
        provider.plan_qualification(_voice_request())
    assert inner.requests == []
