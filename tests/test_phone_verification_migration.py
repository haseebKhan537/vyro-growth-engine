from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from vyro_growth.database import Base
from vyro_growth.models import ContactDiscoveryCall


def test_contact_discovery_call_table_is_registered() -> None:
    assert "contact_discovery_calls" in Base.metadata.tables
    assert ContactDiscoveryCall.__tablename__ == "contact_discovery_calls"
    columns = set(ContactDiscoveryCall.__table__.c.keys())
    assert {
        "organization_id",
        "lead_id",
        "enrichment_run_id",
        "contact_id",
        "suppression_id",
        "status",
        "queued_reason",
        "idempotency_key",
        "dry_run",
        "no_execution",
        "executed",
        "outbound_attempted",
        "live_call_attempted",
        "voice_provider_used",
        "autodial_attempted",
        "suppression_created",
        "contact_fact_created",
        "details_json",
        "queued_at",
        "completed_at",
        "created_at",
        "updated_at",
    }.issubset(columns)


def test_migration_020_follows_email_verification() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("020_contact_discovery_calls")
    assert revision is not None
    assert revision.down_revision == "019_email_verification"
    assert script.get_current_head() == "020_contact_discovery_calls"
