from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from vyro_growth.config import Settings, get_settings
from vyro_growth.services.execution_planning import ExecutionPlanFilters, ExecutionPlanningService
from vyro_growth.workers.base import Job

GENERATE_EXECUTION_PLANS_JOB = "generate_execution_plans"


class GenerateExecutionPlansHandler:
    """Persist dry-run execution plans. Never executes the underlying actions."""

    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        service: ExecutionPlanningService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.service = service or ExecutionPlanningService()

    def handle(self, job: Job) -> None:
        active_settings = self.settings or get_settings()
        self.service.generate(self.db, active_settings, filters=_filters_from_payload(job.payload))


def _filters_from_payload(payload: dict[str, object]) -> ExecutionPlanFilters:
    artifact_type = payload.get("artifact_type")
    raw_id = payload.get("artifact_id")
    artifact_id: UUID | None = None
    if isinstance(raw_id, UUID):
        artifact_id = raw_id
    elif isinstance(raw_id, str) and raw_id.strip():
        artifact_id = UUID(raw_id)
    return ExecutionPlanFilters(
        artifact_type=artifact_type if isinstance(artifact_type, str) else None,
        artifact_id=artifact_id,
    )
