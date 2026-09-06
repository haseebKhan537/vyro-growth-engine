"""Read-only provider credential/setup checklist export.

Phase 49 consolidates existing launch-readiness, go-live index, launch-blocker,
staged-rollout, owner-launch-dossier, settings-preflight, and release-candidate
runbook surfaces into one sanitized provider credential/setup checklist. It
reuses those services as source material and never recalculates readiness. It
never executes, applies settings, lifts halt, enables outbound, calls
providers, builds, publishes, deploys, or changes live state. This checklist
is not permission to go live and is not an execution surface.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity, NextActionCode, SecretName, SecretPresenceStatus
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
from vyro_growth.services.go_live_readiness_index import (
    CLI_COMMAND as INDEX_CLI_COMMAND,
)
from vyro_growth.services.go_live_readiness_index import (
    HTTP_ROUTE as INDEX_HTTP_ROUTE,
)
from vyro_growth.services.launch_blockers_plan import (
    CLI_COMMAND as BLOCKERS_CLI_COMMAND,
)
from vyro_growth.services.launch_blockers_plan import (
    HTTP_ROUTE as BLOCKERS_HTTP_ROUTE,
)
from vyro_growth.services.launch_readiness import (
    LaunchReadinessChecklist,
    LaunchReadinessService,
    SecretInventoryItem,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.owner_launch_dossier import (
    CLI_COMMAND as DOSSIER_CLI_COMMAND,
)
from vyro_growth.services.owner_launch_dossier import (
    HTTP_ROUTE as DOSSIER_HTTP_ROUTE,
)
from vyro_growth.services.owner_launch_dossier import OwnerLaunchDossier, OwnerLaunchDossierService
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.release_candidate_runbook import (
    CLI_COMMAND as RUNBOOK_CLI_COMMAND,
)
from vyro_growth.services.release_candidate_runbook import (
    HTTP_ROUTE as RUNBOOK_HTTP_ROUTE,
)
from vyro_growth.services.staged_rollout_plan import (
    CLI_COMMAND as STAGED_CLI_COMMAND,
)
from vyro_growth.services.staged_rollout_plan import (
    HTTP_ROUTE as STAGED_HTTP_ROUTE,
)
from vyro_growth.services.staged_rollout_plan import (
    LAUNCH_READINESS_COMMAND,
    LAUNCH_READINESS_ROUTE,
)

logger = structlog.get_logger(__name__)

PACKET_KIND = "provider_setup_checklist"
PACKET_PURPOSE = "manual_owner_provider_setup_review_only"
CHECKLIST_NOT_GO_LIVE_CODE = NextActionCode.PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
CLI_COMMAND = "provider-setup-checklist"
HTTP_ROUTE = "/internal/provider-setup-checklist"
HTML_ROUTE = "/internal/operator-provider-setup-checklist"
PREFLIGHT_CLI_COMMAND = "settings-execution-preflight"
PREFLIGHT_HTTP_ROUTE = "/internal/settings-execution-preflight"
DOSSIER_HTML_ROUTE = "/internal/operator-owner-launch-dossier"
INDEX_HTML_ROUTE = "/internal/operator-go-live-readiness-index"
BLOCKERS_HTML_ROUTE = "/internal/operator-launch-blockers-plan"
STAGED_HTML_ROUTE = "/internal/operator-staged-rollout-plan"
PREFLIGHT_HTML_ROUTE = "/internal/operator-settings-execution-preflight"
RUNBOOK_HTML_ROUTE = "/internal/operator-release-candidate-runbook"
OWNER_APPROVAL_TYPES: tuple[str, ...] = (
    "none",
    "owner_review",
    "owner_approval_packet",
    "settings_change_request",
    "live_enablement_review",
)
CATEGORY_KEYS: tuple[str, ...] = (
    "email_outreach",
    "enrichment",
    "calendar",
    "voice",
    "ads_analytics",
    "deployment",
    "database_storage",
)
RELATED_COMMANDS: tuple[str, ...] = (
    LAUNCH_READINESS_COMMAND,
    INDEX_CLI_COMMAND,
    BLOCKERS_CLI_COMMAND,
    STAGED_CLI_COMMAND,
    DOSSIER_CLI_COMMAND,
    PREFLIGHT_CLI_COMMAND,
    RUNBOOK_CLI_COMMAND,
    "check-config",
    "smoke-dry-run",
    CLI_COMMAND,
    "go-live-rehearsal-checklist",
    "rehearsal-outcome-report",
    "supervised-pilot-plan",
    "system-status",
)
RELATED_ROUTES: tuple[str, ...] = (
    LAUNCH_READINESS_ROUTE,
    INDEX_HTML_ROUTE,
    INDEX_HTTP_ROUTE,
    BLOCKERS_HTML_ROUTE,
    BLOCKERS_HTTP_ROUTE,
    STAGED_HTML_ROUTE,
    STAGED_HTTP_ROUTE,
    DOSSIER_HTML_ROUTE,
    DOSSIER_HTTP_ROUTE,
    PREFLIGHT_HTML_ROUTE,
    PREFLIGHT_HTTP_ROUTE,
    RUNBOOK_HTML_ROUTE,
    RUNBOOK_HTTP_ROUTE,
    HTML_ROUTE,
    HTTP_ROUTE,
    "/internal/operator-go-live-rehearsal-checklist",
    "/internal/go-live-rehearsal-checklist",
    "/internal/operator-rehearsal-outcome-report",
    "/internal/rehearsal-outcome-report",
    "/internal/operator-supervised-pilot-plan",
    "/internal/supervised-pilot-plan",
    "/internal/operator-supervised-pilot-candidates",
    "/internal/supervised-pilot-candidates",
    "/internal/operator-supervised-pilot-go-no-go",
    "/internal/supervised-pilot-go-no-go",
)
_STATUS_RANK = {
    FindingSeverity.INFO.value: 0,
    "ready_for_owner_review": 1,
    "open": 1,
    "missing": 2,
    "closed": 2,
    FindingSeverity.WARNING.value: 2,
    FindingSeverity.BLOCKED.value: 3,
}
OwnerApprovalType = Literal[
    "none",
    "owner_review",
    "owner_approval_packet",
    "settings_change_request",
    "live_enablement_review",
]


@dataclass(frozen=True)
class _CategorySpec:
    key: str
    label: str
    credential_names: tuple[str, ...]
    flag_names: tuple[str, ...]
    planned_config_names: tuple[str, ...]
    default_approval: OwnerApprovalType
    command_name: str
    json_route: str
    html_route: str | None


CATEGORY_SPECS: tuple[_CategorySpec, ...] = (
    _CategorySpec(
        key="email_outreach",
        label="Email / outreach",
        credential_names=(SecretName.OPENAI_API_KEY.value, SecretName.SMARTLEAD_API_KEY.value),
        flag_names=(
            "OUTBOUND_ENABLED",
            "OPENAI_PERSONALIZATION_ENABLED",
            "SMARTLEAD_LIVE_ENABLED",
            "OPENAI_REPLY_CLASSIFICATION_ENABLED",
        ),
        planned_config_names=(),
        default_approval="live_enablement_review",
        command_name=LAUNCH_READINESS_COMMAND,
        json_route=LAUNCH_READINESS_ROUTE,
        html_route=LAUNCH_READINESS_ROUTE,
    ),
    _CategorySpec(
        key="enrichment",
        label="Enrichment",
        credential_names=(),
        flag_names=(),
        planned_config_names=(
            "CONTACT_ENRICHMENT_API_KEY",
            "CONTACT_ENRICHMENT_API_BASE_URL",
        ),
        default_approval="live_enablement_review",
        command_name=LAUNCH_READINESS_COMMAND,
        json_route=LAUNCH_READINESS_ROUTE,
        html_route=LAUNCH_READINESS_ROUTE,
    ),
    _CategorySpec(
        key="calendar",
        label="Calendar",
        credential_names=(SecretName.GOOGLE_CALENDAR_API_KEY.value,),
        flag_names=("GOOGLE_CALENDAR_LIVE_ENABLED",),
        planned_config_names=(),
        default_approval="live_enablement_review",
        command_name=LAUNCH_READINESS_COMMAND,
        json_route=LAUNCH_READINESS_ROUTE,
        html_route=LAUNCH_READINESS_ROUTE,
    ),
    _CategorySpec(
        key="voice",
        label="Voice",
        credential_names=(SecretName.VOICE_API_KEY.value,),
        flag_names=("VOICE_LIVE_ENABLED",),
        planned_config_names=(),
        default_approval="live_enablement_review",
        command_name=LAUNCH_READINESS_COMMAND,
        json_route=LAUNCH_READINESS_ROUTE,
        html_route=LAUNCH_READINESS_ROUTE,
    ),
    _CategorySpec(
        key="ads_analytics",
        label="Ads / analytics",
        credential_names=(),
        flag_names=(),
        planned_config_names=(),
        default_approval="live_enablement_review",
        command_name=STAGED_CLI_COMMAND,
        json_route=STAGED_HTTP_ROUTE,
        html_route=STAGED_HTML_ROUTE,
    ),
    _CategorySpec(
        key="deployment",
        label="Deployment",
        credential_names=(SecretName.INTERNAL_API_KEY.value,),
        flag_names=(),
        planned_config_names=(),
        default_approval="owner_review",
        command_name=RUNBOOK_CLI_COMMAND,
        json_route=RUNBOOK_HTTP_ROUTE,
        html_route=RUNBOOK_HTML_ROUTE,
    ),
    _CategorySpec(
        key="database_storage",
        label="Database / storage",
        credential_names=(SecretName.DATABASE_URL.value,),
        flag_names=(),
        planned_config_names=(),
        default_approval="settings_change_request",
        command_name="check-config",
        json_route=LAUNCH_READINESS_ROUTE,
        html_route=LAUNCH_READINESS_ROUTE,
    ),
)


@dataclass(frozen=True)
class ProviderCredentialStatus:
    name: str
    present: bool
    status: str
    required: bool


@dataclass(frozen=True)
class ProviderFlagState:
    name: str
    enabled: bool


@dataclass(frozen=True)
class ProviderSetupCategory:
    key: str
    label: str
    overall_status: str
    required_owner_approval_type: str
    config_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    credential_statuses: tuple[ProviderCredentialStatus, ...]
    flag_states: tuple[ProviderFlagState, ...]
    blocker_codes: tuple[str, ...]
    gate_codes: tuple[str, ...]
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    preparation_label: str
    read_only: bool
    no_execution: bool
    go_live_permitted: bool
    deployment_allowed: bool


@dataclass(frozen=True)
class LocalVerificationGate:
    code: str
    status: str
    label: str
    command_name: str | None
    json_route: str | None


@dataclass(frozen=True)
class ProviderSetupNextAction:
    code: str
    status: str
    label: str
    command_name: str | None
    json_route: str | None
    html_route: str | None
    config_name: str | None


@dataclass(frozen=True)
class ProviderSetupChecklist:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
    no_execution: bool
    no_go_live: bool
    no_deployment: bool
    dry_run_only: bool
    executed: int
    execution_attempted: bool
    outbound_attempted: bool
    live_call_attempted: bool
    recommendation_applied: bool
    spend_attempted: bool
    campaign_launched: bool
    pages_published: bool
    ads_launched: bool
    owner_approved: bool
    settings_applied: bool
    halt_changed: bool
    live_action: bool
    execution_allowed: bool
    future_execution_phase_exists: bool
    future_deployment_phase_exists: bool
    go_live_permitted: bool
    deployment_allowed: bool
    deployment_attempted: bool
    deployed: bool
    build_allowed: bool
    artifact_publish_allowed: bool
    container_build_attempted: bool
    artifact_publish_attempted: bool
    outbound_enabled: bool
    live_providers_enabled: bool
    manual_review_only: bool
    provider_setup_checklist_is_not_go_live: bool
    checklist_is_not_permission_to_go_live: bool
    checklist_is_not_execution: bool
    index_is_not_permission_to_go_live: bool
    dossier_is_not_permission_to_go_live: bool
    staged_rollout_plan_is_not_go_live: bool
    runbook_is_not_deployment: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    closed_provider_flag_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    gate_codes: tuple[str, ...]
    cli_command: str
    http_route: str
    source_launch_readiness_command: str
    source_launch_readiness_route: str
    source_launch_readiness_overall_status: str
    source_index_command: str
    source_index_route: str
    source_index_overall_status: str
    source_blockers_plan_command: str
    source_blockers_plan_route: str
    source_blockers_plan_overall_status: str
    source_staged_rollout_command: str
    source_staged_rollout_route: str
    source_staged_rollout_overall_status: str
    source_dossier_command: str
    source_dossier_route: str
    source_dossier_overall_status: str
    source_preflight_command: str
    source_preflight_route: str
    source_preflight_overall_status: str
    source_runbook_command: str
    source_runbook_route: str
    source_runbook_overall_status: str
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    categories: tuple[ProviderSetupCategory, ...]
    local_verification_gates: tuple[LocalVerificationGate, ...]
    next_actions: tuple[ProviderSetupNextAction, ...]


class ProviderSetupChecklistService:
    """Compose existing read-only exports into a provider setup checklist."""

    def __init__(
        self,
        *,
        owner_dossier: OwnerLaunchDossierService | None = None,
        launch_readiness: LaunchReadinessService | None = None,
    ) -> None:
        self.owner_dossier = owner_dossier or OwnerLaunchDossierService()
        self.launch_readiness = launch_readiness or LaunchReadinessService()

    def build(self, db: Session, settings: Settings) -> ProviderSetupChecklist:
        halt_before = read_operator_halt(db)
        dossier = self.owner_dossier.build(db, settings)
        launch = self.launch_readiness.assess(db, settings)
        halt_after = read_operator_halt(db)
        if halt_after != halt_before:
            raise RuntimeError("provider setup checklist must not change operator halt status")
        inventory = {item.name: item for item in launch.secret_inventory}
        flags = {item.name: item.enabled for item in launch.config_flags}
        categories = _categories(inventory, flags, dossier)
        gates = _local_verification_gates(launch, dossier)
        next_actions = _next_actions(dossier, launch, categories)
        missing_credentials = _unique_sorted(
            (
                *dossier.missing_credential_names,
                *(name for category in categories for name in category.missing_credential_names),
            )
        )
        closed_flags = _unique_sorted(
            (
                *dossier.closed_provider_flag_names,
                *(name for category in categories for name in category.closed_provider_flag_names),
            )
        )
        blocker_codes = _unique_sorted(
            (
                *dossier.blocker_codes,
                *(code for category in categories for code in category.blocker_codes),
                *(action.code for action in next_actions),
            )
        )
        gate_codes = _unique_sorted(
            (
                *dossier.gate_codes,
                *(code for category in categories for code in category.gate_codes),
                *(gate.code for gate in gates),
                "outbound_disabled",
                "operator_halt",
                "live_providers_disabled",
                "no_execution",
                "no_go_live",
                "no_deployment",
                "no_provider_calls",
            )
        )
        checklist = ProviderSetupChecklist(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=_worst_status(
                dossier.overall_status,
                launch.overall_status,
                *(category.overall_status for category in categories),
            ),
            read_only=True,
            no_execution=True,
            no_go_live=True,
            no_deployment=True,
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
            build_allowed=False,
            artifact_publish_allowed=False,
            container_build_attempted=False,
            artifact_publish_attempted=False,
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=dossier.live_providers_enabled,
            manual_review_only=True,
            provider_setup_checklist_is_not_go_live=True,
            checklist_is_not_permission_to_go_live=True,
            checklist_is_not_execution=True,
            index_is_not_permission_to_go_live=True,
            dossier_is_not_permission_to_go_live=True,
            staged_rollout_plan_is_not_go_live=True,
            runbook_is_not_deployment=True,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            closed_provider_flag_names=closed_flags,
            missing_credential_names=missing_credentials,
            blocker_codes=blocker_codes,
            gate_codes=gate_codes,
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
            source_launch_readiness_command=LAUNCH_READINESS_COMMAND,
            source_launch_readiness_route=LAUNCH_READINESS_ROUTE,
            source_launch_readiness_overall_status=launch.overall_status,
            source_index_command=INDEX_CLI_COMMAND,
            source_index_route=INDEX_HTTP_ROUTE,
            source_index_overall_status=dossier.source_index_overall_status,
            source_blockers_plan_command=BLOCKERS_CLI_COMMAND,
            source_blockers_plan_route=BLOCKERS_HTTP_ROUTE,
            source_blockers_plan_overall_status=dossier.source_blockers_plan_overall_status,
            source_staged_rollout_command=STAGED_CLI_COMMAND,
            source_staged_rollout_route=STAGED_HTTP_ROUTE,
            source_staged_rollout_overall_status=dossier.source_staged_rollout_overall_status,
            source_dossier_command=DOSSIER_CLI_COMMAND,
            source_dossier_route=DOSSIER_HTTP_ROUTE,
            source_dossier_overall_status=dossier.overall_status,
            source_preflight_command=PREFLIGHT_CLI_COMMAND,
            source_preflight_route=PREFLIGHT_HTTP_ROUTE,
            source_preflight_overall_status=dossier.source_preflight_overall_status,
            source_runbook_command=RUNBOOK_CLI_COMMAND,
            source_runbook_route=RUNBOOK_HTTP_ROUTE,
            source_runbook_overall_status=dossier.source_runbook_overall_status,
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            local_git=dossier.local_git,
            categories=categories,
            local_verification_gates=gates,
            next_actions=next_actions,
        )
        logger.info(
            "provider_setup_checklist_built",
            read_only=True,
            no_execution=True,
            no_go_live=True,
            no_deployment=True,
            overall_status=checklist.overall_status,
            operator_halt_status=checklist.operator_halt_status,
            outbound_enabled=checklist.outbound_enabled,
            go_live_permitted=False,
            execution_allowed=False,
            deployment_allowed=False,
            settings_applied=False,
            halt_changed=False,
            owner_approved=False,
            provider_setup_checklist_is_not_go_live=True,
        )
        return checklist


def _categories(
    inventory: dict[str, SecretInventoryItem],
    flags: dict[str, bool],
    dossier: OwnerLaunchDossier,
) -> tuple[ProviderSetupCategory, ...]:
    return tuple(_category(spec, inventory, flags, dossier) for spec in CATEGORY_SPECS)


def _category(
    spec: _CategorySpec,
    inventory: dict[str, SecretInventoryItem],
    flags: dict[str, bool],
    dossier: OwnerLaunchDossier,
) -> ProviderSetupCategory:
    credential_statuses = tuple(
        _credential_status(name, inventory) for name in spec.credential_names
    )
    flag_states = tuple(
        ProviderFlagState(name=_safe_text(name), enabled=bool(flags.get(name, False)))
        for name in spec.flag_names
    )
    missing = _unique_sorted(
        item.name for item in credential_statuses if item.required and not item.present
    )
    closed_flags = _unique_sorted(item.name for item in flag_states if not item.enabled)
    config_names = _unique_sorted(
        (*spec.credential_names, *spec.flag_names, *spec.planned_config_names)
    )
    status = FindingSeverity.INFO.value
    if missing:
        status = FindingSeverity.BLOCKED.value
    approval = spec.default_approval
    if missing:
        approval = "settings_change_request"
    blocker_codes = _unique_sorted(
        (
            CHECKLIST_NOT_GO_LIVE_CODE,
            NextActionCode.CONFIGURE_REQUIRED_CREDENTIALS.value if missing else "",
            NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value if closed_flags else "",
        )
    )
    return ProviderSetupCategory(
        key=_safe_text(spec.key),
        label=_safe_text(spec.label),
        overall_status=status,
        required_owner_approval_type=_safe_approval(approval),
        config_names=config_names,
        missing_credential_names=missing,
        closed_provider_flag_names=closed_flags,
        credential_statuses=credential_statuses,
        flag_states=flag_states,
        blocker_codes=blocker_codes,
        gate_codes=_unique_sorted(
            (
                "required_credentials" if spec.credential_names else "",
                "closed_provider_flags" if spec.flag_names else "",
                "planned_config_names" if spec.planned_config_names else "",
                "no_provider_calls",
            )
        ),
        related_commands=_unique_sorted((spec.command_name, CLI_COMMAND, "check-config")),
        related_routes=_unique_sorted(
            route for route in (spec.json_route, spec.html_route, HTTP_ROUTE) if route
        ),
        preparation_label=_preparation_label(spec, missing, closed_flags, dossier),
        read_only=True,
        no_execution=True,
        go_live_permitted=False,
        deployment_allowed=False,
    )


def _credential_status(
    name: str, inventory: dict[str, SecretInventoryItem]
) -> ProviderCredentialStatus:
    item = inventory.get(name)
    if item is None:
        return ProviderCredentialStatus(
            name=_safe_text(name),
            present=False,
            status=SecretPresenceStatus.MISSING.value,
            required=False,
        )
    present = bool(item.present)
    return ProviderCredentialStatus(
        name=_safe_text(item.name),
        present=present,
        status=(
            SecretPresenceStatus.REDACTED.value if present else SecretPresenceStatus.MISSING.value
        ),
        required=bool(item.required),
    )


def _preparation_label(
    spec: _CategorySpec,
    missing: Sequence[str],
    closed_flags: Sequence[str],
    dossier: OwnerLaunchDossier,
) -> str:
    if missing:
        names = ",".join(missing)
        return _safe_text(
            f"Prepare credential variable names {names} in local env later. "
            "This checklist lists names only and never shows values."
        )
    if spec.planned_config_names:
        names = ",".join(spec.planned_config_names)
        return _safe_text(
            f"Review planned config names {names} later. This checklist "
            "does not read those values and does not enable a live provider."
        )
    if spec.key == "ads_analytics":
        return _safe_text(
            "No live ads or analytics provider credentials are configured "
            "in this phase. This checklist does not enable ads, Search "
            "Console, or Analytics."
        )
    if closed_flags:
        return _safe_text(
            f"Keep {spec.label} live flags closed. This checklist does "
            "not enable providers or change live settings."
        )
    if spec.key == "deployment":
        return _safe_text(
            "Review local dry-run and deploy-config gates later. This "
            "checklist does not deploy, build, or call GitHub Actions."
        )
    _ = dossier
    return _safe_text(
        f"Review {spec.label} config names only. This checklist does not "
        "execute, apply settings, or permit go-live."
    )


def _local_verification_gates(
    launch: LaunchReadinessChecklist,
    dossier: OwnerLaunchDossier,
) -> tuple[LocalVerificationGate, ...]:
    smoke = launch.ci_smoke_gate
    smoke_status = FindingSeverity.INFO.value
    if not smoke.present:
        smoke_status = FindingSeverity.BLOCKED.value
    elif not smoke.documented:
        smoke_status = FindingSeverity.WARNING.value
    halt_ok = dossier.operator_halt_status == HaltStatus.HALTED.value
    outbound_ok = not launch.outbound_enabled
    return (
        LocalVerificationGate(
            code="ci_smoke_gate",
            status=smoke_status,
            label=_safe_text(
                "Review the local smoke-dry-run CI gate name and command. "
                "This checklist does not run CI or call GitHub Actions."
            ),
            command_name="smoke-dry-run",
            json_route=LAUNCH_READINESS_ROUTE,
        ),
        LocalVerificationGate(
            code="deploy_config_gate",
            status=FindingSeverity.INFO.value,
            label=_safe_text(
                "Review the deploy-config / check-config gate name. This "
                "checklist does not deploy or apply live settings."
            ),
            command_name="check-config",
            json_route=LAUNCH_READINESS_ROUTE,
        ),
        LocalVerificationGate(
            code="outbound_disabled",
            status=FindingSeverity.INFO.value if outbound_ok else FindingSeverity.BLOCKED.value,
            label=_safe_text(
                "Verify OUTBOUND_ENABLED remains false. This checklist does not enable outbound."
            ),
            command_name=LAUNCH_READINESS_COMMAND,
            json_route=LAUNCH_READINESS_ROUTE,
        ),
        LocalVerificationGate(
            code="operator_halt",
            status=FindingSeverity.INFO.value if halt_ok else FindingSeverity.WARNING.value,
            label=_safe_text(
                "Verify operator halt remains unchanged. This checklist does not lift halt."
            ),
            command_name="system-status",
            json_route="/internal/monitoring/status",
        ),
    )


def _next_actions(
    dossier: OwnerLaunchDossier,
    launch: LaunchReadinessChecklist,
    categories: Sequence[ProviderSetupCategory],
) -> tuple[ProviderSetupNextAction, ...]:
    halt_ok = dossier.operator_halt_status == HaltStatus.HALTED.value
    outbound_ok = not launch.outbound_enabled
    missing = _unique_sorted(
        name for category in categories for name in category.missing_credential_names
    )
    actions = [
        _action(
            CHECKLIST_NOT_GO_LIVE_CODE,
            FindingSeverity.INFO.value,
            (
                "This provider setup checklist is a sanitized review export "
                "only. It is not permission to go live and is not an "
                "execution surface."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            EXECUTION_DISABLED_CODE,
            FindingSeverity.INFO.value,
            (
                "Execution remains disabled. This checklist does not apply "
                "settings, lift halt, enable outbound, deploy, or call providers."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            FindingSeverity.INFO.value if outbound_ok else FindingSeverity.BLOCKED.value,
            "Verify OUTBOUND_ENABLED remains false. This checklist does not enable outbound.",
            command_name=LAUNCH_READINESS_COMMAND,
            json_route=LAUNCH_READINESS_ROUTE,
            html_route=LAUNCH_READINESS_ROUTE,
            config_name="OUTBOUND_ENABLED",
        ),
        _action(
            (
                NextActionCode.KEEP_OPERATOR_HALT.value
                if halt_ok
                else NextActionCode.RECORD_OPERATOR_HALT.value
            ),
            FindingSeverity.INFO.value if halt_ok else FindingSeverity.WARNING.value,
            (
                "Verify operator halt remains halted. This checklist does "
                "not change operator halt state."
            ),
            command_name="system-status",
            json_route="/internal/monitoring/status",
        ),
        _action(
            NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
            FindingSeverity.INFO.value,
            (
                "Keep every live-provider flag disabled. This checklist "
                "lists flag names only and does not enable providers."
            ),
            command_name=LAUNCH_READINESS_COMMAND,
            json_route=LAUNCH_READINESS_ROUTE,
            html_route=LAUNCH_READINESS_ROUTE,
        ),
        _action(
            NextActionCode.OWNER_LAUNCH_DOSSIER_IS_NOT_GO_LIVE.value,
            dossier.overall_status,
            (
                "Review the owner launch dossier. Read-only owner-review "
                "export; it is not permission to go live."
            ),
            command_name=DOSSIER_CLI_COMMAND,
            json_route=DOSSIER_HTTP_ROUTE,
            html_route=DOSSIER_HTML_ROUTE,
        ),
    ]
    if missing:
        actions.append(
            _action(
                NextActionCode.CONFIGURE_REQUIRED_CREDENTIALS.value,
                FindingSeverity.BLOCKED.value,
                (
                    "Prepare named required credentials in local env later. "
                    "This checklist lists variable names only and never "
                    "shows values."
                ),
                command_name=LAUNCH_READINESS_COMMAND,
                json_route=LAUNCH_READINESS_ROUTE,
                html_route=LAUNCH_READINESS_ROUTE,
            )
        )
    for category in categories:
        actions.append(
            _action(
                f"prepare_{category.key}",
                category.overall_status,
                category.preparation_label,
                command_name=(
                    category.related_commands[0] if category.related_commands else CLI_COMMAND
                ),
                json_route=category.related_routes[0] if category.related_routes else HTTP_ROUTE,
                config_name=category.config_names[0] if category.config_names else None,
            )
        )
    return tuple(actions)


def _action(
    code: str,
    status: str,
    label: str,
    *,
    command_name: str | None = None,
    json_route: str | None = None,
    html_route: str | None = None,
    config_name: str | None = None,
) -> ProviderSetupNextAction:
    return ProviderSetupNextAction(
        code=_safe_text(code),
        status=_safe_text(status) or FindingSeverity.INFO.value,
        label=_safe_text(label),
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
        config_name=_safe_optional(config_name),
    )


def _safe_approval(value: str) -> str:
    cleaned = _safe_text(value)
    if cleaned in OWNER_APPROVAL_TYPES:
        return cleaned
    return "owner_review"


def _worst_status(*values: str) -> str:
    cleaned = [_safe_text(item) for item in values if item]
    if not cleaned:
        return FindingSeverity.INFO.value
    return max(cleaned, key=lambda item: _STATUS_RANK.get(item, 0))


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    cleaned = [_safe_text(item) for item in values]
    return tuple(sorted({item for item in cleaned if item}))


def _safe_optional(value: str | None) -> str | None:
    cleaned = _safe_text(value) if value is not None else ""
    return cleaned or None


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    text = sanitize_operator_text(str(value))
    return text or ""


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def checklist_payload(checklist: ProviderSetupChecklist) -> dict[str, Any]:
    return {
        "generated_at": checklist.generated_at.isoformat(),
        "packet_kind": checklist.packet_kind,
        "purpose": checklist.purpose,
        "overall_status": checklist.overall_status,
        "read_only": True,
        "no_execution": True,
        "no_go_live": True,
        "no_deployment": True,
        "dry_run_only": True,
        "executed": 0,
        "execution_attempted": False,
        "outbound_attempted": False,
        "live_call_attempted": False,
        "recommendation_applied": False,
        "spend_attempted": False,
        "campaign_launched": False,
        "pages_published": False,
        "ads_launched": False,
        "owner_approved": False,
        "settings_applied": False,
        "halt_changed": False,
        "live_action": False,
        "execution_allowed": False,
        "future_execution_phase_exists": False,
        "future_deployment_phase_exists": False,
        "go_live_permitted": False,
        "deployment_allowed": False,
        "deployment_attempted": False,
        "deployed": False,
        "build_allowed": False,
        "artifact_publish_allowed": False,
        "container_build_attempted": False,
        "artifact_publish_attempted": False,
        "outbound_enabled": checklist.outbound_enabled,
        "live_providers_enabled": checklist.live_providers_enabled,
        "manual_review_only": True,
        "provider_setup_checklist_is_not_go_live": True,
        "checklist_is_not_permission_to_go_live": True,
        "checklist_is_not_execution": True,
        "index_is_not_permission_to_go_live": True,
        "dossier_is_not_permission_to_go_live": True,
        "staged_rollout_plan_is_not_go_live": True,
        "runbook_is_not_deployment": True,
        "operator_halt_status": checklist.operator_halt_status,
        "operator_halt_before": checklist.operator_halt_before,
        "operator_halt_after": checklist.operator_halt_after,
        "closed_provider_flag_names": list(checklist.closed_provider_flag_names),
        "missing_credential_names": list(checklist.missing_credential_names),
        "blocker_codes": list(checklist.blocker_codes),
        "gate_codes": list(checklist.gate_codes),
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "source_launch_readiness_command": checklist.source_launch_readiness_command,
        "source_launch_readiness_route": checklist.source_launch_readiness_route,
        "source_launch_readiness_overall_status": (
            checklist.source_launch_readiness_overall_status
        ),
        "source_index_command": checklist.source_index_command,
        "source_index_route": checklist.source_index_route,
        "source_index_overall_status": checklist.source_index_overall_status,
        "source_blockers_plan_command": checklist.source_blockers_plan_command,
        "source_blockers_plan_route": checklist.source_blockers_plan_route,
        "source_blockers_plan_overall_status": checklist.source_blockers_plan_overall_status,
        "source_staged_rollout_command": checklist.source_staged_rollout_command,
        "source_staged_rollout_route": checklist.source_staged_rollout_route,
        "source_staged_rollout_overall_status": checklist.source_staged_rollout_overall_status,
        "source_dossier_command": checklist.source_dossier_command,
        "source_dossier_route": checklist.source_dossier_route,
        "source_dossier_overall_status": checklist.source_dossier_overall_status,
        "source_preflight_command": checklist.source_preflight_command,
        "source_preflight_route": checklist.source_preflight_route,
        "source_preflight_overall_status": checklist.source_preflight_overall_status,
        "source_runbook_command": checklist.source_runbook_command,
        "source_runbook_route": checklist.source_runbook_route,
        "source_runbook_overall_status": checklist.source_runbook_overall_status,
        "related_commands": list(checklist.related_commands),
        "related_routes": list(checklist.related_routes),
        "local_git": {
            "available": checklist.local_git.available,
            "current_branch": checklist.local_git.current_branch,
            "current_sha": checklist.local_git.current_sha,
            "working_tree_status": checklist.local_git.working_tree_status,
            "git_provider_called": False,
            "github_actions_called": False,
        },
        "categories": [_category_payload(category) for category in checklist.categories],
        "local_verification_gates": [
            _gate_payload(gate) for gate in checklist.local_verification_gates
        ],
        "next_actions": [_action_payload(action) for action in checklist.next_actions],
    }


def _category_payload(category: ProviderSetupCategory) -> dict[str, Any]:
    return {
        "key": category.key,
        "label": category.label,
        "overall_status": category.overall_status,
        "required_owner_approval_type": category.required_owner_approval_type,
        "config_names": list(category.config_names),
        "missing_credential_names": list(category.missing_credential_names),
        "closed_provider_flag_names": list(category.closed_provider_flag_names),
        "credential_statuses": [
            {
                "name": item.name,
                "present": item.present,
                "status": item.status,
                "required": item.required,
            }
            for item in category.credential_statuses
        ],
        "flag_states": [
            {"name": item.name, "enabled": item.enabled} for item in category.flag_states
        ],
        "blocker_codes": list(category.blocker_codes),
        "gate_codes": list(category.gate_codes),
        "related_commands": list(category.related_commands),
        "related_routes": list(category.related_routes),
        "preparation_label": category.preparation_label,
        "read_only": True,
        "no_execution": True,
        "go_live_permitted": False,
        "deployment_allowed": False,
    }


def _gate_payload(gate: LocalVerificationGate) -> dict[str, Any]:
    return {
        "code": gate.code,
        "status": gate.status,
        "label": gate.label,
        "command_name": gate.command_name,
        "json_route": gate.json_route,
    }


def _action_payload(action: ProviderSetupNextAction) -> dict[str, Any]:
    return {
        "code": action.code,
        "status": action.status,
        "label": action.label,
        "command_name": action.command_name,
        "json_route": action.json_route,
        "html_route": action.html_route,
        "config_name": action.config_name,
    }


def format_provider_setup_checklist(
    checklist: ProviderSetupChecklist,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(checklist_payload(checklist))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(checklist, payload)


def _format_markdown(checklist: ProviderSetupChecklist, payload: dict[str, Any]) -> str:
    lines = [
        "# Provider setup checklist",
        "",
        "This checklist is a sanitized owner/operator review export of "
        "existing launch-readiness, go-live index, launch-blocker, "
        "staged-rollout, owner-launch-dossier, settings-preflight, and "
        "release-candidate runbook surfaces. It is not permission to go "
        "live and is not an execution surface.",
        "",
        f"- overall: {payload['overall_status']}",
        f"- packet_kind: {payload['packet_kind']}",
        f"- purpose: {payload['purpose']}",
        f"- read_only: {_bool_text(payload['read_only'])}",
        f"- no_execution: {_bool_text(payload['no_execution'])}",
        f"- no_go_live: {_bool_text(payload['no_go_live'])}",
        f"- no_deployment: {_bool_text(payload['no_deployment'])}",
        f"- dry_run_only: {_bool_text(payload['dry_run_only'])}",
        f"- executed: {payload['executed']}",
        f"- owner_approved: {_bool_text(payload['owner_approved'])}",
        f"- settings_applied: {_bool_text(payload['settings_applied'])}",
        f"- halt_changed: {_bool_text(payload['halt_changed'])}",
        f"- live_action: {_bool_text(payload['live_action'])}",
        f"- execution_allowed: {_bool_text(payload['execution_allowed'])}",
        f"- go_live_permitted: {_bool_text(payload['go_live_permitted'])}",
        f"- deployment_allowed: {_bool_text(payload['deployment_allowed'])}",
        f"- deployment_attempted: {_bool_text(payload['deployment_attempted'])}",
        f"- deployed: {_bool_text(payload['deployed'])}",
        f"- build_allowed: {_bool_text(payload['build_allowed'])}",
        f"- artifact_publish_allowed: {_bool_text(payload['artifact_publish_allowed'])}",
        f"- manual_review_only: {_bool_text(payload['manual_review_only'])}",
        (
            "- provider_setup_checklist_is_not_go_live: "
            f"{_bool_text(payload['provider_setup_checklist_is_not_go_live'])}"
        ),
        (
            "- checklist_is_not_permission_to_go_live: "
            f"{_bool_text(payload['checklist_is_not_permission_to_go_live'])}"
        ),
        f"- checklist_is_not_execution: {_bool_text(payload['checklist_is_not_execution'])}",
        (
            "- index_is_not_permission_to_go_live: "
            f"{_bool_text(payload['index_is_not_permission_to_go_live'])}"
        ),
        (
            "- dossier_is_not_permission_to_go_live: "
            f"{_bool_text(payload['dossier_is_not_permission_to_go_live'])}"
        ),
        (
            "- staged_rollout_plan_is_not_go_live: "
            f"{_bool_text(payload['staged_rollout_plan_is_not_go_live'])}"
        ),
        f"- runbook_is_not_deployment: {_bool_text(payload['runbook_is_not_deployment'])}",
        (
            "- future_execution_phase_exists: "
            f"{_bool_text(payload['future_execution_phase_exists'])}"
        ),
        (
            "- future_deployment_phase_exists: "
            f"{_bool_text(payload['future_deployment_phase_exists'])}"
        ),
        (
            "- operator_halt: "
            f"status={payload['operator_halt_status']} "
            f"before={payload['operator_halt_before']} "
            f"after={payload['operator_halt_after']}"
        ),
        f"- outbound_enabled: {_bool_text(payload['outbound_enabled'])}",
        f"- live_providers_enabled: {_bool_text(payload['live_providers_enabled'])}",
        f"- cli_command: {payload['cli_command']}",
        f"- http_route: {payload['http_route']}",
        f"- source_launch_readiness_command: {payload['source_launch_readiness_command']}",
        f"- source_launch_readiness_route: {payload['source_launch_readiness_route']}",
        (
            "- source_launch_readiness_overall_status: "
            f"{payload['source_launch_readiness_overall_status']}"
        ),
        f"- source_index_command: {payload['source_index_command']}",
        f"- source_index_route: {payload['source_index_route']}",
        f"- source_index_overall_status: {payload['source_index_overall_status']}",
        f"- source_blockers_plan_command: {payload['source_blockers_plan_command']}",
        f"- source_blockers_plan_route: {payload['source_blockers_plan_route']}",
        (
            "- source_blockers_plan_overall_status: "
            f"{payload['source_blockers_plan_overall_status']}"
        ),
        f"- source_staged_rollout_command: {payload['source_staged_rollout_command']}",
        f"- source_staged_rollout_route: {payload['source_staged_rollout_route']}",
        (
            "- source_staged_rollout_overall_status: "
            f"{payload['source_staged_rollout_overall_status']}"
        ),
        f"- source_dossier_command: {payload['source_dossier_command']}",
        f"- source_dossier_route: {payload['source_dossier_route']}",
        f"- source_dossier_overall_status: {payload['source_dossier_overall_status']}",
        f"- source_preflight_command: {payload['source_preflight_command']}",
        f"- source_preflight_route: {payload['source_preflight_route']}",
        f"- source_preflight_overall_status: {payload['source_preflight_overall_status']}",
        f"- source_runbook_command: {payload['source_runbook_command']}",
        f"- source_runbook_route: {payload['source_runbook_route']}",
        f"- source_runbook_overall_status: {payload['source_runbook_overall_status']}",
        f"- blocker_codes: {_format_codes(checklist.blocker_codes)}",
        f"- gate_codes: {_format_codes(checklist.gate_codes)}",
        f"- missing_credential_names: {_format_codes(checklist.missing_credential_names)}",
        f"- closed_provider_flag_names: {_format_codes(checklist.closed_provider_flag_names)}",
        "",
        "## Live-blocking flags",
        f"- OUTBOUND_ENABLED={_bool_text(checklist.outbound_enabled)}",
        f"- operator_halt_status={checklist.operator_halt_status}",
        f"- live_providers_enabled={_bool_text(checklist.live_providers_enabled)}",
        "- read_only=true",
        "- no_execution=true",
        "- no_go_live=true",
        "- no_deployment=true",
        "- manual_review_only=true",
        "- execution_allowed=false",
        "- go_live_permitted=false",
        "- deployment_allowed=false",
        "- settings_applied=false",
        "- halt_changed=false",
        "- owner_approved=false",
        "- provider_setup_checklist_is_not_go_live=true",
        "- checklist_is_not_permission_to_go_live=true",
        "- checklist_is_not_execution=true",
        f"- local_git_available: {_bool_text(checklist.local_git.available)}",
        f"- current_branch: {checklist.local_git.current_branch}",
        f"- current_sha: {checklist.local_git.current_sha}",
        f"- working_tree_status: {checklist.local_git.working_tree_status}",
        f"- git_provider_called: {_bool_text(checklist.local_git.git_provider_called)}",
        f"- github_actions_called: {_bool_text(checklist.local_git.github_actions_called)}",
        "",
        "## Provider setup categories",
    ]
    for category in checklist.categories:
        lines.extend(
            [
                f"### {category.label}",
                f"- key: {category.key}",
                f"- overall_status: {category.overall_status}",
                f"- required_owner_approval_type: {category.required_owner_approval_type}",
                f"- config_names: {_format_codes(category.config_names)}",
                f"- missing_credential_names: {_format_codes(category.missing_credential_names)}",
                (
                    "- closed_provider_flag_names: "
                    f"{_format_codes(category.closed_provider_flag_names)}"
                ),
                f"- blocker_codes: {_format_codes(category.blocker_codes)}",
                f"- gate_codes: {_format_codes(category.gate_codes)}",
                f"- preparation_label: {category.preparation_label}",
                "- read_only=true",
                "- no_execution=true",
                "- go_live_permitted=false",
                "- deployment_allowed=false",
            ]
        )
        for credential in category.credential_statuses:
            lines.append(
                f"- credential {credential.name}: status={credential.status} "
                f"present={_bool_text(credential.present)} "
                f"required={_bool_text(credential.required)}"
            )
        for flag in category.flag_states:
            lines.append(f"- flag {flag.name}: enabled={_bool_text(flag.enabled)}")
    lines.extend(["", "## Local verification gates"])
    for gate in checklist.local_verification_gates:
        command_name = gate.command_name or "-"
        json_route = gate.json_route or "-"
        lines.append(
            f"- [{gate.status}] {gate.code} command={command_name} "
            f"json_route={json_route} label={gate.label}"
        )
    lines.extend(["", "## Owner next actions"])
    for action in checklist.next_actions:
        command_name = action.command_name or "-"
        json_route = action.json_route or "-"
        html_route = action.html_route or "-"
        config_name = action.config_name or "-"
        lines.append(
            f"- [{action.status}] {action.code} command={command_name} "
            f"json_route={json_route} html_route={html_route} "
            f"config_name={config_name} label={action.label}"
        )
    if not checklist.next_actions:
        lines.append("- next_actions: none")
    return "\n".join(lines)


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"
