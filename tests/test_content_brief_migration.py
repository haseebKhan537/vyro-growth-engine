from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from vyro_growth.database import Base
from vyro_growth.models import AcquisitionChannelPlan, ContentBrief, ContentBriefRun


def test_content_brief_tables_are_registered() -> None:
    assert "acquisition_channel_plans" in Base.metadata.tables
    assert "content_brief_runs" in Base.metadata.tables
    assert "content_briefs" in Base.metadata.tables
    assert AcquisitionChannelPlan.__tablename__ == "acquisition_channel_plans"
    assert ContentBriefRun.__tablename__ == "content_brief_runs"
    assert ContentBrief.__tablename__ == "content_briefs"
    plan_columns = set(AcquisitionChannelPlan.__table__.c.keys())
    run_columns = set(ContentBriefRun.__table__.c.keys())
    brief_columns = set(ContentBrief.__table__.c.keys())
    assert {
        "plan_key",
        "channel_type",
        "specialty",
        "geography",
        "status",
        "dry_run_only",
        "launched",
        "spend_attempted",
        "ads_live",
        "created_at",
    }.issubset(plan_columns)
    assert {
        "snapshot_fingerprint",
        "brief_count",
        "published_count",
        "dry_run_only",
        "published",
        "publish_attempted",
        "outbound_attempted",
        "ads_launched",
        "spend_attempted",
        "snapshot_json",
        "created_at",
    }.issubset(run_columns)
    assert {
        "brief_key",
        "brief_type",
        "source_channel_plan_id",
        "title",
        "summary",
        "outline_sections",
        "recommended_cta",
        "compliance_notes",
        "source_references",
        "generated_at",
        "approval_status",
        "published",
        "dry_run_only",
    }.issubset(brief_columns)


def test_migration_013_follows_review_decisions() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("013_content_briefs")
    assert revision is not None
    assert revision.down_revision == "012_operator_review_decisions"
    assert script.get_current_head() == "013_content_briefs"
