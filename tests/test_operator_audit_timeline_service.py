from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from vyro_growth.config import Settings
from vyro_growth.domain import (
    ReviewArtifactType,
    ReviewDecisionStatus,
    ReviewItemStatus,
    SettingsChangeRequestType,
)
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    LiveSettingsChangeRequest,
    Meeting,
    OperatorReviewDecision,
    OutreachMessage,
)
from vyro_growth.services.operator_audit_timeline import (
    OperatorAuditTimelineService,
    parse_event_type,
    parse_source,
    parse_status,
    parse_window,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _counts(db: Session) -> dict[str, int]:
    return {
        "activities": int(db.scalar(select(func.count()).select_from(Activity)) or 0),
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
        "requests": int(
            db.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) or 0
        ),
    }


def _add_activity(
    db: Session,
    *,
    action: str,
    actor: str,
    details: dict[str, object] | None = None,
    created_at: datetime | None = None,
) -> Activity:
    row = Activity(lead_id=None, actor=actor, action=action, details=details or {})
    db.add(row)
    db.flush()
    if created_at is not None:
        row.created_at = created_at
        db.flush()
    return row


def test_parse_filters_ignore_unknown_values() -> None:
    assert parse_event_type(None) is None
    assert parse_event_type("nppes_discovery_completed") == "nppes_discovery_completed"
    assert parse_event_type("../secrets") is None
    assert parse_event_type("<script>alert(1)</script>") is None
    assert parse_source("review_queue") == "review_queue"
    assert parse_source("execute now") is None
    assert parse_status("approved") == "approved"
    assert parse_status("../secrets") is None
    assert parse_window("7d") == "7d"
    assert parse_window("forever") == "all"
    assert parse_window(None) == "all"


def test_empty_timeline_is_zeroed_and_read_only(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)

    result = OperatorAuditTimelineService().timeline(db_session, _settings())

    assert result.read_only is True
    assert result.no_execution is True
    assert result.dry_run_only is True
    assert result.executed == 0
    assert result.live_action is False
    assert result.outbound_attempted is False
    assert result.owner_approved is False
    assert result.settings_applied is False
    assert result.halt_changed is False
    assert result.matching_count == 0
    assert result.shown_count == 0
    assert result.entries == ()
    assert result.operator_halt_status == HaltStatus.HALTED.value
    assert result.outbound_enabled is False
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_timeline_sanitizes_and_filters_existing_records(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    packet_id = uuid4()
    artifact_id = uuid4()
    older = datetime.now(tz=UTC) - timedelta(days=10)
    _add_activity(
        db_session,
        action="nppes_discovery_completed",
        actor="nppes_discovery",
        details={
            "discovery_run_id": str(uuid4()),
            "email": PROSPECT_EMAIL,
            "body": "do not render this outreach copy",
            "reason": "bounded_query",
            "api_key": SECRET_VALUE,
        },
        created_at=older,
    )
    _add_activity(
        db_session,
        action="approval_packets_generated",
        actor="approval_packets",
        details={
            "owner_approval_packet_id": str(packet_id),
            "status": "completed",
            "no_execution": True,
            "executed": False,
            "reason": PHI_SNIPPET,
        },
    )
    db_session.add(
        OperatorReviewDecision(
            artifact_type=ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value,
            artifact_id=artifact_id,
            decision=ReviewDecisionStatus.APPROVED.value,
            reviewer=PROSPECT_EMAIL,
            source="operator_ui",
            reviewer_notes=PHI_SNIPPET,
            decided_at=datetime.now(tz=UTC),
            item_status=ReviewItemStatus.APPROVED.value,
        )
    )
    db_session.flush()
    settings = _settings(voice_api_key=SECRET_VALUE)
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="timeline-seed",
        reviewer_notes=PHI_SNIPPET,
    )
    SettingsChangeRequestService().record_decision(
        db_session,
        settings,
        request_id=created.request_id,
        decision="approved",
        reviewer="owner",
    )
    before = _counts(db_session)

    result = OperatorAuditTimelineService().timeline(db_session, settings)
    filtered = OperatorAuditTimelineService().timeline(
        db_session,
        settings,
        event_type="operator_review_decision",
        status="approved",
    )
    windowed = OperatorAuditTimelineService().timeline(db_session, settings, window="7d")
    payload = " ".join(
        " ".join(
            [
                item.event_type,
                item.source_surface,
                item.actor_label or "",
                item.reason_label or "",
                str(item.packet_id or ""),
                str(item.artifact_id or ""),
                str(item.request_id or ""),
            ]
        )
        for item in result.entries
    )

    assert result.matching_count >= 3
    assert any(item.event_type == "nppes_discovery_completed" for item in result.entries)
    assert any(item.packet_id == packet_id for item in result.entries)
    assert any(item.artifact_id == artifact_id for item in result.entries)
    assert any(item.request_id == created.request_id for item in result.entries)
    assert any(item.event_type == "operator_review_decision" for item in result.entries)
    assert any(item.event_type == "settings_change_decision" for item in result.entries)
    assert all(item.read_only is True and item.no_execution is True for item in result.entries)
    assert filtered.matching_count >= 1
    assert all(item.event_type == "operator_review_decision" for item in filtered.entries)
    assert all(item.decision_status == "approved" for item in filtered.entries)
    assert all(item.event_type != "nppes_discovery_completed" for item in windowed.entries)
    assert PHI_SNIPPET not in payload
    assert PROSPECT_EMAIL not in payload
    assert SECRET_VALUE not in payload
    assert "do not render this outreach copy" not in payload
    _assert_no_leakage(payload)
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False
