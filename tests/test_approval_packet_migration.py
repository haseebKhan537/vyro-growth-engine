from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from vyro_growth.database import Base
from vyro_growth.models import ApprovalPacketRun, OwnerApprovalPacket


def test_approval_packet_tables_are_registered() -> None:
    assert "approval_packet_runs" in Base.metadata.tables
    assert "owner_approval_packets" in Base.metadata.tables
    assert ApprovalPacketRun.__tablename__ == "approval_packet_runs"
    assert OwnerApprovalPacket.__tablename__ == "owner_approval_packets"
    run_columns = set(ApprovalPacketRun.__table__.c.keys())
    packet_columns = set(OwnerApprovalPacket.__table__.c.keys())
    assert {
        "snapshot_fingerprint",
        "packet_count",
        "missing_plan_count",
        "executed_count",
        "dry_run_only",
        "no_execution",
        "execution_attempted",
        "outbound_attempted",
        "snapshot_json",
        "created_at",
    }.issubset(run_columns)
    assert {
        "source_execution_plan_id",
        "source_execution_plan_run_id",
        "source_artifact_type",
        "source_artifact_id",
        "plan_family",
        "proposed_action",
        "preflight_status",
        "dry_run_only",
        "no_execution",
        "executed",
        "owner_approval_required",
        "idempotency_key",
        "preflight_checklist_json",
        "missing_prerequisites_json",
        "findings_json",
        "required_owner_decisions_json",
        "generated_at",
    }.issubset(packet_columns)


def test_migration_016_follows_execution_plans() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("016_approval_packets")
    assert revision is not None
    assert revision.down_revision == "015_execution_plans"
    assert script.get_current_head() == "018_live_settings_change_requests"
