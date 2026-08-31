from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from vyro_growth.database import Base
from vyro_growth.models import OptimizerRecommendation, OptimizerRun


def test_optimizer_tables_are_registered() -> None:
    assert "optimizer_runs" in Base.metadata.tables
    assert "optimizer_recommendations" in Base.metadata.tables
    assert OptimizerRun.__tablename__ == "optimizer_runs"
    assert OptimizerRecommendation.__tablename__ == "optimizer_recommendations"
    run_columns = set(OptimizerRun.__table__.c.keys())
    rec_columns = set(OptimizerRecommendation.__table__.c.keys())
    assert {
        "snapshot_fingerprint",
        "recommendation_count",
        "applied_count",
        "dry_run_only",
        "outbound_attempted",
        "snapshot_json",
        "created_at",
    }.issubset(run_columns)
    assert {
        "recommendation_key",
        "category",
        "priority",
        "confidence",
        "rationale",
        "source_metrics_json",
        "generated_at",
        "approval_status",
        "applied",
    }.issubset(rec_columns)


def test_migration_011_follows_voice_qualification() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("011_optimizer_recommendations")
    assert revision is not None
    assert revision.down_revision == "010_voice_qualification"
    assert script.get_current_head() == "013_channel_plans"
