"""Phase 25 local-only dry-run smoke harness.

Runs a representative stored-record pipeline against deterministic synthetic
fixture data. It never calls live providers, never writes to the configured
application database from the CLI path, and never executes approved items.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Never

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import vyro_growth.models as _models  # noqa: F401
from vyro_growth.config import (
    Settings,
    any_live_provider_enabled,
    is_development_environment,
    live_provider_flags,
)
from vyro_growth.database import Base
from vyro_growth.domain import (
    ContactRoleCategory,
    ContentBriefType,
    LeadStage,
    MessageDirection,
    ReviewDecisionStatus,
    VoiceConsentChannel,
    VoiceConsentSource,
    WebsiteFactType,
    WebsiteMatchStatus,
)
from vyro_growth.models import (
    Activity,
    Contact,
    Lead,
    Meeting,
    Organization,
    OutreachMessage,
    OwnerApprovalPacket,
    SourceEvidence,
)
from vyro_growth.observability import sanitize_mapping
from vyro_growth.providers.personalization import StubPersonalizationProvider
from vyro_growth.providers.reply_classification import StubReplyClassifier
from vyro_growth.services.action_readiness import ActionReadinessService
from vyro_growth.services.approval_packets import ApprovalPacketService
from vyro_growth.services.booking_plan import BookingPlanService
from vyro_growth.services.channel_planning import ChannelPlanningService, ChannelPlanSeeds
from vyro_growth.services.content_brief import ContentBriefSeed, ContentBriefService
from vyro_growth.services.execution_planning import ExecutionPlanningService
from vyro_growth.services.growth_optimizer import GrowthOptimizerService
from vyro_growth.services.lead_scoring import LeadScoringService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.outreach_enrollment import OutreachEnrollmentService
from vyro_growth.services.personalization import PersonalizationService
from vyro_growth.services.reply_classification import ReplyClassificationService
from vyro_growth.services.review_queue import ReviewQueueService
from vyro_growth.services.voice_qualification import VoiceConsentInput, VoiceQualificationService

SMOKE_ACTOR = "smoke_dry_run"
SMOKE_SOURCE = "phase-25-demo"
SMOKE_CAMPAIGN_NAME = "phase-25-dry-run"
SMOKE_NPI = "0000000014"
SMOKE_ORG_NAME = "VYRO DEMO PRACTICE LLC"
SMOKE_CITY = "DEMOCITY"
SMOKE_STATE = "TX"
SMOKE_SPECIALTY = "Family Medicine"
SMOKE_WEBSITE = "https://demo.invalid/practice"
SMOKE_CONTACT_NAME = "Demo Operator"
SMOKE_CONTACT_TITLE = "Practice Manager"
SMOKE_CONTACT_EMAIL = "demo.operator@example.invalid"
SMOKE_INBOUND_BODY = "Please schedule a meeting to discuss billing operations."
SMOKE_VOICE_PHONE = "5550100100"
SMOKE_REVIEWER = "phase-25-demo"
SMOKE_DECISION_NOTES = "dry-run demo decision record only"
ALWAYS_BLOCKED_CODE = "execution_disabled_in_this_phase"


class SmokeRefusalCode(StrEnum):
    PRODUCTION_ENVIRONMENT = "production_environment"
    OUTBOUND_ENABLED = "outbound_enabled"
    LIVE_PROVIDERS_ENABLED = "live_providers_enabled"


class SmokeDryRunRefused(ValueError):
    def __init__(self, code: SmokeRefusalCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SmokeDryRunResult:
    generated_at: datetime
    environment: str
    local_only: bool
    isolated_demo_database: bool
    status: str
    executed: int
    live_action: bool
    outbound_attempted: bool
    live_call_attempted: bool
    recommendation_applied: bool
    spend_attempted: bool
    campaign_launched: bool
    pages_published: bool
    ads_launched: bool
    owner_approved: bool
    dry_run_only: bool
    no_execution: bool
    operator_halt_before: str
    operator_halt_after: str
    outbound_enabled: bool
    live_providers_enabled: bool
    live_providers: dict[str, bool]
    counts: dict[str, int]
    statuses: dict[str, str]
    blocker_codes: tuple[str, ...]
    readiness_statuses: dict[str, int]
    action_readiness: dict[str, object]
    steps: dict[str, dict[str, object]]


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_element: object, _compiler: object, **_kwargs: object) -> str:
    return "JSON"


@compiles(PGUUID, "sqlite")
def _compile_uuid_sqlite(_element: object, _compiler: object, **_kwargs: object) -> str:
    return "VARCHAR(36)"


@contextmanager
def isolated_demo_session() -> Iterator[Session]:
    """Create a throwaway in-memory demo database. Never uses DATABASE_URL."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def refuse_unsafe_smoke_run(settings: Settings, *, local_only: bool) -> None:
    """Fail closed for production/live workflows. Never starts the demo pipeline."""

    if settings.outbound_enabled:
        raise SmokeDryRunRefused(
            SmokeRefusalCode.OUTBOUND_ENABLED,
            refusal_message(SmokeRefusalCode.OUTBOUND_ENABLED),
        )
    if any_live_provider_enabled(settings):
        raise SmokeDryRunRefused(
            SmokeRefusalCode.LIVE_PROVIDERS_ENABLED,
            refusal_message(SmokeRefusalCode.LIVE_PROVIDERS_ENABLED),
        )
    if not is_development_environment(settings) and not local_only:
        raise SmokeDryRunRefused(
            SmokeRefusalCode.PRODUCTION_ENVIRONMENT,
            refusal_message(SmokeRefusalCode.PRODUCTION_ENVIRONMENT),
        )


def run_smoke_dry_run(
    db: Session,
    settings: Settings,
    *,
    local_only: bool = False,
    isolated_demo_database: bool = False,
) -> SmokeDryRunResult:
    """Seed synthetic demo records and exercise existing dry-run services."""

    refuse_unsafe_smoke_run(settings, local_only=local_only)
    generated_at = datetime.now(tz=UTC)
    halt_before = _ensure_demo_halt(db)
    organization, lead = _seed_demo_fixture(db)

    scoring = LeadScoringService().score_lead(db, lead.id)
    personalization = PersonalizationService(StubPersonalizationProvider()).personalize_lead(
        db, lead.id
    )
    outreach = OutreachEnrollmentService(settings=settings).plan_lead(
        db,
        lead.id,
        campaign_name=SMOKE_CAMPAIGN_NAME,
    )
    inbound = _seed_inbound_reply(db, lead)
    replies = ReplyClassificationService(StubReplyClassifier()).classify_message(db, inbound.id)
    booking = BookingPlanService(settings=settings).plan_lead(
        db,
        lead.id,
        operator_request=True,
        request_key=SMOKE_SOURCE,
    )
    voice = VoiceQualificationService(settings=settings).plan_lead(
        db,
        lead.id,
        operator_request=True,
        request_key=SMOKE_SOURCE,
        consent=VoiceConsentInput(
            source=VoiceConsentSource.OPERATOR_REQUEST,
            channel=VoiceConsentChannel.OPERATOR,
            consented_at=generated_at,
            permitted_phone=SMOKE_VOICE_PHONE,
            evidence_reference_id=SMOKE_SOURCE,
        ),
    )
    optimizer = GrowthOptimizerService().recommend(db, settings)
    channels = ChannelPlanningService().plan(
        db,
        seeds=ChannelPlanSeeds(
            specialty=SMOKE_SPECIALTY,
            geography=SMOKE_STATE,
            keywords=("billing operations",),
            partner_type="independent practice",
        ),
    )
    briefs = ContentBriefService().generate(
        db,
        settings,
        seeds=(
            ContentBriefSeed(
                brief_type=ContentBriefType.SPECIALTY_LANDING_PAGE,
                specialty=SMOKE_SPECIALTY,
                geography=SMOKE_STATE,
                icp_label="independent practice",
                topic="Independent practice billing operations",
            ),
        ),
    )
    review_queue = ReviewQueueService()
    pending = review_queue.list_queue(db, settings)
    review_decisions = []
    for item in pending.items:
        review_decisions.append(
            review_queue.record_decision(
                db,
                artifact_type=item.artifact_type,
                artifact_id=item.artifact_id,
                decision=ReviewDecisionStatus.APPROVED.value,
                reviewer=SMOKE_REVIEWER,
                source=SMOKE_SOURCE,
                reviewer_notes=SMOKE_DECISION_NOTES,
            )
        )
    execution = ExecutionPlanningService().generate(db, settings)
    packets = ApprovalPacketService().generate(db, settings)
    packet_decisions = []
    for packet in packets.packets:
        packet_decisions.append(
            ApprovalPacketService().record_decision(
                db,
                packet_id=packet.id,
                decision=ReviewDecisionStatus.APPROVED.value,
                reviewer=SMOKE_REVIEWER,
                source=SMOKE_SOURCE,
                reviewer_notes=SMOKE_DECISION_NOTES,
            )
        )
    readiness = ActionReadinessService().list_queue(db, settings)
    halt_after = read_operator_halt(db)
    if halt_after is not halt_before:
        raise RuntimeError("smoke-dry-run must not change operator halt status")

    owner_approved = any(
        bool(row.owner_approved)
        for row in db.scalars(select(OwnerApprovalPacket)).all()
    ) or any(item.owner_approved for item in packets.packets)
    live_flags = _live_side_effect_flags(db)
    blocker_codes = _unique_codes(
        tuple(code for item in readiness.candidates for code in item.blocker_codes)
        + (ALWAYS_BLOCKED_CODE,)
    )
    steps: dict[str, dict[str, object]] = {
        "scoring": {
            "lead_id": str(scoring.lead_id),
            "organization_id": str(scoring.organization_id),
            "band": scoring.scoring.band.value,
            "status": "completed",
        },
        "personalization": {
            "status": personalization.status.value,
            "readiness": (
                personalization.readiness_status.value
                if personalization.readiness_status is not None
                else "unknown"
            ),
            "outbound_attempted": personalization.outbound_attempted,
            "live_call_attempted": personalization.live_call_attempted,
        },
        "outreach": {
            "status": outreach.status.value,
            "planned": outreach.planned_count,
            "skipped": outreach.skipped_count,
            "blocked": outreach.blocked_count,
        },
        "replies": {
            "outcome": replies.outcome.value,
            "intent": replies.intent.value if replies.intent is not None else "unknown",
            "outbound_attempted": replies.outbound_attempted,
        },
        "booking": {
            "status": booking.status.value,
            "planned": booking.planned_count,
            "skipped": booking.skipped_count,
            "blocked": booking.blocked_count,
        },
        "voice": {
            "status": voice.status.value,
            "planned": voice.planned_count,
            "skipped": voice.skipped_count,
            "blocked": voice.blocked_count,
        },
        "optimizer": {
            "status": optimizer.status.value,
            "recommendations": optimizer.recommendation_count,
            "applied": optimizer.applied_count,
        },
        "channels": {
            "status": channels.status.value,
            "plans": channels.plan_count,
            "spend_attempted": channels.spend_attempted,
        },
        "content_briefs": {
            "status": briefs.status.value,
            "briefs": briefs.brief_count,
            "published": briefs.published,
        },
        "review_decisions": {
            "recorded": len(review_decisions),
            "executed": sum(1 for item in review_decisions if item.executed),
        },
        "execution_plans": {
            "status": execution.status.value,
            "plans": execution.plan_count,
            "executed": execution.executed_count,
            "readiness": sorted({item.readiness_status for item in execution.plans}),
        },
        "approval_packets": {
            "status": packets.status.value,
            "packets": packets.packet_count,
            "executed": packets.executed_count,
            "preflight": sorted({item.preflight_status for item in packets.packets}),
        },
        "packet_decisions": {
            "recorded": len(packet_decisions),
            "owner_approved": any(item.owner_approved for item in packet_decisions),
            "executed": sum(1 for item in packet_decisions if item.executed),
        },
        "action_readiness": {
            "candidates": readiness.candidate_count,
            "by_readiness_status": dict(readiness.by_readiness_status),
            "by_blocker_status": dict(readiness.by_blocker_status),
            "live_action": readiness.live_action,
            "executed": readiness.executed_count,
        },
    }
    result = SmokeDryRunResult(
        generated_at=generated_at,
        environment=settings.environment,
        local_only=local_only,
        isolated_demo_database=isolated_demo_database,
        status="completed",
        executed=0,
        live_action=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        owner_approved=False,
        dry_run_only=True,
        no_execution=True,
        operator_halt_before=halt_before.value,
        operator_halt_after=halt_after.value,
        outbound_enabled=settings.outbound_enabled,
        live_providers_enabled=any_live_provider_enabled(settings),
        live_providers=live_provider_flags(settings),
        counts={
            "organizations": 1,
            "leads": 1,
            "review_decisions": len(review_decisions),
            "execution_plans": execution.plan_count,
            "approval_packets": packets.packet_count,
            "packet_decisions": len(packet_decisions),
            "action_readiness_candidates": readiness.candidate_count,
            "executed": 0,
        },
        statuses={
            "scoring_band": scoring.scoring.band.value,
            "personalization": (
                personalization.readiness_status.value
                if personalization.readiness_status is not None
                else "unknown"
            ),
            "outreach": outreach.status.value,
            "booking": booking.status.value,
            "voice": voice.status.value,
            "execution": execution.status.value,
            "approval_packets": packets.status.value,
            "operator_halt": halt_after.value,
        },
        blocker_codes=blocker_codes,
        readiness_statuses=dict(readiness.by_readiness_status),
        action_readiness={
            "candidate_count": readiness.candidate_count,
            "by_readiness_status": dict(readiness.by_readiness_status),
            "by_blocker_status": dict(readiness.by_blocker_status),
            "blocker_codes": list(blocker_codes),
            "live_action": False,
            "executed": 0,
            "owner_approved": False,
            "explicit_live_owner_action_required": True,
        },
        steps=steps,
    )
    db.add(
        Activity(
            lead_id=lead.id,
            actor=SMOKE_ACTOR,
            action="smoke_dry_run_completed",
            details={
                "dry_run_only": True,
                "no_execution": True,
                "executed": 0,
                "live_action": False,
                "outbound_attempted": False,
                "organization_id": str(organization.id),
                "lead_id": str(lead.id),
            },
        )
    )
    db.commit()
    if live_flags["meetings_with_urls"] or live_flags["outbound_messages"] or owner_approved:
        raise RuntimeError("smoke-dry-run produced a live side effect")
    return result


def format_smoke_summary(result: SmokeDryRunResult, *, as_json: bool = False) -> str:
    payload = sanitize_mapping(_summary_payload(result))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    lines = [
        "Dry-run smoke:",
        f"status={payload['status']}",
        f"executed={payload['executed']}",
        f"live_action={_bool_text(payload['live_action'])}",
        f"outbound_attempted={_bool_text(payload['outbound_attempted'])}",
        f"dry_run_only={_bool_text(payload['dry_run_only'])}",
        f"no_execution={_bool_text(payload['no_execution'])}",
        f"owner_approved={_bool_text(payload['owner_approved'])}",
        f"isolated_demo_database={_bool_text(payload['isolated_demo_database'])}",
        f"operator_halt={payload['operator_halt_after']}",
        f"readiness={_format_mapping(payload['readiness_statuses'])}",
        f"blockers={','.join(payload['blocker_codes'])}",
        (
            "action_readiness="
            f"candidates={result.action_readiness['candidate_count']}"
            f" live_action={_bool_text(False)}"
            f" executed=0"
        ),
    ]
    return "\n".join(lines)


def _summary_payload(result: SmokeDryRunResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "environment": result.environment,
        "local_only": result.local_only,
        "isolated_demo_database": result.isolated_demo_database,
        "executed": result.executed,
        "live_action": result.live_action,
        "outbound_attempted": result.outbound_attempted,
        "live_call_attempted": result.live_call_attempted,
        "recommendation_applied": result.recommendation_applied,
        "spend_attempted": result.spend_attempted,
        "campaign_launched": result.campaign_launched,
        "pages_published": result.pages_published,
        "ads_launched": result.ads_launched,
        "owner_approved": result.owner_approved,
        "dry_run_only": result.dry_run_only,
        "no_execution": result.no_execution,
        "operator_halt_before": result.operator_halt_before,
        "operator_halt_after": result.operator_halt_after,
        "outbound_enabled": result.outbound_enabled,
        "live_providers_enabled": result.live_providers_enabled,
        "live_providers": dict(result.live_providers),
        "counts": dict(result.counts),
        "statuses": dict(result.statuses),
        "blocker_codes": list(result.blocker_codes),
        "readiness_statuses": dict(result.readiness_statuses),
        "action_readiness": dict(result.action_readiness),
        "steps": result.steps,
        "generated_at": result.generated_at.isoformat(),
    }


def _ensure_demo_halt(db: Session) -> HaltStatus:
    existing = read_operator_halt(db)
    if existing is not HaltStatus.UNAVAILABLE:
        return existing
    set_operator_halt(db, halted=True, reason="phase-25-demo-default")
    db.flush()
    return HaltStatus.HALTED


def _seed_demo_fixture(db: Session) -> tuple[Organization, Lead]:
    organization = db.scalar(select(Organization).where(Organization.npi == SMOKE_NPI))
    if organization is None:
        organization = Organization(
            name=SMOKE_ORG_NAME,
            npi=SMOKE_NPI,
            city=SMOKE_CITY,
            state=SMOKE_STATE,
            specialty=SMOKE_SPECIALTY,
            website=SMOKE_WEBSITE,
            website_match_status=WebsiteMatchStatus.VERIFIED.value,
        )
        db.add(organization)
        db.flush()
        _seed_public_facts(db, organization)
        db.add(
            Contact(
                organization_id=organization.id,
                full_name=SMOKE_CONTACT_NAME,
                title=SMOKE_CONTACT_TITLE,
                email=SMOKE_CONTACT_EMAIL,
                email_verified=False,
                role_category=ContactRoleCategory.PRACTICE_MANAGER.value,
                source_provider=SMOKE_SOURCE,
                verification_status="unverified",
                dedupe_key=f"demo:{SMOKE_NPI}",
            )
        )
        db.flush()
    lead = db.scalar(select(Lead).where(Lead.organization_id == organization.id))
    if lead is None:
        lead = Lead(
            organization_id=organization.id,
            stage=LeadStage.QUALIFIED.value,
            source=SMOKE_SOURCE,
        )
        db.add(lead)
        db.flush()
    return organization, lead


def _seed_public_facts(db: Session, organization: Organization) -> None:
    facts = (
        (
            "nppes_organization_record",
            "https://demo.invalid/nppes",
            SMOKE_ORG_NAME,
            {"business_record": {"status": "A"}, "fabricated": False},
        ),
        (
            WebsiteFactType.WEBSITE_MATCH.value,
            SMOKE_WEBSITE,
            WebsiteMatchStatus.VERIFIED.value,
            {"fabricated": False},
        ),
        (
            WebsiteFactType.OWNERSHIP_SIGNAL.value,
            f"{SMOKE_WEBSITE}/about",
            "independent",
            {"fabricated": False},
        ),
        (
            WebsiteFactType.BILLING_SIGNAL.value,
            f"{SMOKE_WEBSITE}/billing",
            "in-house_billing",
            {"fabricated": False},
        ),
        (
            WebsiteFactType.PRACTICE_SIZE_SIGNAL.value,
            f"{SMOKE_WEBSITE}/about",
            "single_location",
            {"fabricated": False},
        ),
    )
    for claim_type, source_url, extracted_value, metadata in facts:
        db.add(
            SourceEvidence(
                organization_id=organization.id,
                source_url=source_url,
                claim_type=claim_type,
                extracted_value=extracted_value,
                confidence=0.9,
                metadata_json=metadata,
            )
        )


def _seed_inbound_reply(db: Session, lead: Lead) -> OutreachMessage:
    existing = db.scalar(
        select(OutreachMessage).where(
            OutreachMessage.lead_id == lead.id,
            OutreachMessage.direction == MessageDirection.INBOUND.value,
            OutreachMessage.provider_message_id == SMOKE_SOURCE,
        )
    )
    if existing is not None:
        return existing
    contact = db.scalar(select(Contact).where(Contact.organization_id == lead.organization_id))
    message = OutreachMessage(
        lead_id=lead.id,
        contact_id=contact.id if contact is not None else None,
        channel="email",
        direction=MessageDirection.INBOUND.value,
        subject="Re: billing operations",
        body=SMOKE_INBOUND_BODY,
        provider_message_id=SMOKE_SOURCE,
    )
    db.add(message)
    db.flush()
    return message


def _live_side_effect_flags(db: Session) -> dict[str, bool]:
    outbound_messages = any(
        row.direction == MessageDirection.OUTBOUND.value
        for row in db.scalars(select(OutreachMessage)).all()
    )
    meetings_with_urls = any(
        bool(row.meeting_url) or bool(row.provider_event_id)
        for row in db.scalars(select(Meeting)).all()
    )
    return {
        "outbound_messages": outbound_messages,
        "meetings_with_urls": meetings_with_urls,
    }


def _unique_codes(codes: tuple[str, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for code in codes:
        if code not in seen:
            seen.append(code)
    return tuple(seen)


def _bool_text(value: object) -> str:
    return "true" if value is True else "false"


def _format_mapping(value: object) -> str:
    if not isinstance(value, Mapping):
        return str(value)
    if not value:
        return "none"
    return ",".join(f"{key}:{item}" for key, item in sorted(value.items()))


def _unreachable(value: SmokeRefusalCode) -> Never:
    raise RuntimeError(f"unhandled smoke refusal: {value!r}")


def refusal_message(code: SmokeRefusalCode) -> str:
    match code:
        case SmokeRefusalCode.PRODUCTION_ENVIRONMENT:
            return (
                "smoke-dry-run refused: production/live environment requires "
                "--local-only or --dev-demo"
            )
        case SmokeRefusalCode.OUTBOUND_ENABLED:
            return (
                "smoke-dry-run refused: OUTBOUND_ENABLED is true; "
                "this command is local dry-run only"
            )
        case SmokeRefusalCode.LIVE_PROVIDERS_ENABLED:
            return (
                "smoke-dry-run refused: a live provider flag is enabled; "
                "this command is local dry-run only"
            )
        case _:
            return _unreachable(code)
