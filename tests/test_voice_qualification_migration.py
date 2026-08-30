from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from vyro_growth.database import Base
from vyro_growth.models import VoiceQualificationPlan, VoiceQualificationRun


def test_voice_qualification_tables_are_registered() -> None:
    assert "voice_qualification_plans" in Base.metadata.tables
    assert "voice_qualification_runs" in Base.metadata.tables
    assert VoiceQualificationPlan.__tablename__ == "voice_qualification_plans"
    assert VoiceQualificationRun.__tablename__ == "voice_qualification_runs"
    columns = set(VoiceQualificationPlan.__table__.c.keys())
    assert {
        "lead_id",
        "contact_id",
        "consent_source",
        "consent_channel",
        "consent_timestamp",
        "consent_evidence_id",
        "permitted_phone",
        "facts_json",
        "consent_json",
        "provider_name",
        "status",
        "idempotency_key",
        "audit_json",
        "created_at",
        "dry_run",
        "call_placed",
        "live_call_attempted",
    }.issubset(columns)


def test_migration_010_follows_booking_plans() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("010_voice_qualification")
    assert revision is not None
    assert revision.down_revision == "009_booking_plans"
    assert script.get_current_head() == "010_voice_qualification"
