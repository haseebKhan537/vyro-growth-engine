from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from vyro_growth.database import Base
from vyro_growth.models import Contact, EmailPatternCandidate


def test_email_verification_tables_are_registered() -> None:
    assert "email_pattern_candidates" in Base.metadata.tables
    assert EmailPatternCandidate.__tablename__ == "email_pattern_candidates"
    contact_columns = set(Contact.__table__.c.keys())
    assert {
        "email_origin",
        "email_verification_verdict",
        "email_verification_provider",
        "email_verification_checked_at",
    }.issubset(contact_columns)
    candidate_columns = set(EmailPatternCandidate.__table__.c.keys())
    assert {
        "organization_id",
        "contact_id",
        "source_contact_id",
        "candidate_email",
        "pattern_name",
        "origin",
        "promoted",
        "verification_verdict",
        "verification_status",
        "idempotency_key",
        "dry_run",
        "live_call_attempted",
        "smtp_attempted",
        "details_json",
        "created_at",
        "updated_at",
    }.issubset(candidate_columns)


def test_migration_019_follows_live_settings_change_requests() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("019_email_verification")
    assert revision is not None
    assert revision.down_revision == "018_live_settings_change_requests"
    assert script.get_current_head() == "021_website_inquiries"
