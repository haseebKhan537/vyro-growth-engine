"""Add human phone-verification task queue for NO_CONTACT_FOUND.

Revision ID: 020_contact_discovery_calls
Revises: 019_email_verification
Create Date: 2026-09-07 00:00:00.000000

Production-safe: new table only. Existing contacts, suppressions, operator-halt
rows, and outbound flags are unchanged. This phase does not place calls, route
through VoiceProvider, autodial, or call phone APIs.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "020_contact_discovery_calls"
down_revision: str | Sequence[str] | None = "019_email_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_discovery_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("enrichment_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("suppression_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=64),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "queued_reason",
            sa.String(length=64),
            nullable=False,
            server_default="no_contact_found",
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("operator_label", sa.String(length=120), nullable=True),
        sa.Column("operator_notes", sa.String(length=500), nullable=True),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            server_default="contact_enrichment",
        ),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("no_execution", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("execution_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("outbound_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("live_call_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("voice_provider_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("autodial_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suppression_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("contact_fact_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "details_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.ForeignKeyConstraint(["enrichment_run_id"], ["enrichment_runs.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["suppression_id"], ["suppressions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_contact_discovery_calls_idempotency_key",
        ),
    )
    op.create_index(
        op.f("ix_contact_discovery_calls_organization_id"),
        "contact_discovery_calls",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contact_discovery_calls_lead_id"),
        "contact_discovery_calls",
        ["lead_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contact_discovery_calls_enrichment_run_id"),
        "contact_discovery_calls",
        ["enrichment_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contact_discovery_calls_contact_id"),
        "contact_discovery_calls",
        ["contact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contact_discovery_calls_suppression_id"),
        "contact_discovery_calls",
        ["suppression_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contact_discovery_calls_status"),
        "contact_discovery_calls",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_contact_discovery_calls_status"),
        table_name="contact_discovery_calls",
    )
    op.drop_index(
        op.f("ix_contact_discovery_calls_suppression_id"),
        table_name="contact_discovery_calls",
    )
    op.drop_index(
        op.f("ix_contact_discovery_calls_contact_id"),
        table_name="contact_discovery_calls",
    )
    op.drop_index(
        op.f("ix_contact_discovery_calls_enrichment_run_id"),
        table_name="contact_discovery_calls",
    )
    op.drop_index(
        op.f("ix_contact_discovery_calls_lead_id"),
        table_name="contact_discovery_calls",
    )
    op.drop_index(
        op.f("ix_contact_discovery_calls_organization_id"),
        table_name="contact_discovery_calls",
    )
    op.drop_table("contact_discovery_calls")
