"""Add dry-run outreach enrollment planning tables.

Revision ID: 007_outreach_enrollment
Revises: 006_personalization_drafts
Create Date: 2026-08-30 00:00:00.000000

Production-safe: new nullable campaign columns with defaults, a nullable
organization suppression foreign key, and new planning tables. Existing
leads, drafts, and suppressions are unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "007_outreach_enrollment"
down_revision: str | Sequence[str] | None = "006_personalization_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="email"),
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
            server_default="smartlead",
        ),
    )
    op.add_column(
        "campaigns",
        sa.Column("provider_campaign_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("dry_run_only", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.add_column(
        "suppressions",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_suppressions_organization_id"),
        "suppressions",
        ["organization_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_suppressions_organization_id",
        "suppressions",
        "organizations",
        ["organization_id"],
        ["id"],
    )

    op.create_table(
        "outreach_plan_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_outreach_plan_runs_campaign_id"),
        "outreach_plan_runs",
        ["campaign_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outreach_plan_runs_status"),
        "outreach_plan_runs",
        ["status"],
        unique=False,
    )

    op.create_table(
        "campaign_enrollments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outreach_plan_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("personalization_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("skip_reason", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "provider_name",
            sa.String(length=64),
            nullable=False,
            server_default="stub",
        ),
        sa.Column("provider_enrollment_id", sa.String(length=255), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "live_send_attempted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "details_json",
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
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["outreach_plan_run_id"], ["outreach_plan_runs.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["personalization_draft_id"], ["personalization_drafts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_campaign_enrollments_idempotency_key"),
    )
    op.create_index(
        op.f("ix_campaign_enrollments_campaign_id"),
        "campaign_enrollments",
        ["campaign_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_campaign_enrollments_outreach_plan_run_id"),
        "campaign_enrollments",
        ["outreach_plan_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_campaign_enrollments_lead_id"),
        "campaign_enrollments",
        ["lead_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_campaign_enrollments_contact_id"),
        "campaign_enrollments",
        ["contact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_campaign_enrollments_organization_id"),
        "campaign_enrollments",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_campaign_enrollments_personalization_draft_id"),
        "campaign_enrollments",
        ["personalization_draft_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_campaign_enrollments_status"),
        "campaign_enrollments",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_campaign_enrollments_skip_reason"),
        "campaign_enrollments",
        ["skip_reason"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_campaign_enrollments_skip_reason"), table_name="campaign_enrollments")
    op.drop_index(op.f("ix_campaign_enrollments_status"), table_name="campaign_enrollments")
    op.drop_index(
        op.f("ix_campaign_enrollments_personalization_draft_id"),
        table_name="campaign_enrollments",
    )
    op.drop_index(
        op.f("ix_campaign_enrollments_organization_id"),
        table_name="campaign_enrollments",
    )
    op.drop_index(op.f("ix_campaign_enrollments_contact_id"), table_name="campaign_enrollments")
    op.drop_index(op.f("ix_campaign_enrollments_lead_id"), table_name="campaign_enrollments")
    op.drop_index(
        op.f("ix_campaign_enrollments_outreach_plan_run_id"),
        table_name="campaign_enrollments",
    )
    op.drop_index(op.f("ix_campaign_enrollments_campaign_id"), table_name="campaign_enrollments")
    op.drop_table("campaign_enrollments")
    op.drop_index(op.f("ix_outreach_plan_runs_status"), table_name="outreach_plan_runs")
    op.drop_index(op.f("ix_outreach_plan_runs_campaign_id"), table_name="outreach_plan_runs")
    op.drop_table("outreach_plan_runs")
    op.drop_constraint("fk_suppressions_organization_id", "suppressions", type_="foreignkey")
    op.drop_index(op.f("ix_suppressions_organization_id"), table_name="suppressions")
    op.drop_column("suppressions", "organization_id")
    op.drop_column("campaigns", "dry_run_only")
    op.drop_column("campaigns", "provider_campaign_key")
    op.drop_column("campaigns", "provider")
    op.drop_column("campaigns", "channel")
