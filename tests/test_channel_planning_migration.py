from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from vyro_growth.database import Base
from vyro_growth.models import ChannelPlan, ChannelPlanRun


def test_channel_plan_tables_are_registered() -> None:
    assert "channel_plan_runs" in Base.metadata.tables
    assert "channel_plans" in Base.metadata.tables
    assert ChannelPlanRun.__tablename__ == "channel_plan_runs"
    assert ChannelPlan.__tablename__ == "channel_plans"
    run_columns = set(ChannelPlanRun.__table__.c.keys())
    plan_columns = set(ChannelPlan.__table__.c.keys())
    assert {
        "snapshot_fingerprint",
        "plan_count",
        "dry_run_only",
        "no_spend",
        "spend_attempted",
        "campaign_launched",
        "pages_published",
        "outbound_attempted",
        "snapshot_json",
        "created_at",
    }.issubset(run_columns)
    assert {
        "plan_key",
        "channel",
        "plan_type",
        "title",
        "summary",
        "target_specialty",
        "target_geography",
        "priority",
        "confidence",
        "source_metrics_json",
        "seed_input_refs_json",
        "generated_at",
        "approval_status",
        "launched",
        "spend_attempted",
    }.issubset(plan_columns)


def test_migration_013_follows_review_decisions() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("013_channel_plans")
    assert revision is not None
    assert revision.down_revision == "012_operator_review_decisions"
    assert script.get_current_head() == "021_website_inquiries"
