"""Add dry-run booking plan tables.

Revision ID: 009_booking_plans
Revises: 008_reply_classifications
Create Date: 2026-08-30 00:00:00.000000

Production-safe: new tables only. Existing reply classifications, leads,
meetings, outreach, and suppression rows are unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "009_booking_plans"
down_revision: str | Sequence[str] | None = "008_reply_classifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "booking_plan_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "input_params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("planned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("suppressed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reused_count", sa.Integer(), nullable=False, server_default="0"),
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
    op.create_index(
        op.f("ix_booking_plan_runs_status"),
        "booking_plan_runs",
        ["status"],
        unique=False,
    )

    op.create_table(
        "booking_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("booking_plan_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reply_classification_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_source", sa.String(length=64), nullable=False),
        sa.Column("request_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("skip_reason", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False, server_default="stub"),
        sa.Column("requested_window", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "proposed_slots",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("event_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("meet_link_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("live_call_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_event_id", sa.String(length=255), nullable=True),
        sa.Column("meeting_url", sa.String(length=1000), nullable=True),
        sa.Column("lead_stage_before", sa.String(length=64), nullable=False),
        sa.Column("lead_stage_after", sa.String(length=64), nullable=False),
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
        sa.ForeignKeyConstraint(["booking_plan_run_id"], ["booking_plan_runs.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["reply_classification_id"], ["reply_classifications.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_booking_plans_idempotency_key"),
    )
    op.create_index(
        op.f("ix_booking_plans_booking_plan_run_id"),
        "booking_plans",
        ["booking_plan_run_id"],
        unique=False,
    )
    op.create_index(op.f("ix_booking_plans_lead_id"), "booking_plans", ["lead_id"], unique=False)
    op.create_index(
        op.f("ix_booking_plans_contact_id"),
        "booking_plans",
        ["contact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_booking_plans_organization_id"),
        "booking_plans",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_booking_plans_reply_classification_id"),
        "booking_plans",
        ["reply_classification_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_booking_plans_request_source"),
        "booking_plans",
        ["request_source"],
        unique=False,
    )
    op.create_index(
        op.f("ix_booking_plans_request_key"),
        "booking_plans",
        ["request_key"],
        unique=False,
    )
    op.create_index(op.f("ix_booking_plans_status"), "booking_plans", ["status"], unique=False)
    op.create_index(
        op.f("ix_booking_plans_skip_reason"),
        "booking_plans",
        ["skip_reason"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_booking_plans_skip_reason"), table_name="booking_plans")
    op.drop_index(op.f("ix_booking_plans_status"), table_name="booking_plans")
    op.drop_index(op.f("ix_booking_plans_request_key"), table_name="booking_plans")
    op.drop_index(op.f("ix_booking_plans_request_source"), table_name="booking_plans")
    op.drop_index(op.f("ix_booking_plans_reply_classification_id"), table_name="booking_plans")
    op.drop_index(op.f("ix_booking_plans_organization_id"), table_name="booking_plans")
    op.drop_index(op.f("ix_booking_plans_contact_id"), table_name="booking_plans")
    op.drop_index(op.f("ix_booking_plans_lead_id"), table_name="booking_plans")
    op.drop_index(op.f("ix_booking_plans_booking_plan_run_id"), table_name="booking_plans")
    op.drop_table("booking_plans")
    op.drop_index(op.f("ix_booking_plan_runs_status"), table_name="booking_plan_runs")
    op.drop_table("booking_plan_runs")
