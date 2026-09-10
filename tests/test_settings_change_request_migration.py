from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from vyro_growth.database import Base
from vyro_growth.models import LiveSettingsChangeRequest, LiveSettingsChangeRequestDecision


def test_settings_change_request_tables_are_registered() -> None:
    assert "live_settings_change_requests" in Base.metadata.tables
    assert "live_settings_change_request_decisions" in Base.metadata.tables
    assert LiveSettingsChangeRequest.__tablename__ == "live_settings_change_requests"
    assert (
        LiveSettingsChangeRequestDecision.__tablename__
        == "live_settings_change_request_decisions"
    )
    request_columns = set(LiveSettingsChangeRequest.__table__.c.keys())
    assert {
        "request_type",
        "status",
        "owner_decision_status",
        "idempotency_key",
        "requested_setting_names",
        "desired_boolean",
        "desired_status",
        "finding_code",
        "next_action_code",
        "executed",
        "settings_applied",
        "owner_approved",
        "halt_changed",
        "live_action",
        "created_at",
        "updated_at",
    }.issubset(request_columns)
    decision_columns = set(LiveSettingsChangeRequestDecision.__table__.c.keys())
    assert {
        "live_settings_change_request_id",
        "decision",
        "settings_applied",
        "owner_approved",
        "halt_changed",
        "executed",
        "created_at",
    }.issubset(decision_columns)


def test_migration_018_follows_approval_packet_decisions() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("018_live_settings_change_requests")
    assert revision is not None
    assert revision.down_revision == "017_approval_packet_decisions"
    assert script.get_current_head() == "021_website_inquiries"
