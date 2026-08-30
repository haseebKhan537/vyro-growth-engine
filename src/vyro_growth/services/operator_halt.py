from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from vyro_growth.models import GLOBAL_OPERATOR_CONTROL_KEY, OperatorControl


class HaltStatus(StrEnum):
    CLEARED = "cleared"
    HALTED = "halted"
    UNAVAILABLE = "unavailable"


class HaltReader(Protocol):
    def read(self, db: Session) -> HaltStatus: ...


class DatabaseHaltReader:
    def read(self, db: Session) -> HaltStatus:
        return read_operator_halt(db)


class StaticHaltReader:
    """Test/helper reader that does not touch persistence."""

    def __init__(self, status: HaltStatus) -> None:
        self._status = status

    def read(self, _db: Session) -> HaltStatus:
        return self._status


def read_operator_halt(db: Session) -> HaltStatus:
    """Return the persistent operator halt.

    Missing or unreadable state fails closed as UNAVAILABLE.
    """

    try:
        halted = db.scalar(
            select(OperatorControl.outbound_halted).where(
                OperatorControl.key == GLOBAL_OPERATOR_CONTROL_KEY
            )
        )
    except SQLAlchemyError:
        return HaltStatus.UNAVAILABLE
    if halted is None:
        return HaltStatus.UNAVAILABLE
    return HaltStatus.HALTED if halted else HaltStatus.CLEARED


def set_operator_halt(
    db: Session,
    *,
    halted: bool,
    reason: str | None = None,
) -> OperatorControl:
    row = db.get(OperatorControl, GLOBAL_OPERATOR_CONTROL_KEY)
    if row is None:
        row = OperatorControl(
            key=GLOBAL_OPERATOR_CONTROL_KEY,
            outbound_halted=halted,
            reason=reason,
        )
        db.add(row)
    else:
        row.outbound_halted = halted
        row.reason = reason
    db.flush()
    return row
