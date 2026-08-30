"""Add inbound reply classifications.

Revision ID: 008_reply_classifications
Revises: 007_outreach_enrollment
Create Date: 2026-08-30 00:00:00.000000

Production-safe: new table only. Existing outreach, conversation, lead, and
suppression rows are unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "008_reply_classifications"
down_revision: str | Sequence[str] | None = "007_outreach_enrollment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reply_classifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outreach_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("sender_email", sa.String(length=320), nullable=True),
        sa.Column("intent", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("unsubscribe_explicit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suppressed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("outbound_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("live_call_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lead_stage_before", sa.String(length=64), nullable=False),
        sa.Column("lead_stage_after", sa.String(length=64), nullable=False),
        sa.Column("conversation_status_after", sa.String(length=64), nullable=True),
        sa.Column(
            "matched_signals",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "rationale_json",
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
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.ForeignKeyConstraint(["outreach_message_id"], ["outreach_messages.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lead_id",
            "content_hash",
            name="uq_reply_classifications_lead_content_hash",
        ),
        sa.UniqueConstraint("outreach_message_id"),
        sa.UniqueConstraint("provider_message_id"),
    )
    op.create_index(
        op.f("ix_reply_classifications_lead_id"),
        "reply_classifications",
        ["lead_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reply_classifications_outreach_message_id"),
        "reply_classifications",
        ["outreach_message_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_reply_classifications_conversation_id"),
        "reply_classifications",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reply_classifications_provider_message_id"),
        "reply_classifications",
        ["provider_message_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_reply_classifications_sender_email"),
        "reply_classifications",
        ["sender_email"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reply_classifications_intent"),
        "reply_classifications",
        ["intent"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reply_classifications_outcome"),
        "reply_classifications",
        ["outcome"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reply_classifications_provider_name"),
        "reply_classifications",
        ["provider_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reply_classifications_content_hash"),
        "reply_classifications",
        ["content_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_reply_classifications_content_hash"),
        table_name="reply_classifications",
    )
    op.drop_index(
        op.f("ix_reply_classifications_provider_name"),
        table_name="reply_classifications",
    )
    op.drop_index(op.f("ix_reply_classifications_outcome"), table_name="reply_classifications")
    op.drop_index(op.f("ix_reply_classifications_intent"), table_name="reply_classifications")
    op.drop_index(
        op.f("ix_reply_classifications_sender_email"),
        table_name="reply_classifications",
    )
    op.drop_index(
        op.f("ix_reply_classifications_provider_message_id"),
        table_name="reply_classifications",
    )
    op.drop_index(
        op.f("ix_reply_classifications_conversation_id"),
        table_name="reply_classifications",
    )
    op.drop_index(
        op.f("ix_reply_classifications_outreach_message_id"),
        table_name="reply_classifications",
    )
    op.drop_index(op.f("ix_reply_classifications_lead_id"), table_name="reply_classifications")
    op.drop_table("reply_classifications")
