from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.models import ContentBriefRun
from vyro_growth.workers.base import Job
from vyro_growth.workers.content_brief_handler import (
    GENERATE_CONTENT_BRIEFS_JOB,
    GenerateContentBriefsHandler,
)


def test_worker_generates_unpublished_briefs(db_session: Session) -> None:
    handler = GenerateContentBriefsHandler(
        db=db_session,
        settings=Settings(),
    )

    handler.handle(Job(name=GENERATE_CONTENT_BRIEFS_JOB, payload={}))

    run = db_session.scalar(select(ContentBriefRun))
    assert run is not None
    assert run.dry_run_only is True
    assert run.published is False
    assert run.publish_attempted is False
    assert run.published_count == 0
    assert run.outbound_attempted is False
    assert run.ads_launched is False
    assert run.spend_attempted is False
    assert run.live_call_attempted is False
    assert run.status == "completed"


def test_worker_job_name_is_stable() -> None:
    assert GENERATE_CONTENT_BRIEFS_JOB == "generate_content_briefs"
