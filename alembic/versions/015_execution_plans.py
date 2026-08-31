"""Add dry-run approved-item execution plan tables.

Revision ID: 015_execution_plans
Revises: 014_content_briefs
Create Date: 2026-08-31 00:00:00.000000

Production-safe: new tables only. Existing review, content-brief, channel-plan,
optimizer, outreach, booking, and voice rows are unchanged. Execution plans are
readiness records only and never perform the underlying live action.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "015_execution_plans"
down_revision: str | Sequence[str] | None = "014_content_briefs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_plan_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("plan_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reused_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ignored_non_approved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("executed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dry_run_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("no_execution", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("execution_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("outbound_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("live_call_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "recommendation_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("spend_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("campaign_launched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pages_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ads_launched", sa.Boolean(), nullable=False, server_default=sa.false()),
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
            name="uq_execution_plan_runs_snapshot_fingerprint",
        ),
    )
    op.create_index(
        op.f("ix_execution_plan_runs_status"),
        "execution_plan_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_execution_plan_runs_snapshot_fingerprint"),
        "execution_plan_runs",
        ["snapshot_fingerprint"],
        unique=False,
    )
    op.create_table(
        "execution_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "execution_plan_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("execution_plan_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "source_review_decision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operator_review_decisions.id"),
            nullable=False,
        ),
        sa.Column("source_artifact_type", sa.String(length=64), nullable=False),
        sa.Column("source_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("plan_type", sa.String(length=64), nullable=False),
        sa.Column("proposed_action", sa.String(length=255), nullable=False),
        sa.Column("readiness_status", sa.String(length=64), nullable=False),
        sa.Column("dry_run_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("no_execution", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("execution_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("outbound_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("live_call_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "recommendation_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("spend_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("campaign_launched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pages_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ads_launched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "owner_approval_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("owner_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "prerequisites_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "blockers_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "safety_notes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "required_owner_approvals_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "audit_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
            "execution_plan_run_id",
            "source_review_decision_id",
            name="uq_execution_plans_run_decision",
        ),
        sa.UniqueConstraint(
            "execution_plan_run_id",
            "idempotency_key",
            name="uq_execution_plans_run_key",
        ),
    )
    op.create_index(
        op.f("ix_execution_plans_execution_plan_run_id"),
        "execution_plans",
        ["execution_plan_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_execution_plans_source_review_decision_id"),
        "execution_plans",
        ["source_review_decision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_execution_plans_source_artifact_type"),
        "execution_plans",
        ["source_artifact_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_execution_plans_source_artifact_id"),
        "execution_plans",
        ["source_artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_execution_plans_plan_type"),
        "execution_plans",
        ["plan_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_execution_plans_readiness_status"),
        "execution_plans",
        ["readiness_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_execution_plans_idempotency_key"),
        "execution_plans",
        ["idempotency_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_execution_plans_idempotency_key"), table_name="execution_plans")
    op.drop_index(op.f("ix_execution_plans_readiness_status"), table_name="execution_plans")
    op.drop_index(op.f("ix_execution_plans_plan_type"), table_name="execution_plans")
    op.drop_index(op.f("ix_execution_plans_source_artifact_id"), table_name="execution_plans")
    op.drop_index(op.f("ix_execution_plans_source_artifact_type"), table_name="execution_plans")
    op.drop_index(
        op.f("ix_execution_plans_source_review_decision_id"),
        table_name="execution_plans",
    )
    op.drop_index(op.f("ix_execution_plans_execution_plan_run_id"), table_name="execution_plans")
    op.drop_table("execution_plans")
    op.drop_index(
        op.f("ix_execution_plan_runs_snapshot_fingerprint"),
        table_name="execution_plan_runs",
    )
    op.drop_index(op.f("ix_execution_plan_runs_status"), table_name="execution_plan_runs")
    op.drop_table("execution_plan_runs")
