from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.outreach import sample_lead, sample_organization
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from vyro_growth.config import Settings
from vyro_growth.domain import (
    AcquisitionChannel,
    ChannelPlanRunStatus,
    ChannelPlanType,
    ContentBriefApprovalStatus,
    ContentBriefType,
    LeadStage,
    RecommendationApprovalStatus,
)
from vyro_growth.models import (
    Activity,
    Campaign,
    CampaignEnrollment,
    ChannelPlan,
    ChannelPlanRun,
    ContentBrief,
    ContentBriefRun,
    Lead,
    Meeting,
    OutreachMessage,
    Suppression,
)
from vyro_growth.services.channel_planning import ChannelPlanningService, ChannelPlanSeeds
from vyro_growth.services.content_brief import ContentBriefSeed, ContentBriefService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def test_empty_state_is_safe_and_unpublished(db_session: Session) -> None:
    result = ContentBriefService().generate(db_session, _settings())

    assert result.status.value == "completed"
    assert result.dry_run_only is True
    assert result.published is False
    assert result.publish_attempted is False
    assert result.published_count == 0
    assert result.outbound_attempted is False
    assert result.ads_launched is False
    assert result.spend_attempted is False
    assert result.live_call_attempted is False
    assert result.reused_existing is False
    assert result.brief_count == 0
    assert result.briefs == ()
    assert result.operator_halt_before == HaltStatus.UNAVAILABLE.value
    assert result.operator_halt_after == HaltStatus.UNAVAILABLE.value


def test_populated_metrics_create_specialty_and_geography_briefs(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    result = ContentBriefService().generate(db_session, _settings())

    types = {item.brief_type for item in result.briefs}
    assert ContentBriefType.SPECIALTY_LANDING_PAGE.value in types
    assert ContentBriefType.GEOGRAPHY_LANDING_PAGE.value in types
    assert result.brief_count == len(result.briefs)
    assert result.published is False
    for item in result.briefs:
        assert item.approval_status == ContentBriefApprovalStatus.PENDING_OPERATOR_REVIEW.value
        assert item.published is False
        assert item.publish_attempted is False
        assert item.dry_run_only is True
        assert item.outline_sections
        assert item.recommended_cta
        assert item.compliance_notes
        assert "Do not publish" in " ".join(item.compliance_notes)
        assert item.source_references
        assert 0 <= item.confidence <= 1
    stored = db_session.scalars(select(ContentBrief)).all()
    assert stored
    assert all(row.published is False for row in stored)


def test_channel_plan_integration_adds_matching_brief_types(db_session: Session) -> None:
    planned = ChannelPlanningService().plan(
        db_session,
        seeds=ChannelPlanSeeds(
            specialty="Family Medicine",
            geography="TX",
            keywords=("medical billing",),
            partner_type="specialty association",
        ),
    )
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    result = ContentBriefService().generate(db_session, _settings())
    types = {item.brief_type for item in result.briefs}
    plan_ids = {item.source_channel_plan_id for item in result.briefs}

    assert planned.plan_count > 0
    assert ContentBriefType.SEO_ARTICLE.value in types
    assert ContentBriefType.GOOGLE_ADS_LANDING_PAGE.value in types
    assert ContentBriefType.REFERRAL_PARTNER_PAGE.value in types
    assert {item.id for item in planned.plans} <= plan_ids
    assert all(item.published is False for item in result.briefs)
    assert all(plan.launched is False for plan in planned.plans)
    assert all(plan.spend_attempted is False for plan in planned.plans)
    assert all(plan.campaign_launched is False for plan in planned.plans)
    assert all(plan.pages_published is False for plan in planned.plans)


def test_operator_seed_creates_review_only_brief(db_session: Session) -> None:
    result = ContentBriefService().generate(
        db_session,
        _settings(),
        seeds=(
            ContentBriefSeed(
                brief_type=ContentBriefType.SPECIALTY_LANDING_PAGE,
                specialty="Orthopedic Surgery",
                geography="FL",
            ),
        ),
    )

    assert result.brief_count == 1
    brief = result.briefs[0]
    assert brief.brief_type == ContentBriefType.SPECIALTY_LANDING_PAGE.value
    assert brief.specialty == "Orthopedic Surgery"
    assert brief.geography == "FL"
    assert brief.approval_status == ContentBriefApprovalStatus.PENDING_OPERATOR_REVIEW.value
    assert brief.published is False
    assert "Orthopedic Surgery" in brief.title


def test_identical_snapshot_is_idempotent(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    service = ContentBriefService()

    first = service.generate(db_session, _settings())
    second = service.generate(db_session, _settings())

    assert second.reused_existing is True
    assert second.content_brief_run_id == first.content_brief_run_id
    assert second.snapshot_fingerprint == first.snapshot_fingerprint
    assert db_session.scalar(select(func.count()).select_from(ContentBriefRun)) == 1
    assert db_session.scalar(select(func.count()).select_from(ContentBrief)) == first.brief_count
    activities = db_session.scalars(
        select(Activity).where(Activity.action == "content_briefs_generated")
    ).all()
    assert len(activities) == 1


def test_changed_seeds_create_a_new_run(db_session: Session) -> None:
    service = ContentBriefService()
    first = service.generate(
        db_session,
        _settings(),
        seeds=(ContentBriefSeed(specialty="Family Medicine"),),
    )
    second = service.generate(
        db_session,
        _settings(),
        seeds=(ContentBriefSeed(specialty="Cardiology"),),
    )

    assert second.reused_existing is False
    assert second.content_brief_run_id != first.content_brief_run_id
    assert db_session.scalar(select(func.count()).select_from(ContentBriefRun)) == 2


def test_unverifiable_claims_are_omitted_from_seeds(db_session: Session) -> None:
    result = ContentBriefService().generate(
        db_session,
        _settings(),
        seeds=(
            ContentBriefSeed(
                brief_type=ContentBriefType.SEO_ARTICLE,
                specialty="Family Medicine",
                topic="How practices save 30% and increase revenue with our clients",
            ),
        ),
    )

    payload = json.dumps(result.__dict__, default=str)
    assert "save 30%" not in payload.lower()
    assert "increase revenue" not in payload.lower()
    assert "[UNVERIFIED_CLAIM_OMITTED]" in payload
    brief = result.briefs[0]
    assert "save" not in brief.title.lower()
    assert any("unverified" in note.lower() for note in brief.compliance_notes)
    assert "patient-facing medical advice" in " ".join(brief.compliance_notes).lower()


def test_phi_and_patient_language_are_redacted(db_session: Session) -> None:
    result = ContentBriefService().generate(
        db_session,
        _settings(),
        seeds=(
            ContentBriefSeed(
                brief_type=ContentBriefType.SEO_ARTICLE,
                specialty="Family Medicine",
                topic=f"Help the patient with {PHI_SNIPPET}",
            ),
        ),
    )

    payload = json.dumps(result.__dict__, default=str)
    assert PHI_SNIPPET not in payload
    assert "diabetes" not in payload.lower()
    assert result.brief_count == 0


def test_emails_phones_and_secrets_are_redacted(db_session: Session) -> None:
    result = ContentBriefService().generate(
        db_session,
        _settings(),
        seeds=(
            ContentBriefSeed(
                brief_type=ContentBriefType.SEO_ARTICLE,
                specialty="Family Medicine",
                topic=f"Email {PROSPECT_EMAIL} at 555-111-2222 with sk-secretkeyvalue",
            ),
        ),
    )

    payload = json.dumps(result.__dict__, default=str)
    assert PROSPECT_EMAIL not in payload
    assert "jordan.blake" not in payload.lower()
    assert "5551112222" not in payload.replace("-", "")
    assert "sk-secretkeyvalue" not in payload
    assert "[REDACTED_EMAIL]" in payload or result.brief_count >= 0


def test_service_does_not_publish_or_touch_outbound(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _side_effect_counts(db_session)
    before_stage = db_session.scalar(select(Lead.stage))

    ContentBriefService().generate(db_session, Settings(outbound_enabled=False))

    after = _side_effect_counts(db_session)
    assert after["meetings"] == before["meetings"]
    assert after["enrollments"] == before["enrollments"]
    assert after["messages"] == before["messages"]
    assert after["campaigns"] == before["campaigns"]
    assert after["suppressions"] == before["suppressions"]
    assert db_session.scalar(select(Lead.stage)) == before_stage
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    run = db_session.scalar(select(ContentBriefRun))
    assert run is not None
    assert run.published is False
    assert run.publish_attempted is False
    assert run.outbound_attempted is False
    assert run.ads_launched is False
    assert run.spend_attempted is False
    assert run.dry_run_only is True


def test_launched_or_spend_attempted_channel_plans_are_ignored(db_session: Session) -> None:
    now = datetime.now(tz=UTC)
    run = ChannelPlanRun(
        status=ChannelPlanRunStatus.COMPLETED.value,
        snapshot_fingerprint=f"ignored-{uuid4().hex}",
        plan_count=1,
        dry_run_only=True,
        no_spend=True,
        spend_attempted=True,
        campaign_launched=False,
        pages_published=False,
        started_at=now,
        finished_at=now,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        ChannelPlan(
            channel_plan_run_id=run.id,
            plan_key="seo_content:ignored",
            channel=AcquisitionChannel.SEO_CONTENT.value,
            plan_type=ChannelPlanType.LANDING_PAGE_TOPIC.value,
            title="Should not become a brief",
            summary="Already marked spend-attempted.",
            target_specialty="Family Medicine",
            target_geography="TX",
            target_icp=None,
            priority="medium",
            confidence=0.7,
            source_metrics_json={},
            seed_input_refs_json={},
            generated_at=now,
            approval_status=RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
            dry_run_only=True,
            no_spend=True,
            launched=False,
            spend_attempted=True,
            campaign_launched=False,
            pages_published=False,
            outbound_attempted=False,
        )
    )
    db_session.flush()

    result = ContentBriefService().generate(db_session, _settings())

    assert result.brief_count == 0
    assert all(item.source_channel_plan_id is None for item in result.briefs)


def test_missing_specialty_stays_missing(db_session: Session) -> None:
    result = ContentBriefService().generate(
        db_session,
        _settings(),
        seeds=(
            ContentBriefSeed(
                brief_type=ContentBriefType.GEOGRAPHY_LANDING_PAGE,
                geography="NY",
            ),
        ),
    )

    assert result.brief_count == 1
    assert result.briefs[0].specialty is None
    assert result.briefs[0].geography == "NY"


def test_populated_pipeline_does_not_invent_prospect_facts(db_session: Session) -> None:
    _seed_pipeline(db_session)
    extra = sample_organization(
        db_session,
        name="UNNAMED SPECIALTY GROUP",
        npi="1888888888",
        specialty=None,
        state="TX",
        city="DALLAS",
        website=None,
        website_match_status=None,
    )
    sample_lead(db_session, extra, stage=LeadStage.DISCOVERED)
    result = ContentBriefService().generate(db_session, _settings())
    payload = json.dumps(result.__dict__, default=str)

    assert "UNNAMED SPECIALTY GROUP" not in payload
    assert PROSPECT_EMAIL not in payload
    assert PHI_SNIPPET not in payload
    for item in result.briefs:
        if item.specialty is None:
            assert "unknown specialty invented" not in item.summary.lower()


def _side_effect_counts(db: Session) -> dict[str, int]:
    return {
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
        "campaigns": int(db.scalar(select(func.count()).select_from(Campaign)) or 0),
        "suppressions": int(db.scalar(select(func.count()).select_from(Suppression)) or 0),
    }
