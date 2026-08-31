from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from vyro_growth.database import Base
from vyro_growth.models import BookingPlan, BookingPlanRun


def test_booking_plan_tables_are_registered() -> None:
    assert "booking_plans" in Base.metadata.tables
    assert "booking_plan_runs" in Base.metadata.tables
    assert BookingPlan.__tablename__ == "booking_plans"
    assert BookingPlanRun.__tablename__ == "booking_plan_runs"
    columns = set(BookingPlan.__table__.c.keys())
    assert {
        "lead_id",
        "contact_id",
        "requested_window",
        "proposed_slots",
        "provider_name",
        "status",
        "idempotency_key",
        "audit_json",
        "created_at",
        "event_created",
        "meet_link_created",
        "dry_run",
    }.issubset(columns)


def test_migration_009_follows_reply_classifications() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("009_booking_plans")
    assert revision is not None
    assert revision.down_revision == "008_reply_classifications"
    assert script.get_current_head() == "018_live_settings_change_requests"
