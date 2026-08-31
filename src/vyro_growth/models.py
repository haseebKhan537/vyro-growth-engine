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
from vyro_growth.domain import (
    AcquisitionChannelPlanStatus,
    BookingPlanRunStatus,
    BookingPlanStatus,
    ContentBriefApprovalStatus,
    ContentBriefRunStatus,
    ConversationStatus,
    DiscoveryRunStatus,
    EnrichmentRunStatus,
    EnrollmentStatus,
    LeadStage,
    OptimizerRunStatus,
    OutreachPlanRunStatus,
    RecommendationApprovalStatus,
    ReplyClassificationOutcome,
    ReplyIntent,
    ReviewDecisionStatus,
    ReviewItemStatus,
    VoicePlanStatus,
    VoiceQualificationRunStatus,
)


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
    personalization_drafts: Mapped[list[PersonalizationDraft]] = relationship(
        back_populates="organization"
    )


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
    channel: Mapped[str] = mapped_column(String(32), default="email")
    provider: Mapped[str] = mapped_column(String(64), default="smartlead")
    provider_campaign_key: Mapped[str | None] = mapped_column(String(255))
    dry_run_only: Mapped[bool] = mapped_column(Boolean, default=True)
    enrollments: Mapped[list[CampaignEnrollment]] = relationship(back_populates="campaign")
    outreach_plan_runs: Mapped[list[OutreachPlanRun]] = relationship(back_populates="campaign")


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
    status: Mapped[str] = mapped_column(String(64), default=ConversationStatus.OPEN.value)
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
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
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
    personalization_draft_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("personalization_drafts.id"), index=True
    )
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


class PersonalizationDraft(TimestampMixin, Base):
    __tablename__ = "personalization_drafts"
    __table_args__ = (
        UniqueConstraint(
            "lead_id",
            "evidence_fingerprint",
            name="uq_personalization_drafts_lead_fingerprint",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    lead_id: Mapped[UUID] = mapped_column(ForeignKey("leads.id"), index=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    enrichment_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("enrichment_runs.id"), index=True
    )
    readiness_status: Mapped[str] = mapped_column(String(32), index=True)
    prompt_version: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(64))
    provider_name: Mapped[str] = mapped_column(String(64), index=True)
    practice_summary: Mapped[str] = mapped_column(Text)
    why_vyro_relevant: Mapped[str] = mapped_column(Text)
    opening_line: Mapped[str] = mapped_column(Text)
    outreach_angle: Mapped[str] = mapped_column(Text)
    suggested_offer: Mapped[str] = mapped_column(String(255))
    missing_data_notes: Mapped[list[object]] = mapped_column(JSONB, default=list)
    evidence_references: Mapped[list[object]] = mapped_column(JSONB, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    content_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    audit_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    organization: Mapped[Organization] = relationship(back_populates="personalization_drafts")


class OutreachPlanRun(TimestampMixin, Base):
    __tablename__ = "outreach_plan_runs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id"), index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=OutreachPlanRunStatus.PENDING.value, index=True
    )
    input_params: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    planned_count: Mapped[int] = mapped_column(default=0)
    skipped_count: Mapped[int] = mapped_column(default=0)
    suppressed_count: Mapped[int] = mapped_column(default=0)
    blocked_count: Mapped[int] = mapped_column(default=0)
    reused_count: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    campaign: Mapped[Campaign] = relationship(back_populates="outreach_plan_runs")
    enrollments: Mapped[list[CampaignEnrollment]] = relationship(back_populates="plan_run")


class CampaignEnrollment(TimestampMixin, Base):
    __tablename__ = "campaign_enrollments"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_campaign_enrollments_idempotency_key",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id"), index=True)
    outreach_plan_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outreach_plan_runs.id"), index=True
    )
    lead_id: Mapped[UUID] = mapped_column(ForeignKey("leads.id"), index=True)
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    personalization_draft_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("personalization_drafts.id"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default=EnrollmentStatus.SKIPPED.value, index=True
    )
    skip_reason: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    provider_name: Mapped[str] = mapped_column(String(64), default="stub")
    provider_enrollment_id: Mapped[str | None] = mapped_column(String(255))
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    live_send_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    details_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    campaign: Mapped[Campaign] = relationship(back_populates="enrollments")
    plan_run: Mapped[OutreachPlanRun | None] = relationship(back_populates="enrollments")


class ReplyClassification(TimestampMixin, Base):
    __tablename__ = "reply_classifications"
    __table_args__ = (
        UniqueConstraint(
            "lead_id",
            "content_hash",
            name="uq_reply_classifications_lead_content_hash",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    lead_id: Mapped[UUID] = mapped_column(ForeignKey("leads.id"), index=True)
    outreach_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outreach_messages.id"), unique=True, index=True
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    sender_email: Mapped[str | None] = mapped_column(String(320), index=True)
    intent: Mapped[str] = mapped_column(String(64), default=ReplyIntent.UNKNOWN.value, index=True)
    outcome: Mapped[str] = mapped_column(
        String(32), default=ReplyClassificationOutcome.UNKNOWN.value, index=True
    )
    confidence: Mapped[float] = mapped_column(Float)
    provider_name: Mapped[str] = mapped_column(String(64), index=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    unsubscribe_explicit: Mapped[bool] = mapped_column(Boolean, default=False)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    outbound_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    live_call_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    lead_stage_before: Mapped[str] = mapped_column(String(64))
    lead_stage_after: Mapped[str] = mapped_column(String(64))
    conversation_status_after: Mapped[str | None] = mapped_column(String(64))
    matched_signals: Mapped[list[object]] = mapped_column(JSONB, default=list)
    rationale_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    audit_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class BookingPlanRun(TimestampMixin, Base):
    __tablename__ = "booking_plan_runs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(
        String(32), default=BookingPlanRunStatus.PENDING.value, index=True
    )
    input_params: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    planned_count: Mapped[int] = mapped_column(default=0)
    skipped_count: Mapped[int] = mapped_column(default=0)
    suppressed_count: Mapped[int] = mapped_column(default=0)
    blocked_count: Mapped[int] = mapped_column(default=0)
    reused_count: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    plans: Mapped[list[BookingPlan]] = relationship(back_populates="plan_run")


class BookingPlan(TimestampMixin, Base):
    __tablename__ = "booking_plans"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_booking_plans_idempotency_key",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    booking_plan_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("booking_plan_runs.id"), index=True
    )
    lead_id: Mapped[UUID] = mapped_column(ForeignKey("leads.id"), index=True)
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    reply_classification_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reply_classifications.id"), index=True
    )
    request_source: Mapped[str] = mapped_column(String(64), index=True)
    request_key: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=BookingPlanStatus.SKIPPED.value, index=True
    )
    skip_reason: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    provider_name: Mapped[str] = mapped_column(String(64), default="stub")
    requested_window: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    proposed_slots: Mapped[list[object]] = mapped_column(JSONB, default=list)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    event_created: Mapped[bool] = mapped_column(Boolean, default=False)
    meet_link_created: Mapped[bool] = mapped_column(Boolean, default=False)
    live_call_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_event_id: Mapped[str | None] = mapped_column(String(255))
    meeting_url: Mapped[str | None] = mapped_column(String(1000))
    lead_stage_before: Mapped[str] = mapped_column(String(64))
    lead_stage_after: Mapped[str] = mapped_column(String(64))
    audit_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    plan_run: Mapped[BookingPlanRun | None] = relationship(back_populates="plans")


class VoiceQualificationRun(TimestampMixin, Base):
    __tablename__ = "voice_qualification_runs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(
        String(32), default=VoiceQualificationRunStatus.PENDING.value, index=True
    )
    input_params: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    planned_count: Mapped[int] = mapped_column(default=0)
    skipped_count: Mapped[int] = mapped_column(default=0)
    suppressed_count: Mapped[int] = mapped_column(default=0)
    blocked_count: Mapped[int] = mapped_column(default=0)
    reused_count: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    plans: Mapped[list[VoiceQualificationPlan]] = relationship(back_populates="plan_run")


class VoiceQualificationPlan(TimestampMixin, Base):
    __tablename__ = "voice_qualification_plans"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_voice_qualification_plans_idempotency_key",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    voice_qualification_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("voice_qualification_runs.id"), index=True
    )
    lead_id: Mapped[UUID] = mapped_column(ForeignKey("leads.id"), index=True)
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    outreach_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outreach_messages.id"), index=True
    )
    reply_classification_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reply_classifications.id"), index=True
    )
    meeting_id: Mapped[UUID | None] = mapped_column(ForeignKey("meetings.id"), index=True)
    booking_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("booking_plans.id"), index=True
    )
    request_source: Mapped[str] = mapped_column(String(64), index=True)
    request_key: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=VoicePlanStatus.SKIPPED.value, index=True
    )
    skip_reason: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    provider_name: Mapped[str] = mapped_column(String(64), default="stub")
    provider_plan_id: Mapped[str | None] = mapped_column(String(255))
    consent_source: Mapped[str | None] = mapped_column(String(64), index=True)
    consent_channel: Mapped[str | None] = mapped_column(String(32), index=True)
    consent_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_evidence_id: Mapped[str | None] = mapped_column(String(255))
    permitted_phone: Mapped[str | None] = mapped_column(String(50), index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    live_call_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    call_placed: Mapped[bool] = mapped_column(Boolean, default=False)
    facts_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    consent_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    audit_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    plan_run: Mapped[VoiceQualificationRun | None] = relationship(back_populates="plans")


class OptimizerRun(TimestampMixin, Base):
    __tablename__ = "optimizer_runs"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_fingerprint",
            name="uq_optimizer_runs_snapshot_fingerprint",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(
        String(32), default=OptimizerRunStatus.PENDING.value, index=True
    )
    model_version: Mapped[str] = mapped_column(String(64), default="growth-optimizer-v1")
    snapshot_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    recommendation_count: Mapped[int] = mapped_column(default=0)
    reused_count: Mapped[int] = mapped_column(default=0)
    applied_count: Mapped[int] = mapped_column(default=0)
    dry_run_only: Mapped[bool] = mapped_column(Boolean, default=True)
    outbound_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    live_call_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    input_params: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    snapshot_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    recommendations: Mapped[list[OptimizerRecommendation]] = relationship(
        back_populates="optimizer_run"
    )


class OptimizerRecommendation(TimestampMixin, Base):
    __tablename__ = "optimizer_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "optimizer_run_id",
            "recommendation_key",
            name="uq_optimizer_recommendations_run_key",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    optimizer_run_id: Mapped[UUID] = mapped_column(ForeignKey("optimizer_runs.id"), index=True)
    recommendation_key: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    priority: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(255))
    rationale: Mapped[str] = mapped_column(Text)
    source_metrics_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approval_status: Mapped[str] = mapped_column(
        String(64),
        default=RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
        index=True,
    )
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    optimizer_run: Mapped[OptimizerRun] = relationship(back_populates="recommendations")


class OperatorReviewDecision(TimestampMixin, Base):
    """Recorded operator decision for a pending dry-run artifact.

    Phase 14 persists the decision only. It never executes outbound, enrollment,
    booking, voice, autonomous-reply, or optimizer-apply side effects.
    """

    __tablename__ = "operator_review_decisions"
    __table_args__ = (
        UniqueConstraint(
            "artifact_type",
            "artifact_id",
            name="uq_operator_review_decisions_artifact",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    artifact_type: Mapped[str] = mapped_column(String(64), index=True)
    artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    decision: Mapped[str] = mapped_column(
        String(32),
        default=ReviewDecisionStatus.APPROVED.value,
        index=True,
    )
    previous_decision: Mapped[str | None] = mapped_column(String(32))
    reviewer: Mapped[str] = mapped_column(String(120), default="operator")
    source: Mapped[str] = mapped_column(String(64), default="cli")
    reviewer_notes: Mapped[str | None] = mapped_column(String(500))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    item_status: Mapped[str] = mapped_column(
        String(64),
        default=ReviewItemStatus.PENDING_OPERATOR_REVIEW.value,
        index=True,
    )
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    execution_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    outbound_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    live_call_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    recommendation_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    audit_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class AcquisitionChannelPlan(TimestampMixin, Base):
    """Review-only acquisition channel plan. Never launched and never spends."""

    __tablename__ = "acquisition_channel_plans"
    __table_args__ = (
        UniqueConstraint(
            "plan_key",
            name="uq_acquisition_channel_plans_plan_key",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    plan_key: Mapped[str] = mapped_column(String(255), index=True)
    channel_type: Mapped[str] = mapped_column(String(64), index=True)
    specialty: Mapped[str | None] = mapped_column(String(120), index=True)
    geography: Mapped[str | None] = mapped_column(String(120), index=True)
    icp_label: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text)
    source_metrics_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(
        String(64),
        default=AcquisitionChannelPlanStatus.PENDING_OPERATOR_REVIEW.value,
        index=True,
    )
    dry_run_only: Mapped[bool] = mapped_column(Boolean, default=True)
    launched: Mapped[bool] = mapped_column(Boolean, default=False)
    spend_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    ads_live: Mapped[bool] = mapped_column(Boolean, default=False)


class ContentBriefRun(TimestampMixin, Base):
    __tablename__ = "content_brief_runs"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_fingerprint",
            name="uq_content_brief_runs_snapshot_fingerprint",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(
        String(32), default=ContentBriefRunStatus.PENDING.value, index=True
    )
    model_version: Mapped[str] = mapped_column(String(64), default="content-brief-v1")
    snapshot_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    brief_count: Mapped[int] = mapped_column(default=0)
    reused_count: Mapped[int] = mapped_column(default=0)
    published_count: Mapped[int] = mapped_column(default=0)
    dry_run_only: Mapped[bool] = mapped_column(Boolean, default=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    publish_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    outbound_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    live_call_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    ads_launched: Mapped[bool] = mapped_column(Boolean, default=False)
    spend_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    input_params: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    snapshot_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    briefs: Mapped[list[ContentBrief]] = relationship(back_populates="content_brief_run")


class ContentBrief(TimestampMixin, Base):
    __tablename__ = "content_briefs"
    __table_args__ = (
        UniqueConstraint(
            "content_brief_run_id",
            "brief_key",
            name="uq_content_briefs_run_key",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    content_brief_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("content_brief_runs.id"), index=True
    )
    brief_key: Mapped[str] = mapped_column(String(255), index=True)
    brief_type: Mapped[str] = mapped_column(String(64), index=True)
    source_channel_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("acquisition_channel_plans.id"), index=True
    )
    specialty: Mapped[str | None] = mapped_column(String(120), index=True)
    geography: Mapped[str | None] = mapped_column(String(120), index=True)
    icp_label: Mapped[str | None] = mapped_column(String(120))
    priority: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text)
    outline_sections: Mapped[list[object]] = mapped_column(JSONB, default=list)
    recommended_cta: Mapped[str] = mapped_column(String(255))
    compliance_notes: Mapped[list[object]] = mapped_column(JSONB, default=list)
    source_references: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approval_status: Mapped[str] = mapped_column(
        String(64),
        default=ContentBriefApprovalStatus.PENDING_OPERATOR_REVIEW.value,
        index=True,
    )
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    publish_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    dry_run_only: Mapped[bool] = mapped_column(Boolean, default=True)
    content_brief_run: Mapped[ContentBriefRun] = relationship(back_populates="briefs")
