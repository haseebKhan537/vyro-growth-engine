"""Add evidence-grounded personalization drafts.

Revision ID: 006_personalization_drafts
Revises: 005_decision_maker_contacts
Create Date: 2026-08-30 00:00:00.000000

Production-safe: new table plus a nullable evidence foreign key.
Existing discovery, scoring, and enrichment rows are unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "006_personalization_drafts"
down_revision: str | Sequence[str] | None = "005_decision_maker_contacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "personalization_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enrichment_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("readiness_status", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("practice_summary", sa.Text(), nullable=False),
        sa.Column("why_vyro_relevant", sa.Text(), nullable=False),
        sa.Column("opening_line", sa.Text(), nullable=False),
        sa.Column("outreach_angle", sa.Text(), nullable=False),
        sa.Column("suggested_offer", sa.String(length=255), nullable=False),
        sa.Column(
            "missing_data_notes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "evidence_references",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "content_json",
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
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=False),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["enrichment_run_id"], ["enrichment_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lead_id",
            "evidence_fingerprint",
            name="uq_personalization_drafts_lead_fingerprint",
        ),
    )
    op.create_index(
        op.f("ix_personalization_drafts_lead_id"),
        "personalization_drafts",
        ["lead_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_personalization_drafts_organization_id"),
        "personalization_drafts",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_personalization_drafts_enrichment_run_id"),
        "personalization_drafts",
        ["enrichment_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_personalization_drafts_readiness_status"),
        "personalization_drafts",
        ["readiness_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_personalization_drafts_provider_name"),
        "personalization_drafts",
        ["provider_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_personalization_drafts_evidence_fingerprint"),
        "personalization_drafts",
        ["evidence_fingerprint"],
        unique=False,
    )

    op.add_column(
        "source_evidence",
        sa.Column("personalization_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_source_evidence_personalization_draft_id",
        "source_evidence",
        "personalization_drafts",
        ["personalization_draft_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_source_evidence_personalization_draft_id"),
        "source_evidence",
        ["personalization_draft_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_source_evidence_personalization_draft_id"), table_name="source_evidence")
    op.drop_constraint(
        "fk_source_evidence_personalization_draft_id",
        "source_evidence",
        type_="foreignkey",
    )
    op.drop_column("source_evidence", "personalization_draft_id")
    op.drop_index(
        op.f("ix_personalization_drafts_evidence_fingerprint"),
        table_name="personalization_drafts",
    )
    op.drop_index(
        op.f("ix_personalization_drafts_provider_name"),
        table_name="personalization_drafts",
    )
    op.drop_index(
        op.f("ix_personalization_drafts_readiness_status"),
        table_name="personalization_drafts",
    )
    op.drop_index(
        op.f("ix_personalization_drafts_enrichment_run_id"),
        table_name="personalization_drafts",
    )
    op.drop_index(
        op.f("ix_personalization_drafts_organization_id"),
        table_name="personalization_drafts",
    )
    op.drop_index(op.f("ix_personalization_drafts_lead_id"), table_name="personalization_drafts")
    op.drop_table("personalization_drafts")
