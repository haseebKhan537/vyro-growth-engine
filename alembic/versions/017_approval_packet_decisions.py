"""Add owner approval packet decision records.

Revision ID: 017_approval_packet_decisions
Revises: 016_approval_packets
Create Date: 2026-08-31 00:00:00.000000

Production-safe: new table only. Existing approval-packet, execution-plan,
review, and pipeline rows are unchanged. Decisions are audit records only
and never execute the packet or the underlying live action.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "017_approval_packet_decisions"
down_revision: str | Sequence[str] | None = "016_approval_packets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owner_approval_packet_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "owner_approval_packet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("owner_approval_packets.id"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("previous_decision", sa.String(length=32), nullable=True),
        sa.Column("reviewer", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("reviewer_notes", sa.String(length=500), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.Column("owner_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
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
            "owner_approval_packet_id",
            name="uq_owner_approval_packet_decisions_packet",
        ),
    )
    op.create_index(
        op.f("ix_owner_approval_packet_decisions_owner_approval_packet_id"),
        "owner_approval_packet_decisions",
        ["owner_approval_packet_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_owner_approval_packet_decisions_decision"),
        "owner_approval_packet_decisions",
        ["decision"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_owner_approval_packet_decisions_decision"),
        table_name="owner_approval_packet_decisions",
    )
    op.drop_index(
        op.f("ix_owner_approval_packet_decisions_owner_approval_packet_id"),
        table_name="owner_approval_packet_decisions",
    )
    op.drop_table("owner_approval_packet_decisions")
