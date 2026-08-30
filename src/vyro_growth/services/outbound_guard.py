from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.models import Suppression


class OutboundBlockedError(RuntimeError):
    """Raised when an outbound action fails a required safety gate."""


@dataclass(frozen=True)
class OutboundDecision:
    allowed: bool
    reason: str


class OutboundGuard:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, db: Session, *, email: str | None, domain: str | None) -> OutboundDecision:
        if not self._settings.outbound_enabled:
            return OutboundDecision(False, "global_outbound_disabled")

        conditions = []
        if email:
            conditions.append(Suppression.email == email.lower())
        if domain:
            conditions.append(Suppression.domain == domain.lower())

        if conditions:
            suppressed = db.scalar(select(Suppression.id).where(or_(*conditions)).limit(1))
            if suppressed is not None:
                return OutboundDecision(False, "suppressed")

        return OutboundDecision(True, "allowed")

    def require_allowed(self, db: Session, *, email: str | None, domain: str | None) -> None:
        decision = self.evaluate(db, email=email, domain=domain)
        if not decision.allowed:
            raise OutboundBlockedError(decision.reason)
