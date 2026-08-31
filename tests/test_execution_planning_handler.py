from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.models import ExecutionPlanRun
from vyro_growth.workers.base import Job
from vyro_growth.workers.execution_planning_handler import (
    GENERATE_EXECUTION_PLANS_JOB,
    GenerateExecutionPlansHandler,
)


def test_worker_generates_dry_run_execution_plans(db_session: Session) -> None:
    handler = GenerateExecutionPlansHandler(db=db_session, settings=Settings())

    handler.handle(Job(name=GENERATE_EXECUTION_PLANS_JOB, payload={}))

    run = db_session.scalar(select(ExecutionPlanRun))
    assert run is not None
    assert run.dry_run_only is True
    assert run.no_execution is True
    assert run.execution_attempted is False
    assert run.executed_count == 0
    assert run.outbound_attempted is False
    assert run.live_call_attempted is False
    assert run.recommendation_applied is False
    assert run.status == "completed"


def test_worker_job_name_is_stable() -> None:
    assert GENERATE_EXECUTION_PLANS_JOB == "generate_execution_plans"
