from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.monitoring import (
    ActivityActionCount,
    LatestJobStatus,
    MonitoringReadiness,
    MonitoringSafety,
    MonitoringSnapshot,
    OperationalFinding,
    OperatorMonitoringService,
    PendingReviewCounts,
    SanitizedFailure,
)


class LatestJobStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: str
    job_name: str | None
    implemented: bool
    status: str | None
    started_at: datetime | None
    finished_at: datetime | None
    run_id: UUID | None


class SanitizedFailureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: str
    status: str
    occurred_at: datetime | None
    run_id: UUID | None
    error_message: str | None


class MonitoringSafetyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outbound_enabled: bool
    outbound_halted_settings: bool
    operator_halt_status: str
    operator_halt_reason: str | None
    live_providers_enabled: bool
    live_providers: dict[str, bool] = Field(default_factory=dict)
    live_calendar_events: int
    live_meet_links: int
    live_phone_calls: int
    live_send_attempted_enrollments: int
    outbound_attempted_classifications: int
    booking_events_created: int
    booking_meet_links_created: int
    voice_calls_placed: int
    phi_fields_present: bool = False


class MonitoringReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    environment: str
    database: str
    config_ok: bool
    config_issues: list[str] = Field(default_factory=list)
    outbound_enabled: bool
    live_providers_enabled: bool
    live_providers: dict[str, bool] = Field(default_factory=dict)
    ready_for_manual_rollout: bool


class PendingReviewCountsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personalization_drafts: int
    enrollment_plans: int
    booking_plans: int
    voice_plans: int
    optimizer_recommendations: int
    content_briefs: int
    total: int


class ActivityActionCountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    count: int


class OperationalFindingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: str
    code: str
    message: str
    phase: str | None = None


class MonitoringStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    read_only: bool = True
    overall_severity: str
    latest_runs: list[LatestJobStatusResponse]
    recent_failures: list[SanitizedFailureResponse]
    safety: MonitoringSafetyResponse
    readiness: MonitoringReadinessResponse
    pending_review: PendingReviewCountsResponse
    activity_summary: list[ActivityActionCountResponse]
    findings: list[OperationalFindingResponse]


def _job_status_to_response(item: LatestJobStatus) -> LatestJobStatusResponse:
    return LatestJobStatusResponse(
        phase=item.phase,
        job_name=item.job_name,
        implemented=item.implemented,
        status=item.status,
        started_at=item.started_at,
        finished_at=item.finished_at,
        run_id=item.run_id,
    )


def _failure_to_response(item: SanitizedFailure) -> SanitizedFailureResponse:
    return SanitizedFailureResponse(
        phase=item.phase,
        status=item.status,
        occurred_at=item.occurred_at,
        run_id=item.run_id,
        error_message=item.error_message,
    )


def _safety_to_response(item: MonitoringSafety) -> MonitoringSafetyResponse:
    return MonitoringSafetyResponse(
        outbound_enabled=item.outbound_enabled,
        outbound_halted_settings=item.outbound_halted_settings,
        operator_halt_status=item.operator_halt_status,
        operator_halt_reason=item.operator_halt_reason,
        live_providers_enabled=item.live_providers_enabled,
        live_providers=item.live_providers,
        live_calendar_events=item.live_calendar_events,
        live_meet_links=item.live_meet_links,
        live_phone_calls=item.live_phone_calls,
        live_send_attempted_enrollments=item.live_send_attempted_enrollments,
        outbound_attempted_classifications=item.outbound_attempted_classifications,
        booking_events_created=item.booking_events_created,
        booking_meet_links_created=item.booking_meet_links_created,
        voice_calls_placed=item.voice_calls_placed,
        phi_fields_present=item.phi_fields_present,
    )


def _readiness_to_response(item: MonitoringReadiness) -> MonitoringReadinessResponse:
    return MonitoringReadinessResponse(
        status=item.status,
        environment=item.environment,
        database=item.database,
        config_ok=item.config_ok,
        config_issues=list(item.config_issues),
        outbound_enabled=item.outbound_enabled,
        live_providers_enabled=item.live_providers_enabled,
        live_providers=item.live_providers,
        ready_for_manual_rollout=item.ready_for_manual_rollout,
    )


def _pending_to_response(item: PendingReviewCounts) -> PendingReviewCountsResponse:
    return PendingReviewCountsResponse(
        personalization_drafts=item.personalization_drafts,
        enrollment_plans=item.enrollment_plans,
        booking_plans=item.booking_plans,
        voice_plans=item.voice_plans,
        optimizer_recommendations=item.optimizer_recommendations,
        content_briefs=item.content_briefs,
        total=item.total,
    )


def _activity_to_response(item: ActivityActionCount) -> ActivityActionCountResponse:
    return ActivityActionCountResponse(action=item.action, count=item.count)


def _finding_to_response(item: OperationalFinding) -> OperationalFindingResponse:
    return OperationalFindingResponse(
        severity=item.severity.value,
        code=item.code.value,
        message=item.message,
        phase=item.phase,
    )


def monitoring_snapshot_to_response(snapshot: MonitoringSnapshot) -> MonitoringStatusResponse:
    return MonitoringStatusResponse(
        generated_at=snapshot.generated_at,
        read_only=snapshot.read_only,
        overall_severity=snapshot.overall_severity.value,
        latest_runs=[_job_status_to_response(item) for item in snapshot.latest_runs],
        recent_failures=[_failure_to_response(item) for item in snapshot.recent_failures],
        safety=_safety_to_response(snapshot.safety),
        readiness=_readiness_to_response(snapshot.readiness),
        pending_review=_pending_to_response(snapshot.pending_review),
        activity_summary=[_activity_to_response(item) for item in snapshot.activity_summary],
        findings=[_finding_to_response(item) for item in snapshot.findings],
    )


def build_monitoring_status_response(
    db: Session,
    settings: Settings,
    *,
    service: OperatorMonitoringService | None = None,
) -> MonitoringStatusResponse:
    monitor = service or OperatorMonitoringService()
    return monitoring_snapshot_to_response(monitor.snapshot(db, settings))
