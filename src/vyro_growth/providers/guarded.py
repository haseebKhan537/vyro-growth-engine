from __future__ import annotations

from sqlalchemy.orm import Session

from vyro_growth.providers.base import EmailProvider, SendResult
from vyro_growth.services.outbound_guard import OutboundGuard


def _email_domain(email: str) -> str | None:
    if "@" not in email:
        return None
    return email.rsplit("@", maxsplit=1)[1].lower()


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
            email=to.lower(),
            domain=_email_domain(to),
        )
        return self._inner.send_email(to=to, subject=subject, body=body)
