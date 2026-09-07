"""Read-only supervised pilot launch plan export.

Phase 55 turns existing readiness, rehearsal, outcome, provider setup, and
launch dossier surfaces into a practical small-pilot plan for the first
controlled prospecting test. It reuses those services as source material
and never recalculates readiness. It never executes, applies settings,
lifts halt, enables outbound, calls providers, builds, publishes, deploys,
spends, or changes live state. This plan is not permission to go live and
not an execution surface.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity, NextActionCode
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.provider_setup_checklist import (
    CLI_COMMAND as PROVIDER_CLI_COMMAND,
)
from vyro_growth.services.provider_setup_checklist import (
    HTTP_ROUTE as PROVIDER_HTTP_ROUTE,
)
from vyro_growth.services.provider_setup_checklist import (
    ProviderSetupCategory,
    ProviderSetupChecklist,
    ProviderSetupChecklistService,
)
from vyro_growth.services.rehearsal_outcome_report import (
    CLI_COMMAND as OUTCOME_CLI_COMMAND,
)
from vyro_growth.services.rehearsal_outcome_report import (
    HTML_ROUTE as OUTCOME_HTML_ROUTE,
)
from vyro_growth.services.rehearsal_outcome_report import (
    HTTP_ROUTE as OUTCOME_HTTP_ROUTE,
)
from vyro_growth.services.rehearsal_outcome_report import (
    RehearsalOutcomeReport,
    RehearsalOutcomeReportService,
)
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata

logger = structlog.get_logger(__name__)

PACKET_KIND = "supervised_pilot_plan"
PACKET_PURPOSE = "manual_owner_supervised_pilot_review_only"
PLAN_NOT_GO_LIVE_CODE = NextActionCode.SUPERVISED_PILOT_PLAN_IS_NOT_GO_LIVE.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
CLI_COMMAND = "supervised-pilot-plan"
HTTP_ROUTE = "/internal/supervised-pilot-plan"
HTML_ROUTE = "/internal/operator-supervised-pilot-plan"
SUGGESTED_MAX_LEADS = 10
SUGGESTED_MAX_DRAFTS = 5
SUGGESTED_MAX_MANUALLY_REVIEWED_SENDS = 0
SUGGESTED_MAX_DAILY_ACTIVITY = 5
PREREQUISITE_KEYS: tuple[str, ...] = (
    "website_credibility",
    "email_domain_setup",
    "email_outreach_setup",
    "enrichment_credentials",
    "calendar_setup",
    "compliance_review",
    "owner_approvals",
    "monitoring",
)
EXPECTED_SAFE_ASSERTION_KEYS: tuple[str, ...] = (
    "OUTBOUND_ENABLED",
    "go_live_permitted",
    "execution_allowed",
    "deployment_allowed",
    "owner_approved",
    "halt_changed",
    "spend_allowed",
)
RELATED_COMMANDS: tuple[str, ...] = (
    "launch-readiness",
    "go-live-readiness-index",
    "launch-blockers-plan",
    "staged-rollout-plan",
    "owner-launch-dossier",
    PROVIDER_CLI_COMMAND,
    "go-live-rehearsal-checklist",
    OUTCOME_CLI_COMMAND,
    "settings-execution-preflight",
    "check-config",
    "smoke-dry-run",
    CLI_COMMAND,
    "supervised-pilot-candidates",
    "supervised-pilot-go-no-go",
    "supervised-pilot-first-send-preflight",
    "supervised-pilot-launch-rehearsal-control-map",
    "supervised-pilot-first-send-owner-authorization-packet",
    "system-status",
)
RELATED_ROUTES: tuple[str, ...] = (
    "/internal/launch-readiness",
    "/internal/operator-go-live-readiness-index",
    "/internal/go-live-readiness-index",
    "/internal/operator-launch-blockers-plan",
    "/internal/launch-blockers-plan",
    "/internal/operator-staged-rollout-plan",
    "/internal/staged-rollout-plan",
    "/internal/operator-owner-launch-dossier",
    "/internal/owner-launch-dossier",
    "/internal/operator-provider-setup-checklist",
    PROVIDER_HTTP_ROUTE,
    "/internal/operator-go-live-rehearsal-checklist",
    "/internal/go-live-rehearsal-checklist",
    OUTCOME_HTML_ROUTE,
    OUTCOME_HTTP_ROUTE,
    "/internal/operator-settings-execution-preflight",
    "/internal/settings-execution-preflight",
    HTML_ROUTE,
    HTTP_ROUTE,
    "/internal/operator-supervised-pilot-candidates",
    "/internal/supervised-pilot-candidates",
    "/internal/operator-supervised-pilot-go-no-go",
    "/internal/supervised-pilot-go-no-go",
    "/internal/operator-supervised-pilot-first-send-preflight",
    "/internal/supervised-pilot-first-send-preflight",
    "/internal/operator-supervised-pilot-launch-rehearsal-control-map",
    "/internal/supervised-pilot-launch-rehearsal-control-map",
    "/internal/supervised-pilot-first-send-owner-authorization-packet",
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


@dataclass(frozen=True)
class PilotAssertion:
    key: str
    expected: str
    observed: str
    passed: bool


@dataclass(frozen=True)
class PilotScopeRecommendation:
    suggested_max_leads: int
    suggested_max_drafts: int
    suggested_max_manually_reviewed_sends: int
    suggested_max_daily_activity: int
    stop_conditions: tuple[str, ...]
    recommendation_summary: str


@dataclass(frozen=True)
class PilotPrerequisite:
    key: str
    category: str
    label: str
    status: str
    required_owner_approval_type: str
    missing_credential_names: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    review_text: str


@dataclass(frozen=True)
class PilotRunbookStep:
    step_key: str
    label: str
    instruction: str
    status: str
    runnable: bool
    executed: int
    command_name: str | None
    json_route: str | None
    html_route: str | None
    config_name: str | None


@dataclass(frozen=True)
class PilotAbortCriterion:
    code: str
    label: str
    instruction: str


@dataclass(frozen=True)
class PilotNextAction:
    code: str
    status: str
    label: str
    command_name: str | None
    json_route: str | None
    html_route: str | None
    config_name: str | None


@dataclass(frozen=True)
class SupervisedPilotPlan:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
    no_execution: bool
    no_go_live: bool
    no_deployment: bool
    no_spend: bool
    dry_run_only: bool
    executed: int
    execution_attempted: bool
    outbound_attempted: bool
    live_call_attempted: bool
    recommendation_applied: bool
    spend_attempted: bool
    spend_allowed: bool
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
    supervised_pilot_plan_is_not_go_live: bool
    plan_is_not_permission_to_go_live: bool
    plan_is_not_execution: bool
    rehearsal_outcome_report_is_not_go_live: bool
    go_live_rehearsal_checklist_is_not_go_live: bool
    rehearsal_is_not_a_script_runner: bool
    index_is_not_permission_to_go_live: bool
    dossier_is_not_permission_to_go_live: bool
    staged_rollout_plan_is_not_go_live: bool
    provider_setup_checklist_is_not_go_live: bool
    runbook_is_not_deployment: bool
    manifest_is_not_a_build_or_deploy: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    safety_assertions: tuple[PilotAssertion, ...]
    expected_safe_assertion_count: int
    expected_safe_assertions_passed: int
    expected_safe_assertions_failed: int
    failed_safe_assertion_keys: tuple[str, ...]
    remaining_owner_approval_types: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    missing_config_names: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    gate_codes: tuple[str, ...]
    pilot_scope: PilotScopeRecommendation
    prerequisites: tuple[PilotPrerequisite, ...]
    runbook_steps: tuple[PilotRunbookStep, ...]
    abort_criteria: tuple[PilotAbortCriterion, ...]
    cli_command: str
    http_route: str
    source_outcome_command: str
    source_outcome_route: str
    source_outcome_html_route: str
    source_outcome_overall_status: str
    source_rehearsal_command: str
    source_rehearsal_route: str
    source_rehearsal_html_route: str
    source_rehearsal_overall_status: str
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
    source_provider_setup_command: str
    source_provider_setup_route: str
    source_provider_setup_overall_status: str
    source_preflight_command: str
    source_preflight_route: str
    source_preflight_overall_status: str
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    next_actions: tuple[PilotNextAction, ...]


class SupervisedPilotPlanService:
    """Compose a small-pilot plan from existing read-only surfaces."""

    def __init__(
        self,
        *,
        outcome: RehearsalOutcomeReportService | None = None,
        provider: ProviderSetupChecklistService | None = None,
    ) -> None:
        self.outcome = outcome or RehearsalOutcomeReportService()
        self.provider = provider or ProviderSetupChecklistService()

    def build(self, db: Session, settings: Settings) -> SupervisedPilotPlan:
        halt_before = read_operator_halt(db)
        outcome = self.outcome.build(db, settings)
        provider = self.provider.build(db, settings)
        halt_after = read_operator_halt(db)
        if halt_after != halt_before:
            raise RuntimeError("supervised pilot plan must not change operator halt status")
        plan = _from_sources(
            outcome,
            provider,
            halt_before=halt_before,
            halt_after=halt_after,
        )
        logger.info(
            "supervised_pilot_plan_built",
            read_only=True,
            no_execution=True,
            no_go_live=True,
            no_deployment=True,
            no_spend=True,
            overall_status=plan.overall_status,
            operator_halt_status=plan.operator_halt_status,
            outbound_enabled=plan.outbound_enabled,
            go_live_permitted=False,
            execution_allowed=False,
            deployment_allowed=False,
            settings_applied=False,
            halt_changed=False,
            owner_approved=False,
            spend_allowed=False,
            executed=0,
            supervised_pilot_plan_is_not_go_live=True,
        )
        return plan


def _from_sources(
    outcome: RehearsalOutcomeReport,
    provider: ProviderSetupChecklist,
    *,
    halt_before: HaltStatus,
    halt_after: HaltStatus,
) -> SupervisedPilotPlan:
    assertions = _safety_assertions(outcome)
    failed_keys = _unique_sorted(item.key for item in assertions if not item.passed)
    prerequisites = _prerequisites(outcome, provider)
    runbook_steps = _runbook_steps(outcome, prerequisites)
    abort_criteria = _abort_criteria()
    next_actions = _next_actions(outcome)
    overall_status = _worst_status(
        outcome.overall_status,
        provider.overall_status,
        *(item.status for item in prerequisites),
        *(item.status for item in runbook_steps),
    )
    missing_config_names = _unique_sorted(
        (
            *outcome.missing_config_names,
            *(name for item in prerequisites for name in item.missing_credential_names),
        )
    )
    return SupervisedPilotPlan(
        generated_at=datetime.now(tz=UTC),
        packet_kind=PACKET_KIND,
        purpose=PACKET_PURPOSE,
        overall_status=overall_status,
        read_only=True,
        no_execution=True,
        no_go_live=True,
        no_deployment=True,
        no_spend=True,
        dry_run_only=True,
        executed=0,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        spend_allowed=False,
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
        outbound_enabled=outcome.outbound_enabled,
        live_providers_enabled=outcome.live_providers_enabled,
        manual_review_only=True,
        supervised_pilot_plan_is_not_go_live=True,
        plan_is_not_permission_to_go_live=True,
        plan_is_not_execution=True,
        rehearsal_outcome_report_is_not_go_live=True,
        go_live_rehearsal_checklist_is_not_go_live=True,
        rehearsal_is_not_a_script_runner=True,
        index_is_not_permission_to_go_live=True,
        dossier_is_not_permission_to_go_live=True,
        staged_rollout_plan_is_not_go_live=True,
        provider_setup_checklist_is_not_go_live=True,
        runbook_is_not_deployment=True,
        manifest_is_not_a_build_or_deploy=True,
        operator_halt_status=halt_after.value,
        operator_halt_before=halt_before.value,
        operator_halt_after=halt_after.value,
        safety_assertions=assertions,
        expected_safe_assertion_count=len(assertions),
        expected_safe_assertions_passed=sum(1 for item in assertions if item.passed),
        expected_safe_assertions_failed=len(failed_keys),
        failed_safe_assertion_keys=failed_keys,
        remaining_owner_approval_types=tuple(outcome.remaining_owner_approval_types),
        closed_provider_flag_names=_unique_sorted(
            (*outcome.closed_provider_flag_names, *provider.closed_provider_flag_names)
        ),
        missing_credential_names=_unique_sorted(
            (*outcome.missing_credential_names, *provider.missing_credential_names)
        ),
        missing_config_names=missing_config_names,
        blocker_codes=_unique_sorted((*outcome.blocker_codes, *provider.blocker_codes)),
        gate_codes=_unique_sorted((*outcome.gate_codes, *provider.gate_codes)),
        pilot_scope=_pilot_scope(),
        prerequisites=prerequisites,
        runbook_steps=runbook_steps,
        abort_criteria=abort_criteria,
        cli_command=CLI_COMMAND,
        http_route=HTTP_ROUTE,
        source_outcome_command=OUTCOME_CLI_COMMAND,
        source_outcome_route=OUTCOME_HTTP_ROUTE,
        source_outcome_html_route=OUTCOME_HTML_ROUTE,
        source_outcome_overall_status=outcome.overall_status,
        source_rehearsal_command=outcome.source_rehearsal_command,
        source_rehearsal_route=outcome.source_rehearsal_route,
        source_rehearsal_html_route=outcome.source_rehearsal_html_route,
        source_rehearsal_overall_status=outcome.source_rehearsal_overall_status,
        source_launch_readiness_command=outcome.source_launch_readiness_command,
        source_launch_readiness_route=outcome.source_launch_readiness_route,
        source_launch_readiness_overall_status=outcome.source_launch_readiness_overall_status,
        source_index_command=outcome.source_index_command,
        source_index_route=outcome.source_index_route,
        source_index_overall_status=outcome.source_index_overall_status,
        source_blockers_plan_command=outcome.source_blockers_plan_command,
        source_blockers_plan_route=outcome.source_blockers_plan_route,
        source_blockers_plan_overall_status=outcome.source_blockers_plan_overall_status,
        source_staged_rollout_command=outcome.source_staged_rollout_command,
        source_staged_rollout_route=outcome.source_staged_rollout_route,
        source_staged_rollout_overall_status=outcome.source_staged_rollout_overall_status,
        source_dossier_command=outcome.source_dossier_command,
        source_dossier_route=outcome.source_dossier_route,
        source_dossier_overall_status=outcome.source_dossier_overall_status,
        source_provider_setup_command=PROVIDER_CLI_COMMAND,
        source_provider_setup_route=PROVIDER_HTTP_ROUTE,
        source_provider_setup_overall_status=provider.overall_status,
        source_preflight_command=outcome.source_preflight_command,
        source_preflight_route=outcome.source_preflight_route,
        source_preflight_overall_status=outcome.source_preflight_overall_status,
        related_commands=RELATED_COMMANDS,
        related_routes=RELATED_ROUTES,
        local_git=outcome.local_git,
        next_actions=next_actions,
    )


def _safety_assertions(outcome: RehearsalOutcomeReport) -> tuple[PilotAssertion, ...]:
    observed = {
        "OUTBOUND_ENABLED": _bool_text(outcome.outbound_enabled),
        "go_live_permitted": _bool_text(outcome.go_live_permitted),
        "execution_allowed": _bool_text(outcome.execution_allowed),
        "deployment_allowed": _bool_text(outcome.deployment_allowed),
        "owner_approved": _bool_text(outcome.owner_approved),
        "halt_changed": _bool_text(outcome.halt_changed),
        "spend_allowed": "false",
    }
    expected = {key: "false" for key in EXPECTED_SAFE_ASSERTION_KEYS}
    return tuple(
        PilotAssertion(
            key=_safe_text(key),
            expected=expected[key],
            observed=_safe_text(observed[key]),
            passed=observed[key] == expected[key],
        )
        for key in EXPECTED_SAFE_ASSERTION_KEYS
    )


def _pilot_scope() -> PilotScopeRecommendation:
    stop_conditions = (
        "stop_if_outbound_enabled",
        "stop_if_operator_halt_changed",
        "stop_if_spend_attempted",
        "stop_if_live_provider_enabled",
        "stop_if_safe_assertion_fails",
        "stop_if_go_live_permitted",
        "stop_if_owner_approval_missing",
    )
    return PilotScopeRecommendation(
        suggested_max_leads=SUGGESTED_MAX_LEADS,
        suggested_max_drafts=SUGGESTED_MAX_DRAFTS,
        suggested_max_manually_reviewed_sends=SUGGESTED_MAX_MANUALLY_REVIEWED_SENDS,
        suggested_max_daily_activity=SUGGESTED_MAX_DAILY_ACTIVITY,
        stop_conditions=stop_conditions,
        recommendation_summary=_safe_text(
            "Supervised first-pilot count limits only. "
            f"max_leads={SUGGESTED_MAX_LEADS} "
            f"max_drafts={SUGGESTED_MAX_DRAFTS} "
            f"max_manually_reviewed_sends={SUGGESTED_MAX_MANUALLY_REVIEWED_SENDS} "
            f"max_daily_activity={SUGGESTED_MAX_DAILY_ACTIVITY}. "
            "Sends remain 0 because outbound is disabled and this plan does "
            "not permit go-live, spend, or execution."
        ),
    )


def _prerequisites(
    outcome: RehearsalOutcomeReport,
    provider: ProviderSetupChecklist,
) -> tuple[PilotPrerequisite, ...]:
    categories = {item.key: item for item in provider.categories}
    email = categories.get("email_outreach")
    enrichment = categories.get("enrichment")
    calendar = categories.get("calendar")
    remaining = outcome.remaining_owner_approval_types
    approval_status = FindingSeverity.WARNING.value if remaining else FindingSeverity.INFO.value
    return (
        _prerequisite(
            "website_credibility",
            "Website credibility",
            outcome.source_launch_readiness_overall_status,
            "owner_review",
            (),
            (),
            (NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value,),
            ("launch-readiness", "go-live-readiness-index"),
            ("/internal/launch-readiness", "/internal/go-live-readiness-index"),
            (
                "Review website credibility on the existing launch-readiness "
                "and go-live index surfaces. Names and evidence snippets are "
                "not included. This plan does not publish pages."
            ),
        ),
        _from_provider_category(
            "email_domain_setup",
            "Email / domain setup",
            email,
            fallback_status=outcome.source_provider_setup_overall_status,
            review_text=(
                "Review email and domain setup names only on the provider "
                "setup checklist. Do not enable outbound or live outreach."
            ),
        ),
        _from_provider_category(
            "email_outreach_setup",
            "Email / outreach setup",
            email,
            fallback_status=outcome.source_provider_setup_overall_status,
            review_text=(
                "Review outreach enrollment credential and live-flag names "
                "only. Keep live outreach flags closed. This plan does not "
                "enroll campaigns or send email."
            ),
        ),
        _from_provider_category(
            "enrichment_credentials",
            "Enrichment credentials",
            enrichment,
            fallback_status=outcome.source_provider_setup_overall_status,
            review_text=(
                "Review enrichment credential variable names only. Do not "
                "call enrichment providers from this plan."
            ),
        ),
        _from_provider_category(
            "calendar_setup",
            "Calendar setup",
            calendar,
            fallback_status=outcome.source_provider_setup_overall_status,
            review_text=(
                "Review calendar credential and live-flag names only. This "
                "plan does not book meetings or create video-meet links."
            ),
        ),
        _prerequisite(
            "compliance_review",
            "Compliance review",
            _worst_status(
                outcome.source_launch_readiness_overall_status,
                outcome.overall_status,
            ),
            "owner_review",
            (),
            (),
            (NextActionCode.BINDER_IS_NOT_GO_LIVE.value,),
            ("compliance-evidence-binder", "go-live-rehearsal-checklist"),
            (
                "/internal/compliance-evidence-binder",
                "/internal/go-live-rehearsal-checklist",
            ),
            (
                "Review compliance evidence binder and rehearsal surfaces. "
                "This plan does not ingest PHI or real patient data."
            ),
        ),
        _prerequisite(
            "owner_approvals",
            "Owner approvals",
            approval_status,
            remaining[0] if remaining else "owner_review",
            (),
            (),
            (NextActionCode.OWNER_REVIEW_APPROVAL_PACKETS.value,),
            ("owner-launch-dossier", "owner-handoff-packet"),
            (
                "/internal/owner-launch-dossier",
                "/internal/owner-handoff-packet",
            ),
            (
                "Review remaining owner approval types as codes only. This "
                "plan does not set owner_approved or execute packets."
            ),
        ),
        _prerequisite(
            "monitoring",
            "Monitoring",
            FindingSeverity.INFO.value,
            "none",
            (),
            (),
            (NextActionCode.INSPECT_OPERATOR_AUDIT_TIMELINE.value,),
            ("system-status", "operator-command-center"),
            (
                "/internal/monitoring/status",
                "/internal/operator-command-center",
            ),
            (
                "Review operator monitoring and command-center counts only. "
                "This plan does not change live flags or lift halt."
            ),
        ),
    )


def _from_provider_category(
    key: str,
    label: str,
    category: ProviderSetupCategory | None,
    *,
    fallback_status: str,
    review_text: str,
) -> PilotPrerequisite:
    if category is None:
        return _prerequisite(
            key,
            label,
            fallback_status,
            "owner_review",
            (),
            (),
            (NextActionCode.PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value,),
            (PROVIDER_CLI_COMMAND,),
            (PROVIDER_HTTP_ROUTE,),
            review_text,
        )
    return _prerequisite(
        key,
        label,
        category.overall_status,
        category.required_owner_approval_type,
        category.missing_credential_names,
        category.closed_provider_flag_names,
        category.blocker_codes,
        category.related_commands,
        category.related_routes,
        review_text,
    )


def _prerequisite(
    key: str,
    label: str,
    status: str,
    approval: str,
    missing: Sequence[str],
    closed_flags: Sequence[str],
    blocker_codes: Sequence[str],
    commands: Sequence[str],
    routes: Sequence[str],
    review_text: str,
) -> PilotPrerequisite:
    return PilotPrerequisite(
        key=_safe_text(key),
        category=_safe_text(key),
        label=_safe_text(label),
        status=_safe_text(status) or FindingSeverity.INFO.value,
        required_owner_approval_type=_safe_text(approval) or "none",
        missing_credential_names=_unique_sorted(missing),
        closed_provider_flag_names=_unique_sorted(closed_flags),
        blocker_codes=_unique_sorted(blocker_codes),
        related_commands=_unique_sorted(commands),
        related_routes=_unique_sorted(routes),
        review_text=_safe_text(review_text),
    )


def _runbook_steps(
    outcome: RehearsalOutcomeReport,
    prerequisites: Sequence[PilotPrerequisite],
) -> tuple[PilotRunbookStep, ...]:
    by_key = {item.key: item for item in prerequisites}
    safe_status = (
        FindingSeverity.BLOCKED.value
        if outcome.outbound_enabled or outcome.halt_changed
        else FindingSeverity.INFO.value
    )
    return (
        _step(
            "confirm_safe_defaults",
            "Confirm safe defaults and operator halt",
            (
                "Confirm OUTBOUND_ENABLED=false, spend_allowed=false, and "
                "operator halt unchanged. Do not lift halt or enable outbound."
            ),
            safe_status,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
            config_name="OUTBOUND_ENABLED",
        ),
        _step_from_prerequisite(
            "review_website_credibility",
            "Review website credibility",
            (
                "Inspect website credibility status on launch-readiness and "
                "the go-live index. Do not publish content."
            ),
            by_key.get("website_credibility"),
            command_name="launch-readiness",
            json_route="/internal/launch-readiness",
        ),
        _step_from_prerequisite(
            "review_email_domain_setup",
            "Review email and domain setup",
            ("Inspect email and domain setup credential names only. Do not send email."),
            by_key.get("email_domain_setup"),
            command_name=PROVIDER_CLI_COMMAND,
            json_route=PROVIDER_HTTP_ROUTE,
        ),
        _step_from_prerequisite(
            "review_email_outreach_setup",
            "Review email and outreach setup",
            (
                "Inspect outreach enrollment setup names and closed live "
                "flags only. Do not enroll campaigns."
            ),
            by_key.get("email_outreach_setup"),
            command_name=PROVIDER_CLI_COMMAND,
            json_route=PROVIDER_HTTP_ROUTE,
        ),
        _step_from_prerequisite(
            "review_enrichment_credentials",
            "Review enrichment credentials",
            (
                "Inspect enrichment credential variable names only. Do not "
                "call enrichment providers."
            ),
            by_key.get("enrichment_credentials"),
            command_name=PROVIDER_CLI_COMMAND,
            json_route=PROVIDER_HTTP_ROUTE,
        ),
        _step_from_prerequisite(
            "review_calendar_setup",
            "Review calendar setup",
            ("Inspect calendar setup names and closed live flags only. Do not book meetings."),
            by_key.get("calendar_setup"),
            command_name=PROVIDER_CLI_COMMAND,
            json_route=PROVIDER_HTTP_ROUTE,
        ),
        _step_from_prerequisite(
            "review_compliance",
            "Review compliance",
            (
                "Inspect compliance and rehearsal review text only. Do not "
                "ingest PHI or real patient data."
            ),
            by_key.get("compliance_review"),
            command_name="go-live-rehearsal-checklist",
            json_route="/internal/go-live-rehearsal-checklist",
        ),
        _step_from_prerequisite(
            "review_owner_approvals",
            "Review owner approvals",
            (
                "Inspect remaining owner approval type codes only. Do not "
                "set owner_approved or execute packets."
            ),
            by_key.get("owner_approvals"),
            command_name="owner-launch-dossier",
            json_route="/internal/owner-launch-dossier",
        ),
        _step_from_prerequisite(
            "review_monitoring",
            "Review monitoring",
            ("Inspect monitoring and command-center counts only. Do not change live flags."),
            by_key.get("monitoring"),
            command_name="system-status",
            json_route="/internal/monitoring/status",
        ),
        _step(
            "confirm_pilot_scope_limits",
            "Confirm count-only pilot scope limits",
            (
                f"Keep suggested max leads at {SUGGESTED_MAX_LEADS}, max "
                f"drafts at {SUGGESTED_MAX_DRAFTS}, max manually reviewed "
                f"sends at {SUGGESTED_MAX_MANUALLY_REVIEWED_SENDS}, and max "
                f"daily activity at {SUGGESTED_MAX_DAILY_ACTIVITY}. These "
                "are planning counts only."
            ),
            FindingSeverity.INFO.value,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _step(
            "review_abort_criteria",
            "Review abort and rollback criteria",
            (
                "If any safe assertion fails, abort the pilot plan review. "
                "Do not continue to execution, send, spend, or go-live."
            ),
            FindingSeverity.INFO.value,
            command_name=OUTCOME_CLI_COMMAND,
            json_route=OUTCOME_HTTP_ROUTE,
            html_route=OUTCOME_HTML_ROUTE,
        ),
        _step(
            "do_not_execute_or_go_live",
            "Do not execute or go live",
            (
                "This supervised pilot plan is review text only. Command "
                "names and routes are references. Do not execute, deploy, "
                "send, call, book, enroll, spend, or lift halt."
            ),
            FindingSeverity.INFO.value,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
    )


def _step_from_prerequisite(
    step_key: str,
    label: str,
    instruction: str,
    prerequisite: PilotPrerequisite | None,
    *,
    command_name: str | None,
    json_route: str | None,
) -> PilotRunbookStep:
    status = prerequisite.status if prerequisite else FindingSeverity.INFO.value
    return _step(
        step_key,
        label,
        instruction,
        status,
        command_name=command_name,
        json_route=json_route,
    )


def _step(
    step_key: str,
    label: str,
    instruction: str,
    status: str,
    *,
    command_name: str | None = None,
    json_route: str | None = None,
    html_route: str | None = None,
    config_name: str | None = None,
) -> PilotRunbookStep:
    return PilotRunbookStep(
        step_key=_safe_text(step_key),
        label=_safe_text(label),
        instruction=_safe_text(instruction),
        status=_safe_text(status) or FindingSeverity.INFO.value,
        runnable=False,
        executed=0,
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
        config_name=_safe_optional(config_name),
    )


def _abort_criteria() -> tuple[PilotAbortCriterion, ...]:
    return (
        _abort(
            "abort_on_failed_assertion",
            "Abort when a safe assertion fails",
            (
                "If OUTBOUND_ENABLED, go_live_permitted, execution_allowed, "
                "deployment_allowed, owner_approved, halt_changed, or "
                "spend_allowed is not the expected safe value, stop. Do not "
                "continue the pilot."
            ),
        ),
        _abort(
            "keep_operator_halt",
            "Keep operator halt unchanged",
            (
                "Do not lift operator halt during or after this plan. If "
                "halt differs from the before value, treat the plan as "
                "failed."
            ),
        ),
        _abort(
            "keep_outbound_disabled",
            "Keep outbound disabled",
            ("Leave OUTBOUND_ENABLED=false. This plan does not enable outbound or live providers."),
        ),
        _abort(
            "no_spend_or_live_action",
            "Do not spend or take live action",
            (
                "Do not send email, enroll campaigns, place calls, book "
                "meetings, publish content, launch ads, or spend money."
            ),
        ),
        _abort(
            "do_not_deploy_or_publish",
            "Do not deploy, build, or publish",
            (
                "Do not build containers, publish artifacts, deploy, apply "
                "settings, or call deployment providers. Return to the "
                "failing read-only export for owner review."
            ),
        ),
        _abort(
            "no_script_runner",
            "Do not treat command names as runnable automation",
            (
                "Command names and routes are references only. This export "
                "is not a script runner and must not execute those commands."
            ),
        ),
    )


def _abort(code: str, label: str, instruction: str) -> PilotAbortCriterion:
    return PilotAbortCriterion(
        code=_safe_text(code),
        label=_safe_text(label),
        instruction=_safe_text(instruction),
    )


def _next_actions(outcome: RehearsalOutcomeReport) -> tuple[PilotNextAction, ...]:
    actions = [
        _action(
            PLAN_NOT_GO_LIVE_CODE,
            FindingSeverity.INFO.value,
            (
                "This supervised pilot plan is a sanitized small-pilot "
                "planning export. It is not permission to go live and not "
                "an execution surface."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            EXECUTION_DISABLED_CODE,
            FindingSeverity.INFO.value,
            (
                "Execution remains disabled. This plan does not run "
                "commands, apply settings, lift halt, enable outbound, "
                "deploy, build, publish, send, or spend."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            NextActionCode.REHEARSAL_OUTCOME_REPORT_IS_NOT_GO_LIVE.value,
            outcome.overall_status,
            (
                "Review the source rehearsal outcome report. Compact "
                "outcome review only; it is not permission to go live."
            ),
            command_name=OUTCOME_CLI_COMMAND,
            json_route=OUTCOME_HTTP_ROUTE,
            html_route=OUTCOME_HTML_ROUTE,
        ),
        _action(
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            FindingSeverity.INFO.value,
            "Keep OUTBOUND_ENABLED=false.",
            command_name="launch-readiness",
            json_route="/internal/launch-readiness",
            config_name="OUTBOUND_ENABLED",
        ),
    ]
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
) -> PilotNextAction:
    return PilotNextAction(
        code=_safe_text(code),
        status=_safe_text(status) or FindingSeverity.INFO.value,
        label=_safe_text(label),
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
        config_name=_safe_optional(config_name),
    )


def _worst_status(*values: str) -> str:
    cleaned = [_safe_text(item) or FindingSeverity.INFO.value for item in values if item]
    if not cleaned:
        return FindingSeverity.INFO.value
    return max(cleaned, key=lambda item: _STATUS_RANK.get(item, 0))


def _unique_sorted(values: Iterable[str | None]) -> tuple[str, ...]:
    cleaned = [_safe_text(item) for item in values if item]
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


def supervised_pilot_plan_payload(plan: SupervisedPilotPlan) -> dict[str, Any]:
    return {
        "generated_at": plan.generated_at.isoformat(),
        "packet_kind": plan.packet_kind,
        "purpose": plan.purpose,
        "overall_status": plan.overall_status,
        "read_only": True,
        "no_execution": True,
        "no_go_live": True,
        "no_deployment": True,
        "no_spend": True,
        "dry_run_only": True,
        "executed": 0,
        "execution_attempted": False,
        "outbound_attempted": False,
        "live_call_attempted": False,
        "recommendation_applied": False,
        "spend_attempted": False,
        "spend_allowed": False,
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
        "outbound_enabled": plan.outbound_enabled,
        "live_providers_enabled": plan.live_providers_enabled,
        "manual_review_only": True,
        "supervised_pilot_plan_is_not_go_live": True,
        "plan_is_not_permission_to_go_live": True,
        "plan_is_not_execution": True,
        "rehearsal_outcome_report_is_not_go_live": True,
        "go_live_rehearsal_checklist_is_not_go_live": True,
        "rehearsal_is_not_a_script_runner": True,
        "index_is_not_permission_to_go_live": True,
        "dossier_is_not_permission_to_go_live": True,
        "staged_rollout_plan_is_not_go_live": True,
        "provider_setup_checklist_is_not_go_live": True,
        "runbook_is_not_deployment": True,
        "manifest_is_not_a_build_or_deploy": True,
        "operator_halt_status": plan.operator_halt_status,
        "operator_halt_before": plan.operator_halt_before,
        "operator_halt_after": plan.operator_halt_after,
        "safety_assertions": [_assertion_payload(item) for item in plan.safety_assertions],
        "expected_safe_assertion_count": plan.expected_safe_assertion_count,
        "expected_safe_assertions_passed": plan.expected_safe_assertions_passed,
        "expected_safe_assertions_failed": plan.expected_safe_assertions_failed,
        "failed_safe_assertion_keys": list(plan.failed_safe_assertion_keys),
        "remaining_owner_approval_types": list(plan.remaining_owner_approval_types),
        "closed_provider_flag_names": list(plan.closed_provider_flag_names),
        "missing_credential_names": list(plan.missing_credential_names),
        "missing_config_names": list(plan.missing_config_names),
        "blocker_codes": list(plan.blocker_codes),
        "gate_codes": list(plan.gate_codes),
        "pilot_scope": {
            "suggested_max_leads": plan.pilot_scope.suggested_max_leads,
            "suggested_max_drafts": plan.pilot_scope.suggested_max_drafts,
            "suggested_max_manually_reviewed_sends": (
                plan.pilot_scope.suggested_max_manually_reviewed_sends
            ),
            "suggested_max_daily_activity": plan.pilot_scope.suggested_max_daily_activity,
            "stop_conditions": list(plan.pilot_scope.stop_conditions),
            "recommendation_summary": plan.pilot_scope.recommendation_summary,
        },
        "prerequisites": [_prerequisite_payload(item) for item in plan.prerequisites],
        "runbook_steps": [_step_payload(item) for item in plan.runbook_steps],
        "abort_criteria": [_abort_payload(item) for item in plan.abort_criteria],
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "source_outcome_command": plan.source_outcome_command,
        "source_outcome_route": plan.source_outcome_route,
        "source_outcome_html_route": plan.source_outcome_html_route,
        "source_outcome_overall_status": plan.source_outcome_overall_status,
        "source_rehearsal_command": plan.source_rehearsal_command,
        "source_rehearsal_route": plan.source_rehearsal_route,
        "source_rehearsal_html_route": plan.source_rehearsal_html_route,
        "source_rehearsal_overall_status": plan.source_rehearsal_overall_status,
        "source_launch_readiness_command": plan.source_launch_readiness_command,
        "source_launch_readiness_route": plan.source_launch_readiness_route,
        "source_launch_readiness_overall_status": plan.source_launch_readiness_overall_status,
        "source_index_command": plan.source_index_command,
        "source_index_route": plan.source_index_route,
        "source_index_overall_status": plan.source_index_overall_status,
        "source_blockers_plan_command": plan.source_blockers_plan_command,
        "source_blockers_plan_route": plan.source_blockers_plan_route,
        "source_blockers_plan_overall_status": plan.source_blockers_plan_overall_status,
        "source_staged_rollout_command": plan.source_staged_rollout_command,
        "source_staged_rollout_route": plan.source_staged_rollout_route,
        "source_staged_rollout_overall_status": plan.source_staged_rollout_overall_status,
        "source_dossier_command": plan.source_dossier_command,
        "source_dossier_route": plan.source_dossier_route,
        "source_dossier_overall_status": plan.source_dossier_overall_status,
        "source_provider_setup_command": plan.source_provider_setup_command,
        "source_provider_setup_route": plan.source_provider_setup_route,
        "source_provider_setup_overall_status": plan.source_provider_setup_overall_status,
        "source_preflight_command": plan.source_preflight_command,
        "source_preflight_route": plan.source_preflight_route,
        "source_preflight_overall_status": plan.source_preflight_overall_status,
        "related_commands": list(plan.related_commands),
        "related_routes": list(plan.related_routes),
        "local_git": {
            "available": plan.local_git.available,
            "current_branch": plan.local_git.current_branch,
            "current_sha": plan.local_git.current_sha,
            "working_tree_status": plan.local_git.working_tree_status,
            "git_provider_called": False,
            "github_actions_called": False,
        },
        "next_actions": [_action_payload(action) for action in plan.next_actions],
    }


def _assertion_payload(item: PilotAssertion) -> dict[str, Any]:
    return {
        "key": item.key,
        "expected": item.expected,
        "observed": item.observed,
        "passed": item.passed,
    }


def _prerequisite_payload(item: PilotPrerequisite) -> dict[str, Any]:
    return {
        "key": item.key,
        "category": item.category,
        "label": item.label,
        "status": item.status,
        "required_owner_approval_type": item.required_owner_approval_type,
        "missing_credential_names": list(item.missing_credential_names),
        "closed_provider_flag_names": list(item.closed_provider_flag_names),
        "blocker_codes": list(item.blocker_codes),
        "related_commands": list(item.related_commands),
        "related_routes": list(item.related_routes),
        "review_text": item.review_text,
    }


def _step_payload(item: PilotRunbookStep) -> dict[str, Any]:
    return {
        "step_key": item.step_key,
        "label": item.label,
        "instruction": item.instruction,
        "status": item.status,
        "runnable": False,
        "executed": 0,
        "command_name": item.command_name,
        "json_route": item.json_route,
        "html_route": item.html_route,
        "config_name": item.config_name,
    }


def _abort_payload(item: PilotAbortCriterion) -> dict[str, Any]:
    return {
        "code": item.code,
        "label": item.label,
        "instruction": item.instruction,
    }


def _action_payload(action: PilotNextAction) -> dict[str, Any]:
    return {
        "code": action.code,
        "status": action.status,
        "label": action.label,
        "command_name": action.command_name,
        "json_route": action.json_route,
        "html_route": action.html_route,
        "config_name": action.config_name,
    }


def format_supervised_pilot_plan(
    plan: SupervisedPilotPlan,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(supervised_pilot_plan_payload(plan))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(plan, payload)


def _format_markdown(plan: SupervisedPilotPlan, payload: dict[str, Any]) -> str:
    lines = [
        "# Supervised pilot launch plan",
        "",
        "This plan is a sanitized small-pilot planning export over existing "
        "readiness, rehearsal, outcome, provider setup, and launch dossier "
        "surfaces. It reuses those services as source material and never "
        "executes commands, applies settings, lifts halt, enables outbound, "
        "deploys, builds, publishes, or spends. It is not permission to go "
        "live and not an execution surface.",
        "",
        f"- overall: {payload['overall_status']}",
        f"- packet_kind: {payload['packet_kind']}",
        f"- purpose: {payload['purpose']}",
        f"- read_only: {_bool_text(payload['read_only'])}",
        f"- no_execution: {_bool_text(payload['no_execution'])}",
        f"- no_go_live: {_bool_text(payload['no_go_live'])}",
        f"- no_deployment: {_bool_text(payload['no_deployment'])}",
        f"- no_spend: {_bool_text(payload['no_spend'])}",
        f"- dry_run_only: {_bool_text(payload['dry_run_only'])}",
        f"- executed: {payload['executed']}",
        f"- owner_approved: {_bool_text(payload['owner_approved'])}",
        f"- settings_applied: {_bool_text(payload['settings_applied'])}",
        f"- halt_changed: {_bool_text(payload['halt_changed'])}",
        f"- live_action: {_bool_text(payload['live_action'])}",
        f"- execution_allowed: {_bool_text(payload['execution_allowed'])}",
        f"- go_live_permitted: {_bool_text(payload['go_live_permitted'])}",
        f"- deployment_allowed: {_bool_text(payload['deployment_allowed'])}",
        f"- spend_allowed: {_bool_text(payload['spend_allowed'])}",
        f"- manual_review_only: {_bool_text(payload['manual_review_only'])}",
        (
            "- supervised_pilot_plan_is_not_go_live: "
            f"{_bool_text(payload['supervised_pilot_plan_is_not_go_live'])}"
        ),
        (
            "- plan_is_not_permission_to_go_live: "
            f"{_bool_text(payload['plan_is_not_permission_to_go_live'])}"
        ),
        f"- plan_is_not_execution: {_bool_text(payload['plan_is_not_execution'])}",
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
        f"- source_outcome_command: {payload['source_outcome_command']}",
        f"- source_rehearsal_command: {payload['source_rehearsal_command']}",
        f"- source_launch_readiness_command: {payload['source_launch_readiness_command']}",
        f"- source_index_command: {payload['source_index_command']}",
        f"- source_blockers_plan_command: {payload['source_blockers_plan_command']}",
        f"- source_staged_rollout_command: {payload['source_staged_rollout_command']}",
        f"- source_dossier_command: {payload['source_dossier_command']}",
        f"- source_provider_setup_command: {payload['source_provider_setup_command']}",
        f"- source_preflight_command: {payload['source_preflight_command']}",
        f"- expected_safe_assertion_count: {payload['expected_safe_assertion_count']}",
        f"- expected_safe_assertions_passed: {payload['expected_safe_assertions_passed']}",
        f"- expected_safe_assertions_failed: {payload['expected_safe_assertions_failed']}",
        f"- failed_safe_assertion_keys: {_format_codes(plan.failed_safe_assertion_keys)}",
        f"- remaining_owner_approval_types: {_format_codes(plan.remaining_owner_approval_types)}",
        f"- blocker_codes: {_format_codes(plan.blocker_codes)}",
        f"- gate_codes: {_format_codes(plan.gate_codes)}",
        f"- missing_credential_names: {_format_codes(plan.missing_credential_names)}",
        f"- missing_config_names: {_format_codes(plan.missing_config_names)}",
        f"- closed_provider_flag_names: {_format_codes(plan.closed_provider_flag_names)}",
        "",
        "## Live-blocking flags",
        f"- OUTBOUND_ENABLED={_bool_text(plan.outbound_enabled)}",
        f"- operator_halt_status={plan.operator_halt_status}",
        f"- live_providers_enabled={_bool_text(plan.live_providers_enabled)}",
        "- read_only=true",
        "- no_execution=true",
        "- no_go_live=true",
        "- no_deployment=true",
        "- no_spend=true",
        "- manual_review_only=true",
        "- execution_allowed=false",
        "- go_live_permitted=false",
        "- deployment_allowed=false",
        "- spend_allowed=false",
        "- settings_applied=false",
        "- halt_changed=false",
        "- owner_approved=false",
        "- supervised_pilot_plan_is_not_go_live=true",
        "- plan_is_not_permission_to_go_live=true",
        "- plan_is_not_execution=true",
        f"- local_git_available: {_bool_text(plan.local_git.available)}",
        f"- current_branch: {plan.local_git.current_branch}",
        f"- current_sha: {plan.local_git.current_sha}",
        f"- working_tree_status: {plan.local_git.working_tree_status}",
        f"- git_provider_called: {_bool_text(plan.local_git.git_provider_called)}",
        f"- github_actions_called: {_bool_text(plan.local_git.github_actions_called)}",
        "",
        "## Pilot scope recommendation",
        f"- suggested_max_leads: {plan.pilot_scope.suggested_max_leads}",
        f"- suggested_max_drafts: {plan.pilot_scope.suggested_max_drafts}",
        (
            "- suggested_max_manually_reviewed_sends: "
            f"{plan.pilot_scope.suggested_max_manually_reviewed_sends}"
        ),
        f"- suggested_max_daily_activity: {plan.pilot_scope.suggested_max_daily_activity}",
        f"- stop_conditions: {_format_codes(plan.pilot_scope.stop_conditions)}",
        f"- recommendation_summary: {plan.pilot_scope.recommendation_summary}",
        "",
        "## Safety assertions",
    ]
    for assertion in plan.safety_assertions:
        lines.append(
            f"- {assertion.key}: expected={assertion.expected} "
            f"observed={assertion.observed} passed={_bool_text(assertion.passed)}"
        )
    lines.extend(["", "## Pilot prerequisites"])
    for prerequisite in plan.prerequisites:
        lines.append(
            f"- [{prerequisite.status}] {prerequisite.key} "
            f"approval={prerequisite.required_owner_approval_type} "
            f"missing={_format_codes(prerequisite.missing_credential_names)} "
            f"closed_flags={_format_codes(prerequisite.closed_provider_flag_names)} "
            f"label={prerequisite.label}"
        )
    lines.extend(["", "## Manual pilot runbook"])
    for step in plan.runbook_steps:
        command_name = step.command_name or "-"
        json_route = step.json_route or "-"
        lines.append(
            f"- [{step.status}] {step.step_key} runnable={_bool_text(step.runnable)} "
            f"executed={step.executed} command={command_name} "
            f"json_route={json_route} label={step.label}"
        )
    lines.extend(["", "## Pilot abort and rollback criteria"])
    for criterion in plan.abort_criteria:
        lines.append(
            f"- {criterion.code}: {criterion.label} instruction={criterion.instruction}"
        )
    lines.extend(["", "## Owner next actions"])
    for action in plan.next_actions:
        command_name = action.command_name or "-"
        json_route = action.json_route or "-"
        html_route = action.html_route or "-"
        config_name = action.config_name or "-"
        lines.append(
            f"- [{action.status}] {action.code} command={command_name} "
            f"json_route={json_route} html_route={html_route} "
            f"config_name={config_name} label={action.label}"
        )
    if not plan.next_actions:
        lines.append("- next_actions: none")
    return "\n".join(lines)


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"
