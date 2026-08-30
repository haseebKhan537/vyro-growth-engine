"""Add official-website enrichment runs and evidence fields.

Revision ID: 004_website_enrichment
Revises: 003_operator_halt_and_phone_suppression
Create Date: 2026-08-30 00:00:00.000000

Production-safe: creates a new table and nullable columns only.
Existing discovery/NPPES rows are unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "004_website_enrichment"
down_revision: str | Sequence[str] | None = "003_operator_halt_and_phone_suppression"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("website_match_status", sa.String(length=32), nullable=True),
    )
    op.create_index(
        op.f("ix_organizations_website_match_status"),
        "organizations",
        ["website_match_status"],
        unique=False,
    )

    op.create_table(
        "enrichment_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("match_status", sa.String(length=32), nullable=True),
        sa.Column("official_website", sa.String(length=500), nullable=True),
        sa.Column("facts_extracted", sa.Integer(), nullable=False),
        sa.Column("pages_fetched", sa.Integer(), nullable=False),
        sa.Column("candidates_considered", sa.Integer(), nullable=False),
        sa.Column("input_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_enrichment_runs_organization_id"),
        "enrichment_runs",
        ["organization_id"],
        unique=False,
    )
    op.create_index(op.f("ix_enrichment_runs_source"), "enrichment_runs", ["source"], unique=False)
    op.create_index(op.f("ix_enrichment_runs_status"), "enrichment_runs", ["status"], unique=False)
    op.create_index(
        op.f("ix_enrichment_runs_match_status"),
        "enrichment_runs",
        ["match_status"],
        unique=False,
    )

    op.add_column("source_evidence", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("source_evidence", sa.Column("evidence_snippet", sa.Text(), nullable=True))
    op.add_column(
        "source_evidence",
        sa.Column("enrichment_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_source_evidence_enrichment_run_id",
        "source_evidence",
        "enrichment_runs",
        ["enrichment_run_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_source_evidence_enrichment_run_id"),
        "source_evidence",
        ["enrichment_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_source_evidence_enrichment_run_id"), table_name="source_evidence")
    op.drop_constraint(
        "fk_source_evidence_enrichment_run_id",
        "source_evidence",
        type_="foreignkey",
    )
    op.drop_column("source_evidence", "enrichment_run_id")
    op.drop_column("source_evidence", "evidence_snippet")
    op.drop_column("source_evidence", "confidence")
    op.drop_index(op.f("ix_enrichment_runs_match_status"), table_name="enrichment_runs")
    op.drop_index(op.f("ix_enrichment_runs_status"), table_name="enrichment_runs")
    op.drop_index(op.f("ix_enrichment_runs_source"), table_name="enrichment_runs")
    op.drop_index(op.f("ix_enrichment_runs_organization_id"), table_name="enrichment_runs")
    op.drop_table("enrichment_runs")
    op.drop_index(op.f("ix_organizations_website_match_status"), table_name="organizations")
    op.drop_column("organizations", "website_match_status")
