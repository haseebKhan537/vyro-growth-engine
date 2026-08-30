from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.outbound_guard import OutboundBlockedError, OutboundGuard


@pytest.fixture
def enabled_settings() -> Settings:
    return Settings(outbound_enabled=True)


@pytest.fixture
def disabled_settings() -> Settings:
    return Settings(outbound_enabled=False)


def test_outbound_blocked_when_global_switch_disabled(disabled_settings: Settings) -> None:
    guard = OutboundGuard(disabled_settings)
    db = MagicMock(spec=Session)

    decision = guard.evaluate(db, email="owner@clinic.com", domain="clinic.com")

    assert decision.allowed is False
    assert decision.reason == "global_outbound_disabled"
    db.scalar.assert_not_called()


def test_outbound_allowed_when_enabled_and_not_suppressed(enabled_settings: Settings) -> None:
    guard = OutboundGuard(enabled_settings)
    db = MagicMock(spec=Session)
    db.scalar.return_value = None

    decision = guard.evaluate(db, email="owner@clinic.com", domain="clinic.com")

    assert decision.allowed is True
    assert decision.reason == "allowed"


def test_outbound_blocked_when_email_suppressed(enabled_settings: Settings) -> None:
    guard = OutboundGuard(enabled_settings)
    db = MagicMock(spec=Session)
    db.scalar.return_value = "suppression-id"

    decision = guard.evaluate(db, email="blocked@clinic.com", domain="clinic.com")

    assert decision.allowed is False
    assert decision.reason == "suppressed"


def test_outbound_blocked_when_domain_suppressed(enabled_settings: Settings) -> None:
    guard = OutboundGuard(enabled_settings)
    db = MagicMock(spec=Session)
    db.scalar.return_value = "suppression-id"

    decision = guard.evaluate(db, email=None, domain="blocked.com")

    assert decision.allowed is False
    assert decision.reason == "suppressed"


def test_require_allowed_raises_outbound_blocked_error(enabled_settings: Settings) -> None:
    guard = OutboundGuard(enabled_settings)
    db = MagicMock(spec=Session)
    db.scalar.return_value = "suppression-id"

    with pytest.raises(OutboundBlockedError, match="suppressed"):
        guard.require_allowed(db, email="blocked@clinic.com", domain="clinic.com")
