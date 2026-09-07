from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from vyro_growth.database import Base
from vyro_growth.models import OwnerApprovalPacketDecision


def test_approval_packet_decision_table_is_registered() -> None:
    assert "owner_approval_packet_decisions" in Base.metadata.tables
    assert OwnerApprovalPacketDecision.__tablename__ == "owner_approval_packet_decisions"
    columns = set(OwnerApprovalPacketDecision.__table__.c.keys())
    assert {
        "owner_approval_packet_id",
        "decision",
        "previous_decision",
        "reviewer",
        "source",
        "reviewer_notes",
        "decided_at",
        "executed",
        "outbound_attempted",
        "owner_approved",
        "created_at",
    }.issubset(columns)


def test_migration_017_follows_approval_packets() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("017_approval_packet_decisions")
    assert revision is not None
    assert revision.down_revision == "016_approval_packets"
    assert script.get_current_head() == "019_email_verification"
