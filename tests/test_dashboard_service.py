from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.outreach import (
    sample_contact,
    sample_draft,
    sample_lead,
    sample_organization,
    sample_score,
)
from vyro_growth.config import Settings
from vyro_growth.domain import (
    BookingPlanRunStatus,
    BookingPlanStatus,
    DiscoveryRunStatus,
    EnrichmentRunStatus,
    EnrollmentStatus,
    LeadStage,
    OutreachPlanRunStatus,
    PersonalizationReadiness,
    ReplyClassificationOutcome,
    ReplyIntent,
    VoicePlanStatus,
    VoiceQualificationRunStatus,
    WebsiteMatchStatus,
)
from vyro_growth.models import (
    Activity,
    BookingPlan,
    BookingPlanRun,
    Campaign,
    CampaignEnrollment,
    DiscoveryRun,
    EnrichmentRun,
    Meeting,
    OutreachMessage,
    OutreachPlanRun,
    ReplyClassification,
    Suppression,
    VoiceQualificationPlan,
    VoiceQualificationRun,
)
from vyro_growth.providers.decision_makers import DECISION_MAKER_SOURCE
from vyro_growth.providers.personalization import PERSONALIZATION_SOURCE
from vyro_growth.providers.website import WEBSITE_ENRICHMENT_SOURCE
from vyro_growth.services.dashboard import DashboardAnalyticsService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

PHI_SNIPPET = "The patient has a diagnosis of diabetes."
PROSPECT_EMAIL = "jordan.blake@austinfamily.example"


def _settings() -> Settings:
    return Settings()


def test_empty_database_summary_is_zeroed_and_safe(db_session: Session) -> None:
    summary = DashboardAnalyticsService().summarize(db_session, _settings())

    assert summary.read_only is True
    assert summary.discovery.organizations == 0
    assert summary.discovery.leads == 0
    assert summary.website_enrichment.enrichment_runs == 0
    assert summary.decision_maker_enrichment.contacts == 0
    assert summary.scoring.scores_total == 0
    assert summary.scoring.by_band["hot"] == 0
    assert summary.personalization.drafts == 0
    assert summary.outreach_plans.enrollments == 0
    assert summary.reply_classifications.classifications == 0
    assert summary.booking_plans.plans == 0
    assert summary.voice_qualification_plans.plans == 0
    assert summary.suppressions.records == 0
    assert summary.safety.outbound_enabled is False
    assert summary.safety.operator_halt_status == HaltStatus.UNAVAILABLE.value
    assert summary.safety.openai_personalization_enabled is False
    assert summary.safety.openai_reply_classification_enabled is False
    assert summary.safety.smartlead_live_enabled is False
    assert summary.safety.google_calendar_live_enabled is False
    assert summary.safety.voice_live_enabled is False
    assert summary.safety.decision_maker_live_enabled is False
    assert summary.safety.email_verification_live_enabled is False
    assert summary.safety.planned_count == 0
    assert summary.safety.live_calendar_events == 0
    assert summary.safety.live_meet_links == 0
    assert summary.safety.live_phone_calls == 0
    assert summary.safety.phi_fields_present is False
    assert {run.phase for run in summary.latest_runs} == {
        "discovery",
        "website_enrichment",
        "decision_maker_enrichment",
        "scoring",
        "personalization",
        "outreach_plans",
        "reply_classifications",
        "booking_plans",
        "voice_qualification_plans",
    }
    assert all(run.status == "not_started" for run in summary.latest_runs)


def test_populated_summary_counts_and_latest_runs(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="incident")

    summary = DashboardAnalyticsService().summarize(db_session, _settings())

    assert summary.discovery.organizations == 1
    assert summary.discovery.leads == 1
    assert summary.discovery.leads_by_stage[LeadStage.READY_FOR_OUTREACH.value] == 1
    assert summary.discovery.discovery_runs == 1
    assert summary.discovery.records_upserted == 1
    assert summary.website_enrichment.by_match_status[WebsiteMatchStatus.VERIFIED.value] == 1
    assert summary.website_enrichment.enrichment_runs == 1
    assert summary.decision_maker_enrichment.contacts == 1
    assert summary.decision_maker_enrichment.enrichment_runs == 1
    assert summary.scoring.latest_scores == 1
    assert summary.scoring.by_band["hot"] == 1
    assert summary.personalization.drafts == 1
    assert summary.personalization.by_readiness[PersonalizationReadiness.READY.value] == 1
    assert summary.outreach_plans.planned_count == 1
    assert summary.outreach_plans.skipped_count == 1
    assert summary.reply_classifications.classifications == 1
    assert summary.reply_classifications.by_intent[ReplyIntent.MEETING_REQUEST.value] == 1
    assert summary.booking_plans.planned_count == 1
    assert summary.booking_plans.events_created == 0
    assert summary.voice_qualification_plans.planned_count == 1
    assert summary.voice_qualification_plans.calls_placed == 0
    assert summary.suppressions.records == 1
    assert summary.safety.operator_halt_status == HaltStatus.HALTED.value
    assert summary.safety.operator_halt_reason == "incident"
    assert summary.safety.planned_count == 3
    assert summary.safety.skipped_count == 1
    assert summary.safety.suppression_records == 1
    assert all(run.status != "not_started" for run in summary.latest_runs)


def test_dashboard_is_read_only_and_preserves_halt(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _pipeline_counts(db_session)

    DashboardAnalyticsService().summarize(db_session, Settings(outbound_enabled=False))

    assert _pipeline_counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    control_reason = db_session.scalar(select(func.count()).select_from(Activity))
    assert control_reason == before["activities"]


def test_dashboard_does_not_expose_phi_or_prospect_facts(db_session: Session) -> None:
    _seed_pipeline(db_session)
    payload = json.dumps(
        DashboardAnalyticsService().summarize(db_session, _settings()).__dict__,
        default=str,
    )

    assert PHI_SNIPPET not in payload
    assert PROSPECT_EMAIL not in payload
    assert "diabetes" not in payload.lower()
    assert "practice_summary" not in payload
    assert "opening_line" not in payload
    assert "permitted_phone" not in payload
    assert "evidence_snippet" not in payload


def test_default_safety_flags_stay_disabled(db_session: Session) -> None:
    summary = DashboardAnalyticsService().summarize(db_session, Settings())

    assert summary.safety.outbound_enabled is False
    assert summary.safety.outbound_halted_settings is False
    assert summary.safety.openai_personalization_enabled is False
    assert summary.safety.smartlead_live_enabled is False
    assert summary.safety.google_calendar_live_enabled is False
    assert summary.safety.voice_live_enabled is False
    assert summary.safety.decision_maker_live_enabled is False
    assert summary.safety.email_verification_live_enabled is False
    assert summary.safety.live_send_attempted_enrollments == 0
    assert summary.safety.outbound_attempted_classifications == 0
    assert summary.safety.booking_events_created == 0
    assert summary.safety.booking_meet_links_created == 0
    assert summary.safety.voice_calls_placed == 0


def _pipeline_counts(db: Session) -> dict[str, int]:
    return {
        "activities": int(db.scalar(select(func.count()).select_from(Activity)) or 0),
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
        "booking_plans": int(db.scalar(select(func.count()).select_from(BookingPlan)) or 0),
        "voice_plans": int(
            db.scalar(select(func.count()).select_from(VoiceQualificationPlan)) or 0
        ),
        "suppressions": int(db.scalar(select(func.count()).select_from(Suppression)) or 0),
    }


def _seed_pipeline(db: Session) -> None:
    organization = sample_organization(db)
    lead = sample_lead(db, organization)
    contact = sample_contact(db, organization, email=PROSPECT_EMAIL)
    sample_score(db, lead, band="hot")
    sample_draft(
        db,
        lead,
        organization,
        practice_summary=f"Clinic summary must not leak. {PHI_SNIPPET}",
        opening_line="Jordan, this opening line is prospect-specific.",
        readiness_status=PersonalizationReadiness.READY.value,
    )
    now = datetime.now(tz=UTC)
    db.add(
        DiscoveryRun(
            source="nppes",
            status=DiscoveryRunStatus.COMPLETED.value,
            query_params={"state": "TX", "city": "Austin"},
            records_fetched=1,
            records_upserted=1,
            records_skipped=0,
            started_at=now,
            finished_at=now,
        )
    )
    db.add(
        EnrichmentRun(
            organization_id=organization.id,
            source=WEBSITE_ENRICHMENT_SOURCE,
            status=EnrichmentRunStatus.COMPLETED.value,
            match_status=WebsiteMatchStatus.VERIFIED.value,
            official_website=organization.website,
            facts_extracted=2,
            started_at=now,
            finished_at=now,
        )
    )
    db.add(
        EnrichmentRun(
            organization_id=organization.id,
            source=DECISION_MAKER_SOURCE,
            status=EnrichmentRunStatus.COMPLETED.value,
            contacts_upserted=1,
            started_at=now,
            finished_at=now,
        )
    )
    db.add(
        EnrichmentRun(
            organization_id=organization.id,
            source=PERSONALIZATION_SOURCE,
            status=EnrichmentRunStatus.COMPLETED.value,
            started_at=now,
            finished_at=now,
        )
    )
    campaign = Campaign(name=f"phase-10-{uuid4().hex[:8]}", active=False, dry_run_only=True)
    db.add(campaign)
    db.flush()
    outreach_run = OutreachPlanRun(
        campaign_id=campaign.id,
        status=OutreachPlanRunStatus.COMPLETED.value,
        planned_count=1,
        skipped_count=1,
        started_at=now,
        finished_at=now,
    )
    db.add(outreach_run)
    db.flush()
    db.add(
        CampaignEnrollment(
            campaign_id=campaign.id,
            outreach_plan_run_id=outreach_run.id,
            lead_id=lead.id,
            contact_id=contact.id,
            organization_id=organization.id,
            status=EnrollmentStatus.PLANNED.value,
            idempotency_key=f"plan-{uuid4()}",
            dry_run=True,
            live_send_attempted=False,
        )
    )
    db.add(
        CampaignEnrollment(
            campaign_id=campaign.id,
            outreach_plan_run_id=outreach_run.id,
            lead_id=lead.id,
            contact_id=contact.id,
            organization_id=organization.id,
            status=EnrollmentStatus.SKIPPED.value,
            skip_reason="missing_personalization",
            idempotency_key=f"skip-{uuid4()}",
            dry_run=True,
            live_send_attempted=False,
        )
    )
    message = OutreachMessage(
        lead_id=lead.id,
        contact_id=contact.id,
        channel="email",
        direction="inbound",
        subject="Re: billing",
        body=f"Please call me. {PHI_SNIPPET}",
        provider_message_id=f"msg-{uuid4()}",
    )
    db.add(message)
    db.flush()
    classification = ReplyClassification(
        lead_id=lead.id,
        outreach_message_id=message.id,
        provider_message_id=message.provider_message_id,
        sender_email=PROSPECT_EMAIL,
        intent=ReplyIntent.MEETING_REQUEST.value,
        outcome=ReplyClassificationOutcome.CLASSIFIED.value,
        confidence=0.8,
        provider_name="stub",
        schema_version="reply-classification-v1",
        content_hash=f"hash-{uuid4().hex}",
        outbound_attempted=False,
        live_call_attempted=False,
        lead_stage_before=LeadStage.CONTACTED.value,
        lead_stage_after=LeadStage.INTERESTED.value,
    )
    db.add(classification)
    db.flush()
    booking_run = BookingPlanRun(
        status=BookingPlanRunStatus.COMPLETED.value,
        planned_count=1,
        started_at=now,
        finished_at=now,
    )
    db.add(booking_run)
    db.flush()
    db.add(
        BookingPlan(
            booking_plan_run_id=booking_run.id,
            lead_id=lead.id,
            contact_id=contact.id,
            organization_id=organization.id,
            reply_classification_id=classification.id,
            request_source="meeting_request_reply",
            request_key=str(classification.id),
            status=BookingPlanStatus.PLANNED.value,
            idempotency_key=f"booking-{uuid4()}",
            dry_run=True,
            event_created=False,
            meet_link_created=False,
            live_call_attempted=False,
            lead_stage_before=LeadStage.INTERESTED.value,
            lead_stage_after=LeadStage.MEETING_READY.value,
        )
    )
    voice_run = VoiceQualificationRun(
        status=VoiceQualificationRunStatus.COMPLETED.value,
        planned_count=1,
        started_at=now,
        finished_at=now,
    )
    db.add(voice_run)
    db.flush()
    db.add(
        VoiceQualificationPlan(
            voice_qualification_run_id=voice_run.id,
            lead_id=lead.id,
            contact_id=contact.id,
            organization_id=organization.id,
            request_source="operator_request",
            request_key="ops-1",
            status=VoicePlanStatus.PLANNED.value,
            idempotency_key=f"voice-{uuid4()}",
            dry_run=True,
            live_call_attempted=False,
            call_placed=False,
            facts_json={"note": PHI_SNIPPET},
            permitted_phone="5551112222",
        )
    )
    db.add(
        Suppression(
            email="optout@example.com",
            reason="unsubscribe",
            permanent=True,
        )
    )
    db.add(
        Activity(
            lead_id=lead.id,
            actor="test",
            action="seeded",
            details={"note": "pre-existing audit row"},
        )
    )
    db.flush()
