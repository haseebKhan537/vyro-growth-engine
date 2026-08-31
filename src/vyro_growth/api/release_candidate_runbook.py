from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.release_candidate_runbook import (
    ReleaseCandidateRunbook,
    ReleaseCandidateRunbookService,
    RunbookChecklistItem,
    RunbookCiAndLocalVerification,
    RunbookCiGate,
    RunbookGuardrailDoc,
    RunbookHaltVerification,
    RunbookIdentity,
    RunbookInstructionStep,
    RunbookReusedSummaries,
    RunbookSafeDefaults,
)


class RunbookChecklistItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    source_section: str
    status: str


class RunbookInstructionStepResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    instruction: str
    command_name: str | None = None
    route_name: str | None = None


class RunbookIdentityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_base_branch: str
    expected_workflow_path: str
    expected_release_channel: str
    git_provider_called: bool = False
    deployment_from_runbook: bool = False


class RunbookCiGateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    present: bool = False
    documented: bool = False
    job_name: str
    command_name: str


class RunbookCiAndLocalVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_ci_job_names: list[str] = Field(default_factory=list)
    smoke_gate: RunbookCiGateResponse
    deploy_config_gate: RunbookCiGateResponse
    local_verification_commands: list[str] = Field(default_factory=list)
    github_actions_called: bool = False


class RunbookSafeDefaultsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outbound_enabled_required: bool = False
    outbound_enabled: bool = False
    live_providers_enabled: bool = False
    required_flag_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    env_example_defaults_present: bool = False
    dockerfile_defaults_present: bool = False
    compose_defaults_present: bool = False
    secret_values_included: bool = False


class RunbookHaltVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outbound_enabled: bool = False
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    halt_changed: bool = False
    keep_outbound_disabled: bool = True
    verification_commands: list[str] = Field(default_factory=list)
    verification_routes: list[str] = Field(default_factory=list)


class RunbookGuardrailDocResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    present: bool = False
    documented_codes: list[str] = Field(default_factory=list)


class RunbookReusedSummariesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    launch_readiness_overall_status: str
    launch_readiness_blocker_codes: list[str] = Field(default_factory=list)
    settings_preflight_overall_status: str
    settings_preflight_blocked_count: int = 0
    settings_preflight_execution_allowed: bool = False
    owner_handoff_go_live_permitted: bool = False
    owner_handoff_execution_allowed: bool = False
    binder_is_not_go_live: bool = True
    binder_command: str
    binder_route: str
    audit_timeline_matching_count: int = 0
    audit_timeline_route: str


class ReleaseCandidateRunbookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "release_candidate_deployment_runbook"
    purpose: str = "future_manual_owner_review_only"
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
    future_deployment_phase_exists: bool = False
    go_live_permitted: bool = False
    deployment_allowed: bool = False
    deployment_attempted: bool = False
    deployed: bool = False
    manual_review_only: bool = True
    runbook_is_not_deployment: bool = True
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    outbound_enabled: bool = False
    live_providers_enabled: bool = False
    cli_command: str = "release-candidate-runbook"
    http_route: str = "/internal/release-candidate-runbook"
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    release_candidate_identity: RunbookIdentityResponse
    ci_gates_and_local_verification: RunbookCiAndLocalVerificationResponse
    safe_environment_defaults: RunbookSafeDefaultsResponse
    operator_halt_and_outbound: RunbookHaltVerificationResponse
    manual_deployment_sequence: list[RunbookInstructionStepResponse] = Field(default_factory=list)
    rollback_checklist: list[RunbookInstructionStepResponse] = Field(default_factory=list)
    post_deploy_verification: list[RunbookInstructionStepResponse] = Field(default_factory=list)
    documented_guardrails: list[RunbookGuardrailDocResponse] = Field(default_factory=list)
    reused_summaries: RunbookReusedSummariesResponse
    remaining_manual_owner_checklist: list[RunbookChecklistItemResponse] = Field(
        default_factory=list
    )


def _identity_to_response(identity: RunbookIdentity) -> RunbookIdentityResponse:
    return RunbookIdentityResponse(
        expected_base_branch=identity.expected_base_branch,
        expected_workflow_path=identity.expected_workflow_path,
        expected_release_channel=identity.expected_release_channel,
        git_provider_called=False,
        deployment_from_runbook=False,
    )


def _gate_to_response(gate: RunbookCiGate) -> RunbookCiGateResponse:
    return RunbookCiGateResponse(
        present=gate.present,
        documented=gate.documented,
        job_name=gate.job_name,
        command_name=gate.command_name,
    )


def _ci_to_response(
    evidence: RunbookCiAndLocalVerification,
) -> RunbookCiAndLocalVerificationResponse:
    return RunbookCiAndLocalVerificationResponse(
        required_ci_job_names=list(evidence.required_ci_job_names),
        smoke_gate=_gate_to_response(evidence.smoke_gate),
        deploy_config_gate=_gate_to_response(evidence.deploy_config_gate),
        local_verification_commands=list(evidence.local_verification_commands),
        github_actions_called=False,
    )


def _defaults_to_response(defaults: RunbookSafeDefaults) -> RunbookSafeDefaultsResponse:
    return RunbookSafeDefaultsResponse(
        outbound_enabled_required=False,
        outbound_enabled=defaults.outbound_enabled,
        live_providers_enabled=defaults.live_providers_enabled,
        required_flag_names=list(defaults.required_flag_names),
        closed_provider_flag_names=list(defaults.closed_provider_flag_names),
        missing_credential_names=list(defaults.missing_credential_names),
        env_example_defaults_present=defaults.env_example_defaults_present,
        dockerfile_defaults_present=defaults.dockerfile_defaults_present,
        compose_defaults_present=defaults.compose_defaults_present,
        secret_values_included=False,
    )


def _halt_to_response(halt: RunbookHaltVerification) -> RunbookHaltVerificationResponse:
    return RunbookHaltVerificationResponse(
        outbound_enabled=halt.outbound_enabled,
        operator_halt_status=halt.operator_halt_status,
        operator_halt_before=halt.operator_halt_before,
        operator_halt_after=halt.operator_halt_after,
        halt_changed=False,
        keep_outbound_disabled=halt.keep_outbound_disabled,
        verification_commands=list(halt.verification_commands),
        verification_routes=list(halt.verification_routes),
    )


def _step_to_response(item: RunbookInstructionStep) -> RunbookInstructionStepResponse:
    return RunbookInstructionStepResponse(
        code=item.code,
        instruction=item.instruction,
        command_name=item.command_name,
        route_name=item.route_name,
    )


def _guardrail_to_response(item: RunbookGuardrailDoc) -> RunbookGuardrailDocResponse:
    return RunbookGuardrailDocResponse(
        path=item.path,
        present=item.present,
        documented_codes=list(item.documented_codes),
    )


def _reused_to_response(summary: RunbookReusedSummaries) -> RunbookReusedSummariesResponse:
    return RunbookReusedSummariesResponse(
        launch_readiness_overall_status=summary.launch_readiness_overall_status,
        launch_readiness_blocker_codes=list(summary.launch_readiness_blocker_codes),
        settings_preflight_overall_status=summary.settings_preflight_overall_status,
        settings_preflight_blocked_count=summary.settings_preflight_blocked_count,
        settings_preflight_execution_allowed=False,
        owner_handoff_go_live_permitted=False,
        owner_handoff_execution_allowed=False,
        binder_is_not_go_live=True,
        binder_command=summary.binder_command,
        binder_route=summary.binder_route,
        audit_timeline_matching_count=summary.audit_timeline_matching_count,
        audit_timeline_route=summary.audit_timeline_route,
    )


def _checklist_to_response(item: RunbookChecklistItem) -> RunbookChecklistItemResponse:
    return RunbookChecklistItemResponse(
        code=item.code,
        severity=item.severity,
        source_section=item.source_section,
        status=item.status,
    )


def runbook_to_response(runbook: ReleaseCandidateRunbook) -> ReleaseCandidateRunbookResponse:
    return ReleaseCandidateRunbookResponse(
        generated_at=runbook.generated_at,
        packet_kind="release_candidate_deployment_runbook",
        purpose="future_manual_owner_review_only",
        overall_status=runbook.overall_status,
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
        future_deployment_phase_exists=False,
        go_live_permitted=False,
        deployment_allowed=False,
        deployment_attempted=False,
        deployed=False,
        manual_review_only=True,
        runbook_is_not_deployment=True,
        operator_halt_status=runbook.operator_halt_status,
        operator_halt_before=runbook.operator_halt_before,
        operator_halt_after=runbook.operator_halt_after,
        outbound_enabled=runbook.outbound_enabled,
        live_providers_enabled=runbook.live_providers_enabled,
        cli_command="release-candidate-runbook",
        http_route="/internal/release-candidate-runbook",
        related_commands=list(runbook.related_commands),
        related_routes=list(runbook.related_routes),
        blocker_codes=list(runbook.blocker_codes),
        missing_credential_names=list(runbook.missing_credential_names),
        closed_provider_flag_names=list(runbook.closed_provider_flag_names),
        release_candidate_identity=_identity_to_response(runbook.release_candidate_identity),
        ci_gates_and_local_verification=_ci_to_response(runbook.ci_gates_and_local_verification),
        safe_environment_defaults=_defaults_to_response(runbook.safe_environment_defaults),
        operator_halt_and_outbound=_halt_to_response(runbook.operator_halt_and_outbound),
        manual_deployment_sequence=[
            _step_to_response(item) for item in runbook.manual_deployment_sequence
        ],
        rollback_checklist=[_step_to_response(item) for item in runbook.rollback_checklist],
        post_deploy_verification=[
            _step_to_response(item) for item in runbook.post_deploy_verification
        ],
        documented_guardrails=[
            _guardrail_to_response(item) for item in runbook.documented_guardrails
        ],
        reused_summaries=_reused_to_response(runbook.reused_summaries),
        remaining_manual_owner_checklist=[
            _checklist_to_response(item) for item in runbook.remaining_manual_owner_checklist
        ],
    )


def build_release_candidate_runbook_response(
    db: Session,
    settings: Settings,
    *,
    service: ReleaseCandidateRunbookService | None = None,
) -> ReleaseCandidateRunbookResponse:
    builder = service or ReleaseCandidateRunbookService()
    return runbook_to_response(builder.build(db, settings))
