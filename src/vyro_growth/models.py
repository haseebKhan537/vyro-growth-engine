from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vyro_growth.database import Base
from vyro_growth.domain import DiscoveryRunStatus, EnrichmentRunStatus, LeadStage


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    npi: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    specialty: Mapped[str | None] = mapped_column(String(255), index=True)
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(2), index=True)
    website_match_status: Mapped[str | None] = mapped_column(String(32), index=True)
    leads: Mapped[list[Lead]] = relationship(back_populates="organization")
    enrichment_runs: Mapped[list[EnrichmentRun]] = relationship(back_populates="organization")


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "dedupe_key",
            name="uq_contacts_organization_dedupe_key",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(50))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    role_category: Mapped[str | None] = mapped_column(String(64), index=True)
    role_rank: Mapped[int | None] = mapped_column(Integer)
    source_provider: Mapped[str | None] = mapped_column(String(64), index=True)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float | None] = mapped_column(Float)
    verification_status: Mapped[str | None] = mapped_column(String(32))
    provenance_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(512))


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    stage: Mapped[str] = mapped_column(String(64), default=LeadStage.DISCOVERED.value, index=True)
    source: Mapped[str] = mapped_column(String(120))
    organization: Mapped[Organization] = relationship(back_populates="leads")


class LeadScore(TimestampMixin, Base):
    __tablename__ = "lead_scores"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    lead_id: Mapped[UUID] = mapped_column(ForeignKey("leads.id"), index=True)
    score: Mapped[int]
    model_version: Mapped[str] = mapped_column(String(64))
    rationale: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class Campaign(TimestampMixin, Base):
    __tablename__ = "campaigns"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)


class OutreachMessage(TimestampMixin, Base):
    __tablename__ = "outreach_messages"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    lead_id: Mapped[UUID] = mapped_column(ForeignKey("leads.id"), index=True)
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), unique=True)


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    lead_id: Mapped[UUID] = mapped_column(ForeignKey("leads.id"), index=True)
    status: Mapped[str] = mapped_column(String(64), default="open")
    summary: Mapped[str | None] = mapped_column(Text)


class Meeting(TimestampMixin, Base):
    __tablename__ = "meetings"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    lead_id: Mapped[UUID] = mapped_column(ForeignKey("leads.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    meeting_url: Mapped[str | None] = mapped_column(String(1000))
    provider_event_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(64), default="scheduled")


class Activity(TimestampMixin, Base):
    __tablename__ = "activities"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("leads.id"), index=True)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(120), index=True)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class Suppression(TimestampMixin, Base):
    __tablename__ = "suppressions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    reason: Mapped[str] = mapped_column(String(120))
    permanent: Mapped[bool] = mapped_column(Boolean, default=True)


GLOBAL_OPERATOR_CONTROL_KEY = "global"


class OperatorControl(TimestampMixin, Base):
    """Singleton-style operator safety controls, keyed by a stable name."""

    __tablename__ = "operator_controls"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    outbound_halted: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str | None] = mapped_column(String(255))


class DiscoveryRun(TimestampMixin, Base):
    __tablename__ = "discovery_runs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=DiscoveryRunStatus.PENDING.value, index=True
    )
    query_params: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    records_fetched: Mapped[int] = mapped_column(default=0)
    records_upserted: Mapped[int] = mapped_column(default=0)
    records_skipped: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list[SourceEvidence]] = relationship(back_populates="discovery_run")


class SourceEvidence(TimestampMixin, Base):
    __tablename__ = "source_evidence"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    discovery_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("discovery_runs.id"), index=True
    )
    source_url: Mapped[str] = mapped_column(String(1000))
    claim_type: Mapped[str] = mapped_column(String(120), index=True)
    extracted_value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_snippet: Mapped[str | None] = mapped_column(Text)
    enrichment_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("enrichment_runs.id"), index=True
    )
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    discovery_run: Mapped[DiscoveryRun | None] = relationship(back_populates="evidence")
    enrichment_run: Mapped[EnrichmentRun | None] = relationship(back_populates="evidence")


class EnrichmentRun(TimestampMixin, Base):
    __tablename__ = "enrichment_runs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=EnrichmentRunStatus.PENDING.value, index=True
    )
    match_status: Mapped[str | None] = mapped_column(String(32), index=True)
    official_website: Mapped[str | None] = mapped_column(String(500))
    facts_extracted: Mapped[int] = mapped_column(default=0)
    pages_fetched: Mapped[int] = mapped_column(default=0)
    candidates_considered: Mapped[int] = mapped_column(default=0)
    contacts_upserted: Mapped[int] = mapped_column(default=0)
    contacts_skipped: Mapped[int] = mapped_column(default=0)
    input_params: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    organization: Mapped[Organization] = relationship(back_populates="enrichment_runs")
    evidence: Mapped[list[SourceEvidence]] = relationship(back_populates="enrichment_run")
