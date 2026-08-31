"""Add operator review decision records.

Revision ID: 012_operator_review_decisions
Revises: 011_optimizer_recommendations
Create Date: 2026-08-30 00:00:00.000000

Production-safe: new table only. Existing personalization, outreach, reply,
booking, voice, and optimizer rows are unchanged. Decisions are recorded
approvals only and never execute outbound or provider actions.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "012_operator_review_decisions"
down_revision: str | Sequence[str] | None = "011_optimizer_recommendations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operator_review_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("previous_decision", sa.String(length=32), nullable=True),
        sa.Column("reviewer", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("reviewer_notes", sa.String(length=500), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("item_status", sa.String(length=64), nullable=False),
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
            "artifact_type",
            "artifact_id",
            name="uq_operator_review_decisions_artifact",
        ),
    )
    op.create_index(
        op.f("ix_operator_review_decisions_artifact_type"),
        "operator_review_decisions",
        ["artifact_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_operator_review_decisions_artifact_id"),
        "operator_review_decisions",
        ["artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_operator_review_decisions_decision"),
        "operator_review_decisions",
        ["decision"],
        unique=False,
    )
    op.create_index(
        op.f("ix_operator_review_decisions_item_status"),
        "operator_review_decisions",
        ["item_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_operator_review_decisions_item_status"),
        table_name="operator_review_decisions",
    )
    op.drop_index(
        op.f("ix_operator_review_decisions_decision"),
        table_name="operator_review_decisions",
    )
    op.drop_index(
        op.f("ix_operator_review_decisions_artifact_id"),
        table_name="operator_review_decisions",
    )
    op.drop_index(
        op.f("ix_operator_review_decisions_artifact_type"),
        table_name="operator_review_decisions",
    )
    op.drop_table("operator_review_decisions")
