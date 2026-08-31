from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.settings_change_requests import (
    SettingsChangeProposal,
    SettingsChangeProposeResult,
    SettingsChangeRequestError,
    SettingsChangeRequestList,
    SettingsChangeRequestService,
    SettingsChangeRequestView,
)


class SettingsChangeDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    decision: str
    reviewer: str
    source: str
    reviewer_notes: str | None = None
    decided_at: datetime
    executed: bool = False
    settings_applied: bool = False
    owner_approved: bool = False
    halt_changed: bool = False
    live_action: bool = False
    no_execution: bool = True


class SettingsChangeRequestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    request_type: str
    status: str
    owner_decision_status: str
    idempotency_key: str
    requested_setting_names: list[str] = Field(default_factory=list)
    desired_boolean: bool | None = None
    desired_status: str | None = None
    finding_code: str | None = None
    next_action_code: str | None = None
    source: str
    reviewer_notes: str | None = None
    requested_at: datetime
    record_only: bool = True
    no_execution: bool = True
    executed: bool = False
    execution_attempted: bool = False
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    recommendation_applied: bool = False
    spend_attempted: bool = False
    campaign_launched: bool = False
    pages_published: bool = False
    ads_launched: bool = False
    owner_approved: bool = False
    settings_applied: bool = False
    halt_changed: bool = False
    live_action: bool = False
    reused: bool = False
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    decision: SettingsChangeDecisionResponse | None = None


class SettingsChangeRequestListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    request_count: int = 0
    pending_count: int = 0
    decided_count: int = 0
    by_request_type: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_decision_status: dict[str, int] = Field(default_factory=dict)
    record_only: bool = True
    no_execution: bool = True
    executed: int = 0
    live_action: bool = False
    outbound_attempted: bool = False
    owner_approved: bool = False
    settings_applied: bool = False
    halt_changed: bool = False
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    requests: list[SettingsChangeRequestResponse] = Field(default_factory=list)


class CreateSettingsChangeRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_type: str
    requested_setting_names: list[str] = Field(default_factory=list)
    desired_boolean: bool | None = None
    desired_status: str | None = None
    finding_code: str | None = None
    next_action_code: str | None = None
    idempotency_key: str | None = None
    reviewer_notes: str | None = None


class RecordSettingsChangeDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str
    reviewer: str | None = None
    reviewer_notes: str | None = None


class SettingsChangeProposeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_count: int = 0
    reused_count: int = 0
    request_count: int = 0
    record_only: bool = True
    no_execution: bool = True
    executed: int = 0
    live_action: bool = False
    outbound_attempted: bool = False
    owner_approved: bool = False
    settings_applied: bool = False
    halt_changed: bool = False
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    requests: list[SettingsChangeRequestResponse] = Field(default_factory=list)


def decision_to_response(item: SettingsChangeRequestView) -> SettingsChangeDecisionResponse | None:
    if item.decision is None:
        return None
    return SettingsChangeDecisionResponse(
        decision_id=item.decision.decision_id,
        decision=item.decision.decision,
        reviewer=item.decision.reviewer,
        source=item.decision.source,
        reviewer_notes=item.decision.reviewer_notes,
        decided_at=item.decision.decided_at,
        executed=False,
        settings_applied=False,
        owner_approved=False,
        halt_changed=False,
        live_action=False,
        no_execution=True,
    )


def request_to_response(item: SettingsChangeRequestView) -> SettingsChangeRequestResponse:
    return SettingsChangeRequestResponse(
        request_id=item.request_id,
        request_type=item.request_type,
        status=item.status,
        owner_decision_status=item.owner_decision_status,
        idempotency_key=item.idempotency_key,
        requested_setting_names=list(item.requested_setting_names),
        desired_boolean=item.desired_boolean,
        desired_status=item.desired_status,
        finding_code=item.finding_code,
        next_action_code=item.next_action_code,
        source=item.source,
        reviewer_notes=item.reviewer_notes,
        requested_at=item.requested_at,
        record_only=True,
        no_execution=True,
        executed=False,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        owner_approved=False,
        settings_applied=False,
        halt_changed=False,
        live_action=False,
        reused=item.reused,
        operator_halt_status=item.operator_halt_status,
        operator_halt_before=item.operator_halt_before,
        operator_halt_after=item.operator_halt_after,
        decision=decision_to_response(item),
    )


def list_to_response(result: SettingsChangeRequestList) -> SettingsChangeRequestListResponse:
    return SettingsChangeRequestListResponse(
        generated_at=result.generated_at,
        request_count=result.request_count,
        pending_count=result.pending_count,
        decided_count=result.decided_count,
        by_request_type=dict(result.by_request_type),
        by_status=dict(result.by_status),
        by_decision_status=dict(result.by_decision_status),
        record_only=True,
        no_execution=True,
        executed=0,
        live_action=False,
        outbound_attempted=False,
        owner_approved=False,
        settings_applied=False,
        halt_changed=False,
        operator_halt_status=result.operator_halt_status,
        operator_halt_before=result.operator_halt_before,
        operator_halt_after=result.operator_halt_after,
        requests=[request_to_response(item) for item in result.requests],
    )


def propose_to_response(result: SettingsChangeProposeResult) -> SettingsChangeProposeResponse:
    return SettingsChangeProposeResponse(
        created_count=result.created_count,
        reused_count=result.reused_count,
        request_count=result.request_count,
        record_only=True,
        no_execution=True,
        executed=0,
        live_action=False,
        outbound_attempted=False,
        owner_approved=False,
        settings_applied=False,
        halt_changed=False,
        operator_halt_status=result.operator_halt_status,
        operator_halt_before=result.operator_halt_before,
        operator_halt_after=result.operator_halt_after,
        requests=[request_to_response(item) for item in result.requests],
    )


def build_settings_change_list_response(
    db: Session,
    settings: Settings,
    *,
    status: str | None = None,
    request_type: str | None = None,
    owner_decision_status: str | None = None,
    service: SettingsChangeRequestService | None = None,
) -> SettingsChangeRequestListResponse:
    queue = service or SettingsChangeRequestService()
    return list_to_response(
        queue.list_requests(
            db,
            settings,
            status=status,
            request_type=request_type,
            owner_decision_status=owner_decision_status,
        )
    )


def build_settings_change_create_response(
    db: Session,
    settings: Settings,
    request: CreateSettingsChangeRequestBody,
    *,
    source: str = "internal_api",
    service: SettingsChangeRequestService | None = None,
) -> SettingsChangeRequestResponse:
    queue = service or SettingsChangeRequestService()
    return request_to_response(
        queue.create(
            db,
            settings,
            request_type=request.request_type,
            requested_setting_names=request.requested_setting_names,
            desired_boolean=request.desired_boolean,
            desired_status=request.desired_status,
            finding_code=request.finding_code,
            next_action_code=request.next_action_code,
            idempotency_key=request.idempotency_key,
            source=source,
            reviewer_notes=request.reviewer_notes,
        )
    )


def build_settings_change_detail_response(
    db: Session,
    settings: Settings,
    request_id: UUID,
    *,
    service: SettingsChangeRequestService | None = None,
) -> SettingsChangeRequestResponse | None:
    queue = service or SettingsChangeRequestService()
    item = queue.get_request(db, settings, request_id)
    if item is None:
        return None
    return request_to_response(item)


def build_settings_change_decision_response(
    db: Session,
    settings: Settings,
    request_id: UUID,
    request: RecordSettingsChangeDecisionBody,
    *,
    source: str = "internal_api",
    service: SettingsChangeRequestService | None = None,
) -> SettingsChangeRequestResponse:
    queue = service or SettingsChangeRequestService()
    return request_to_response(
        queue.record_decision(
            db,
            settings,
            request_id=request_id,
            decision=request.decision,
            reviewer=request.reviewer,
            source=source,
            reviewer_notes=request.reviewer_notes,
        )
    )


def build_settings_change_propose_response(
    db: Session,
    settings: Settings,
    proposals: Sequence[SettingsChangeProposal],
    *,
    source: str = "launch_readiness",
    service: SettingsChangeRequestService | None = None,
) -> SettingsChangeProposeResponse:
    queue = service or SettingsChangeRequestService()
    return propose_to_response(
        queue.propose_from_seeds(db, settings, proposals, source=source)
    )


def settings_change_http_error(error: SettingsChangeRequestError) -> tuple[int, str]:
    if error.code == "not_found":
        return (404, error.message)
    return (400, error.message)
