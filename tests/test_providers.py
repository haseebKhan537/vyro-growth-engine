from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.providers.guarded import GuardedEmailProvider
from vyro_growth.providers.stubs import StubEmailProvider
from vyro_growth.services.outbound_guard import OutboundBlockedError, OutboundGuard


def test_guarded_email_provider_blocks_when_outbound_disabled() -> None:
    guard = OutboundGuard(Settings(outbound_enabled=False))
    provider = GuardedEmailProvider(StubEmailProvider(), guard, MagicMock(spec=Session))

    with pytest.raises(OutboundBlockedError, match="global_outbound_disabled"):
        provider.send_email(to="owner@clinic.com", subject="Hello", body="Test")


def test_guarded_email_provider_blocks_when_suppressed() -> None:
    guard = OutboundGuard(Settings(outbound_enabled=True))
    db = MagicMock(spec=Session)
    db.scalar.return_value = "suppression-id"
    provider = GuardedEmailProvider(StubEmailProvider(), guard, db)

    with pytest.raises(OutboundBlockedError, match="suppressed"):
        provider.send_email(to="blocked@clinic.com", subject="Hello", body="Test")


def test_guarded_email_provider_delegates_when_allowed() -> None:
    guard = OutboundGuard(Settings(outbound_enabled=True))
    db = MagicMock(spec=Session)
    db.scalar.return_value = None
    provider = GuardedEmailProvider(StubEmailProvider(), guard, db)

    result = provider.send_email(to="owner@clinic.com", subject="Hello", body="Test")

    assert result.accepted is True
    assert result.provider_message_id == "stub-email:owner@clinic.com"
