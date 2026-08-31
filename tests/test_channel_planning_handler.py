from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.models import ChannelPlanRun
from vyro_growth.workers.base import Job
from vyro_growth.workers.channel_planning_handler import (
    GENERATE_CHANNEL_PLANS_JOB,
    GenerateChannelPlansHandler,
)


def test_worker_generates_dry_run_channel_plans(db_session: Session) -> None:
    handler = GenerateChannelPlansHandler(db=db_session)

    handler.handle(
        Job(
            name=GENERATE_CHANNEL_PLANS_JOB,
            payload={"seed_specialty": "Family Medicine", "seed_state": "TX"},
        )
    )

    run = db_session.scalar(select(ChannelPlanRun))
    assert run is not None
    assert run.dry_run_only is True
    assert run.no_spend is True
    assert run.spend_attempted is False
    assert run.campaign_launched is False
    assert run.pages_published is False
    assert run.outbound_attempted is False
    assert run.live_call_attempted is False
    assert run.status == "completed"


def test_worker_job_name_is_stable() -> None:
    assert GENERATE_CHANNEL_PLANS_JOB == "generate_channel_plans"
