"""Add record-only live settings change request queue.

Revision ID: 018_live_settings_requests
Revises: 017_approval_packet_decisions
Create Date: 2026-08-31 00:00:00.000000

Production-safe: new tables only. Existing launch-readiness, approval-packet,
execution-plan, review, and pipeline rows are unchanged. Requests and
decisions are audit records only and never apply settings, lift halt, or
execute live actions.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "018_live_settings_requests"
down_revision: str | Sequence[str] | None = "017_approval_packet_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "live_settings_change_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("owner_decision_status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "requested_setting_names",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("desired_boolean", sa.Boolean(), nullable=True),
        sa.Column("desired_status", sa.String(length=32), nullable=True),
        sa.Column("finding_code", sa.String(length=64), nullable=True),
        sa.Column("next_action_code", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("reviewer_notes", sa.String(length=500), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record_only", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.Column("owner_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("settings_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("halt_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("live_action", sa.Boolean(), nullable=False, server_default=sa.false()),
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
            "idempotency_key",
            name="uq_live_settings_change_requests_idempotency_key",
        ),
    )
    op.create_index(
        op.f("ix_live_settings_change_requests_request_type"),
        "live_settings_change_requests",
        ["request_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_live_settings_change_requests_status"),
        "live_settings_change_requests",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_live_settings_change_requests_owner_decision_status"),
        "live_settings_change_requests",
        ["owner_decision_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_live_settings_change_requests_idempotency_key"),
        "live_settings_change_requests",
        ["idempotency_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_live_settings_change_requests_finding_code"),
        "live_settings_change_requests",
        ["finding_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_live_settings_change_requests_next_action_code"),
        "live_settings_change_requests",
        ["next_action_code"],
        unique=False,
    )
    op.create_table(
        "live_settings_change_request_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "live_settings_change_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("live_settings_change_requests.id"),
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
        sa.Column("settings_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("halt_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("live_action", sa.Boolean(), nullable=False, server_default=sa.false()),
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
            "live_settings_change_request_id",
            name="uq_live_settings_change_request_decisions_request",
        ),
    )
    op.create_index(
        op.f("ix_live_settings_change_request_decisions_live_settings_change_request_id"),
        "live_settings_change_request_decisions",
        ["live_settings_change_request_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_live_settings_change_request_decisions_decision"),
        "live_settings_change_request_decisions",
        ["decision"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_live_settings_change_request_decisions_decision"),
        table_name="live_settings_change_request_decisions",
    )
    op.drop_index(
        op.f("ix_live_settings_change_request_decisions_live_settings_change_request_id"),
        table_name="live_settings_change_request_decisions",
    )
    op.drop_table("live_settings_change_request_decisions")
    op.drop_index(
        op.f("ix_live_settings_change_requests_next_action_code"),
        table_name="live_settings_change_requests",
    )
    op.drop_index(
        op.f("ix_live_settings_change_requests_finding_code"),
        table_name="live_settings_change_requests",
    )
    op.drop_index(
        op.f("ix_live_settings_change_requests_idempotency_key"),
        table_name="live_settings_change_requests",
    )
    op.drop_index(
        op.f("ix_live_settings_change_requests_owner_decision_status"),
        table_name="live_settings_change_requests",
    )
    op.drop_index(
        op.f("ix_live_settings_change_requests_status"),
        table_name="live_settings_change_requests",
    )
    op.drop_index(
        op.f("ix_live_settings_change_requests_request_type"),
        table_name="live_settings_change_requests",
    )
    op.drop_table("live_settings_change_requests")
