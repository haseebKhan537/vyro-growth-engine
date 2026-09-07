from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from vyro_growth.database import Base
from vyro_growth.models import ExecutionPlan, ExecutionPlanRun


def test_execution_plan_tables_are_registered() -> None:
    assert "execution_plan_runs" in Base.metadata.tables
    assert "execution_plans" in Base.metadata.tables
    assert ExecutionPlanRun.__tablename__ == "execution_plan_runs"
    assert ExecutionPlan.__tablename__ == "execution_plans"
    run_columns = set(ExecutionPlanRun.__table__.c.keys())
    plan_columns = set(ExecutionPlan.__table__.c.keys())
    assert {
        "snapshot_fingerprint",
        "plan_count",
        "ignored_non_approved_count",
        "executed_count",
        "dry_run_only",
        "no_execution",
        "execution_attempted",
        "outbound_attempted",
        "snapshot_json",
        "created_at",
    }.issubset(run_columns)
    assert {
        "source_review_decision_id",
        "source_artifact_type",
        "source_artifact_id",
        "plan_type",
        "proposed_action",
        "readiness_status",
        "dry_run_only",
        "no_execution",
        "executed",
        "owner_approval_required",
        "idempotency_key",
        "prerequisites_json",
        "blockers_json",
        "safety_notes_json",
        "required_owner_approvals_json",
        "generated_at",
    }.issubset(plan_columns)


def test_migration_015_follows_content_briefs() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("015_execution_plans")
    assert revision is not None
    assert revision.down_revision == "014_content_briefs"
    assert script.get_current_head() == "019_email_verification"
