from __future__ import annotations

from uuid import uuid4

import pytest

from vyro_growth.config import Settings
from vyro_growth.domain import BookingRequestSource
from vyro_growth.providers.calendar_booking import (
    BookingPlanPayload,
    MalformedBookingPlanOutput,
    StubBookingCalendarProvider,
    booking_idempotency_key,
    build_booking_calendar_provider,
    default_proposed_slots,
    parse_booking_plan_result,
)


def _payload() -> BookingPlanPayload:
    return BookingPlanPayload(
        lead_id=uuid4(),
        organization_id=uuid4(),
        idempotency_key="key-1",
        request_source=BookingRequestSource.MEETING_REQUEST_REPLY.value,
        organization_name="AUSTIN FAMILY MEDICINE PLLC",
        attendee_email="jordan.blake@austinfamily.example",
    )


def test_stub_plans_without_event_or_meet() -> None:
    provider = StubBookingCalendarProvider()
    result = provider.plan_booking(_payload())
    assert result.accepted is True
    assert result.dry_run is True
    assert result.live_call_attempted is False
    assert result.event_created is False
    assert result.meet_link_created is False
    assert result.provider_event_id is None
    assert result.meeting_url is None
    assert len(result.proposed_slots) == 3


def test_build_booking_calendar_provider_always_returns_stub() -> None:
    settings = Settings(google_calendar_live_enabled=True, google_calendar_api_key="placeholder")
    provider = build_booking_calendar_provider(settings)
    assert isinstance(provider, StubBookingCalendarProvider)


def test_parse_rejects_meeting_url_and_event_id() -> None:
    with pytest.raises(MalformedBookingPlanOutput, match="meeting URL"):
        parse_booking_plan_result(
            {
                "accepted": True,
                "dry_run": True,
                "live_call_attempted": False,
                "event_created": False,
                "meet_link_created": False,
                "provider_name": "stub",
                "meeting_url": "https://meet.example/abc",
            }
        )
    with pytest.raises(MalformedBookingPlanOutput, match="provider event id"):
        parse_booking_plan_result(
            {
                "accepted": True,
                "dry_run": True,
                "live_call_attempted": False,
                "event_created": False,
                "meet_link_created": False,
                "provider_name": "stub",
                "provider_event_id": "evt-1",
            }
        )


def test_idempotency_key_includes_classification_or_operator() -> None:
    lead_id = uuid4()
    contact_id = uuid4()
    first = booking_idempotency_key(
        lead_id=lead_id,
        contact_id=contact_id,
        request_source=BookingRequestSource.MEETING_REQUEST_REPLY,
        request_key="class-1",
    )
    second = booking_idempotency_key(
        lead_id=lead_id,
        contact_id=contact_id,
        request_source=BookingRequestSource.MEETING_REQUEST_REPLY,
        request_key="class-1",
    )
    operator = booking_idempotency_key(
        lead_id=lead_id,
        contact_id=contact_id,
        request_source=BookingRequestSource.OPERATOR_REQUEST,
        request_key="ops-1",
    )
    assert first == second
    assert first != operator


def test_default_slots_use_requested_window_when_present() -> None:
    slots = default_proposed_slots({"starts_at": "2026-10-01T14:00:00+00:00"})
    assert slots[0].starts_at_iso.startswith("2026-10-01T14:00:00")
    assert slots[0].duration_minutes == 30
