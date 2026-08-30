from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Never

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.models import Suppression
from vyro_growth.services.operator_halt import (
    DatabaseHaltReader,
    HaltReader,
    HaltStatus,
)


class OutboundBlockedError(RuntimeError):
    """Raised when an outbound action fails a required safety gate."""


class OutboundAction(StrEnum):
    EMAIL_SEND = "email_send"
    CALENDAR_SCHEDULE = "calendar_schedule"
    PHONE_DIAL = "phone_dial"


@dataclass(frozen=True)
class OutboundDecision:
    allowed: bool
    reason: str


def normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    cleaned = email.strip().lower()
    return cleaned or None


def normalize_domain(domain: str | None) -> str | None:
    if domain is None:
        return None
    cleaned = domain.strip().lower().lstrip("@")
    return cleaned or None


def domain_from_email(email: str | None) -> str | None:
    normalized = normalize_email(email)
    if normalized is None or "@" not in normalized:
        return None
    return normalize_domain(normalized.rsplit("@", maxsplit=1)[1])


def normalize_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    digits = "".join(character for character in phone if character.isdigit())
    return digits or None


def _unreachable(value: object) -> Never:
    raise RuntimeError(f"unhandled safety variant: {value!r}")


def _halt_block_reason(status: HaltStatus) -> OutboundDecision | None:
    match status:
        case HaltStatus.CLEARED:
            return None
        case HaltStatus.HALTED:
            return OutboundDecision(False, "operator_global_halt")
        case HaltStatus.UNAVAILABLE:
            return OutboundDecision(False, "operator_halt_unavailable")
        case _:
            return _unreachable(status)


def _action_policy_reason(
    action: OutboundAction,
    consent_to_call: bool,
) -> OutboundDecision | None:
    match action:
        case OutboundAction.EMAIL_SEND | OutboundAction.CALENDAR_SCHEDULE:
            return None
        case OutboundAction.PHONE_DIAL:
            if not consent_to_call:
                return OutboundDecision(False, "voice_consent_required")
            return None
        case _:
            return _unreachable(action)


class OutboundGuard:
    """Central fail-closed gate for any outreach-like external action."""

    def __init__(
        self,
        settings: Settings,
        *,
        halt_reader: HaltReader | None = None,
    ) -> None:
        self._settings = settings
        self._halt_reader = halt_reader or DatabaseHaltReader()

    def evaluate(
        self,
        db: Session,
        *,
        action: OutboundAction,
        email: str | None = None,
        domain: str | None = None,
        phone: str | None = None,
        consent_to_call: bool = False,
    ) -> OutboundDecision:
        if not self._settings.outbound_enabled:
            return OutboundDecision(False, "global_outbound_disabled")

        if self._settings.outbound_halted:
            return OutboundDecision(False, "operator_global_halt")

        try:
            halt_status = self._halt_reader.read(db)
        except Exception:
            halt_status = HaltStatus.UNAVAILABLE
        halt_decision = _halt_block_reason(halt_status)
        if halt_decision is not None:
            return halt_decision

        action_decision = _action_policy_reason(action, consent_to_call)
        if action_decision is not None:
            return action_decision

        email_n = normalize_email(email)
        domain_n = normalize_domain(domain) or domain_from_email(email_n)
        phone_n = normalize_phone(phone)
        if email_n is None and domain_n is None and phone_n is None:
            return OutboundDecision(False, "target_unidentified")

        return self._suppression_decision(db, email=email_n, domain=domain_n, phone=phone_n)

    def require_allowed(
        self,
        db: Session,
        *,
        action: OutboundAction,
        email: str | None = None,
        domain: str | None = None,
        phone: str | None = None,
        consent_to_call: bool = False,
    ) -> None:
        decision = self.evaluate(
            db,
            action=action,
            email=email,
            domain=domain,
            phone=phone,
            consent_to_call=consent_to_call,
        )
        if not decision.allowed:
            raise OutboundBlockedError(decision.reason)

    def _suppression_decision(
        self,
        db: Session,
        *,
        email: str | None,
        domain: str | None,
        phone: str | None,
    ) -> OutboundDecision:
        conditions = []
        if email:
            conditions.append(Suppression.email == email)
        if domain:
            conditions.append(Suppression.domain == domain)
        if phone:
            conditions.append(Suppression.phone == phone)

        if not conditions:
            return OutboundDecision(False, "target_unidentified")

        try:
            suppressed = db.scalar(select(Suppression.id).where(or_(*conditions)).limit(1))
        except SQLAlchemyError:
            return OutboundDecision(False, "suppression_check_unavailable")
        if suppressed is not None:
            return OutboundDecision(False, "suppressed")
        return OutboundDecision(True, "allowed")
