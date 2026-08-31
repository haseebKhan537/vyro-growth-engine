from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from vyro_growth.config import Settings
from vyro_growth.domain import (
    DiscoveryRunStatus,
    FindingCode,
    FindingSeverity,
    RecommendationApprovalStatus,
)
from vyro_growth.models import (
    Activity,
    BookingPlan,
    CampaignEnrollment,
    DiscoveryRun,
    Meeting,
    OptimizerRecommendation,
    OptimizerRun,
    OutreachMessage,
    VoiceQualificationPlan,
)
from vyro_growth.services.monitoring import OperatorMonitoringService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

UNSAFE_ERROR = (
    f"Provider failed for {PROSPECT_EMAIL} phone=5551112222 "
    f"token=sk-testsecret12345 {PHI_SNIPPET}"
)


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _payload(snapshot: object) -> str:
    return json.dumps(snapshot, default=str)


def test_empty_status_is_zeroed_and_safe(db_session: Session) -> None:
    snapshot = OperatorMonitoringService().snapshot(db_session, _settings())

    assert snapshot.read_only is True
    assert snapshot.overall_severity is FindingSeverity.WARNING
    assert snapshot.recent_failures == ()
    assert snapshot.pending_review.total == 0
    assert snapshot.safety.outbound_enabled is False
    assert snapshot.safety.live_providers_enabled is False
    assert snapshot.safety.operator_halt_status == HaltStatus.UNAVAILABLE.value
    assert snapshot.safety.phi_fields_present is False
    assert snapshot.readiness.status == "ready"
    assert snapshot.readiness.config_ok is True
    assert snapshot.readiness.ready_for_manual_rollout is True
    assert {run.phase for run in snapshot.latest_runs} >= {
        "discovery",
        "growth_optimizer",
        "booking_plans",
        "voice_qualification_plans",
        "acquisition_channel_plans",
        "content_briefs",
    }
    assert all(run.status == "not_started" for run in snapshot.latest_runs)
    codes = {item.code for item in snapshot.findings}
    assert FindingCode.SAFE_DEFAULTS in codes
    assert FindingCode.OPERATOR_HALT_UNAVAILABLE in codes


def test_populated_status_counts_pending_review_and_runs(db_session: Session) -> None:
    _seed_pipeline(db_session)
    _seed_optimizer_recommendation(db_session)
    set_operator_halt(db_session, halted=True, reason="incident")

    snapshot = OperatorMonitoringService().snapshot(db_session, _settings())

    assert snapshot.pending_review.personalization_drafts == 1
    assert snapshot.pending_review.enrollment_plans == 1
    assert snapshot.pending_review.booking_plans == 1
    assert snapshot.pending_review.voice_plans == 1
    assert snapshot.pending_review.optimizer_recommendations == 1
    assert snapshot.pending_review.channel_plans == 0
    assert snapshot.pending_review.content_briefs == 0
    assert snapshot.pending_review.total == 5
    assert snapshot.safety.operator_halt_status == HaltStatus.HALTED.value
    assert snapshot.readiness.ready_for_manual_rollout is True
    assert any(
        run.phase == "discovery" and run.status != "not_started" for run in snapshot.latest_runs
    )
    assert any(
        run.phase == "growth_optimizer" and run.status == "completed"
        for run in snapshot.latest_runs
    )
    assert any(item.action == "seeded" for item in snapshot.activity_summary)
    codes = {item.code for item in snapshot.findings}
    assert FindingCode.PENDING_OPERATOR_REVIEW in codes
    assert FindingCode.OPERATOR_HALT_ACTIVE in codes
    assert FindingCode.SAFE_DEFAULTS in codes


def test_failed_runs_are_sanitized(db_session: Session) -> None:
    now = datetime.now(tz=UTC)
    db_session.add(
        DiscoveryRun(
            source="nppes",
            status=DiscoveryRunStatus.FAILED.value,
            query_params={"state": "TX", "city": "Austin"},
            error_message=UNSAFE_ERROR,
            started_at=now,
            finished_at=now,
        )
    )
    db_session.flush()

    snapshot = OperatorMonitoringService().snapshot(db_session, _settings())
    payload = _payload(snapshot.__dict__)

    assert snapshot.overall_severity is FindingSeverity.WARNING
    assert len(snapshot.recent_failures) == 1
    failure = snapshot.recent_failures[0]
    assert failure.phase == "discovery"
    assert failure.status == DiscoveryRunStatus.FAILED.value
    assert failure.error_message is not None
    assert PROSPECT_EMAIL not in failure.error_message
    assert "5551112222" not in failure.error_message
    assert "sk-testsecret12345" not in failure.error_message
    assert PHI_SNIPPET not in failure.error_message
    assert "diabetes" not in failure.error_message.lower()
    assert PROSPECT_EMAIL not in payload
    assert "diabetes" not in payload.lower()
    assert any(item.code is FindingCode.RECENT_FAILURES for item in snapshot.findings)


def test_monitoring_is_read_only_and_preserves_halt(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _pipeline_counts(db_session)

    OperatorMonitoringService().snapshot(db_session, Settings(outbound_enabled=False))

    assert _pipeline_counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_monitoring_does_not_expose_phi_or_prospect_facts(db_session: Session) -> None:
    _seed_pipeline(db_session)
    payload = _payload(OperatorMonitoringService().snapshot(db_session, _settings()).__dict__)

    assert PHI_SNIPPET not in payload
    assert PROSPECT_EMAIL not in payload
    assert "diabetes" not in payload.lower()
    assert "practice_summary" not in payload
    assert "opening_line" not in payload
    assert "permitted_phone" not in payload
    assert "evidence_snippet" not in payload
    assert "sk-" not in payload


def test_outbound_enabled_is_blocked(db_session: Session) -> None:
    snapshot = OperatorMonitoringService().snapshot(
        db_session,
        Settings(outbound_enabled=True),
    )

    assert snapshot.overall_severity is FindingSeverity.BLOCKED
    assert snapshot.safety.outbound_enabled is True
    assert snapshot.readiness.ready_for_manual_rollout is False
    assert any(item.code is FindingCode.OUTBOUND_ENABLED for item in snapshot.findings)


def test_live_provider_flag_is_blocked(db_session: Session) -> None:
    snapshot = OperatorMonitoringService().snapshot(
        db_session,
        Settings(smartlead_live_enabled=True, smartlead_api_key="placeholder"),
    )

    assert snapshot.overall_severity is FindingSeverity.BLOCKED
    assert snapshot.safety.live_providers_enabled is True
    assert snapshot.safety.live_providers["smartlead"] is True
    assert snapshot.readiness.ready_for_manual_rollout is False
    assert any(item.code is FindingCode.LIVE_PROVIDER_ENABLED for item in snapshot.findings)


def test_live_artifacts_are_blocked(db_session: Session) -> None:
    _seed_pipeline(db_session)
    lead_id = db_session.scalar(select(CampaignEnrollment.lead_id))
    assert lead_id is not None
    db_session.add(
        Meeting(
            lead_id=lead_id,
            starts_at=datetime.now(tz=UTC),
            meeting_url="https://meet.example/should-not-leak",
            provider_event_id="evt-1",
        )
    )
    db_session.flush()

    snapshot = OperatorMonitoringService().snapshot(db_session, _settings())
    payload = _payload(snapshot.__dict__)

    assert snapshot.overall_severity is FindingSeverity.BLOCKED
    assert snapshot.safety.live_calendar_events == 1
    assert snapshot.safety.live_meet_links == 1
    assert snapshot.readiness.ready_for_manual_rollout is False
    assert any(item.code is FindingCode.LIVE_OUTBOUND_ARTIFACT for item in snapshot.findings)
    assert "https://meet.example/should-not-leak" not in payload


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
        "optimizer_runs": int(db.scalar(select(func.count()).select_from(OptimizerRun)) or 0),
    }


def _seed_optimizer_recommendation(db: Session) -> None:
    now = datetime.now(tz=UTC)
    run = OptimizerRun(
        status="completed",
        snapshot_fingerprint=uuid4().hex,
        recommendation_count=1,
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    db.flush()
    db.add(
        OptimizerRecommendation(
            optimizer_run_id=run.id,
            recommendation_key="safety_risk",
            category="safety_risk",
            priority="high",
            confidence=0.8,
            title="Review safety posture",
            rationale="Counts only; no prospect copy.",
            source_metrics_json={"planned": 1},
            generated_at=now,
            approval_status=RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
            applied=False,
        )
    )
    db.flush()
