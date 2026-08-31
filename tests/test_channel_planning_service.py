from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.outreach import sample_lead, sample_organization, sample_score
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from vyro_growth.domain import (
    AcquisitionChannel,
    ChannelPlanType,
    LeadStage,
    RecommendationApprovalStatus,
    ReplyClassificationOutcome,
    ReplyIntent,
    WebsiteMatchStatus,
)
from vyro_growth.models import (
    Activity,
    Campaign,
    CampaignEnrollment,
    ChannelPlan,
    ChannelPlanRun,
    Lead,
    Meeting,
    OutreachMessage,
    ReplyClassification,
    Suppression,
)
from vyro_growth.services.channel_planning import ChannelPlanningService, ChannelPlanSeeds
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt


def test_empty_state_is_safe_and_does_not_invent_plans(db_session: Session) -> None:
    result = ChannelPlanningService().plan(db_session)

    assert result.status.value == "completed"
    assert result.dry_run_only is True
    assert result.no_spend is True
    assert result.spend_attempted is False
    assert result.campaign_launched is False
    assert result.pages_published is False
    assert result.outbound_attempted is False
    assert result.live_call_attempted is False
    assert result.reused_existing is False
    assert result.plan_count == 0
    assert result.plans == ()
    assert result.operator_halt_before == HaltStatus.UNAVAILABLE.value
    assert result.operator_halt_after == HaltStatus.UNAVAILABLE.value


def test_seeded_empty_state_uses_operator_seeds_only(db_session: Session) -> None:
    result = ChannelPlanningService().plan(
        db_session,
        seeds=ChannelPlanSeeds(
            specialty="Family Medicine",
            geography="TX",
            keywords=("medical billing",),
            partner_type="specialty association",
        ),
    )

    channels = {item.channel for item in result.plans}
    types = {item.plan_type for item in result.plans}
    assert AcquisitionChannel.GOOGLE_SEARCH_ADS.value in channels
    assert AcquisitionChannel.SEO_CONTENT.value in channels
    assert AcquisitionChannel.REFERRAL_PARTNER.value in channels
    assert AcquisitionChannel.SPECIALTY_GEOGRAPHY.value in channels
    assert ChannelPlanType.KEYWORD_GROUP.value in types
    assert ChannelPlanType.LANDING_PAGE_TOPIC.value in types
    assert ChannelPlanType.PARTNER_CAMPAIGN.value in types
    assert ChannelPlanType.POSITIONING.value in types
    assert result.plan_count == len(result.plans)
    for item in result.plans:
        assert item.approval_status == RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value
        assert item.dry_run_only is True
        assert item.no_spend is True
        assert item.launched is False
        assert item.spend_attempted is False
        assert item.campaign_launched is False
        assert item.pages_published is False
        assert item.source_metrics or item.seed_input_refs
        assert item.generated_at is not None


def test_populated_aggregates_cover_channel_types(db_session: Session) -> None:
    _seed_channel_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    result = ChannelPlanningService().plan(db_session)

    channels = {item.channel for item in result.plans}
    keys = {item.plan_key for item in result.plans}
    assert AcquisitionChannel.GOOGLE_SEARCH_ADS.value in channels
    assert AcquisitionChannel.SEO_CONTENT.value in channels
    assert AcquisitionChannel.REFERRAL_PARTNER.value in channels
    assert AcquisitionChannel.SPECIALTY_GEOGRAPHY.value in channels
    assert any(key.startswith("google_search_ads:") for key in keys)
    assert any(key.startswith("seo_content:") for key in keys)
    assert "referral_partner:stored_referral_intents" in keys
    assert all(
        item.approval_status == RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value
        for item in result.plans
    )
    assert all(item.launched is False for item in result.plans)
    stored = db_session.scalars(select(ChannelPlan)).all()
    assert stored
    assert all(row.launched is False for row in stored)
    assert all(row.spend_attempted is False for row in stored)
    assert all(row.pages_published is False for row in stored)


def test_identical_snapshot_is_idempotent(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    service = ChannelPlanningService()

    first = service.plan(db_session)
    second = service.plan(db_session)

    assert second.reused_existing is True
    assert second.channel_plan_run_id == first.channel_plan_run_id
    assert second.snapshot_fingerprint == first.snapshot_fingerprint
    assert db_session.scalar(select(func.count()).select_from(ChannelPlanRun)) == 1
    assert db_session.scalar(select(func.count()).select_from(ChannelPlan)) == first.plan_count
    activities = db_session.scalars(
        select(Activity).where(Activity.action == "channel_plans_generated")
    ).all()
    assert len(activities) == 1


def test_changed_metrics_or_seeds_create_a_new_run(db_session: Session) -> None:
    _seed_pipeline(db_session)
    service = ChannelPlanningService()
    first = service.plan(db_session)

    sample_organization(
        db_session,
        name="UNVERIFIED CLINIC",
        npi="1999999999",
        website=None,
        website_match_status=WebsiteMatchStatus.NO_MATCH.value,
        specialty="Dermatology",
        state="CA",
        city="SAN DIEGO",
    )
    second = service.plan(db_session)
    third = service.plan(
        db_session,
        seeds=ChannelPlanSeeds(keywords=("revenue leakage analysis",)),
    )

    assert second.reused_existing is False
    assert second.channel_plan_run_id != first.channel_plan_run_id
    assert third.reused_existing is False
    assert third.channel_plan_run_id != second.channel_plan_run_id
    assert db_session.scalar(select(func.count()).select_from(ChannelPlanRun)) == 3


def test_channel_planning_does_not_launch_or_touch_outbound(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _side_effect_counts(db_session)
    before_stage = db_session.scalar(select(Lead.stage))

    ChannelPlanningService().plan(db_session)

    after = _side_effect_counts(db_session)
    assert after["meetings"] == before["meetings"]
    assert after["enrollments"] == before["enrollments"]
    assert after["messages"] == before["messages"]
    assert after["campaigns"] == before["campaigns"]
    assert after["suppressions"] == before["suppressions"]
    assert db_session.scalar(select(Lead.stage)) == before_stage
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    run = db_session.scalar(select(ChannelPlanRun))
    assert run is not None
    assert run.spend_attempted is False
    assert run.campaign_launched is False
    assert run.pages_published is False
    assert run.outbound_attempted is False
    assert run.dry_run_only is True
    assert run.no_spend is True


def test_channel_planning_does_not_expose_phi_or_prospect_identifiers(
    db_session: Session,
) -> None:
    _seed_pipeline(db_session)
    result = ChannelPlanningService().plan(
        db_session,
        seeds=ChannelPlanSeeds(
            specialty="Family Medicine",
            keywords=(f"{PROSPECT_EMAIL} medical billing",),
            partner_type=PHI_SNIPPET,
        ),
    )
    payload = json.dumps(result.__dict__, default=str)
    stored = json.dumps(
        [
            {
                "title": row.title,
                "summary": row.summary,
                "metrics": row.source_metrics_json,
                "seeds": row.seed_input_refs_json,
                "snapshot": row.plan_run.snapshot_json,
            }
            for row in db_session.scalars(select(ChannelPlan)).all()
        ],
        default=str,
    )

    for text in (payload, stored):
        assert PHI_SNIPPET not in text
        assert PROSPECT_EMAIL not in text
        assert "diabetes" not in text.lower()
        assert "jordan.blake" not in text.lower()
        assert "practice_summary" not in text
        assert "opening_line" not in text
        assert "permitted_phone" not in text
        assert "evidence_snippet" not in text
        assert "5551112222" not in text


def test_unsafe_seeds_are_dropped_not_invented(db_session: Session) -> None:
    result = ChannelPlanningService().plan(
        db_session,
        seeds=ChannelPlanSeeds(
            specialty="the patient has a diagnosis of diabetes",
            keywords=("jordan.blake@austinfamily.example",),
            partner_type="sk-testsecret12345",
        ),
    )

    assert result.plan_count == 0
    assert all("diabetes" not in item.title.lower() for item in result.plans)
    assert all(PROSPECT_EMAIL not in item.summary for item in result.plans)


def test_latest_returns_none_before_a_run(db_session: Session) -> None:
    assert ChannelPlanningService().latest(db_session) is None


def test_missing_specialty_stays_missing(db_session: Session) -> None:
    org = sample_organization(
        db_session,
        name="STATE ONLY PRACTICE",
        npi="1888888888",
        specialty=None,
        state="FL",
        city="MIAMI",
        website=None,
        website_match_status=None,
    )
    sample_lead(db_session, org, stage=LeadStage.DISCOVERED)

    result = ChannelPlanningService().plan(db_session)
    ads = [item for item in result.plans if item.channel == "google_search_ads"]
    assert ads
    assert all(item.target_specialty is None for item in ads)
    assert all(item.target_geography == "FL" for item in ads)


def _side_effect_counts(db: Session) -> dict[str, int]:
    return {
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
        "campaigns": int(db.scalar(select(func.count()).select_from(Campaign)) or 0),
        "suppressions": int(db.scalar(select(func.count()).select_from(Suppression)) or 0),
    }


def _seed_channel_pipeline(db: Session) -> None:
    _seed_pipeline(db)
    austin = db.scalars(select(Lead)).first()
    assert austin is not None
    austin.stage = LeadStage.INTERESTED.value
    sample_score(db, austin, total=40, band="low")

    other_family = sample_organization(
        db,
        name="SECOND FAMILY PRACTICE",
        npi="1222222222",
        specialty="Family Medicine",
        state="TX",
        city="DALLAS",
        website=None,
        website_match_status=WebsiteMatchStatus.AMBIGUOUS.value,
    )
    family_lead = sample_lead(db, other_family, stage=LeadStage.MEETING_READY)
    sample_score(db, family_lead, total=35, band="research")

    weak_org = sample_organization(
        db,
        name="COASTAL DERM",
        npi="1333333333",
        specialty="Dermatology",
        state="CA",
        city="SAN DIEGO",
        website=None,
        website_match_status=WebsiteMatchStatus.NO_MATCH.value,
    )
    weak_one = sample_lead(db, weak_org, stage=LeadStage.DISCOVERED)
    weak_two = sample_lead(db, weak_org, stage=LeadStage.DISCOVERED)
    sample_score(db, weak_one, total=20, band="low")
    sample_score(db, weak_two, total=22, band="disqualified")

    db.add(
        ReplyClassification(
            lead_id=family_lead.id,
            intent=ReplyIntent.REFERRAL.value,
            outcome=ReplyClassificationOutcome.CLASSIFIED.value,
            confidence=0.8,
            provider_name="stub",
            schema_version="reply-v1",
            content_hash=f"referral-{uuid4().hex}",
            lead_stage_before=LeadStage.REPLIED.value,
            lead_stage_after=LeadStage.REPLIED.value,
            created_at=datetime.now(tz=UTC),
        )
    )
    db.flush()
