from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from vyro_growth.providers.reply_classification import (
    ReplyClassifierProvider,
    build_reply_classifier,
)
from vyro_growth.services.reply_classification import (
    ReplyClassificationError,
    ReplyClassificationService,
)
from vyro_growth.workers.base import Job

CLASSIFY_INBOUND_REPLIES_JOB = "classify_inbound_replies"


@dataclass
class ClassifyInboundRepliesHandler:
    db: Session
    provider: ReplyClassifierProvider | None = None

    def handle(self, job: Job) -> None:
        message_id = _optional_uuid(job.payload.get("message_id"))
        lead_id = _optional_uuid(job.payload.get("lead_id"))
        limit = _optional_int(job.payload.get("limit"))
        if message_id is not None and lead_id is not None:
            raise ReplyClassificationError("Provide message_id or lead_id, not both")

        service = ReplyClassificationService(self.provider or build_reply_classifier())
        if message_id is not None:
            service.classify_message(self.db, message_id)
            return
        if lead_id is not None:
            service.classify_lead(self.db, lead_id)
            return
        service.classify_batch(self.db, limit=limit or 50)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _optional_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str) and value.strip():
        return UUID(value)
    return None
