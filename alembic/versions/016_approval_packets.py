"""Add owner approval packet and live-readiness preflight tables.

Revision ID: 016_approval_packets
Revises: 015_execution_plans
Create Date: 2026-08-31 00:00:00.000000

Production-safe: new tables only. Existing execution-plan, review, content-brief,
channel-plan, optimizer, outreach, booking, and voice rows are unchanged.
Approval packets are readiness records only and never perform live action.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "016_approval_packets"
down_revision: str | Sequence[str] | None = "015_execution_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_packet_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("packet_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reused_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_plan_count", sa.Integer(), nullable=False, server_default="0"),
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
            name="uq_approval_packet_runs_snapshot_fingerprint",
        ),
    )
    op.create_index(
        op.f("ix_approval_packet_runs_status"),
        "approval_packet_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_approval_packet_runs_snapshot_fingerprint"),
        "approval_packet_runs",
        ["snapshot_fingerprint"],
        unique=False,
    )
    op.create_table(
        "owner_approval_packets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "approval_packet_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approval_packet_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "source_execution_plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("execution_plans.id"),
            nullable=False,
        ),
        sa.Column(
            "source_execution_plan_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("execution_plan_runs.id"),
            nullable=False,
        ),
        sa.Column("source_artifact_type", sa.String(length=64), nullable=False),
        sa.Column("source_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_family", sa.String(length=64), nullable=False),
        sa.Column("proposed_action", sa.String(length=255), nullable=False),
        sa.Column("preflight_status", sa.String(length=64), nullable=False),
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
            "preflight_checklist_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "missing_prerequisites_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "findings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "required_owner_decisions_json",
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
            "approval_packet_run_id",
            "source_execution_plan_id",
            name="uq_owner_approval_packets_run_plan",
        ),
        sa.UniqueConstraint(
            "approval_packet_run_id",
            "idempotency_key",
            name="uq_owner_approval_packets_run_key",
        ),
    )
    op.create_index(
        op.f("ix_owner_approval_packets_approval_packet_run_id"),
        "owner_approval_packets",
        ["approval_packet_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_owner_approval_packets_source_execution_plan_id"),
        "owner_approval_packets",
        ["source_execution_plan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_owner_approval_packets_source_execution_plan_run_id"),
        "owner_approval_packets",
        ["source_execution_plan_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_owner_approval_packets_source_artifact_type"),
        "owner_approval_packets",
        ["source_artifact_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_owner_approval_packets_source_artifact_id"),
        "owner_approval_packets",
        ["source_artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_owner_approval_packets_plan_family"),
        "owner_approval_packets",
        ["plan_family"],
        unique=False,
    )
    op.create_index(
        op.f("ix_owner_approval_packets_preflight_status"),
        "owner_approval_packets",
        ["preflight_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_owner_approval_packets_idempotency_key"),
        "owner_approval_packets",
        ["idempotency_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_owner_approval_packets_idempotency_key"),
        table_name="owner_approval_packets",
    )
    op.drop_index(
        op.f("ix_owner_approval_packets_preflight_status"),
        table_name="owner_approval_packets",
    )
    op.drop_index(
        op.f("ix_owner_approval_packets_plan_family"),
        table_name="owner_approval_packets",
    )
    op.drop_index(
        op.f("ix_owner_approval_packets_source_artifact_id"),
        table_name="owner_approval_packets",
    )
    op.drop_index(
        op.f("ix_owner_approval_packets_source_artifact_type"),
        table_name="owner_approval_packets",
    )
    op.drop_index(
        op.f("ix_owner_approval_packets_source_execution_plan_run_id"),
        table_name="owner_approval_packets",
    )
    op.drop_index(
        op.f("ix_owner_approval_packets_source_execution_plan_id"),
        table_name="owner_approval_packets",
    )
    op.drop_index(
        op.f("ix_owner_approval_packets_approval_packet_run_id"),
        table_name="owner_approval_packets",
    )
    op.drop_table("owner_approval_packets")
    op.drop_index(
        op.f("ix_approval_packet_runs_snapshot_fingerprint"),
        table_name="approval_packet_runs",
    )
    op.drop_index(op.f("ix_approval_packet_runs_status"), table_name="approval_packet_runs")
    op.drop_table("approval_packet_runs")
