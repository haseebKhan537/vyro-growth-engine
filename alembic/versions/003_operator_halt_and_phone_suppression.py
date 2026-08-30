"""Add operator halt control and phone suppressions.

Revision ID: 003_operator_halt_and_phone_suppression
Revises: 002_discovery_runs
Create Date: 2026-08-30 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003_operator_halt_and_phone_suppression"
down_revision: str | Sequence[str] | None = "002_discovery_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operator_controls",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("outbound_halted", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("reason", sa.String(length=255), nullable=True),
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
        sa.PrimaryKeyConstraint("key"),
    )
    op.execute(
        sa.text(
            "INSERT INTO operator_controls (key, outbound_halted, reason) "
            "VALUES ('global', true, 'seeded_halted')"
        )
    )

    op.add_column("suppressions", sa.Column("phone", sa.String(length=50), nullable=True))
    op.create_index(op.f("ix_suppressions_phone"), "suppressions", ["phone"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_suppressions_phone"), table_name="suppressions")
    op.drop_column("suppressions", "phone")
    op.drop_table("operator_controls")
