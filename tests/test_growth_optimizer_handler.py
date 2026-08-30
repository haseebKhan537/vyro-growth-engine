from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.models import OptimizerRun
from vyro_growth.workers.base import Job
from vyro_growth.workers.growth_optimizer_handler import (
    GENERATE_GROWTH_RECOMMENDATIONS_JOB,
    GenerateGrowthRecommendationsHandler,
)


def test_worker_generates_dry_run_recommendations(db_session: Session) -> None:
    handler = GenerateGrowthRecommendationsHandler(
        db=db_session,
        settings=Settings(),
    )

    handler.handle(Job(name=GENERATE_GROWTH_RECOMMENDATIONS_JOB, payload={}))

    run = db_session.scalar(select(OptimizerRun))
    assert run is not None
    assert run.dry_run_only is True
    assert run.applied_count == 0
    assert run.outbound_attempted is False
    assert run.live_call_attempted is False
    assert run.status == "completed"


def test_worker_job_name_is_stable() -> None:
    assert GENERATE_GROWTH_RECOMMENDATIONS_JOB == "generate_growth_recommendations"
