"""Read-only owner live-provider setup checklist JSON export.

Phase 76 exposes existing provider-setup, launch-readiness, supervised-validation,
settings-preflight, and compliance-binder surfaces as one sanitized credential
readiness packet. It reuses LiveProviderSetupChecklistService, which reuses those
source services. It never verifies credentials, calls providers, sends email,
enrolls campaigns, places calls, autodials, uses AI voice, books meetings,
creates Meet links, launches ads, spends, publishes, deploys, applies settings,
lifts halt, enables outbound, or grants owner approval. This export is not
permission to run a supervised validation and not an execution surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.live_provider_setup_checklist import (
    CLI_COMMAND,
    HTTP_ROUTE,
    LiveProviderSetupChecklistService,
    live_provider_setup_checklist_payload,
)


class LocalGitMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool = False
    github_actions_called: bool = False


class NamedPresenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    present: bool


class ProviderFlagStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool


class ProviderAccountItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    category: str
    applicable: bool = True
    credential_names: list[str] = Field(default_factory=list)
    config_names: list[str] = Field(default_factory=list)
    flag_names: list[str] = Field(default_factory=list)
    credentials: list[NamedPresenceResponse] = Field(default_factory=list)
    configs: list[NamedPresenceResponse] = Field(default_factory=list)
    flags: list[ProviderFlagStateResponse] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    live_enabled: bool = False
    credential_ready: bool = False
    live_execution_allowed: bool = False


class OwnerDecisionItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    granted: bool = False


class BudgetRateLimitItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str
    configured: bool
    safe_value: str | None = None
    placeholder_label: str


class CompliancePrerequisiteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    blocking: bool
    documented: bool


class ValidationRunConstraintResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    limit: int | None = None
    required: bool = True


class OwnerNextStepResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None
    config_name: str | None = None


class LiveProviderSetupChecklistResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "live_provider_setup_checklist"
    purpose: str = "manual_owner_live_provider_credential_readiness_review_only"
    overall_status: str
    read_only: bool = True
    dry_run_only: bool = True
    no_execution: bool = True
    no_outbound: bool = True
    no_provider_calls: bool = True
    no_credential_verification: bool = True
    no_send: bool = True
    no_call: bool = True
    no_book: bool = True
    no_spend: bool = True
    no_deploy: bool = True
    no_autodial: bool = True
    no_ai_voice: bool = True
    manual_review_only: bool = True
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    live_provider_calls_attempted: bool = False
    credential_verification_attempted: bool = False
    smtp_attempted: bool = False
    autodial_attempted: bool = False
    campaign_enrolled: bool = False
    booking_attempted: bool = False
    meet_link_created: bool = False
    ads_launched: bool = False
    execution_allowed: bool = False
    owner_approved: bool = False
    validation_permitted: bool = False
    spend_attempted: bool = False
    campaign_launched: bool = False
    halt_changed: bool = False
    settings_applied: bool = False
    scoring_thresholds_changed: bool = False
    outbound_enabled: bool = False
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    operator_halt_unchanged: bool = True
    live_providers_enabled: bool = False
    live_providers: dict[str, bool] = Field(default_factory=dict)
    contact_validation_is_not_outbound: bool = True
    contact_validation_is_not_live_send: bool = True
    supervised_validation_run_packet_is_not_execution: bool = True
    export_is_not_permission_to_run: bool = True
    live_provider_setup_checklist_is_not_go_live: bool = True
    checklist_is_not_permission_to_go_live: bool = True
    checklist_is_not_execution: bool = True
    supervised_validation_run_permitted: bool = False
    credential_values_included: bool = False
    source_provider_setup_command: str
    source_provider_setup_route: str
    source_provider_setup_overall_status: str
    source_launch_readiness_command: str
    source_launch_readiness_route: str
    source_launch_readiness_overall_status: str
    source_validation_packet_command: str
    source_validation_packet_route: str
    source_validation_packet_overall_status: str
    source_preflight_command: str
    source_preflight_route: str
    source_preflight_overall_status: str
    source_binder_command: str
    source_binder_route: str
    source_binder_overall_status: str
    provider_accounts: list[ProviderAccountItemResponse] = Field(default_factory=list)
    required_credentials: list[NamedPresenceResponse] = Field(default_factory=list)
    required_configs: list[NamedPresenceResponse] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    missing_config_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    owner_decisions: list[OwnerDecisionItemResponse] = Field(default_factory=list)
    budget_rate_limits: list[BudgetRateLimitItemResponse] = Field(default_factory=list)
    compliance_prerequisites: list[CompliancePrerequisiteResponse] = Field(default_factory=list)
    validation_run_constraints: list[ValidationRunConstraintResponse] = Field(default_factory=list)
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    local_git: LocalGitMetadataResponse
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE
    next_actions: list[OwnerNextStepResponse] = Field(default_factory=list)


def build_live_provider_setup_checklist_response(
    db: Session,
    settings: Settings,
    *,
    service: LiveProviderSetupChecklistService | None = None,
) -> LiveProviderSetupChecklistResponse:
    builder = service or LiveProviderSetupChecklistService()
    return LiveProviderSetupChecklistResponse.model_validate(
        live_provider_setup_checklist_payload(builder.build(db, settings))
    )
