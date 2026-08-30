from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.models import Organization, Suppression
from vyro_growth.services.operator_halt import (
    HaltStatus,
    StaticHaltReader,
    read_operator_halt,
    set_operator_halt,
)
from vyro_growth.services.outbound_guard import (
    OutboundAction,
    OutboundBlockedError,
    OutboundGuard,
)


class _BoomHaltReader:
    def read(self, _db: Session) -> HaltStatus:
        raise RuntimeError("halt store unavailable")


def _enabled_settings() -> Settings:
    return Settings(outbound_enabled=True, outbound_halted=False)


def _cleared_guard(db: Session, settings: Settings | None = None) -> OutboundGuard:
    set_operator_halt(db, halted=False, reason="test_clear")
    return OutboundGuard(settings or _enabled_settings())


def test_default_settings_block_outbound(db_session: Session) -> None:
    settings = Settings()
    assert settings.outbound_enabled is False
    assert settings.outbound_halted is False

    guard = _cleared_guard(db_session, settings)
    decision = guard.evaluate(
        db_session,
        action=OutboundAction.EMAIL_SEND,
        email="owner@clinic.com",
    )

    assert decision.allowed is False
    assert decision.reason == "global_outbound_disabled"


def test_env_enabled_blocked_when_settings_halt_active(db_session: Session) -> None:
    set_operator_halt(db_session, halted=False, reason="cleared")
    guard = OutboundGuard(Settings(outbound_enabled=True, outbound_halted=True))

    decision = guard.evaluate(
        db_session,
        action=OutboundAction.EMAIL_SEND,
        email="owner@clinic.com",
    )

    assert decision.allowed is False
    assert decision.reason == "operator_global_halt"


def test_env_enabled_blocked_when_persistent_halt_active(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    guard = OutboundGuard(_enabled_settings())

    decision = guard.evaluate(
        db_session,
        action=OutboundAction.EMAIL_SEND,
        email="owner@clinic.com",
    )

    assert decision.allowed is False
    assert decision.reason == "operator_global_halt"
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_missing_operator_row_fails_closed(db_session: Session) -> None:
    guard = OutboundGuard(_enabled_settings())

    decision = guard.evaluate(
        db_session,
        action=OutboundAction.EMAIL_SEND,
        email="owner@clinic.com",
    )

    assert decision.allowed is False
    assert decision.reason == "operator_halt_unavailable"
    assert read_operator_halt(db_session) is HaltStatus.UNAVAILABLE


def test_halt_reader_error_fails_closed() -> None:
    guard = OutboundGuard(_enabled_settings(), halt_reader=_BoomHaltReader())
    db = MagicMock(spec=Session)

    decision = guard.evaluate(db, action=OutboundAction.EMAIL_SEND, email="owner@clinic.com")

    assert decision.allowed is False
    assert decision.reason == "operator_halt_unavailable"
    db.scalar.assert_not_called()


def test_outbound_allowed_when_enabled_halt_cleared_and_not_suppressed(
    db_session: Session,
) -> None:
    guard = _cleared_guard(db_session)

    decision = guard.evaluate(
        db_session,
        action=OutboundAction.EMAIL_SEND,
        email="owner@clinic.com",
        domain="clinic.com",
    )

    assert decision.allowed is True
    assert decision.reason == "allowed"


def test_email_suppression_is_honored(db_session: Session) -> None:
    guard = _cleared_guard(db_session)
    db_session.add(
        Suppression(email="blocked@clinic.com", reason="unsubscribe", permanent=True)
    )
    db_session.flush()

    decision = guard.evaluate(
        db_session,
        action=OutboundAction.EMAIL_SEND,
        email="blocked@clinic.com",
    )

    assert decision.allowed is False
    assert decision.reason == "suppressed"


def test_domain_suppression_is_honored(db_session: Session) -> None:
    guard = _cleared_guard(db_session)
    db_session.add(Suppression(domain="blocked.com", reason="domain_opt_out", permanent=True))
    db_session.flush()

    decision = guard.evaluate(
        db_session,
        action=OutboundAction.CALENDAR_SCHEDULE,
        email="owner@blocked.com",
    )

    assert decision.allowed is False
    assert decision.reason == "suppressed"


def test_phone_suppression_is_honored(db_session: Session) -> None:
    guard = _cleared_guard(db_session)
    db_session.add(Suppression(phone="5551112222", reason="do_not_call", permanent=True))
    db_session.flush()

    decision = guard.evaluate(
        db_session,
        action=OutboundAction.PHONE_DIAL,
        phone="(555) 111-2222",
        consent_to_call=True,
    )

    assert decision.allowed is False
    assert decision.reason == "suppressed"


def test_organization_suppression_is_honored(db_session: Session) -> None:
    guard = _cleared_guard(db_session)
    organization = Organization(name="Blocked Clinic", npi="1487448189", state="TX")
    db_session.add(organization)
    db_session.flush()
    db_session.add(
        Suppression(organization_id=organization.id, reason="org_block", permanent=True)
    )
    db_session.flush()

    decision = guard.evaluate(
        db_session,
        action=OutboundAction.CAMPAIGN_ENROLL,
        email="owner@clinic.com",
        organization_id=organization.id,
    )

    assert decision.allowed is False
    assert decision.reason == "suppressed"


def test_voice_without_consent_fails_closed(db_session: Session) -> None:
    guard = _cleared_guard(db_session)

    decision = guard.evaluate(
        db_session,
        action=OutboundAction.PHONE_DIAL,
        phone="5551112222",
        consent_to_call=False,
    )

    assert decision.allowed is False
    assert decision.reason == "voice_consent_required"


def test_unidentified_target_fails_closed(db_session: Session) -> None:
    guard = _cleared_guard(db_session)

    decision = guard.evaluate(db_session, action=OutboundAction.EMAIL_SEND)

    assert decision.allowed is False
    assert decision.reason == "target_unidentified"


def test_suppression_query_error_fails_closed() -> None:
    guard = OutboundGuard(_enabled_settings(), halt_reader=StaticHaltReader(HaltStatus.CLEARED))
    db = MagicMock(spec=Session)
    db.scalar.side_effect = SQLAlchemyError("suppression store unavailable")

    decision = guard.evaluate(db, action=OutboundAction.EMAIL_SEND, email="owner@clinic.com")

    assert decision.allowed is False
    assert decision.reason == "suppression_check_unavailable"


def test_require_allowed_raises_outbound_blocked_error(db_session: Session) -> None:
    guard = _cleared_guard(db_session)
    db_session.add(
        Suppression(email="blocked@clinic.com", reason="unsubscribe", permanent=True)
    )
    db_session.flush()

    with pytest.raises(OutboundBlockedError, match="suppressed"):
        guard.require_allowed(
            db_session,
            action=OutboundAction.EMAIL_SEND,
            email="blocked@clinic.com",
        )


def test_outbound_blocked_when_global_switch_disabled() -> None:
    guard = OutboundGuard(Settings(outbound_enabled=False))
    db = MagicMock(spec=Session)

    decision = guard.evaluate(db, action=OutboundAction.EMAIL_SEND, email="owner@clinic.com")

    assert decision.allowed is False
    assert decision.reason == "global_outbound_disabled"
    db.scalar.assert_not_called()
