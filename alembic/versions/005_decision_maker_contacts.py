"""Add decision-maker contact enrichment fields.

Revision ID: 005_decision_maker_contacts
Revises: 004_website_enrichment
Create Date: 2026-08-30 00:00:00.000000

Production-safe: nullable contact columns, counters with defaults, and a
nullable evidence foreign key. Existing rows are unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "005_decision_maker_contacts"
down_revision: str | Sequence[str] | None = "004_website_enrichment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("contacts", sa.Column("role_category", sa.String(length=64), nullable=True))
    op.add_column("contacts", sa.Column("role_rank", sa.Integer(), nullable=True))
    op.add_column("contacts", sa.Column("source_provider", sa.String(length=64), nullable=True))
    op.add_column(
        "contacts",
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("contacts", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column(
        "contacts",
        sa.Column("verification_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "provenance_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("contacts", sa.Column("dedupe_key", sa.String(length=512), nullable=True))
    op.create_index(op.f("ix_contacts_role_category"), "contacts", ["role_category"], unique=False)
    op.create_index(
        op.f("ix_contacts_source_provider"),
        "contacts",
        ["source_provider"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_contacts_organization_dedupe_key",
        "contacts",
        ["organization_id", "dedupe_key"],
    )

    op.add_column(
        "enrichment_runs",
        sa.Column("contacts_upserted", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "enrichment_runs",
        sa.Column("contacts_skipped", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column(
        "source_evidence",
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_source_evidence_contact_id",
        "source_evidence",
        "contacts",
        ["contact_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_source_evidence_contact_id"),
        "source_evidence",
        ["contact_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_source_evidence_contact_id"), table_name="source_evidence")
    op.drop_constraint("fk_source_evidence_contact_id", "source_evidence", type_="foreignkey")
    op.drop_column("source_evidence", "contact_id")
    op.drop_column("enrichment_runs", "contacts_skipped")
    op.drop_column("enrichment_runs", "contacts_upserted")
    op.drop_constraint("uq_contacts_organization_dedupe_key", "contacts", type_="unique")
    op.drop_index(op.f("ix_contacts_source_provider"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_role_category"), table_name="contacts")
    op.drop_column("contacts", "dedupe_key")
    op.drop_column("contacts", "provenance_json")
    op.drop_column("contacts", "verification_status")
    op.drop_column("contacts", "confidence")
    op.drop_column("contacts", "source_timestamp")
    op.drop_column("contacts", "source_provider")
    op.drop_column("contacts", "role_rank")
    op.drop_column("contacts", "role_category")
