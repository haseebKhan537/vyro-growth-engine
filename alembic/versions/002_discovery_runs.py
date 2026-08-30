from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "002_discovery_runs"
down_revision: str | Sequence[str] | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("query_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("records_fetched", sa.Integer(), nullable=False),
        sa.Column("records_upserted", sa.Integer(), nullable=False),
        sa.Column("records_skipped", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_discovery_runs_source"), "discovery_runs", ["source"], unique=False)
    op.create_index(op.f("ix_discovery_runs_status"), "discovery_runs", ["status"], unique=False)

    op.add_column(
        "source_evidence",
        sa.Column("discovery_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_source_evidence_discovery_run_id",
        "source_evidence",
        "discovery_runs",
        ["discovery_run_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_source_evidence_discovery_run_id"),
        "source_evidence",
        ["discovery_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_source_evidence_discovery_run_id"), table_name="source_evidence")
    op.drop_constraint("fk_source_evidence_discovery_run_id", "source_evidence", type_="foreignkey")
    op.drop_column("source_evidence", "discovery_run_id")
    op.drop_index(op.f("ix_discovery_runs_status"), table_name="discovery_runs")
    op.drop_index(op.f("ix_discovery_runs_source"), table_name="discovery_runs")
    op.drop_table("discovery_runs")
