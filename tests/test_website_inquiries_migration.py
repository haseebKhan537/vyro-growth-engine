from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migration_021_follows_contact_discovery_calls() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("021_website_inquiries")

    assert revision is not None
    assert revision.down_revision == "020_contact_discovery_calls"
    assert script.get_current_head() == "021_website_inquiries"
