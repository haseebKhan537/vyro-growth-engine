"""Add review-only acquisition channel plans and content briefs.

Revision ID: 013_content_briefs
Revises: 012_operator_review_decisions
Create Date: 2026-08-31 00:00:00.000000

Production-safe: new tables only. Existing review, optimizer, outreach,
booking, and voice rows are unchanged. Briefs are operator-review drafts
and are never published, launched, or spent against.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "013_content_briefs"
down_revision: str | Sequence[str] | None = "012_operator_review_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "acquisition_channel_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_key", sa.String(length=255), nullable=False),
        sa.Column("channel_type", sa.String(length=64), nullable=False),
        sa.Column("specialty", sa.String(length=120), nullable=True),
        sa.Column("geography", sa.String(length=120), nullable=True),
        sa.Column("icp_label", sa.String(length=120), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "source_metrics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("dry_run_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("launched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("spend_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ads_live", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.UniqueConstraint("plan_key", name="uq_acquisition_channel_plans_plan_key"),
    )
    op.create_index(
        op.f("ix_acquisition_channel_plans_plan_key"),
        "acquisition_channel_plans",
        ["plan_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_acquisition_channel_plans_channel_type"),
        "acquisition_channel_plans",
        ["channel_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_acquisition_channel_plans_specialty"),
        "acquisition_channel_plans",
        ["specialty"],
        unique=False,
    )
    op.create_index(
        op.f("ix_acquisition_channel_plans_geography"),
        "acquisition_channel_plans",
        ["geography"],
        unique=False,
    )
    op.create_index(
        op.f("ix_acquisition_channel_plans_status"),
        "acquisition_channel_plans",
        ["status"],
        unique=False,
    )

    op.create_table(
        "content_brief_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("brief_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reused_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dry_run_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("publish_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("outbound_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("live_call_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ads_launched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("spend_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
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
            name="uq_content_brief_runs_snapshot_fingerprint",
        ),
    )
    op.create_index(
        op.f("ix_content_brief_runs_status"),
        "content_brief_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_brief_runs_snapshot_fingerprint"),
        "content_brief_runs",
        ["snapshot_fingerprint"],
        unique=False,
    )

    op.create_table(
        "content_briefs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_brief_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brief_key", sa.String(length=255), nullable=False),
        sa.Column("brief_type", sa.String(length=64), nullable=False),
        sa.Column("source_channel_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("specialty", sa.String(length=120), nullable=True),
        sa.Column("geography", sa.String(length=120), nullable=True),
        sa.Column("icp_label", sa.String(length=120), nullable=True),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "outline_sections",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("recommended_cta", sa.String(length=255), nullable=False),
        sa.Column(
            "compliance_notes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "source_references",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approval_status", sa.String(length=64), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("publish_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dry_run_only", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.ForeignKeyConstraint(["content_brief_run_id"], ["content_brief_runs.id"]),
        sa.ForeignKeyConstraint(["source_channel_plan_id"], ["acquisition_channel_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "content_brief_run_id",
            "brief_key",
            name="uq_content_briefs_run_key",
        ),
    )
    op.create_index(
        op.f("ix_content_briefs_content_brief_run_id"),
        "content_briefs",
        ["content_brief_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_briefs_brief_key"),
        "content_briefs",
        ["brief_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_briefs_brief_type"),
        "content_briefs",
        ["brief_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_briefs_source_channel_plan_id"),
        "content_briefs",
        ["source_channel_plan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_briefs_specialty"),
        "content_briefs",
        ["specialty"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_briefs_geography"),
        "content_briefs",
        ["geography"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_briefs_priority"),
        "content_briefs",
        ["priority"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_briefs_approval_status"),
        "content_briefs",
        ["approval_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_content_briefs_approval_status"), table_name="content_briefs")
    op.drop_index(op.f("ix_content_briefs_priority"), table_name="content_briefs")
    op.drop_index(op.f("ix_content_briefs_geography"), table_name="content_briefs")
    op.drop_index(op.f("ix_content_briefs_specialty"), table_name="content_briefs")
    op.drop_index(op.f("ix_content_briefs_source_channel_plan_id"), table_name="content_briefs")
    op.drop_index(op.f("ix_content_briefs_brief_type"), table_name="content_briefs")
    op.drop_index(op.f("ix_content_briefs_brief_key"), table_name="content_briefs")
    op.drop_index(op.f("ix_content_briefs_content_brief_run_id"), table_name="content_briefs")
    op.drop_table("content_briefs")
    op.drop_index(
        op.f("ix_content_brief_runs_snapshot_fingerprint"),
        table_name="content_brief_runs",
    )
    op.drop_index(op.f("ix_content_brief_runs_status"), table_name="content_brief_runs")
    op.drop_table("content_brief_runs")
    op.drop_index(
        op.f("ix_acquisition_channel_plans_status"),
        table_name="acquisition_channel_plans",
    )
    op.drop_index(
        op.f("ix_acquisition_channel_plans_geography"),
        table_name="acquisition_channel_plans",
    )
    op.drop_index(
        op.f("ix_acquisition_channel_plans_specialty"),
        table_name="acquisition_channel_plans",
    )
    op.drop_index(
        op.f("ix_acquisition_channel_plans_channel_type"),
        table_name="acquisition_channel_plans",
    )
    op.drop_index(
        op.f("ix_acquisition_channel_plans_plan_key"),
        table_name="acquisition_channel_plans",
    )
    op.drop_table("acquisition_channel_plans")
