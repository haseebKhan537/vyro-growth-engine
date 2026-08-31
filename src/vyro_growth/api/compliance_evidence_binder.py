from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.compliance_evidence_binder import (
    AuditTimelineEntryEvidence,
    AuditTimelineEvidence,
    BinderChecklistItem,
    CiGateEvidence,
    CiGateStatus,
    ComplianceEvidenceBinder,
    ComplianceEvidenceBinderService,
    ConsentPhoneEvidence,
    GuardrailDocEvidence,
    LiveProviderDefaultEvidence,
    NoExecutionEvidence,
    OutboundHaltEvidence,
    RedactionEvidence,
    ReusedSummaryEvidence,
    SecretPresenceItem,
)


class BinderChecklistItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    source_section: str
    status: str


class SecretPresenceItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    present: bool = False
    status: str
    required: bool = False


class OutboundHaltEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outbound_enabled: bool = False
    outbound_halted_settings: bool = False
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    halt_changed: bool = False
    keep_outbound_disabled: bool = True
    command_name: str
    route_name: str


class LiveProviderDefaultEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    live_providers_enabled: bool = False
    live_provider_flags: dict[str, bool] = Field(default_factory=dict)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    required_flag_names: list[str] = Field(default_factory=list)
    env_example_defaults_present: bool = False
    dockerfile_defaults_present: bool = False
    compose_defaults_present: bool = False


class NoExecutionEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executed: int = 0
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
    live_action: bool = False
    execution_allowed: bool = False
    go_live_permitted: bool = False
    future_execution_phase_exists: bool = False
    live_calendar_events: int = 0
    live_meet_links: int = 0
    live_phone_calls: int = 0
    live_send_attempted_enrollments: int = 0
    outbound_attempted_classifications: int = 0
    undeployed_outbound_jobs: list[str] = Field(default_factory=list)


class RedactionEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phi_fields_present: bool = False
    secret_values_included: bool = False
    message_bodies_included: bool = False
    evidence_snippets_included: bool = False
    emails_included: bool = False
    phones_included: bool = False
    redaction_applied: bool = True
    missing_credential_names: list[str] = Field(default_factory=list)
    secret_inventory: list[SecretPresenceItemResponse] = Field(default_factory=list)


class ConsentPhoneEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_live_enabled: bool = False
    consent_to_call_required: bool = True
    cold_calling_disabled: bool = True
    no_live_dialer: bool = True
    undeployed_callback_job: str
    live_phone_calls: int = 0
    voice_calls_placed: int = 0


class CiGateStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    present: bool = False
    documented: bool = False
    job_name: str
    command_name: str


class CiGateEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    smoke_gate: CiGateStatusResponse
    deploy_config_gate: CiGateStatusResponse
    smoke_run_command: str
    smoke_check_command: str


class GuardrailDocEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    present: bool = False
    documented_codes: list[str] = Field(default_factory=list)


class AuditTimelineEntryEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    source_surface: str
    occurred_at: datetime
    status: str | None = None
    decision_status: str | None = None
    no_execution: bool = True
    executed: bool = False
    live_action: bool = False
    owner_approved: bool = False
    settings_applied: bool = False
    halt_changed: bool = False


class AuditTimelineEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matching_count: int = 0
    shown_count: int = 0
    truncated: bool = False
    available_event_types: list[str] = Field(default_factory=list)
    available_sources: list[str] = Field(default_factory=list)
    by_event_type: dict[str, int] = Field(default_factory=dict)
    route_name: str
    entries: list[AuditTimelineEntryEvidenceResponse] = Field(default_factory=list)


class ReusedSummaryEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    launch_readiness_overall_status: str
    launch_readiness_blocker_codes: list[str] = Field(default_factory=list)
    launch_readiness_next_action_codes: list[str] = Field(default_factory=list)
    settings_preflight_overall_status: str
    settings_preflight_blocked_count: int = 0
    settings_preflight_executable_count: int = 0
    settings_preflight_execution_allowed: bool = False
    owner_handoff_command: str
    owner_handoff_route: str
    owner_handoff_go_live_permitted: bool = False
    owner_handoff_execution_allowed: bool = False


class ComplianceEvidenceBinderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "compliance_evidence_binder"
    purpose: str = "manual_owner_review_only"
    overall_status: str
    read_only: bool = True
    no_execution: bool = True
    dry_run_only: bool = True
    executed: int = 0
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
    execution_allowed: bool = False
    future_execution_phase_exists: bool = False
    go_live_permitted: bool = False
    manual_review_only: bool = True
    binder_is_not_go_live: bool = True
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    outbound_enabled: bool = False
    live_providers_enabled: bool = False
    cli_command: str = "compliance-evidence-binder"
    http_route: str = "/internal/compliance-evidence-binder"
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    outbound_and_halt: OutboundHaltEvidenceResponse
    live_provider_defaults: LiveProviderDefaultEvidenceResponse
    no_execution_side_effects: NoExecutionEvidenceResponse
    phi_secrets_redaction: RedactionEvidenceResponse
    consent_phone_boundary: ConsentPhoneEvidenceResponse
    ci_gates: CiGateEvidenceResponse
    documented_guardrails: list[GuardrailDocEvidenceResponse] = Field(default_factory=list)
    operator_audit_timeline: AuditTimelineEvidenceResponse
    reused_summaries: ReusedSummaryEvidenceResponse
    remaining_manual_owner_checklist: list[BinderChecklistItemResponse] = Field(
        default_factory=list
    )


def _secret_to_response(item: SecretPresenceItem) -> SecretPresenceItemResponse:
    return SecretPresenceItemResponse(
        name=item.name,
        present=item.present,
        status=item.status,
        required=item.required,
    )


def _outbound_to_response(evidence: OutboundHaltEvidence) -> OutboundHaltEvidenceResponse:
    return OutboundHaltEvidenceResponse(
        outbound_enabled=evidence.outbound_enabled,
        outbound_halted_settings=evidence.outbound_halted_settings,
        operator_halt_status=evidence.operator_halt_status,
        operator_halt_before=evidence.operator_halt_before,
        operator_halt_after=evidence.operator_halt_after,
        halt_changed=False,
        keep_outbound_disabled=evidence.keep_outbound_disabled,
        command_name=evidence.command_name,
        route_name=evidence.route_name,
    )


def _live_defaults_to_response(
    evidence: LiveProviderDefaultEvidence,
) -> LiveProviderDefaultEvidenceResponse:
    return LiveProviderDefaultEvidenceResponse(
        live_providers_enabled=evidence.live_providers_enabled,
        live_provider_flags=dict(evidence.live_provider_flags),
        closed_provider_flag_names=list(evidence.closed_provider_flag_names),
        required_flag_names=list(evidence.required_flag_names),
        env_example_defaults_present=evidence.env_example_defaults_present,
        dockerfile_defaults_present=evidence.dockerfile_defaults_present,
        compose_defaults_present=evidence.compose_defaults_present,
    )


def _no_execution_to_response(evidence: NoExecutionEvidence) -> NoExecutionEvidenceResponse:
    return NoExecutionEvidenceResponse(
        executed=0,
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
        live_action=False,
        execution_allowed=False,
        go_live_permitted=False,
        future_execution_phase_exists=False,
        live_calendar_events=evidence.live_calendar_events,
        live_meet_links=evidence.live_meet_links,
        live_phone_calls=evidence.live_phone_calls,
        live_send_attempted_enrollments=evidence.live_send_attempted_enrollments,
        outbound_attempted_classifications=evidence.outbound_attempted_classifications,
        undeployed_outbound_jobs=list(evidence.undeployed_outbound_jobs),
    )


def _redaction_to_response(evidence: RedactionEvidence) -> RedactionEvidenceResponse:
    return RedactionEvidenceResponse(
        phi_fields_present=evidence.phi_fields_present,
        secret_values_included=False,
        message_bodies_included=False,
        evidence_snippets_included=False,
        emails_included=False,
        phones_included=False,
        redaction_applied=True,
        missing_credential_names=list(evidence.missing_credential_names),
        secret_inventory=[_secret_to_response(item) for item in evidence.secret_inventory],
    )


def _consent_to_response(evidence: ConsentPhoneEvidence) -> ConsentPhoneEvidenceResponse:
    return ConsentPhoneEvidenceResponse(
        voice_live_enabled=evidence.voice_live_enabled,
        consent_to_call_required=True,
        cold_calling_disabled=True,
        no_live_dialer=True,
        undeployed_callback_job=evidence.undeployed_callback_job,
        live_phone_calls=evidence.live_phone_calls,
        voice_calls_placed=evidence.voice_calls_placed,
    )


def _gate_to_response(status: CiGateStatus) -> CiGateStatusResponse:
    return CiGateStatusResponse(
        present=status.present,
        documented=status.documented,
        job_name=status.job_name,
        command_name=status.command_name,
    )


def _ci_gates_to_response(evidence: CiGateEvidence) -> CiGateEvidenceResponse:
    return CiGateEvidenceResponse(
        smoke_gate=_gate_to_response(evidence.smoke_gate),
        deploy_config_gate=_gate_to_response(evidence.deploy_config_gate),
        smoke_run_command=evidence.smoke_run_command,
        smoke_check_command=evidence.smoke_check_command,
    )


def _guardrail_to_response(item: GuardrailDocEvidence) -> GuardrailDocEvidenceResponse:
    return GuardrailDocEvidenceResponse(
        path=item.path,
        present=item.present,
        documented_codes=list(item.documented_codes),
    )


def _audit_entry_to_response(
    item: AuditTimelineEntryEvidence,
) -> AuditTimelineEntryEvidenceResponse:
    return AuditTimelineEntryEvidenceResponse(
        event_type=item.event_type,
        source_surface=item.source_surface,
        occurred_at=item.occurred_at,
        status=item.status,
        decision_status=item.decision_status,
        no_execution=True,
        executed=False,
        live_action=False,
        owner_approved=False,
        settings_applied=False,
        halt_changed=False,
    )


def _audit_to_response(evidence: AuditTimelineEvidence) -> AuditTimelineEvidenceResponse:
    return AuditTimelineEvidenceResponse(
        matching_count=evidence.matching_count,
        shown_count=evidence.shown_count,
        truncated=evidence.truncated,
        available_event_types=list(evidence.available_event_types),
        available_sources=list(evidence.available_sources),
        by_event_type=dict(evidence.by_event_type),
        route_name=evidence.route_name,
        entries=[_audit_entry_to_response(item) for item in evidence.entries],
    )


def _reused_to_response(evidence: ReusedSummaryEvidence) -> ReusedSummaryEvidenceResponse:
    return ReusedSummaryEvidenceResponse(
        launch_readiness_overall_status=evidence.launch_readiness_overall_status,
        launch_readiness_blocker_codes=list(evidence.launch_readiness_blocker_codes),
        launch_readiness_next_action_codes=list(evidence.launch_readiness_next_action_codes),
        settings_preflight_overall_status=evidence.settings_preflight_overall_status,
        settings_preflight_blocked_count=evidence.settings_preflight_blocked_count,
        settings_preflight_executable_count=0,
        settings_preflight_execution_allowed=False,
        owner_handoff_command=evidence.owner_handoff_command,
        owner_handoff_route=evidence.owner_handoff_route,
        owner_handoff_go_live_permitted=False,
        owner_handoff_execution_allowed=False,
    )


def _checklist_to_response(item: BinderChecklistItem) -> BinderChecklistItemResponse:
    return BinderChecklistItemResponse(
        code=item.code,
        severity=item.severity,
        source_section=item.source_section,
        status=item.status,
    )


def binder_to_response(binder: ComplianceEvidenceBinder) -> ComplianceEvidenceBinderResponse:
    return ComplianceEvidenceBinderResponse(
        generated_at=binder.generated_at,
        packet_kind="compliance_evidence_binder",
        purpose="manual_owner_review_only",
        overall_status=binder.overall_status,
        read_only=True,
        no_execution=True,
        dry_run_only=True,
        executed=0,
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
        execution_allowed=False,
        future_execution_phase_exists=False,
        go_live_permitted=False,
        manual_review_only=True,
        binder_is_not_go_live=True,
        operator_halt_status=binder.operator_halt_status,
        operator_halt_before=binder.operator_halt_before,
        operator_halt_after=binder.operator_halt_after,
        outbound_enabled=binder.outbound_enabled,
        live_providers_enabled=binder.live_providers_enabled,
        cli_command="compliance-evidence-binder",
        http_route="/internal/compliance-evidence-binder",
        related_commands=list(binder.related_commands),
        related_routes=list(binder.related_routes),
        blocker_codes=list(binder.blocker_codes),
        missing_credential_names=list(binder.missing_credential_names),
        closed_provider_flag_names=list(binder.closed_provider_flag_names),
        outbound_and_halt=_outbound_to_response(binder.outbound_and_halt),
        live_provider_defaults=_live_defaults_to_response(binder.live_provider_defaults),
        no_execution_side_effects=_no_execution_to_response(binder.no_execution_side_effects),
        phi_secrets_redaction=_redaction_to_response(binder.phi_secrets_redaction),
        consent_phone_boundary=_consent_to_response(binder.consent_phone_boundary),
        ci_gates=_ci_gates_to_response(binder.ci_gates),
        documented_guardrails=[
            _guardrail_to_response(item) for item in binder.documented_guardrails
        ],
        operator_audit_timeline=_audit_to_response(binder.operator_audit_timeline),
        reused_summaries=_reused_to_response(binder.reused_summaries),
        remaining_manual_owner_checklist=[
            _checklist_to_response(item) for item in binder.remaining_manual_owner_checklist
        ],
    )


def build_compliance_evidence_binder_response(
    db: Session,
    settings: Settings,
    *,
    service: ComplianceEvidenceBinderService | None = None,
) -> ComplianceEvidenceBinderResponse:
    builder = service or ComplianceEvidenceBinderService()
    return binder_to_response(builder.build(db, settings))
