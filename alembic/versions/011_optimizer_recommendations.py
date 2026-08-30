"""Add dry-run growth optimizer recommendation tables.

Revision ID: 011_optimizer_recommendations
Revises: 010_voice_qualification
Create Date: 2026-08-30 00:00:00.000000

Production-safe: new tables only. Existing dashboard, voice, booking, outreach,
lead, and suppression rows are unchanged. Recommendations are drafts for
operator review and are never auto-applied.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "011_optimizer_recommendations"
down_revision: str | Sequence[str] | None = "010_voice_qualification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "optimizer_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recommendation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reused_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applied_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dry_run_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("outbound_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("live_call_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "input_params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        sa.UniqueConstraint(
            "snapshot_fingerprint",
            name="uq_optimizer_runs_snapshot_fingerprint",
        ),
    )
    op.create_index(op.f("ix_optimizer_runs_status"), "optimizer_runs", ["status"], unique=False)
    op.create_index(
        op.f("ix_optimizer_runs_snapshot_fingerprint"),
        "optimizer_runs",
        ["snapshot_fingerprint"],
        unique=False,
    )

    op.create_table(
        "optimizer_recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("optimizer_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation_key", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "source_metrics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approval_status", sa.String(length=64), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["optimizer_run_id"], ["optimizer_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "optimizer_run_id",
            "recommendation_key",
            name="uq_optimizer_recommendations_run_key",
        ),
    )
    op.create_index(
        op.f("ix_optimizer_recommendations_optimizer_run_id"),
        "optimizer_recommendations",
        ["optimizer_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_optimizer_recommendations_recommendation_key"),
        "optimizer_recommendations",
        ["recommendation_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_optimizer_recommendations_category"),
        "optimizer_recommendations",
        ["category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_optimizer_recommendations_priority"),
        "optimizer_recommendations",
        ["priority"],
        unique=False,
    )
    op.create_index(
        op.f("ix_optimizer_recommendations_approval_status"),
        "optimizer_recommendations",
        ["approval_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_optimizer_recommendations_approval_status"),
        table_name="optimizer_recommendations",
    )
    op.drop_index(
        op.f("ix_optimizer_recommendations_priority"),
        table_name="optimizer_recommendations",
    )
    op.drop_index(
        op.f("ix_optimizer_recommendations_category"),
        table_name="optimizer_recommendations",
    )
    op.drop_index(
        op.f("ix_optimizer_recommendations_recommendation_key"),
        table_name="optimizer_recommendations",
    )
    op.drop_index(
        op.f("ix_optimizer_recommendations_optimizer_run_id"),
        table_name="optimizer_recommendations",
    )
    op.drop_table("optimizer_recommendations")
    op.drop_index(op.f("ix_optimizer_runs_snapshot_fingerprint"), table_name="optimizer_runs")
    op.drop_index(op.f("ix_optimizer_runs_status"), table_name="optimizer_runs")
    op.drop_table("optimizer_runs")
