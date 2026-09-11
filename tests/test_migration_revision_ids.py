from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_revision_ids_fit_alembic_version_table() -> None:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)

    oversized = [
        revision.revision
        for revision in script.walk_revisions()
        if len(revision.revision) > 32
    ]

    assert oversized == []
