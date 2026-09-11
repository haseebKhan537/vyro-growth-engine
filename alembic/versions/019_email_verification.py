"""Add email verification verdict columns and inferred-email candidates.

Revision ID: 019_email_verification
Revises: 018_live_settings_requests
Create Date: 2026-09-07 00:00:00.000000

Production-safe: nullable contact columns with defaults, plus a new table for
inferred/unverified email candidates. Existing contacts, enrollments, and
operator-halt rows are unchanged. This phase does not send email, enroll
campaigns, or call live verifiers.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "019_email_verification"
down_revision: str | Sequence[str] | None = "018_live_settings_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("contacts", sa.Column("email_origin", sa.String(length=32), nullable=True))
    op.add_column(
        "contacts",
        sa.Column("email_verification_verdict", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("email_verification_provider", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("email_verification_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_contacts_email_verification_verdict"),
        "contacts",
        ["email_verification_verdict"],
        unique=False,
    )

    op.create_table(
        "email_pattern_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_email", sa.String(length=320), nullable=False),
        sa.Column("pattern_name", sa.String(length=32), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False, server_default="inferred"),
        sa.Column("promoted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verification_verdict", sa.String(length=32), nullable=True),
        sa.Column(
            "verification_status",
            sa.String(length=32),
            nullable=False,
            server_default="inferred",
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("live_call_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("smtp_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["source_contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_email_pattern_candidates_idempotency_key",
        ),
    )
    op.create_index(
        op.f("ix_email_pattern_candidates_organization_id"),
        "email_pattern_candidates",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_email_pattern_candidates_contact_id"),
        "email_pattern_candidates",
        ["contact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_email_pattern_candidates_source_contact_id"),
        "email_pattern_candidates",
        ["source_contact_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_email_pattern_candidates_source_contact_id"),
        table_name="email_pattern_candidates",
    )
    op.drop_index(
        op.f("ix_email_pattern_candidates_contact_id"),
        table_name="email_pattern_candidates",
    )
    op.drop_index(
        op.f("ix_email_pattern_candidates_organization_id"),
        table_name="email_pattern_candidates",
    )
    op.drop_table("email_pattern_candidates")
    op.drop_index(op.f("ix_contacts_email_verification_verdict"), table_name="contacts")
    op.drop_column("contacts", "email_verification_checked_at")
    op.drop_column("contacts", "email_verification_provider")
    op.drop_column("contacts", "email_verification_verdict")
    op.drop_column("contacts", "email_origin")
