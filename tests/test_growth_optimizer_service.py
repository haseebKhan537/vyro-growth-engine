from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.outreach import sample_lead, sample_organization, sample_score
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from vyro_growth.config import Settings
from vyro_growth.domain import (
    BookingPlanRunStatus,
    BookingPlanStatus,
    LeadStage,
    RecommendationApprovalStatus,
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
    Lead,
    Meeting,
    OptimizerRecommendation,
    OptimizerRun,
    OutreachMessage,
    Suppression,
    VoiceQualificationPlan,
    VoiceQualificationRun,
)
from vyro_growth.services.growth_optimizer import GrowthOptimizerService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def test_empty_state_is_safe_and_pending_review(db_session: Session) -> None:
    result = GrowthOptimizerService().recommend(db_session, _settings())

    assert result.status.value == "completed"
    assert result.dry_run_only is True
    assert result.applied_count == 0
    assert result.outbound_attempted is False
    assert result.live_call_attempted is False
    assert result.reused_existing is False
    assert result.operator_halt_before == HaltStatus.UNAVAILABLE.value
    assert result.operator_halt_after == HaltStatus.UNAVAILABLE.value
    assert result.recommendation_count == len(result.recommendations)
    assert {item.recommendation_key for item in result.recommendations} == {
        "safety_operator_halt_unavailable"
    }
    for item in result.recommendations:
        assert item.approval_status == RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value
        assert item.applied is False
        assert item.category
        assert item.priority
        assert 0 <= item.confidence <= 1
        assert item.rationale
        assert item.source_metrics
        assert item.generated_at is not None


def test_populated_metrics_cover_review_categories(db_session: Session) -> None:
    _seed_review_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    result = GrowthOptimizerService().recommend(db_session, _settings())

    keys = {item.recommendation_key for item in result.recommendations}
    assert "website_enrichment_gap" in keys
    assert "decision_maker_coverage_gap" in keys
    assert "personalization_readiness_gap" in keys
    assert "outreach_plan_friction" in keys
    assert "reply_intent_trend" in keys
    assert "booking_plan_bottleneck" in keys
    assert "voice_plan_bottleneck" in keys
    assert "icp_scoring_conservative_mix" in keys
    assert "specialty_geography_stronger" in keys
    assert "specialty_geography_weaker" in keys
    assert all(
        item.approval_status == RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value
        for item in result.recommendations
    )
    assert all(item.applied is False for item in result.recommendations)
    assert result.applied_count == 0
    stored = db_session.scalars(select(OptimizerRecommendation)).all()
    assert stored
    assert all(row.applied is False for row in stored)
    assert all(
        row.approval_status == RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value
        for row in stored
    )


def test_identical_snapshot_is_idempotent(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    service = GrowthOptimizerService()

    first = service.recommend(db_session, _settings())
    second = service.recommend(db_session, _settings())

    assert second.reused_existing is True
    assert second.optimizer_run_id == first.optimizer_run_id
    assert second.snapshot_fingerprint == first.snapshot_fingerprint
    assert db_session.scalar(select(func.count()).select_from(OptimizerRun)) == 1
    assert db_session.scalar(select(func.count()).select_from(OptimizerRecommendation)) == (
        first.recommendation_count
    )
    activities = db_session.scalars(
        select(Activity).where(Activity.action == "optimizer_recommendations_generated")
    ).all()
    assert len(activities) == 1


def test_changed_metrics_create_a_new_run(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    service = GrowthOptimizerService()
    first = service.recommend(db_session, _settings())

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
    second = service.recommend(db_session, _settings())

    assert second.reused_existing is False
    assert second.optimizer_run_id != first.optimizer_run_id
    assert db_session.scalar(select(func.count()).select_from(OptimizerRun)) == 2


def test_optimizer_does_not_apply_or_touch_outbound(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _side_effect_counts(db_session)
    before_stage = db_session.scalar(select(Lead.stage))

    GrowthOptimizerService().recommend(db_session, Settings(outbound_enabled=False))

    after = _side_effect_counts(db_session)
    assert after["meetings"] == before["meetings"]
    assert after["enrollments"] == before["enrollments"]
    assert after["messages"] == before["messages"]
    assert after["booking_plans"] == before["booking_plans"]
    assert after["voice_plans"] == before["voice_plans"]
    assert after["campaigns"] == before["campaigns"]
    assert after["suppressions"] == before["suppressions"]
    assert after["lead_scores"] == before["lead_scores"]
    assert db_session.scalar(select(Lead.stage)) == before_stage
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    run = db_session.scalar(select(OptimizerRun))
    assert run is not None
    assert run.applied_count == 0
    assert run.outbound_attempted is False
    assert run.live_call_attempted is False
    assert run.dry_run_only is True


def test_optimizer_does_not_expose_phi_or_prospect_identifiers(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    result = GrowthOptimizerService().recommend(db_session, _settings())
    payload = json.dumps(result.__dict__, default=str)
    stored = json.dumps(
        [
            {
                "title": row.title,
                "rationale": row.rationale,
                "metrics": row.source_metrics_json,
                "snapshot": row.optimizer_run.snapshot_json,
            }
            for row in db_session.scalars(select(OptimizerRecommendation)).all()
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


def test_default_safety_flags_stay_disabled(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="default-safe")
    result = GrowthOptimizerService().recommend(db_session, Settings())
    keys = {item.recommendation_key for item in result.recommendations}

    assert "safety_outbound_enabled" not in keys
    assert "safety_live_provider_flags" not in keys
    assert "safety_live_artifacts" not in keys
    assert result.outbound_attempted is False
    settings = Settings()
    assert settings.outbound_enabled is False
    assert settings.smartlead_live_enabled is False
    assert settings.google_calendar_live_enabled is False
    assert settings.voice_live_enabled is False
    assert settings.openai_personalization_enabled is False


def test_live_provider_flags_produce_safety_recommendation(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    result = GrowthOptimizerService().recommend(
        db_session,
        Settings(smartlead_live_enabled=True, voice_live_enabled=True),
    )
    safety = next(
        item
        for item in result.recommendations
        if item.recommendation_key == "safety_live_provider_flags"
    )
    assert safety.priority == "high"
    assert safety.applied is False
    assert "smartlead_live_enabled" in safety.source_metrics["enabled_flags"]


def test_latest_returns_none_before_a_run(db_session: Session) -> None:
    assert GrowthOptimizerService().latest(db_session) is None


def _side_effect_counts(db: Session) -> dict[str, int]:
    return {
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
        "booking_plans": int(db.scalar(select(func.count()).select_from(BookingPlan)) or 0),
        "voice_plans": int(
            db.scalar(select(func.count()).select_from(VoiceQualificationPlan)) or 0
        ),
        "campaigns": int(db.scalar(select(func.count()).select_from(Campaign)) or 0),
        "suppressions": int(db.scalar(select(func.count()).select_from(Suppression)) or 0),
        "lead_scores": int(db.scalar(select(func.count()).select_from(Lead)) or 0),
    }


def _seed_review_pipeline(db: Session) -> None:
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

    now = datetime.now(tz=UTC)
    booking_run = BookingPlanRun(
        status=BookingPlanRunStatus.COMPLETED.value,
        skipped_count=1,
        started_at=now,
        finished_at=now,
    )
    db.add(booking_run)
    db.flush()
    db.add(
        BookingPlan(
            booking_plan_run_id=booking_run.id,
            lead_id=family_lead.id,
            organization_id=other_family.id,
            request_source="meeting_request_reply",
            request_key="gap-booking",
            status=BookingPlanStatus.SKIPPED.value,
            skip_reason="missing_meeting_request",
            idempotency_key=f"booking-skip-{uuid4()}",
            dry_run=True,
            event_created=False,
            meet_link_created=False,
            live_call_attempted=False,
            lead_stage_before=LeadStage.INTERESTED.value,
            lead_stage_after=LeadStage.INTERESTED.value,
        )
    )
    voice_run = VoiceQualificationRun(
        status=VoiceQualificationRunStatus.COMPLETED.value,
        skipped_count=1,
        started_at=now,
        finished_at=now,
    )
    db.add(voice_run)
    db.flush()
    db.add(
        VoiceQualificationPlan(
            voice_qualification_run_id=voice_run.id,
            lead_id=family_lead.id,
            organization_id=other_family.id,
            request_source="operator_request",
            request_key="gap-voice",
            status=VoicePlanStatus.SKIPPED.value,
            skip_reason="missing_consent_proof",
            idempotency_key=f"voice-skip-{uuid4()}",
            dry_run=True,
            live_call_attempted=False,
            call_placed=False,
        )
    )
    db.flush()
