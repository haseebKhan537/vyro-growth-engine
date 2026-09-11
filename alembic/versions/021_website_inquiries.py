"""Add consented public website inquiry records.

Revision ID: 021_website_inquiries
Revises: 020_contact_discovery_calls
Create Date: 2026-09-10 00:00:00.000000

Record-only: this migration does not enable outbound actions or providers.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "021_website_inquiries"
down_revision: str | Sequence[str] | None = "020_contact_discovery_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "website_inquiries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("form_name", sa.String(length=64), nullable=False),
        sa.Column("source_page", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="new", nullable=False),
        sa.Column("provider_count", sa.String(length=32), nullable=True),
        sa.Column("primary_concern", sa.String(length=120), nullable=True),
        sa.Column("preferred_contact", sa.String(length=32), nullable=True),
        sa.Column("business_context", sa.Text(), nullable=True),
        sa.Column("contact_consent", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("consent_text_version", sa.String(length=32), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["outreach_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", name="uq_website_inquiries_submission_id"),
    )
    for column in (
        "submission_id",
        "organization_id",
        "contact_id",
        "lead_id",
        "message_id",
        "form_name",
        "status",
        "primary_concern",
    ):
        op.create_index(
            op.f(f"ix_website_inquiries_{column}"),
            "website_inquiries",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in reversed(
        (
            "submission_id",
            "organization_id",
            "contact_id",
            "lead_id",
            "message_id",
            "form_name",
            "status",
            "primary_concern",
        )
    ):
        op.drop_index(op.f(f"ix_website_inquiries_{column}"), table_name="website_inquiries")
    op.drop_table("website_inquiries")
