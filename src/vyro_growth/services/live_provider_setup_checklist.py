"""Read-only owner live-provider setup checklist and credential readiness packet.

Phase 76 tells the owner which provider accounts, env/config names, spending
limits, and manual confirmations are needed before a later bounded supervised
validation can be considered. It reuses provider setup, launch readiness,
supervised validation packet, settings preflight, and compliance binder
services and never recalculates those sources of truth. It never verifies
credentials by calling providers, never enables live execution, never sends
email, enrolls campaigns, places calls, autodials, uses AI voice, books
meetings, creates Meet links, launches ads, spends, publishes, deploys,
applies settings, lifts halt, or grants owner approval. This checklist is
not permission to run a supervised validation and not an execution surface.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Never

import structlog
from sqlalchemy.orm import Session

from vyro_growth.config import Settings, credential_presence_flags
from vyro_growth.domain import FindingSeverity, NextActionCode, SecretName
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
from vyro_growth.services.compliance_evidence_binder import (
    CLI_COMMAND as BINDER_CLI_COMMAND,
)
from vyro_growth.services.compliance_evidence_binder import (
    HTTP_ROUTE as BINDER_HTTP_ROUTE,
)
from vyro_growth.services.compliance_evidence_binder import (
    ComplianceEvidenceBinder,
    ComplianceEvidenceBinderService,
)
from vyro_growth.services.launch_readiness import (
    LaunchReadinessChecklist,
    LaunchReadinessService,
    SecretInventoryItem,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.provider_setup_checklist import (
    CLI_COMMAND as PROVIDER_SETUP_CLI_COMMAND,
)
from vyro_growth.services.provider_setup_checklist import (
    HTTP_ROUTE as PROVIDER_SETUP_HTTP_ROUTE,
)
from vyro_growth.services.provider_setup_checklist import (
    ProviderSetupChecklist,
    ProviderSetupChecklistService,
)
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.settings_execution_preflight import SettingsExecutionPreflightService
from vyro_growth.services.supervised_validation_run_packet import (
    CLI_COMMAND as VALIDATION_CLI_COMMAND,
)
from vyro_growth.services.supervised_validation_run_packet import (
    HTTP_ROUTE as VALIDATION_HTTP_ROUTE,
)
from vyro_growth.services.supervised_validation_run_packet import (
    SupervisedValidationRunPacket,
    SupervisedValidationRunPacketService,
)

logger = structlog.get_logger(__name__)

PACKET_KIND = "live_provider_setup_checklist"
PACKET_PURPOSE = "manual_owner_live_provider_credential_readiness_review_only"
CLI_COMMAND = "live-provider-setup-checklist"
HTTP_ROUTE = "/internal/live-provider-setup-checklist"
CHECKLIST_NOT_GO_LIVE_CODE = NextActionCode.LIVE_PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
PREFLIGHT_CLI_COMMAND = "settings-execution-preflight"
PREFLIGHT_HTTP_ROUTE = "/internal/settings-execution-preflight"
LAUNCH_CLI_COMMAND = "launch-readiness"
LAUNCH_HTTP_ROUTE = "/internal/launch-readiness"
VALIDATION_HTML_ROUTE = "/internal/operator-supervised-validation-run-packet"
MAX_VALIDATION_PRACTICES = 200
ProviderKey = Literal[
    "apollo",
    "hunter",
    "email_verifier",
    "smartlead",
    "openai",
    "google_calendar",
    "voice",
    "deployment",
]
PROVIDER_KEYS: tuple[ProviderKey, ...] = (
    "apollo",
    "hunter",
    "email_verifier",
    "smartlead",
    "openai",
    "google_calendar",
    "voice",
    "deployment",
)
INFO_STATUS = FindingSeverity.INFO.value
WARNING_STATUS = FindingSeverity.WARNING.value
BLOCKED_STATUS = FindingSeverity.BLOCKED.value
READY_STATUS = "ready_for_owner_review"
_STATUS_RANK = {
    INFO_STATUS: 0,
    READY_STATUS: 1,
    WARNING_STATUS: 2,
    BLOCKED_STATUS: 3,
}
RELATED_COMMANDS: tuple[str, ...] = (
    CLI_COMMAND,
    PROVIDER_SETUP_CLI_COMMAND,
    LAUNCH_CLI_COMMAND,
    VALIDATION_CLI_COMMAND,
    PREFLIGHT_CLI_COMMAND,
    BINDER_CLI_COMMAND,
    "check-config",
    "contact-validation-plan",
    "contact-validation-report",
)
RELATED_ROUTES: tuple[str, ...] = (
    HTTP_ROUTE,
    PROVIDER_SETUP_HTTP_ROUTE,
    LAUNCH_HTTP_ROUTE,
    VALIDATION_HTTP_ROUTE,
    VALIDATION_HTML_ROUTE,
    PREFLIGHT_HTTP_ROUTE,
    BINDER_HTTP_ROUTE,
    "/internal/contact-validation/plan",
    "/internal/contact-validation/report",
    "/internal/operator-provider-setup-checklist",
    "/internal/operator-compliance-evidence-binder",
)
OWNER_DECISION_SPECS: tuple[tuple[str, str], ...] = (
    (
        "prepare_apollo_account",
        "Prepare an Apollo people-search account later. This checklist does not call Apollo.",
    ),
    (
        "prepare_hunter_account",
        "Prepare a Hunter account later. This checklist does not call Hunter.",
    ),
    (
        "prepare_email_verifier_account",
        "Prepare an email-verifier account later. This checklist does not call a verifier.",
    ),
    (
        "prepare_smartlead_account",
        "Prepare a Smartlead account later. This checklist does not enroll or send.",
    ),
    (
        "prepare_openai_account",
        "Prepare an OpenAI account later. This checklist does not call OpenAI.",
    ),
    (
        "prepare_google_calendar_account",
        (
            "Prepare a Google Calendar account later. This checklist does not book "
            "or create Meet links."
        ),
    ),
    (
        "prepare_voice_account",
        "Prepare a consent-only voice account later. This checklist does not place calls.",
    ),
    (
        "prepare_deployment_credentials",
        "Prepare deployment/internal config names later. This checklist does not deploy.",
    ),
    (
        "approve_live_provider_credentials",
        "Approve live provider credentials later. This checklist does not grant that approval.",
    ),
    (
        "permit_supervised_validation_run",
        (
            "Permit a later owner-supervised validation run. "
            "supervised_validation_run_permitted stays false."
        ),
    ),
    (
        "enable_outbound",
        "Keep OUTBOUND_ENABLED=false. This checklist is not permission to enable outbound.",
    ),
    (
        "lift_operator_halt",
        "Keep operator halt unchanged. This checklist never lifts halt.",
    ),
    (
        "set_spending_limits",
        "Review budget and rate-limit placeholders later. This checklist does not spend.",
    ),
)


@dataclass(frozen=True)
class _ProviderSpec:
    key: ProviderKey
    label: str
    category: str
    credential_names: tuple[str, ...]
    flag_names: tuple[str, ...]
    config_names: tuple[str, ...]


PROVIDER_SPECS: tuple[_ProviderSpec, ...] = (
    _ProviderSpec(
        key="apollo",
        label="Apollo",
        category="people_search",
        credential_names=(SecretName.DECISION_MAKER_API_KEY.value,),
        flag_names=("DECISION_MAKER_LIVE_ENABLED",),
        config_names=("DECISION_MAKER_API_BASE_URL",),
    ),
    _ProviderSpec(
        key="hunter",
        label="Hunter",
        category="email_finder_verifier",
        credential_names=(SecretName.EMAIL_VERIFICATION_API_KEY.value,),
        flag_names=("EMAIL_VERIFICATION_LIVE_ENABLED",),
        config_names=("EMAIL_VERIFICATION_API_BASE_URL",),
    ),
    _ProviderSpec(
        key="email_verifier",
        label="Email verifier",
        category="email_verification",
        credential_names=(SecretName.EMAIL_VERIFICATION_API_KEY.value,),
        flag_names=("EMAIL_VERIFICATION_LIVE_ENABLED", "EMAIL_VERIFICATION_SMTP_ENABLED"),
        config_names=("EMAIL_VERIFICATION_API_BASE_URL",),
    ),
    _ProviderSpec(
        key="smartlead",
        label="Smartlead",
        category="email_outreach",
        credential_names=(SecretName.SMARTLEAD_API_KEY.value,),
        flag_names=("SMARTLEAD_LIVE_ENABLED", "OUTBOUND_ENABLED"),
        config_names=("SMARTLEAD_API_BASE_URL",),
    ),
    _ProviderSpec(
        key="openai",
        label="OpenAI",
        category="generative_ai",
        credential_names=(SecretName.OPENAI_API_KEY.value,),
        flag_names=("OPENAI_PERSONALIZATION_ENABLED", "OPENAI_REPLY_CLASSIFICATION_ENABLED"),
        config_names=("OPENAI_API_BASE_URL",),
    ),
    _ProviderSpec(
        key="google_calendar",
        label="Google Calendar",
        category="calendar",
        credential_names=(SecretName.GOOGLE_CALENDAR_API_KEY.value,),
        flag_names=("GOOGLE_CALENDAR_LIVE_ENABLED",),
        config_names=("GOOGLE_CALENDAR_API_BASE_URL",),
    ),
    _ProviderSpec(
        key="voice",
        label="Voice provider",
        category="voice",
        credential_names=(SecretName.VOICE_API_KEY.value,),
        flag_names=("VOICE_LIVE_ENABLED",),
        config_names=("VOICE_API_BASE_URL",),
    ),
    _ProviderSpec(
        key="deployment",
        label="Deployment",
        category="deployment",
        credential_names=(SecretName.INTERNAL_API_KEY.value, SecretName.DATABASE_URL.value),
        flag_names=(),
        config_names=(),
    ),
)


@dataclass(frozen=True)
class NamedPresence:
    name: str
    present: bool


@dataclass(frozen=True)
class ProviderFlagState:
    name: str
    enabled: bool


@dataclass(frozen=True)
class ProviderAccountItem:
    key: str
    label: str
    category: str
    applicable: bool
    credential_names: tuple[str, ...]
    config_names: tuple[str, ...]
    flag_names: tuple[str, ...]
    credentials: tuple[NamedPresence, ...]
    configs: tuple[NamedPresence, ...]
    flags: tuple[ProviderFlagState, ...]
    missing_credential_names: tuple[str, ...]
    live_enabled: bool
    credential_ready: bool
    live_execution_allowed: bool


@dataclass(frozen=True)
class OwnerDecisionItem:
    code: str
    name: str
    granted: bool


@dataclass(frozen=True)
class BudgetRateLimitItem:
    name: str
    kind: str
    configured: bool
    safe_value: str | None
    placeholder_label: str


@dataclass(frozen=True)
class CompliancePrerequisite:
    code: str
    status: str
    label: str
    blocking: bool
    documented: bool


@dataclass(frozen=True)
class ValidationRunConstraint:
    code: str
    label: str
    limit: int | None
    required: bool


@dataclass(frozen=True)
class OwnerNextStep:
    code: str
    status: str
    label: str
    command_name: str | None
    json_route: str | None
    html_route: str | None
    config_name: str | None


@dataclass(frozen=True)
class LiveProviderSetupChecklist:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
    dry_run_only: bool
    no_execution: bool
    no_outbound: bool
    no_provider_calls: bool
    no_credential_verification: bool
    no_send: bool
    no_call: bool
    no_book: bool
    no_spend: bool
    no_deploy: bool
    no_autodial: bool
    no_ai_voice: bool
    manual_review_only: bool
    outbound_attempted: bool
    live_call_attempted: bool
    live_provider_calls_attempted: bool
    credential_verification_attempted: bool
    smtp_attempted: bool
    autodial_attempted: bool
    campaign_enrolled: bool
    booking_attempted: bool
    meet_link_created: bool
    ads_launched: bool
    execution_allowed: bool
    owner_approved: bool
    validation_permitted: bool
    spend_attempted: bool
    campaign_launched: bool
    halt_changed: bool
    settings_applied: bool
    scoring_thresholds_changed: bool
    outbound_enabled: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    operator_halt_unchanged: bool
    live_providers_enabled: bool
    live_providers: dict[str, bool]
    contact_validation_is_not_outbound: bool
    contact_validation_is_not_live_send: bool
    supervised_validation_run_packet_is_not_execution: bool
    export_is_not_permission_to_run: bool
    live_provider_setup_checklist_is_not_go_live: bool
    checklist_is_not_permission_to_go_live: bool
    checklist_is_not_execution: bool
    supervised_validation_run_permitted: bool
    credential_values_included: bool
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
    provider_accounts: tuple[ProviderAccountItem, ...]
    required_credentials: tuple[NamedPresence, ...]
    required_configs: tuple[NamedPresence, ...]
    missing_credential_names: tuple[str, ...]
    missing_config_names: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    owner_decisions: tuple[OwnerDecisionItem, ...]
    budget_rate_limits: tuple[BudgetRateLimitItem, ...]
    compliance_prerequisites: tuple[CompliancePrerequisite, ...]
    validation_run_constraints: tuple[ValidationRunConstraint, ...]
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    cli_command: str
    http_route: str
    next_actions: tuple[OwnerNextStep, ...]


class LiveProviderSetupChecklistService:
    """Compose existing read-only exports into a live-provider credential checklist."""

    def __init__(
        self,
        *,
        provider_setup: ProviderSetupChecklistService | None = None,
        launch_readiness: LaunchReadinessService | None = None,
        validation_packet: SupervisedValidationRunPacketService | None = None,
        settings_preflight: SettingsExecutionPreflightService | None = None,
        compliance_binder: ComplianceEvidenceBinderService | None = None,
    ) -> None:
        launch = launch_readiness or LaunchReadinessService()
        preflight = settings_preflight or SettingsExecutionPreflightService()
        self.launch_readiness = launch
        self.settings_preflight = preflight
        self.provider_setup = provider_setup or ProviderSetupChecklistService(
            launch_readiness=launch
        )
        self.validation_packet = validation_packet or SupervisedValidationRunPacketService()
        self.compliance_binder = compliance_binder or ComplianceEvidenceBinderService(
            launch_readiness=launch,
            settings_preflight=preflight,
        )

    def build(self, db: Session, settings: Settings) -> LiveProviderSetupChecklist:
        halt_before = read_operator_halt(db)
        launch = self.launch_readiness.assess(db, settings)
        provider_setup = self.provider_setup.build(db, settings)
        validation = self.validation_packet.build(db, settings)
        preflight = self.settings_preflight.simulate(db, settings)
        binder = self.compliance_binder.build(db, settings)
        halt_after = read_operator_halt(db)
        _assert_halt_unchanged(halt_before, halt_after)
        inventory = {item.name: item for item in launch.secret_inventory}
        flags = {item.name: item.enabled for item in launch.config_flags}
        accounts = _provider_accounts(settings, inventory, flags)
        credentials = _unique_credentials(accounts, settings, inventory)
        configs = _unique_configs(accounts, settings)
        decisions = _owner_decisions()
        constraints = _validation_constraints(validation)
        compliance = _compliance_prerequisites(binder, launch)
        budgets = _budget_rate_limits(settings)
        next_actions = _next_actions(
            launch=launch,
            provider_setup=provider_setup,
            validation=validation,
            accounts=accounts,
        )
        missing_credentials = _unique_sorted(
            item.name for item in credentials if not item.present
        )
        missing_configs = _unique_sorted(item.name for item in configs if not item.present)
        closed_flags = _unique_sorted(
            flag.name for account in accounts for flag in account.flags if not flag.enabled
        )
        checklist = LiveProviderSetupChecklist(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=_worst_status(
                launch.overall_status,
                provider_setup.overall_status,
                validation.overall_status,
                preflight.overall_status,
                binder.overall_status,
                BLOCKED_STATUS if settings.outbound_enabled else INFO_STATUS,
                BLOCKED_STATUS if launch.live_providers_enabled else INFO_STATUS,
            ),
            read_only=True,
            dry_run_only=True,
            no_execution=True,
            no_outbound=True,
            no_provider_calls=True,
            no_credential_verification=True,
            no_send=True,
            no_call=True,
            no_book=True,
            no_spend=True,
            no_deploy=True,
            no_autodial=True,
            no_ai_voice=True,
            manual_review_only=True,
            outbound_attempted=False,
            live_call_attempted=False,
            live_provider_calls_attempted=False,
            credential_verification_attempted=False,
            smtp_attempted=False,
            autodial_attempted=False,
            campaign_enrolled=False,
            booking_attempted=False,
            meet_link_created=False,
            ads_launched=False,
            execution_allowed=False,
            owner_approved=False,
            validation_permitted=False,
            spend_attempted=False,
            campaign_launched=False,
            halt_changed=False,
            settings_applied=False,
            scoring_thresholds_changed=False,
            outbound_enabled=settings.outbound_enabled,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            operator_halt_unchanged=halt_before is halt_after,
            live_providers_enabled=launch.live_providers_enabled,
            live_providers=dict(launch.live_providers),
            contact_validation_is_not_outbound=True,
            contact_validation_is_not_live_send=True,
            supervised_validation_run_packet_is_not_execution=True,
            export_is_not_permission_to_run=True,
            live_provider_setup_checklist_is_not_go_live=True,
            checklist_is_not_permission_to_go_live=True,
            checklist_is_not_execution=True,
            supervised_validation_run_permitted=False,
            credential_values_included=False,
            source_provider_setup_command=PROVIDER_SETUP_CLI_COMMAND,
            source_provider_setup_route=PROVIDER_SETUP_HTTP_ROUTE,
            source_provider_setup_overall_status=provider_setup.overall_status,
            source_launch_readiness_command=LAUNCH_CLI_COMMAND,
            source_launch_readiness_route=LAUNCH_HTTP_ROUTE,
            source_launch_readiness_overall_status=launch.overall_status,
            source_validation_packet_command=VALIDATION_CLI_COMMAND,
            source_validation_packet_route=VALIDATION_HTTP_ROUTE,
            source_validation_packet_overall_status=validation.overall_status,
            source_preflight_command=PREFLIGHT_CLI_COMMAND,
            source_preflight_route=PREFLIGHT_HTTP_ROUTE,
            source_preflight_overall_status=preflight.overall_status,
            source_binder_command=BINDER_CLI_COMMAND,
            source_binder_route=BINDER_HTTP_ROUTE,
            source_binder_overall_status=binder.overall_status,
            provider_accounts=accounts,
            required_credentials=credentials,
            required_configs=configs,
            missing_credential_names=missing_credentials,
            missing_config_names=missing_configs,
            closed_provider_flag_names=closed_flags,
            owner_decisions=decisions,
            budget_rate_limits=budgets,
            compliance_prerequisites=compliance,
            validation_run_constraints=constraints,
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            local_git=provider_setup.local_git,
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
            next_actions=next_actions,
        )
        logger.info(
            "live_provider_setup_checklist_built",
            read_only=True,
            no_execution=True,
            no_provider_calls=True,
            no_credential_verification=True,
            overall_status=checklist.overall_status,
            operator_halt_status=checklist.operator_halt_status,
            outbound_enabled=checklist.outbound_enabled,
            owner_approved=False,
            validation_permitted=False,
            supervised_validation_run_permitted=False,
            halt_changed=False,
            live_provider_setup_checklist_is_not_go_live=True,
        )
        return checklist


def live_provider_setup_checklist_payload(
    checklist: LiveProviderSetupChecklist,
) -> dict[str, Any]:
    return {
        "generated_at": checklist.generated_at.isoformat(),
        "packet_kind": checklist.packet_kind,
        "purpose": checklist.purpose,
        "overall_status": checklist.overall_status,
        "read_only": True,
        "dry_run_only": True,
        "no_execution": True,
        "no_outbound": True,
        "no_provider_calls": True,
        "no_credential_verification": True,
        "no_send": True,
        "no_call": True,
        "no_book": True,
        "no_spend": True,
        "no_deploy": True,
        "no_autodial": True,
        "no_ai_voice": True,
        "manual_review_only": True,
        "outbound_attempted": False,
        "live_call_attempted": False,
        "live_provider_calls_attempted": False,
        "credential_verification_attempted": False,
        "smtp_attempted": False,
        "autodial_attempted": False,
        "campaign_enrolled": False,
        "booking_attempted": False,
        "meet_link_created": False,
        "ads_launched": False,
        "execution_allowed": False,
        "owner_approved": False,
        "validation_permitted": False,
        "spend_attempted": False,
        "campaign_launched": False,
        "halt_changed": False,
        "settings_applied": False,
        "scoring_thresholds_changed": False,
        "outbound_enabled": checklist.outbound_enabled,
        "operator_halt_status": checklist.operator_halt_status,
        "operator_halt_before": checklist.operator_halt_before,
        "operator_halt_after": checklist.operator_halt_after,
        "operator_halt_unchanged": checklist.operator_halt_unchanged,
        "live_providers_enabled": checklist.live_providers_enabled,
        "live_providers": dict(checklist.live_providers),
        "contact_validation_is_not_outbound": True,
        "contact_validation_is_not_live_send": True,
        "supervised_validation_run_packet_is_not_execution": True,
        "export_is_not_permission_to_run": True,
        "live_provider_setup_checklist_is_not_go_live": True,
        "checklist_is_not_permission_to_go_live": True,
        "checklist_is_not_execution": True,
        "supervised_validation_run_permitted": False,
        "credential_values_included": False,
        "source_provider_setup_command": checklist.source_provider_setup_command,
        "source_provider_setup_route": checklist.source_provider_setup_route,
        "source_provider_setup_overall_status": checklist.source_provider_setup_overall_status,
        "source_launch_readiness_command": checklist.source_launch_readiness_command,
        "source_launch_readiness_route": checklist.source_launch_readiness_route,
        "source_launch_readiness_overall_status": (
            checklist.source_launch_readiness_overall_status
        ),
        "source_validation_packet_command": checklist.source_validation_packet_command,
        "source_validation_packet_route": checklist.source_validation_packet_route,
        "source_validation_packet_overall_status": (
            checklist.source_validation_packet_overall_status
        ),
        "source_preflight_command": checklist.source_preflight_command,
        "source_preflight_route": checklist.source_preflight_route,
        "source_preflight_overall_status": checklist.source_preflight_overall_status,
        "source_binder_command": checklist.source_binder_command,
        "source_binder_route": checklist.source_binder_route,
        "source_binder_overall_status": checklist.source_binder_overall_status,
        "provider_accounts": [_account_payload(item) for item in checklist.provider_accounts],
        "required_credentials": [
            _presence_payload(item) for item in checklist.required_credentials
        ],
        "required_configs": [_presence_payload(item) for item in checklist.required_configs],
        "missing_credential_names": list(checklist.missing_credential_names),
        "missing_config_names": list(checklist.missing_config_names),
        "closed_provider_flag_names": list(checklist.closed_provider_flag_names),
        "owner_decisions": [_decision_payload(item) for item in checklist.owner_decisions],
        "budget_rate_limits": [_budget_payload(item) for item in checklist.budget_rate_limits],
        "compliance_prerequisites": [
            _compliance_payload(item) for item in checklist.compliance_prerequisites
        ],
        "validation_run_constraints": [
            _constraint_payload(item) for item in checklist.validation_run_constraints
        ],
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
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "next_actions": [_action_payload(item) for item in checklist.next_actions],
    }


def format_live_provider_setup_checklist(
    checklist: LiveProviderSetupChecklist,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(live_provider_setup_checklist_payload(checklist))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(checklist, payload)


def _provider_accounts(
    settings: Settings,
    inventory: dict[str, SecretInventoryItem],
    flags: dict[str, bool],
) -> tuple[ProviderAccountItem, ...]:
    presence = credential_presence_flags(settings)
    return tuple(
        _provider_account(spec, settings, inventory, flags, presence) for spec in PROVIDER_SPECS
    )


def _provider_account(
    spec: _ProviderSpec,
    settings: Settings,
    inventory: dict[str, SecretInventoryItem],
    flags: dict[str, bool],
    presence: dict[str, bool],
) -> ProviderAccountItem:
    credentials = tuple(
        NamedPresence(
            name=_safe_text(name),
            present=_credential_present(name, inventory, presence),
        )
        for name in spec.credential_names
    )
    configs = tuple(
        NamedPresence(name=_safe_text(name), present=_config_present(name, settings))
        for name in spec.config_names
    )
    flag_states = tuple(
        ProviderFlagState(name=_safe_text(name), enabled=bool(flags.get(name, False)))
        for name in spec.flag_names
    )
    missing = _unique_sorted(item.name for item in credentials if not item.present)
    live_enabled = any(item.enabled for item in flag_states)
    return ProviderAccountItem(
        key=_provider_key(spec.key),
        label=_safe_text(spec.label),
        category=_safe_text(spec.category),
        applicable=True,
        credential_names=tuple(_safe_text(name) for name in spec.credential_names),
        config_names=tuple(_safe_text(name) for name in spec.config_names),
        flag_names=tuple(_safe_text(name) for name in spec.flag_names),
        credentials=credentials,
        configs=configs,
        flags=flag_states,
        missing_credential_names=missing,
        live_enabled=live_enabled,
        credential_ready=not missing,
        live_execution_allowed=False,
    )


def _provider_key(key: ProviderKey) -> str:
    match key:
        case "apollo":
            return "apollo"
        case "hunter":
            return "hunter"
        case "email_verifier":
            return "email_verifier"
        case "smartlead":
            return "smartlead"
        case "openai":
            return "openai"
        case "google_calendar":
            return "google_calendar"
        case "voice":
            return "voice"
        case "deployment":
            return "deployment"
        case _:
            return _unknown_provider_key(key)


def _unknown_provider_key(key: str) -> Never:
    raise RuntimeError(f"unhandled live provider setup checklist provider key: {key!r}")


def _credential_present(
    name: str,
    inventory: dict[str, SecretInventoryItem],
    presence: dict[str, bool],
) -> bool:
    item = inventory.get(name)
    if item is not None:
        return bool(item.present)
    mapping = {
        SecretName.DECISION_MAKER_API_KEY.value: presence["decision_maker_api_key"],
        SecretName.EMAIL_VERIFICATION_API_KEY.value: presence["email_verification_api_key"],
        SecretName.SMARTLEAD_API_KEY.value: presence["campaign_provider_api_key"],
        SecretName.OPENAI_API_KEY.value: presence["generative_ai_api_key"],
        SecretName.GOOGLE_CALENDAR_API_KEY.value: presence["calendar_api_key"],
        SecretName.VOICE_API_KEY.value: presence["voice_api_key"],
        SecretName.INTERNAL_API_KEY.value: presence["internal_api_key"],
        SecretName.DATABASE_URL.value: False,
    }
    return bool(mapping.get(name, False))


def _config_present(name: str, settings: Settings) -> bool:
    mapping = {
        "DECISION_MAKER_API_BASE_URL": bool(settings.decision_maker_api_base_url.strip()),
        "EMAIL_VERIFICATION_API_BASE_URL": bool(settings.email_verification_api_base_url.strip()),
        "SMARTLEAD_API_BASE_URL": bool(settings.smartlead_api_base_url.strip()),
        "OPENAI_API_BASE_URL": bool(settings.openai_api_base_url.strip()),
        "GOOGLE_CALENDAR_API_BASE_URL": bool(settings.google_calendar_api_base_url.strip()),
        "VOICE_API_BASE_URL": bool(settings.voice_api_base_url.strip()),
        "OUTBOUND_ENABLED": settings.outbound_enabled,
        "DECISION_MAKER_LIVE_ENABLED": settings.decision_maker_live_enabled,
        "EMAIL_VERIFICATION_LIVE_ENABLED": settings.email_verification_live_enabled,
        "EMAIL_VERIFICATION_SMTP_ENABLED": settings.email_verification_smtp_enabled,
        "SMARTLEAD_LIVE_ENABLED": settings.smartlead_live_enabled,
        "OPENAI_PERSONALIZATION_ENABLED": settings.openai_personalization_enabled,
        "OPENAI_REPLY_CLASSIFICATION_ENABLED": settings.openai_reply_classification_enabled,
        "GOOGLE_CALENDAR_LIVE_ENABLED": settings.google_calendar_live_enabled,
        "VOICE_LIVE_ENABLED": settings.voice_live_enabled,
    }
    return bool(mapping.get(name, False))


def _unique_credentials(
    accounts: Sequence[ProviderAccountItem],
    settings: Settings,
    inventory: dict[str, SecretInventoryItem],
) -> tuple[NamedPresence, ...]:
    presence = credential_presence_flags(settings)
    names = _unique_sorted(name for account in accounts for name in account.credential_names)
    return tuple(
        NamedPresence(name=name, present=_credential_present(name, inventory, presence))
        for name in names
    )


def _unique_configs(
    accounts: Sequence[ProviderAccountItem],
    settings: Settings,
) -> tuple[NamedPresence, ...]:
    names = _unique_sorted(
        (
            *(name for account in accounts for name in account.config_names),
            *(name for account in accounts for name in account.flag_names),
            "OUTBOUND_ENABLED",
        )
    )
    return tuple(
        NamedPresence(name=name, present=_config_present(name, settings)) for name in names
    )


def _owner_decisions() -> tuple[OwnerDecisionItem, ...]:
    return tuple(
        OwnerDecisionItem(code=_safe_text(code), name=_safe_text(name), granted=False)
        for code, name in OWNER_DECISION_SPECS
    )


def _budget_rate_limits(settings: Settings) -> tuple[BudgetRateLimitItem, ...]:
    cost_limit = settings.openai_estimated_cost_usd_limit
    cost_configured = cost_limit is not None
    return (
        BudgetRateLimitItem(
            name="OPENAI_ESTIMATED_COST_USD_LIMIT",
            kind="budget_placeholder",
            configured=cost_configured,
            safe_value=_safe_number(cost_limit) if cost_configured else None,
            placeholder_label=_safe_text(
                "Owner spending-limit placeholder for a later live adapter. "
                "This checklist does not spend or enforce a budget."
            ),
        ),
        BudgetRateLimitItem(
            name="WEBSITE_RATE_LIMIT_SECONDS",
            kind="rate_limit",
            configured=True,
            safe_value=_safe_number(settings.website_rate_limit_seconds),
            placeholder_label=_safe_text(
                "Safe public-page fetch rate limit. This checklist does not call providers."
            ),
        ),
        BudgetRateLimitItem(
            name="DECISION_MAKER_TIMEOUT_SECONDS",
            kind="rate_limit",
            configured=True,
            safe_value=_safe_number(settings.decision_maker_timeout_seconds),
            placeholder_label=_safe_text(
                "People-search timeout placeholder. This checklist does not call Apollo."
            ),
        ),
        BudgetRateLimitItem(
            name="EMAIL_VERIFICATION_TIMEOUT_SECONDS",
            kind="rate_limit",
            configured=True,
            safe_value=_safe_number(settings.email_verification_timeout_seconds),
            placeholder_label=_safe_text(
                "Email-verifier timeout placeholder. This checklist does not call a verifier."
            ),
        ),
    )


def _compliance_prerequisites(
    binder: ComplianceEvidenceBinder,
    launch: LaunchReadinessChecklist,
) -> tuple[CompliancePrerequisite, ...]:
    phi_blocking = bool(binder.phi_secrets_redaction.phi_fields_present)
    outbound_blocking = bool(launch.outbound_enabled)
    voice_ok = binder.consent_phone_boundary.consent_to_call_required
    documented = {code for item in binder.documented_guardrails for code in item.documented_codes}
    return (
        CompliancePrerequisite(
            code="suppression_controls",
            status=INFO_STATUS,
            label=_safe_text(
                "Keep durable suppression controls in place. "
                "This checklist does not contact anyone."
            ),
            blocking=False,
            documented=True,
        ),
        CompliancePrerequisite(
            code="opt_out_unsubscribe",
            status=INFO_STATUS,
            label=_safe_text(
                "Honor opt-out and do-not-contact outcomes. This checklist does not send mail."
            ),
            blocking=False,
            documented=True,
        ),
        CompliancePrerequisite(
            code="no_phi",
            status=BLOCKED_STATUS if phi_blocking else INFO_STATUS,
            label=_safe_text(
                "Keep protected health fields out of this sales system. "
                "This checklist never exports those fields."
            ),
            blocking=phi_blocking,
            documented=True,
        ),
        CompliancePrerequisite(
            code="consent_only_voice",
            status=INFO_STATUS if voice_ok else WARNING_STATUS,
            label=_safe_text(
                "Voice remains consent-only. This checklist does not place calls, autodial, "
                "or use AI voice."
            ),
            blocking=False,
            documented=voice_ok or "consent_based_phone_only" in documented,
        ),
        CompliancePrerequisite(
            code="no_linkedin_automation",
            status=INFO_STATUS,
            label=_safe_text(
                "Do not add LinkedIn or Sales Navigator automation. This checklist has no "
                "LinkedIn provider."
            ),
            blocking=False,
            documented=True,
        ),
        CompliancePrerequisite(
            code="no_restricted_job_board_scraping",
            status=INFO_STATUS,
            label=_safe_text(
                "Do not scrape restricted job boards. "
                "Job signals stay on the official website only."
            ),
            blocking=False,
            documented=True,
        ),
        CompliancePrerequisite(
            code="keep_outbound_disabled",
            status=BLOCKED_STATUS if outbound_blocking else INFO_STATUS,
            label=_safe_text(
                "Keep OUTBOUND_ENABLED=false. This checklist is not permission to enable outbound."
            ),
            blocking=outbound_blocking,
            documented=True,
        ),
    )


def _validation_constraints(
    validation: SupervisedValidationRunPacket,
) -> tuple[ValidationRunConstraint, ...]:
    max_size = min(validation.max_cohort_size, MAX_VALIDATION_PRACTICES)
    return (
        ValidationRunConstraint(
            code="max_practices",
            label=_safe_text(
                "Supervised validation stays bounded to at most 200 practices. "
                "This checklist does not execute that run."
            ),
            limit=max_size,
            required=True,
        ),
        ValidationRunConstraint(
            code="one_target_state",
            label=_safe_text(
                "Use one target state for a later supervised validation. "
                "This checklist does not select or export prospects."
            ),
            limit=1,
            required=True,
        ),
        ValidationRunConstraint(
            code="one_target_specialty",
            label=_safe_text(
                "Use one target specialty for a later supervised validation. "
                "This checklist does not select or export prospects."
            ),
            limit=1,
            required=True,
        ),
        ValidationRunConstraint(
            code="no_sending_during_enrichment_validation",
            label=_safe_text(
                "Do not send email or enroll campaigns during enrichment validation. "
                "contact_validation_is_not_live_send stays true."
            ),
            limit=0,
            required=True,
        ),
    )


def _next_actions(
    *,
    launch: LaunchReadinessChecklist,
    provider_setup: ProviderSetupChecklist,
    validation: SupervisedValidationRunPacket,
    accounts: Sequence[ProviderAccountItem],
) -> tuple[OwnerNextStep, ...]:
    halt_ok = launch.operator_halt_status == HaltStatus.HALTED.value
    outbound_ok = not launch.outbound_enabled
    missing = _unique_sorted(
        name for account in accounts for name in account.missing_credential_names
    )
    actions = [
        _action(
            CHECKLIST_NOT_GO_LIVE_CODE,
            INFO_STATUS,
            (
                "This live-provider setup checklist is a sanitized review export only. "
                "It is not permission to go live and is not an execution surface."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
        _action(
            EXECUTION_DISABLED_CODE,
            INFO_STATUS,
            (
                "Execution remains disabled. This checklist does not verify credentials, "
                "call providers, apply settings, lift halt, enable outbound, or send."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
        _action(
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            INFO_STATUS if outbound_ok else BLOCKED_STATUS,
            "Verify OUTBOUND_ENABLED remains false. This checklist does not enable outbound.",
            command_name=LAUNCH_CLI_COMMAND,
            json_route=LAUNCH_HTTP_ROUTE,
            config_name="OUTBOUND_ENABLED",
        ),
        _action(
            (
                NextActionCode.KEEP_OPERATOR_HALT.value
                if halt_ok
                else NextActionCode.RECORD_OPERATOR_HALT.value
            ),
            INFO_STATUS if halt_ok else WARNING_STATUS,
            "Verify operator halt remains unchanged. This checklist does not lift halt.",
            command_name="system-status",
            json_route="/internal/monitoring/status",
        ),
        _action(
            NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
            INFO_STATUS,
            (
                "Keep every live-provider flag disabled. This checklist lists names and "
                "present/missing booleans only and does not enable providers."
            ),
            command_name=LAUNCH_CLI_COMMAND,
            json_route=LAUNCH_HTTP_ROUTE,
        ),
        _action(
            NextActionCode.PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value,
            _bucket_status(provider_setup.overall_status),
            (
                "Review the existing provider setup checklist. Read-only credential/setup "
                "export; it is not permission to go live."
            ),
            command_name=PROVIDER_SETUP_CLI_COMMAND,
            json_route=PROVIDER_SETUP_HTTP_ROUTE,
            html_route="/internal/operator-provider-setup-checklist",
        ),
        _action(
            "review_supervised_validation_run_packet",
            _bucket_status(validation.overall_status),
            (
                "Review the supervised validation owner run packet. That packet does not "
                "execute the run or grant approval."
            ),
            command_name=VALIDATION_CLI_COMMAND,
            json_route=VALIDATION_HTTP_ROUTE,
            html_route=VALIDATION_HTML_ROUTE,
        ),
        _action(
            "supervised_validation_run_not_permitted",
            INFO_STATUS,
            (
                "supervised_validation_run_permitted=false and validation_permitted=false. "
                "Do not execute a 200-practice validation run from this checklist."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
    ]
    if missing:
        actions.append(
            _action(
                NextActionCode.CONFIGURE_REQUIRED_CREDENTIALS.value,
                WARNING_STATUS,
                (
                    "Prepare named required credentials in local env later. This checklist "
                    "lists variable names only and never shows values or verifies them."
                ),
                command_name=LAUNCH_CLI_COMMAND,
                json_route=LAUNCH_HTTP_ROUTE,
            )
        )
    for account in accounts:
        actions.append(
            _action(
                f"prepare_{account.key}_account",
                WARNING_STATUS if account.missing_credential_names else INFO_STATUS,
                (
                    f"Review {account.label} account and config names only. This checklist "
                    "does not create the account, verify the key, or enable the provider."
                ),
                command_name=CLI_COMMAND,
                json_route=HTTP_ROUTE,
                config_name=account.credential_names[0] if account.credential_names else None,
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
) -> OwnerNextStep:
    return OwnerNextStep(
        code=_safe_text(code),
        status=_bucket_status(status),
        label=_safe_text(label),
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
        config_name=_safe_optional(config_name),
    )


def _worst_status(*values: str) -> str:
    cleaned = [_bucket_status(item) for item in values if item]
    if not cleaned:
        return INFO_STATUS
    return max(cleaned, key=lambda item: _STATUS_RANK.get(item, 0))


def _bucket_status(status: str) -> str:
    match _safe_text(status):
        case "ready_for_owner_review" | "info" | "execution_gates_closed":
            return INFO_STATUS
        case "blocked" | "dry_run_blocked":
            return BLOCKED_STATUS
        case (
            "warning"
            | "pending_decision"
            | "decision_not_approved"
            | "missing_owner_packet_decision"
            | "missing_explicit_owner_approval"
        ):
            return WARNING_STATUS
        case _:
            return INFO_STATUS


def _assert_halt_unchanged(before: HaltStatus, after: HaltStatus) -> None:
    if after is not before:
        raise RuntimeError("live provider setup checklist must not change operator halt")


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


def _safe_number(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return ""
    return _safe_text(f"{value:g}")


def _bool_text(value: object) -> str:
    return "true" if value is True else "false"


def _account_payload(item: ProviderAccountItem) -> dict[str, Any]:
    return {
        "key": item.key,
        "label": item.label,
        "category": item.category,
        "applicable": True,
        "credential_names": list(item.credential_names),
        "config_names": list(item.config_names),
        "flag_names": list(item.flag_names),
        "credentials": [_presence_payload(entry) for entry in item.credentials],
        "configs": [_presence_payload(entry) for entry in item.configs],
        "flags": [{"name": flag.name, "enabled": flag.enabled} for flag in item.flags],
        "missing_credential_names": list(item.missing_credential_names),
        "live_enabled": item.live_enabled,
        "credential_ready": item.credential_ready,
        "live_execution_allowed": False,
    }


def _presence_payload(item: NamedPresence) -> dict[str, Any]:
    return {"name": item.name, "present": item.present}


def _decision_payload(item: OwnerDecisionItem) -> dict[str, Any]:
    return {"code": item.code, "name": item.name, "granted": False}


def _budget_payload(item: BudgetRateLimitItem) -> dict[str, Any]:
    return {
        "name": item.name,
        "kind": item.kind,
        "configured": item.configured,
        "safe_value": item.safe_value,
        "placeholder_label": item.placeholder_label,
    }


def _compliance_payload(item: CompliancePrerequisite) -> dict[str, Any]:
    return {
        "code": item.code,
        "status": item.status,
        "label": item.label,
        "blocking": item.blocking,
        "documented": item.documented,
    }


def _constraint_payload(item: ValidationRunConstraint) -> dict[str, Any]:
    return {
        "code": item.code,
        "label": item.label,
        "limit": item.limit,
        "required": item.required,
    }


def _action_payload(item: OwnerNextStep) -> dict[str, Any]:
    return {
        "code": item.code,
        "status": item.status,
        "label": item.label,
        "command_name": item.command_name,
        "json_route": item.json_route,
        "html_route": item.html_route,
        "config_name": item.config_name,
    }


def _format_markdown(checklist: LiveProviderSetupChecklist, payload: dict[str, Any]) -> str:
    lines = [
        "# Owner live-provider setup checklist",
        "",
        (
            "This checklist is a sanitized owner-review export of existing provider "
            "setup, launch-readiness, supervised-validation, settings-preflight, and "
            "compliance-binder surfaces. It never verifies credentials, calls "
            "providers, or executes a supervised validation."
        ),
        "",
        (
            f"status={payload['overall_status']} "
            f"kind={payload['packet_kind']} "
            f"purpose={payload['purpose']}"
        ),
        f"- generated_at: {payload['generated_at']}",
        (
            f"- operator_halt_before={payload['operator_halt_before']} "
            f"status={payload['operator_halt_status']} "
            f"after={payload['operator_halt_after']} "
            f"unchanged={_bool_text(payload['operator_halt_unchanged'])}"
        ),
        f"- outbound_enabled: {_bool_text(payload['outbound_enabled'])}",
        f"- live_providers_enabled: {_bool_text(payload['live_providers_enabled'])}",
        f"- cli_command: {payload['cli_command']}",
        f"- http_route: {payload['http_route']}",
        f"- source_provider_setup_command: {payload['source_provider_setup_command']}",
        f"- source_provider_setup_route: {payload['source_provider_setup_route']}",
        (
            "- source_provider_setup_overall_status: "
            f"{payload['source_provider_setup_overall_status']}"
        ),
        f"- source_launch_readiness_command: {payload['source_launch_readiness_command']}",
        f"- source_launch_readiness_route: {payload['source_launch_readiness_route']}",
        (
            "- source_launch_readiness_overall_status: "
            f"{payload['source_launch_readiness_overall_status']}"
        ),
        f"- source_validation_packet_command: {payload['source_validation_packet_command']}",
        f"- source_validation_packet_route: {payload['source_validation_packet_route']}",
        (
            "- source_validation_packet_overall_status: "
            f"{payload['source_validation_packet_overall_status']}"
        ),
        f"- source_preflight_command: {payload['source_preflight_command']}",
        f"- source_preflight_route: {payload['source_preflight_route']}",
        f"- source_preflight_overall_status: {payload['source_preflight_overall_status']}",
        f"- source_binder_command: {payload['source_binder_command']}",
        f"- source_binder_route: {payload['source_binder_route']}",
        f"- source_binder_overall_status: {payload['source_binder_overall_status']}",
        "",
        "## Safety flags",
        "- read_only=true",
        "- dry_run_only=true",
        "- no_execution=true",
        "- no_outbound=true",
        "- no_provider_calls=true",
        "- no_credential_verification=true",
        "- no_send=true",
        "- no_call=true",
        "- no_book=true",
        "- no_spend=true",
        "- no_deploy=true",
        "- no_autodial=true",
        "- no_ai_voice=true",
        "- owner_approved=false",
        "- validation_permitted=false",
        "- supervised_validation_run_permitted=false",
        "- execution_allowed=false",
        "- credential_values_included=false",
        "- live_provider_setup_checklist_is_not_go_live=true",
        "- checklist_is_not_permission_to_go_live=true",
        "- checklist_is_not_execution=true",
        "- export_is_not_permission_to_run=true",
        f"- halt_changed={_bool_text(payload['halt_changed'])}",
        f"- operator_halt_unchanged={_bool_text(payload['operator_halt_unchanged'])}",
        "",
        "## Provider account checklist",
    ]
    for account in checklist.provider_accounts:
        lines.extend(
            [
                f"### {account.label}",
                f"- key: {account.key}",
                f"- category: {account.category}",
                f"- applicable: {_bool_text(account.applicable)}",
                f"- credential_ready: {_bool_text(account.credential_ready)}",
                f"- live_enabled: {_bool_text(account.live_enabled)}",
                "- live_execution_allowed=false",
                f"- credential_names: {_format_codes(account.credential_names)}",
                f"- config_names: {_format_codes(account.config_names)}",
                f"- flag_names: {_format_codes(account.flag_names)}",
                f"- missing_credential_names: {_format_codes(account.missing_credential_names)}",
            ]
        )
        for credential in account.credentials:
            lines.append(f"- credential {credential.name} present={_bool_text(credential.present)}")
        for config in account.configs:
            lines.append(f"- config {config.name} present={_bool_text(config.present)}")
        for flag in account.flags:
            lines.append(f"- flag {flag.name} enabled={_bool_text(flag.enabled)}")
    lines.extend(["", "## Required credentials"])
    for credential in checklist.required_credentials:
        lines.append(f"- {credential.name} present={_bool_text(credential.present)}")
    lines.extend(["", "## Required configs"])
    for config in checklist.required_configs:
        lines.append(f"- {config.name} present={_bool_text(config.present)}")
    lines.extend(["", "## Owner decisions"])
    for decision in checklist.owner_decisions:
        lines.append(
            f"- {decision.code} granted={_bool_text(decision.granted)} name={decision.name}"
        )
    lines.extend(["", "## Budget and rate-limit placeholders"])
    for budget in checklist.budget_rate_limits:
        safe_value = budget.safe_value if budget.safe_value else "-"
        lines.append(
            f"- {budget.name} kind={budget.kind} configured={_bool_text(budget.configured)} "
            f"safe_value={safe_value} label={budget.placeholder_label}"
        )
    lines.extend(["", "## Compliance prerequisites"])
    for prerequisite in checklist.compliance_prerequisites:
        lines.append(
            f"- [{prerequisite.status}] {prerequisite.code} "
            f"blocking={_bool_text(prerequisite.blocking)} "
            f"documented={_bool_text(prerequisite.documented)} label={prerequisite.label}"
        )
    lines.extend(["", "## Validation run constraints"])
    for constraint in checklist.validation_run_constraints:
        limit = str(constraint.limit) if constraint.limit is not None else "-"
        lines.append(
            f"- {constraint.code} limit={limit} required={_bool_text(constraint.required)} "
            f"label={constraint.label}"
        )
    lines.extend(["", "## Owner next steps"])
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
    lines.extend(
        [
            "",
            "## Local git",
            f"- available: {_bool_text(checklist.local_git.available)}",
            f"- current_branch: {checklist.local_git.current_branch}",
            f"- current_sha: {checklist.local_git.current_sha}",
            f"- working_tree_status: {checklist.local_git.working_tree_status}",
            "- git_provider_called: false",
            "- github_actions_called: false",
        ]
    )
    return "\n".join(lines)


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"
