from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from vyro_growth.config import Settings, get_settings
from vyro_growth.services.approval_packets import ApprovalPacketFilters, ApprovalPacketService
from vyro_growth.workers.base import Job

GENERATE_APPROVAL_PACKETS_JOB = "generate_approval_packets"


class GenerateApprovalPacketsHandler:
    """Persist owner approval packets. Never executes the underlying actions."""

    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        service: ApprovalPacketService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.service = service or ApprovalPacketService()

    def handle(self, job: Job) -> None:
        active_settings = self.settings or get_settings()
        self.service.generate(self.db, active_settings, filters=_filters_from_payload(job.payload))


def _filters_from_payload(payload: dict[str, object]) -> ApprovalPacketFilters:
    plan_type = payload.get("plan_type")
    raw_id = payload.get("execution_plan_id")
    execution_plan_id: UUID | None = None
    if isinstance(raw_id, UUID):
        execution_plan_id = raw_id
    elif isinstance(raw_id, str) and raw_id.strip():
        execution_plan_id = UUID(raw_id)
    return ApprovalPacketFilters(
        plan_type=plan_type if isinstance(plan_type, str) else None,
        execution_plan_id=execution_plan_id,
    )
