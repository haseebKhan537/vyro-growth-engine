"""Add dry-run voice qualification plan tables.

Revision ID: 010_voice_qualification
Revises: 009_booking_plans
Create Date: 2026-08-30 00:00:00.000000

Production-safe: new tables only. Existing booking plans, meetings, replies,
leads, outreach, and suppression rows are unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "010_voice_qualification"
down_revision: str | Sequence[str] | None = "009_booking_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voice_qualification_runs",
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
        op.f("ix_voice_qualification_runs_status"),
        "voice_qualification_runs",
        ["status"],
        unique=False,
    )

    op.create_table(
        "voice_qualification_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("voice_qualification_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outreach_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reply_classification_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("booking_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_source", sa.String(length=64), nullable=False),
        sa.Column("request_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("skip_reason", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False, server_default="stub"),
        sa.Column("provider_plan_id", sa.String(length=255), nullable=True),
        sa.Column("consent_source", sa.String(length=64), nullable=True),
        sa.Column("consent_channel", sa.String(length=32), nullable=True),
        sa.Column("consent_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_evidence_id", sa.String(length=255), nullable=True),
        sa.Column("permitted_phone", sa.String(length=50), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "live_call_attempted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("call_placed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "facts_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "consent_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
        sa.ForeignKeyConstraint(["voice_qualification_run_id"], ["voice_qualification_runs.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["outreach_message_id"], ["outreach_messages.id"]),
        sa.ForeignKeyConstraint(["reply_classification_id"], ["reply_classifications.id"]),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"]),
        sa.ForeignKeyConstraint(["booking_plan_id"], ["booking_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_voice_qualification_plans_idempotency_key",
        ),
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_voice_qualification_run_id"),
        "voice_qualification_plans",
        ["voice_qualification_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_lead_id"),
        "voice_qualification_plans",
        ["lead_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_contact_id"),
        "voice_qualification_plans",
        ["contact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_organization_id"),
        "voice_qualification_plans",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_outreach_message_id"),
        "voice_qualification_plans",
        ["outreach_message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_reply_classification_id"),
        "voice_qualification_plans",
        ["reply_classification_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_meeting_id"),
        "voice_qualification_plans",
        ["meeting_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_booking_plan_id"),
        "voice_qualification_plans",
        ["booking_plan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_request_source"),
        "voice_qualification_plans",
        ["request_source"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_request_key"),
        "voice_qualification_plans",
        ["request_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_status"),
        "voice_qualification_plans",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_skip_reason"),
        "voice_qualification_plans",
        ["skip_reason"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_consent_source"),
        "voice_qualification_plans",
        ["consent_source"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_consent_channel"),
        "voice_qualification_plans",
        ["consent_channel"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_qualification_plans_permitted_phone"),
        "voice_qualification_plans",
        ["permitted_phone"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_voice_qualification_plans_permitted_phone"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_consent_channel"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_consent_source"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_skip_reason"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_status"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_request_key"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_request_source"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_booking_plan_id"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_meeting_id"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_reply_classification_id"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_outreach_message_id"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_organization_id"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_contact_id"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_lead_id"),
        table_name="voice_qualification_plans",
    )
    op.drop_index(
        op.f("ix_voice_qualification_plans_voice_qualification_run_id"),
        table_name="voice_qualification_plans",
    )
    op.drop_table("voice_qualification_plans")
    op.drop_index(
        op.f("ix_voice_qualification_runs_status"),
        table_name="voice_qualification_runs",
    )
    op.drop_table("voice_qualification_runs")
