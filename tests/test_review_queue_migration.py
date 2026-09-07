from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from vyro_growth.database import Base
from vyro_growth.models import OperatorReviewDecision


def test_review_decision_table_is_registered() -> None:
    assert "operator_review_decisions" in Base.metadata.tables
    assert OperatorReviewDecision.__tablename__ == "operator_review_decisions"
    columns = set(OperatorReviewDecision.__table__.c.keys())
    assert {
        "artifact_type",
        "artifact_id",
        "decision",
        "reviewer",
        "source",
        "reviewer_notes",
        "decided_at",
        "executed",
        "outbound_attempted",
        "recommendation_applied",
        "created_at",
    }.issubset(columns)


def test_migration_012_follows_optimizer_recommendations() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("012_operator_review_decisions")
    assert revision is not None
    assert revision.down_revision == "011_optimizer_recommendations"
    assert script.get_current_head() == "020_contact_discovery_calls"
