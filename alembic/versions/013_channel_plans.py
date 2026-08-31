"""Add dry-run acquisition channel planning tables.

Revision ID: 013_channel_plans
Revises: 012_operator_review_decisions
Create Date: 2026-08-31 00:00:00.000000

Production-safe: new tables only. Existing review, optimizer, outreach, booking,
and voice rows are unchanged. Channel plans are dry-run drafts for operator
review and never launch campaigns, publish pages, or spend money.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "013_channel_plans"
down_revision: str | Sequence[str] | None = "012_operator_review_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_plan_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("plan_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reused_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dry_run_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("no_spend", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("spend_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("campaign_launched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pages_published", sa.Boolean(), nullable=False, server_default=sa.false()),
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
            name="uq_channel_plan_runs_snapshot_fingerprint",
        ),
    )
    op.create_index(
        op.f("ix_channel_plan_runs_status"),
        "channel_plan_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_channel_plan_runs_snapshot_fingerprint"),
        "channel_plan_runs",
        ["snapshot_fingerprint"],
        unique=False,
    )

    op.create_table(
        "channel_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_plan_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_key", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("plan_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("target_specialty", sa.String(length=255), nullable=True),
        sa.Column("target_geography", sa.String(length=64), nullable=True),
        sa.Column("target_icp", sa.String(length=255), nullable=True),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "source_metrics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "seed_input_refs_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approval_status", sa.String(length=64), nullable=False),
        sa.Column("dry_run_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("no_spend", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("launched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("spend_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("campaign_launched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pages_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("outbound_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.ForeignKeyConstraint(["channel_plan_run_id"], ["channel_plan_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel_plan_run_id",
            "plan_key",
            name="uq_channel_plans_run_key",
        ),
    )
    op.create_index(
        op.f("ix_channel_plans_channel_plan_run_id"),
        "channel_plans",
        ["channel_plan_run_id"],
        unique=False,
    )
    op.create_index(op.f("ix_channel_plans_plan_key"), "channel_plans", ["plan_key"], unique=False)
    op.create_index(op.f("ix_channel_plans_channel"), "channel_plans", ["channel"], unique=False)
    op.create_index(
        op.f("ix_channel_plans_plan_type"),
        "channel_plans",
        ["plan_type"],
        unique=False,
    )
    op.create_index(op.f("ix_channel_plans_priority"), "channel_plans", ["priority"], unique=False)
    op.create_index(
        op.f("ix_channel_plans_approval_status"),
        "channel_plans",
        ["approval_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_channel_plans_approval_status"), table_name="channel_plans")
    op.drop_index(op.f("ix_channel_plans_priority"), table_name="channel_plans")
    op.drop_index(op.f("ix_channel_plans_plan_type"), table_name="channel_plans")
    op.drop_index(op.f("ix_channel_plans_channel"), table_name="channel_plans")
    op.drop_index(op.f("ix_channel_plans_plan_key"), table_name="channel_plans")
    op.drop_index(op.f("ix_channel_plans_channel_plan_run_id"), table_name="channel_plans")
    op.drop_table("channel_plans")
    op.drop_index(op.f("ix_channel_plan_runs_snapshot_fingerprint"), table_name="channel_plan_runs")
    op.drop_index(op.f("ix_channel_plan_runs_status"), table_name="channel_plan_runs")
    op.drop_table("channel_plan_runs")
