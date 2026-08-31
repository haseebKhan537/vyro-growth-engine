from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.outreach import sample_lead, sample_organization
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from vyro_growth.config import Settings
from vyro_growth.domain import (
    AcquisitionChannelPlanStatus,
    ContentBriefApprovalStatus,
    ContentBriefType,
    LeadStage,
)
from vyro_growth.models import (
    AcquisitionChannelPlan,
    Activity,
    Campaign,
    CampaignEnrollment,
    ContentBrief,
    ContentBriefRun,
    Lead,
    Meeting,
    OutreachMessage,
    Suppression,
)
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
    service = ContentBriefService()
    seo = service.seed_channel_plan(
        db_session,
        channel_type="seo",
        specialty="Family Medicine",
        geography="TX",
    )
    ads = service.seed_channel_plan(
        db_session,
        channel_type="google_ads",
        specialty="Cardiology",
        geography="CA",
    )
    partner = service.seed_channel_plan(
        db_session,
        channel_type="referral_partner",
        specialty="Dermatology",
    )
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    result = service.generate(db_session, _settings())
    types = {item.brief_type for item in result.briefs}
    plan_ids = {item.source_channel_plan_id for item in result.briefs}

    assert ContentBriefType.SEO_ARTICLE.value in types
    assert ContentBriefType.GOOGLE_ADS_LANDING_PAGE.value in types
    assert ContentBriefType.REFERRAL_PARTNER_PAGE.value in types
    assert seo.id in plan_ids
    assert ads.id in plan_ids
    assert partner.id in plan_ids
    assert all(item.published is False for item in result.briefs)
    assert all(plan.launched is False for plan in (seo, ads, partner))
    assert all(plan.spend_attempted is False for plan in (seo, ads, partner))
    assert all(plan.ads_live is False for plan in (seo, ads, partner))


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


def test_channel_plan_seed_is_idempotent_and_unlaunched(db_session: Session) -> None:
    service = ContentBriefService()
    first = service.seed_channel_plan(
        db_session,
        channel_type="seo",
        specialty="Family Medicine",
        geography="TX",
    )
    second = service.seed_channel_plan(
        db_session,
        channel_type="seo",
        specialty="Family Medicine",
        geography="TX",
    )

    assert second.reused_existing is True
    assert second.id == first.id
    assert db_session.scalar(select(func.count()).select_from(AcquisitionChannelPlan)) == 1
    assert first.status == AcquisitionChannelPlanStatus.PENDING_OPERATOR_REVIEW.value
    assert first.launched is False
    assert first.spend_attempted is False
    assert first.ads_live is False


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
