"""Read-only supervised pilot first-send preflight export.

Phase 61 consolidates the Phase 59 go/no-go packet, Phase 55 supervised
pilot plan, and operator halt / control flags into one sanitized first-send
preflight. It reuses those services as source material and never
recalculates readiness. It never executes, applies settings, lifts halt,
enables outbound, calls providers, scrapes, builds, publishes, deploys,
spends, or changes live state. This preflight is not permission to send,
not permission to go live, and not an execution surface.
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
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.supervised_pilot_go_no_go import (
    CLI_COMMAND as GO_NO_GO_CLI_COMMAND,
)
from vyro_growth.services.supervised_pilot_go_no_go import (
    HTML_ROUTE as GO_NO_GO_HTML_ROUTE,
)
from vyro_growth.services.supervised_pilot_go_no_go import (
    HTTP_ROUTE as GO_NO_GO_HTTP_ROUTE,
)
from vyro_growth.services.supervised_pilot_go_no_go import (
    GoNoGoCount,
    GoNoGoGate,
    SupervisedPilotGoNoGo,
    SupervisedPilotGoNoGoService,
)
from vyro_growth.services.supervised_pilot_plan import (
    CLI_COMMAND as PILOT_CLI_COMMAND,
)
from vyro_growth.services.supervised_pilot_plan import (
    HTML_ROUTE as PILOT_HTML_ROUTE,
)
from vyro_growth.services.supervised_pilot_plan import (
    HTTP_ROUTE as PILOT_HTTP_ROUTE,
)
from vyro_growth.services.supervised_pilot_plan import (
    PilotAbortCriterion,
    PilotScopeRecommendation,
    SupervisedPilotPlan,
    SupervisedPilotPlanService,
)

logger = structlog.get_logger(__name__)

PACKET_KIND = "supervised_pilot_first_send_preflight"
PACKET_PURPOSE = "manual_owner_supervised_pilot_first_send_preflight_review_only"
PREFLIGHT_NOT_GO_LIVE_CODE = (
    NextActionCode.SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_IS_NOT_GO_LIVE.value
)
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
CLI_COMMAND = "supervised-pilot-first-send-preflight"
HTTP_ROUTE = "/internal/supervised-pilot-first-send-preflight"
HTML_ROUTE = "/internal/operator-supervised-pilot-first-send-preflight"
SUGGESTED_MAX_FIRST_SENDS = 0
RELATED_COMMANDS: tuple[str, ...] = (
    GO_NO_GO_CLI_COMMAND,
    PILOT_CLI_COMMAND,
    "supervised-pilot-candidates",
    "launch-readiness",
    "go-live-readiness-index",
    "launch-blockers-plan",
    "staged-rollout-plan",
    "owner-launch-dossier",
    "provider-setup-checklist",
    "go-live-rehearsal-checklist",
    "rehearsal-outcome-report",
    "action-readiness",
    "settings-execution-preflight",
    "dashboard-summary",
    "check-config",
    "smoke-dry-run",
    CLI_COMMAND,
    "supervised-pilot-launch-rehearsal-control-map",
    "supervised-pilot-first-send-owner-authorization-packet",
    "system-status",
)
RELATED_ROUTES: tuple[str, ...] = (
    GO_NO_GO_HTML_ROUTE,
    GO_NO_GO_HTTP_ROUTE,
    PILOT_HTML_ROUTE,
    PILOT_HTTP_ROUTE,
    "/internal/operator-supervised-pilot-candidates",
    "/internal/supervised-pilot-candidates",
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
    "/internal/provider-setup-checklist",
    "/internal/operator-go-live-rehearsal-checklist",
    "/internal/go-live-rehearsal-checklist",
    "/internal/operator-rehearsal-outcome-report",
    "/internal/rehearsal-outcome-report",
    "/internal/operator-action-readiness",
    "/internal/action-readiness",
    "/internal/operator-review-queue",
    "/internal/review-queue",
    "/internal/operator-approval-packets",
    "/internal/operator-settings-change-requests",
    HTML_ROUTE,
    HTTP_ROUTE,
    "/internal/operator-supervised-pilot-launch-rehearsal-control-map",
    "/internal/supervised-pilot-launch-rehearsal-control-map",
    "/internal/supervised-pilot-first-send-owner-authorization-packet",
)


@dataclass(frozen=True)
class FirstSendCount:
    key: str
    count: int


@dataclass(frozen=True)
class FirstSendPreflightCheck:
    code: str
    status: str
    label: str
    blocking: bool
    command_name: str | None
    json_route: str | None
    html_route: str | None


@dataclass(frozen=True)
class FirstSendAbortCriterion:
    code: str
    label: str
    instruction: str


@dataclass(frozen=True)
class FirstSendNextAction:
    code: str
    status: str
    label: str
    command_name: str | None
    json_route: str | None
    html_route: str | None
    config_name: str | None


@dataclass(frozen=True)
class SupervisedPilotFirstSendPreflight:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
    no_execution: bool
    no_go_live: bool
    no_deployment: bool
    no_outbound: bool
    no_provider_calls: bool
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
    first_send_allowed: bool
    first_send_attempted: bool
    first_send_executed: int
    sends_executed: int
    suggested_max_first_sends: int
    suggested_max_leads: int
    suggested_max_drafts: int
    suggested_max_manually_reviewed_sends: int
    suggested_max_daily_activity: int
    supervised_pilot_first_send_preflight_is_not_go_live: bool
    first_send_preflight_is_not_a_send: bool
    export_is_not_permission_to_go_live: bool
    export_is_not_execution: bool
    supervised_pilot_go_no_go_is_not_go_live: bool
    supervised_pilot_plan_is_not_go_live: bool
    supervised_pilot_candidates_is_not_go_live: bool
    rehearsal_outcome_report_is_not_go_live: bool
    go_live_rehearsal_checklist_is_not_go_live: bool
    provider_setup_checklist_is_not_go_live: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    source_go_no_go_overall_status: str
    source_pilot_plan_overall_status: str
    source_candidates_overall_status: str
    ready_for_review_count: int
    blocked_candidate_count: int
    total_candidate_count: int
    review_queue_pending_count: int
    action_readiness_candidate_count: int
    approval_packet_count: int
    settings_request_count: int
    settings_request_pending_count: int
    prerequisite_counts_by_status: tuple[FirstSendCount, ...]
    candidate_counts_by_readiness: tuple[FirstSendCount, ...]
    blocked_reason_counts: tuple[FirstSendCount, ...]
    expected_safe_assertion_count: int
    expected_safe_assertions_passed: int
    expected_safe_assertions_failed: int
    failed_safe_assertion_keys: tuple[str, ...]
    preflight_checks: tuple[FirstSendPreflightCheck, ...]
    abort_criteria: tuple[FirstSendAbortCriterion, ...]
    stop_conditions: tuple[str, ...]
    owner_decision_prerequisites: tuple[str, ...]
    remaining_owner_approval_types: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    missing_config_names: tuple[str, ...]
    missing_prerequisite_codes: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    gate_codes: tuple[str, ...]
    cli_command: str
    http_route: str
    source_go_no_go_command: str
    source_go_no_go_route: str
    source_go_no_go_html_route: str
    source_pilot_plan_command: str
    source_pilot_plan_route: str
    source_pilot_plan_html_route: str
    source_candidates_command: str
    source_candidates_route: str
    source_candidates_html_route: str
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    next_actions: tuple[FirstSendNextAction, ...]


class SupervisedPilotFirstSendPreflightService:
    """Compose a sanitized first-send preflight from existing review surfaces."""

    def __init__(
        self,
        *,
        go_no_go: SupervisedPilotGoNoGoService | None = None,
        pilot_plan: SupervisedPilotPlanService | None = None,
    ) -> None:
        self.go_no_go = go_no_go or SupervisedPilotGoNoGoService()
        self.pilot_plan = pilot_plan or SupervisedPilotPlanService()

    def build(self, db: Session, settings: Settings) -> SupervisedPilotFirstSendPreflight:
        halt_before = read_operator_halt(db)
        go_no_go = self.go_no_go.build(db, settings)
        plan = self.pilot_plan.build(db, settings)
        halt_after = read_operator_halt(db)
        if halt_after != halt_before:
            raise RuntimeError(
                "supervised pilot first-send preflight must not change operator halt status"
            )
        packet = _from_sources(
            go_no_go,
            plan,
            halt_before=halt_before,
            halt_after=halt_after,
        )
        logger.info(
            "supervised_pilot_first_send_preflight_built",
            read_only=True,
            no_execution=True,
            no_go_live=True,
            no_outbound=True,
            no_provider_calls=True,
            no_spend=True,
            overall_status=packet.overall_status,
            operator_halt_status=packet.operator_halt_status,
            outbound_enabled=packet.outbound_enabled,
            go_live_permitted=False,
            execution_allowed=False,
            first_send_allowed=False,
            first_send_executed=0,
            deployment_allowed=False,
            settings_applied=False,
            halt_changed=False,
            owner_approved=False,
            spend_allowed=False,
            executed=0,
            supervised_pilot_first_send_preflight_is_not_go_live=True,
        )
        return packet


def _from_sources(
    go_no_go: SupervisedPilotGoNoGo,
    plan: SupervisedPilotPlan,
    *,
    halt_before: HaltStatus,
    halt_after: HaltStatus,
) -> SupervisedPilotFirstSendPreflight:
    scope = plan.pilot_scope
    failed_keys = _failed_assertion_keys(go_no_go, plan)
    checks = _preflight_checks(go_no_go, plan, failed_keys=failed_keys)
    abort_criteria = _abort_criteria(plan.abort_criteria)
    next_actions = _next_actions(go_no_go)
    expected_count = _expected_assertion_count()
    passed_count = expected_count - len(failed_keys)
    return SupervisedPilotFirstSendPreflight(
        generated_at=datetime.now(tz=UTC),
        packet_kind=PACKET_KIND,
        purpose=PACKET_PURPOSE,
        overall_status=_safe_text(go_no_go.overall_status) or FindingSeverity.INFO.value,
        read_only=True,
        no_execution=True,
        no_go_live=True,
        no_deployment=True,
        no_outbound=True,
        no_provider_calls=True,
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
        outbound_enabled=go_no_go.outbound_enabled,
        live_providers_enabled=go_no_go.live_providers_enabled,
        manual_review_only=True,
        first_send_allowed=False,
        first_send_attempted=False,
        first_send_executed=0,
        sends_executed=0,
        suggested_max_first_sends=SUGGESTED_MAX_FIRST_SENDS,
        suggested_max_leads=scope.suggested_max_leads,
        suggested_max_drafts=scope.suggested_max_drafts,
        suggested_max_manually_reviewed_sends=scope.suggested_max_manually_reviewed_sends,
        suggested_max_daily_activity=scope.suggested_max_daily_activity,
        supervised_pilot_first_send_preflight_is_not_go_live=True,
        first_send_preflight_is_not_a_send=True,
        export_is_not_permission_to_go_live=True,
        export_is_not_execution=True,
        supervised_pilot_go_no_go_is_not_go_live=True,
        supervised_pilot_plan_is_not_go_live=True,
        supervised_pilot_candidates_is_not_go_live=True,
        rehearsal_outcome_report_is_not_go_live=True,
        go_live_rehearsal_checklist_is_not_go_live=True,
        provider_setup_checklist_is_not_go_live=True,
        operator_halt_status=halt_after.value,
        operator_halt_before=halt_before.value,
        operator_halt_after=halt_after.value,
        source_go_no_go_overall_status=go_no_go.overall_status,
        source_pilot_plan_overall_status=plan.overall_status,
        source_candidates_overall_status=go_no_go.source_candidates_overall_status,
        ready_for_review_count=go_no_go.ready_for_review_count,
        blocked_candidate_count=go_no_go.blocked_candidate_count,
        total_candidate_count=go_no_go.total_candidate_count,
        review_queue_pending_count=go_no_go.review_queue_pending_count,
        action_readiness_candidate_count=go_no_go.action_readiness_candidate_count,
        approval_packet_count=go_no_go.approval_packet_count,
        settings_request_count=go_no_go.settings_request_count,
        settings_request_pending_count=go_no_go.settings_request_pending_count,
        prerequisite_counts_by_status=_copy_counts(go_no_go.prerequisite_counts_by_status),
        candidate_counts_by_readiness=_copy_counts(go_no_go.candidate_counts_by_readiness),
        blocked_reason_counts=_copy_counts(go_no_go.blocked_reason_counts),
        expected_safe_assertion_count=expected_count,
        expected_safe_assertions_passed=passed_count,
        expected_safe_assertions_failed=len(failed_keys),
        failed_safe_assertion_keys=failed_keys,
        preflight_checks=checks,
        abort_criteria=abort_criteria,
        stop_conditions=_stop_conditions(scope),
        owner_decision_prerequisites=tuple(go_no_go.owner_decision_prerequisites),
        remaining_owner_approval_types=tuple(go_no_go.remaining_owner_approval_types),
        closed_provider_flag_names=tuple(go_no_go.closed_provider_flag_names),
        missing_credential_names=tuple(go_no_go.missing_credential_names),
        missing_config_names=tuple(go_no_go.missing_config_names),
        missing_prerequisite_codes=tuple(go_no_go.missing_prerequisite_codes),
        blocker_codes=_unique_sorted(
            (
                *go_no_go.blocker_codes,
                *plan.blocker_codes,
                *(item.code for item in checks if item.blocking),
            )
        ),
        gate_codes=_unique_sorted(
            (*go_no_go.gate_codes, *plan.gate_codes, *(item.code for item in checks))
        ),
        cli_command=CLI_COMMAND,
        http_route=HTTP_ROUTE,
        source_go_no_go_command=GO_NO_GO_CLI_COMMAND,
        source_go_no_go_route=GO_NO_GO_HTTP_ROUTE,
        source_go_no_go_html_route=GO_NO_GO_HTML_ROUTE,
        source_pilot_plan_command=PILOT_CLI_COMMAND,
        source_pilot_plan_route=PILOT_HTTP_ROUTE,
        source_pilot_plan_html_route=PILOT_HTML_ROUTE,
        source_candidates_command=go_no_go.source_candidates_command,
        source_candidates_route=go_no_go.source_candidates_route,
        source_candidates_html_route=go_no_go.source_candidates_html_route,
        related_commands=RELATED_COMMANDS,
        related_routes=RELATED_ROUTES,
        local_git=go_no_go.local_git,
        next_actions=next_actions,
    )


def _copy_counts(items: Sequence[GoNoGoCount]) -> tuple[FirstSendCount, ...]:
    return tuple(FirstSendCount(key=_safe_text(item.key), count=int(item.count)) for item in items)


def _expected_assertion_count() -> int:
    return len(_assertion_pairs(None, None))


def _assertion_pairs(
    go_no_go: SupervisedPilotGoNoGo | None,
    plan: SupervisedPilotPlan | None,
) -> tuple[tuple[str, bool], ...]:
    outbound_ok = True if go_no_go is None else not go_no_go.outbound_enabled
    halt_ok = True if go_no_go is None else not go_no_go.halt_changed
    spend_ok = True if go_no_go is None else not go_no_go.spend_allowed
    live_ok = True if go_no_go is None else not go_no_go.live_providers_enabled
    plan_sends_ok = (
        True
        if plan is None
        else plan.pilot_scope.suggested_max_manually_reviewed_sends == 0
    )
    return (
        ("outbound_enabled_false", outbound_ok),
        ("go_live_permitted_false", True),
        ("execution_allowed_false", True),
        ("first_send_allowed_false", True),
        ("first_send_executed_zero", True),
        ("deployment_allowed_false", True),
        ("owner_approved_false", True),
        ("settings_applied_false", True),
        ("halt_changed_false", halt_ok),
        ("spend_allowed_false", spend_ok),
        ("live_providers_enabled_false", live_ok),
        ("suggested_max_first_sends_zero", True),
        ("suggested_max_manually_reviewed_sends_zero", plan_sends_ok),
    )


def _failed_assertion_keys(
    go_no_go: SupervisedPilotGoNoGo,
    plan: SupervisedPilotPlan,
) -> tuple[str, ...]:
    return tuple(key for key, passed in _assertion_pairs(go_no_go, plan) if not passed)


def _preflight_checks(
    go_no_go: SupervisedPilotGoNoGo,
    plan: SupervisedPilotPlan,
    *,
    failed_keys: Sequence[str],
) -> tuple[FirstSendPreflightCheck, ...]:
    reused = tuple(_check_from_gate(gate) for gate in go_no_go.go_no_go_gates)
    extra = (
        _check(
            "first_send_not_permitted",
            FindingSeverity.INFO.value,
            (
                "First send remains not permitted. This preflight does "
                "not send, enqueue, or select a candidate."
            ),
            blocking=False,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _check(
            "suggested_max_first_sends",
            FindingSeverity.INFO.value,
            (
                f"Suggested max first sends remains {SUGGESTED_MAX_FIRST_SENDS}. "
                "This is a planning count only."
            ),
            blocking=False,
            command_name=PILOT_CLI_COMMAND,
            json_route=PILOT_HTTP_ROUTE,
            html_route=PILOT_HTML_ROUTE,
        ),
        _check(
            "safe_assertions",
            FindingSeverity.BLOCKED.value if failed_keys else FindingSeverity.INFO.value,
            (
                "Expected safe assertions failed."
                if failed_keys
                else "Expected safe assertions passed using flag names only."
            ),
            blocking=bool(failed_keys),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _check(
            "source_go_no_go",
            go_no_go.overall_status,
            "Reuse the supervised pilot go/no-go packet. Do not recalculate readiness.",
            blocking=_is_blocking(go_no_go.overall_status),
            command_name=GO_NO_GO_CLI_COMMAND,
            json_route=GO_NO_GO_HTTP_ROUTE,
            html_route=GO_NO_GO_HTML_ROUTE,
        ),
        _check(
            "source_pilot_plan",
            plan.overall_status,
            "Reuse the supervised pilot plan abort and scope counts only.",
            blocking=_is_blocking(plan.overall_status),
            command_name=PILOT_CLI_COMMAND,
            json_route=PILOT_HTTP_ROUTE,
            html_route=PILOT_HTML_ROUTE,
        ),
        _check(
            "preflight_is_not_a_send",
            FindingSeverity.INFO.value,
            (
                "This first-send preflight is owner review only. It is "
                "not a send, not permission to go live, and not an "
                "execution surface."
            ),
            blocking=False,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
    )
    return (*reused, *extra)


def _check_from_gate(gate: GoNoGoGate) -> FirstSendPreflightCheck:
    return _check(
        gate.code,
        gate.status,
        gate.label,
        blocking=gate.blocking,
        command_name=gate.command_name,
        json_route=gate.json_route,
        html_route=gate.html_route,
    )


def _check(
    code: str,
    status: str,
    label: str,
    *,
    blocking: bool,
    command_name: str | None = None,
    json_route: str | None = None,
    html_route: str | None = None,
) -> FirstSendPreflightCheck:
    cleaned_status = _safe_text(status) or FindingSeverity.INFO.value
    return FirstSendPreflightCheck(
        code=_safe_text(code),
        status=cleaned_status,
        label=_safe_text(label),
        blocking=bool(blocking) or _is_blocking(cleaned_status),
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
    )


def _abort_criteria(
    items: Sequence[PilotAbortCriterion],
) -> tuple[FirstSendAbortCriterion, ...]:
    copied = tuple(
        FirstSendAbortCriterion(
            code=_safe_text(item.code),
            label=_safe_text(item.label),
            instruction=_safe_text(item.instruction),
        )
        for item in items
    )
    extra = FirstSendAbortCriterion(
        code="abort_before_any_first_send",
        label="Abort before any first send",
        instruction=(
            "Do not send, enqueue, or contact a candidate from this "
            "preflight. If any safe assertion fails, return to the "
            "go/no-go packet for owner review."
        ),
    )
    return (*copied, extra)


def _stop_conditions(scope: PilotScopeRecommendation) -> tuple[str, ...]:
    return _unique_sorted(
        (
            *(_safe_text(item) for item in scope.stop_conditions),
            "first_send_not_permitted",
            "outbound_enabled",
            "halt_changed",
            "owner_approved",
            "spend_allowed",
        )
    )


def _next_actions(
    go_no_go: SupervisedPilotGoNoGo,
) -> tuple[FirstSendNextAction, ...]:
    return (
        _action(
            PREFLIGHT_NOT_GO_LIVE_CODE,
            FindingSeverity.INFO.value,
            (
                "This supervised pilot first-send preflight is a sanitized "
                "owner-review export. It is not permission to send, not "
                "permission to go live, and not an execution surface."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            EXECUTION_DISABLED_CODE,
            FindingSeverity.INFO.value,
            (
                "Execution remains disabled. This preflight does not "
                "select candidates, run commands, apply settings, lift "
                "halt, enable outbound, deploy, build, publish, send, "
                "or spend."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            NextActionCode.SUPERVISED_PILOT_GO_NO_GO_IS_NOT_GO_LIVE.value,
            FindingSeverity.INFO.value,
            (
                "Review the source go/no-go packet using counts, codes, "
                "and flag names only."
            ),
            command_name=GO_NO_GO_CLI_COMMAND,
            json_route=GO_NO_GO_HTTP_ROUTE,
            html_route=GO_NO_GO_HTML_ROUTE,
        ),
        _action(
            NextActionCode.SUPERVISED_PILOT_PLAN_IS_NOT_GO_LIVE.value,
            FindingSeverity.INFO.value,
            (
                "Review the source supervised pilot plan abort criteria "
                "and count-only scope limits."
            ),
            command_name=PILOT_CLI_COMMAND,
            json_route=PILOT_HTTP_ROUTE,
            html_route=PILOT_HTML_ROUTE,
        ),
        _action(
            NextActionCode.SUPERVISED_PILOT_CANDIDATES_IS_NOT_GO_LIVE.value,
            FindingSeverity.INFO.value,
            (
                "Review candidate readiness counts only. This preflight "
                "does not select or contact candidates."
            ),
            command_name=go_no_go.source_candidates_command,
            json_route=go_no_go.source_candidates_route,
            html_route=go_no_go.source_candidates_html_route,
        ),
        _action(
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            FindingSeverity.INFO.value,
            "Leave OUTBOUND_ENABLED=false. This preflight does not enable outbound.",
            command_name="launch-readiness",
            json_route="/internal/launch-readiness",
            config_name="OUTBOUND_ENABLED",
        ),
        _action(
            NextActionCode.KEEP_OPERATOR_HALT.value
            if go_no_go.operator_halt_status == HaltStatus.HALTED.value
            else NextActionCode.RECORD_OPERATOR_HALT.value,
            FindingSeverity.INFO.value,
            (
                "Keep operator halt unchanged. This preflight reads halt "
                "status only and never lifts it."
            ),
            command_name="system-status",
            json_route="/internal/monitoring/status",
        ),
        _action(
            NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
            FindingSeverity.INFO.value,
            (
                "Keep live provider flags closed. This preflight lists "
                "closed flag names only."
            ),
            command_name="provider-setup-checklist",
            json_route="/internal/provider-setup-checklist",
            html_route="/internal/operator-provider-setup-checklist",
        ),
        _action(
            NextActionCode.INSPECT_SETTINGS_EXECUTION_PREFLIGHT.value,
            FindingSeverity.INFO.value,
            (
                "Inspect settings-execution preflight counts only. This "
                "export does not apply settings."
            ),
            command_name="settings-execution-preflight",
            json_route="/internal/settings-execution-preflight",
            html_route="/internal/operator-settings-execution-preflight",
        ),
        _action(
            "return_to_go_no_go_review",
            FindingSeverity.INFO.value
            if not _is_blocking(go_no_go.overall_status)
            else go_no_go.overall_status,
            (
                "Return to the go/no-go packet when any gate is blocked. "
                "Do not treat this preflight as a first send."
            ),
            command_name=GO_NO_GO_CLI_COMMAND,
            json_route=GO_NO_GO_HTTP_ROUTE,
            html_route=GO_NO_GO_HTML_ROUTE,
        ),
    )


def _action(
    code: str,
    status: str,
    label: str,
    *,
    command_name: str | None = None,
    json_route: str | None = None,
    html_route: str | None = None,
    config_name: str | None = None,
) -> FirstSendNextAction:
    return FirstSendNextAction(
        code=_safe_text(code),
        status=_safe_text(status) or FindingSeverity.INFO.value,
        label=_safe_text(label),
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
        config_name=_safe_optional(config_name),
    )


def _is_blocking(status: str) -> bool:
    return _safe_text(status) == FindingSeverity.BLOCKED.value


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    cleaned = {_safe_text(value) for value in values}
    return tuple(sorted(item for item in cleaned if item))


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    text = sanitize_operator_text(str(value))
    return text or ""


def _safe_optional(value: str | None) -> str | None:
    cleaned = _safe_text(value)
    return cleaned or None


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def supervised_pilot_first_send_preflight_payload(
    packet: SupervisedPilotFirstSendPreflight,
) -> dict[str, Any]:
    return {
        "generated_at": packet.generated_at.isoformat(),
        "packet_kind": packet.packet_kind,
        "purpose": packet.purpose,
        "overall_status": packet.overall_status,
        "read_only": True,
        "no_execution": True,
        "no_go_live": True,
        "no_deployment": True,
        "no_outbound": True,
        "no_provider_calls": True,
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
        "outbound_enabled": packet.outbound_enabled,
        "live_providers_enabled": packet.live_providers_enabled,
        "manual_review_only": True,
        "first_send_allowed": False,
        "first_send_attempted": False,
        "first_send_executed": 0,
        "sends_executed": 0,
        "suggested_max_first_sends": packet.suggested_max_first_sends,
        "suggested_max_leads": packet.suggested_max_leads,
        "suggested_max_drafts": packet.suggested_max_drafts,
        "suggested_max_manually_reviewed_sends": packet.suggested_max_manually_reviewed_sends,
        "suggested_max_daily_activity": packet.suggested_max_daily_activity,
        "supervised_pilot_first_send_preflight_is_not_go_live": True,
        "first_send_preflight_is_not_a_send": True,
        "export_is_not_permission_to_go_live": True,
        "export_is_not_execution": True,
        "supervised_pilot_go_no_go_is_not_go_live": True,
        "supervised_pilot_plan_is_not_go_live": True,
        "supervised_pilot_candidates_is_not_go_live": True,
        "rehearsal_outcome_report_is_not_go_live": True,
        "go_live_rehearsal_checklist_is_not_go_live": True,
        "provider_setup_checklist_is_not_go_live": True,
        "operator_halt_status": packet.operator_halt_status,
        "operator_halt_before": packet.operator_halt_before,
        "operator_halt_after": packet.operator_halt_after,
        "source_go_no_go_overall_status": packet.source_go_no_go_overall_status,
        "source_pilot_plan_overall_status": packet.source_pilot_plan_overall_status,
        "source_candidates_overall_status": packet.source_candidates_overall_status,
        "ready_for_review_count": packet.ready_for_review_count,
        "blocked_candidate_count": packet.blocked_candidate_count,
        "total_candidate_count": packet.total_candidate_count,
        "review_queue_pending_count": packet.review_queue_pending_count,
        "action_readiness_candidate_count": packet.action_readiness_candidate_count,
        "approval_packet_count": packet.approval_packet_count,
        "settings_request_count": packet.settings_request_count,
        "settings_request_pending_count": packet.settings_request_pending_count,
        "prerequisite_counts_by_status": [
            _count_payload(item) for item in packet.prerequisite_counts_by_status
        ],
        "candidate_counts_by_readiness": [
            _count_payload(item) for item in packet.candidate_counts_by_readiness
        ],
        "blocked_reason_counts": [_count_payload(item) for item in packet.blocked_reason_counts],
        "expected_safe_assertion_count": packet.expected_safe_assertion_count,
        "expected_safe_assertions_passed": packet.expected_safe_assertions_passed,
        "expected_safe_assertions_failed": packet.expected_safe_assertions_failed,
        "failed_safe_assertion_keys": list(packet.failed_safe_assertion_keys),
        "preflight_checks": [_check_payload(item) for item in packet.preflight_checks],
        "abort_criteria": [_abort_payload(item) for item in packet.abort_criteria],
        "stop_conditions": list(packet.stop_conditions),
        "owner_decision_prerequisites": list(packet.owner_decision_prerequisites),
        "remaining_owner_approval_types": list(packet.remaining_owner_approval_types),
        "closed_provider_flag_names": list(packet.closed_provider_flag_names),
        "missing_credential_names": list(packet.missing_credential_names),
        "missing_config_names": list(packet.missing_config_names),
        "missing_prerequisite_codes": list(packet.missing_prerequisite_codes),
        "blocker_codes": list(packet.blocker_codes),
        "gate_codes": list(packet.gate_codes),
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "source_go_no_go_command": packet.source_go_no_go_command,
        "source_go_no_go_route": packet.source_go_no_go_route,
        "source_go_no_go_html_route": packet.source_go_no_go_html_route,
        "source_pilot_plan_command": packet.source_pilot_plan_command,
        "source_pilot_plan_route": packet.source_pilot_plan_route,
        "source_pilot_plan_html_route": packet.source_pilot_plan_html_route,
        "source_candidates_command": packet.source_candidates_command,
        "source_candidates_route": packet.source_candidates_route,
        "source_candidates_html_route": packet.source_candidates_html_route,
        "related_commands": list(packet.related_commands),
        "related_routes": list(packet.related_routes),
        "local_git": {
            "available": packet.local_git.available,
            "current_branch": packet.local_git.current_branch,
            "current_sha": packet.local_git.current_sha,
            "working_tree_status": packet.local_git.working_tree_status,
            "git_provider_called": False,
            "github_actions_called": False,
        },
        "next_actions": [_action_payload(action) for action in packet.next_actions],
    }


def _count_payload(item: FirstSendCount) -> dict[str, Any]:
    return {"key": item.key, "count": item.count}


def _check_payload(item: FirstSendPreflightCheck) -> dict[str, Any]:
    return {
        "code": item.code,
        "status": item.status,
        "label": item.label,
        "blocking": item.blocking,
        "command_name": item.command_name,
        "json_route": item.json_route,
        "html_route": item.html_route,
    }


def _abort_payload(item: FirstSendAbortCriterion) -> dict[str, Any]:
    return {
        "code": item.code,
        "label": item.label,
        "instruction": item.instruction,
    }


def _action_payload(action: FirstSendNextAction) -> dict[str, Any]:
    return {
        "code": action.code,
        "status": action.status,
        "label": action.label,
        "command_name": action.command_name,
        "json_route": action.json_route,
        "html_route": action.html_route,
        "config_name": action.config_name,
    }


def format_supervised_pilot_first_send_preflight(
    packet: SupervisedPilotFirstSendPreflight,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(supervised_pilot_first_send_preflight_payload(packet))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(packet, payload)


def _format_markdown(
    packet: SupervisedPilotFirstSendPreflight,
    payload: dict[str, Any],
) -> str:
    lines = [
        "# Supervised pilot first-send preflight",
        "",
        "This export is a sanitized first-send preflight over the "
        "supervised pilot go/no-go packet, supervised pilot plan, "
        "candidate readiness, provider setup, rehearsal outcome, launch "
        "readiness, review and action-readiness queues, owner approval "
        "and settings-request rollups, and operator halt state. It "
        "reuses those services as source material and never executes "
        "commands, applies settings, lifts halt, enables outbound, "
        "deploys, builds, publishes, sends, or spends. It is not "
        "permission to send, not permission to go live, and not an "
        "execution surface.",
        "",
        f"- overall: {payload['overall_status']}",
        f"- packet_kind: {payload['packet_kind']}",
        f"- purpose: {payload['purpose']}",
        f"- read_only: {_bool_text(payload['read_only'])}",
        f"- no_execution: {_bool_text(payload['no_execution'])}",
        f"- no_go_live: {_bool_text(payload['no_go_live'])}",
        f"- no_deployment: {_bool_text(payload['no_deployment'])}",
        f"- no_outbound: {_bool_text(payload['no_outbound'])}",
        f"- no_provider_calls: {_bool_text(payload['no_provider_calls'])}",
        f"- no_spend: {_bool_text(payload['no_spend'])}",
        f"- dry_run_only: {_bool_text(payload['dry_run_only'])}",
        f"- executed: {payload['executed']}",
        f"- first_send_allowed: {_bool_text(payload['first_send_allowed'])}",
        f"- first_send_attempted: {_bool_text(payload['first_send_attempted'])}",
        f"- first_send_executed: {payload['first_send_executed']}",
        f"- sends_executed: {payload['sends_executed']}",
        f"- suggested_max_first_sends: {payload['suggested_max_first_sends']}",
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
            "- supervised_pilot_first_send_preflight_is_not_go_live: "
            f"{_bool_text(payload['supervised_pilot_first_send_preflight_is_not_go_live'])}"
        ),
        (
            "- first_send_preflight_is_not_a_send: "
            f"{_bool_text(payload['first_send_preflight_is_not_a_send'])}"
        ),
        (
            "- export_is_not_permission_to_go_live: "
            f"{_bool_text(payload['export_is_not_permission_to_go_live'])}"
        ),
        f"- export_is_not_execution: {_bool_text(payload['export_is_not_execution'])}",
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
        f"- source_go_no_go_command: {payload['source_go_no_go_command']}",
        f"- source_pilot_plan_command: {payload['source_pilot_plan_command']}",
        f"- source_candidates_command: {payload['source_candidates_command']}",
        f"- source_go_no_go_overall_status: {payload['source_go_no_go_overall_status']}",
        f"- source_pilot_plan_overall_status: {payload['source_pilot_plan_overall_status']}",
        f"- blocker_codes: {_format_codes(packet.blocker_codes)}",
        f"- gate_codes: {_format_codes(packet.gate_codes)}",
        f"- missing_prerequisite_codes: {_format_codes(packet.missing_prerequisite_codes)}",
        (
            "- owner_decision_prerequisites: "
            f"{_format_codes(packet.owner_decision_prerequisites)}"
        ),
        f"- remaining_owner_approval_types: {_format_codes(packet.remaining_owner_approval_types)}",
        f"- missing_credential_names: {_format_codes(packet.missing_credential_names)}",
        f"- missing_config_names: {_format_codes(packet.missing_config_names)}",
        f"- closed_provider_flag_names: {_format_codes(packet.closed_provider_flag_names)}",
        f"- failed_safe_assertion_keys: {_format_codes(packet.failed_safe_assertion_keys)}",
        "",
        "## Live-blocking flags",
        f"- OUTBOUND_ENABLED={_bool_text(packet.outbound_enabled)}",
        f"- operator_halt_status={packet.operator_halt_status}",
        f"- live_providers_enabled={_bool_text(packet.live_providers_enabled)}",
        "- read_only=true",
        "- no_execution=true",
        "- no_go_live=true",
        "- no_outbound=true",
        "- no_provider_calls=true",
        "- no_spend=true",
        "- manual_review_only=true",
        "- execution_allowed=false",
        "- first_send_allowed=false",
        "- first_send_attempted=false",
        "- first_send_executed=0",
        "- sends_executed=0",
        f"- suggested_max_first_sends={packet.suggested_max_first_sends}",
        "- go_live_permitted=false",
        "- deployment_allowed=false",
        "- spend_allowed=false",
        "- settings_applied=false",
        "- halt_changed=false",
        "- owner_approved=false",
        "- supervised_pilot_first_send_preflight_is_not_go_live=true",
        "- first_send_preflight_is_not_a_send=true",
        "- export_is_not_permission_to_go_live=true",
        "- export_is_not_execution=true",
        f"- local_git_available: {_bool_text(packet.local_git.available)}",
        f"- current_branch: {packet.local_git.current_branch}",
        f"- current_sha: {packet.local_git.current_sha}",
        f"- working_tree_status: {packet.local_git.working_tree_status}",
        f"- git_provider_called: {_bool_text(packet.local_git.git_provider_called)}",
        f"- github_actions_called: {_bool_text(packet.local_git.github_actions_called)}",
        "",
        "## First-send scope recommendation",
        f"- suggested_max_first_sends: {packet.suggested_max_first_sends}",
        f"- suggested_max_leads: {packet.suggested_max_leads}",
        f"- suggested_max_drafts: {packet.suggested_max_drafts}",
        (
            "- suggested_max_manually_reviewed_sends: "
            f"{packet.suggested_max_manually_reviewed_sends}"
        ),
        f"- suggested_max_daily_activity: {packet.suggested_max_daily_activity}",
        "",
        "## Candidate and queue counts",
        f"- ready_for_review_count: {packet.ready_for_review_count}",
        f"- blocked_candidate_count: {packet.blocked_candidate_count}",
        f"- total_candidate_count: {packet.total_candidate_count}",
        f"- review_queue_pending_count: {packet.review_queue_pending_count}",
        f"- action_readiness_candidate_count: {packet.action_readiness_candidate_count}",
        f"- approval_packet_count: {packet.approval_packet_count}",
        f"- settings_request_count: {packet.settings_request_count}",
        f"- settings_request_pending_count: {packet.settings_request_pending_count}",
        (
            "- expected_safe_assertions: "
            f"passed={packet.expected_safe_assertions_passed} "
            f"failed={packet.expected_safe_assertions_failed} "
            f"count={packet.expected_safe_assertion_count}"
        ),
    ]
    lines.extend(["", "## Prerequisite category summary"])
    _append_counts(lines, packet.prerequisite_counts_by_status)
    lines.extend(["", "## Candidate readiness summary"])
    _append_counts(lines, packet.candidate_counts_by_readiness)
    lines.extend(["", "## Blocked-count reasons"])
    _append_counts(lines, packet.blocked_reason_counts)
    lines.extend(["", "## First-send preflight checks"])
    for check in packet.preflight_checks:
        command_name = check.command_name or "-"
        json_route = check.json_route or "-"
        html_route = check.html_route or "-"
        lines.append(
            f"- [{check.status}] {check.code} blocking={_bool_text(check.blocking)} "
            f"command={command_name} json_route={json_route} "
            f"html_route={html_route} label={check.label}"
        )
    lines.extend(["", "## Abort and stop conditions"])
    for criterion in packet.abort_criteria:
        lines.append(
            f"- {criterion.code}: {criterion.label} instruction={criterion.instruction}"
        )
    if packet.stop_conditions:
        lines.append(f"- stop_conditions: {_format_codes(packet.stop_conditions)}")
    lines.extend(["", "## Owner next actions"])
    for action in packet.next_actions:
        command_name = action.command_name or "-"
        json_route = action.json_route or "-"
        html_route = action.html_route or "-"
        config_name = action.config_name or "-"
        lines.append(
            f"- [{action.status}] {action.code} command={command_name} "
            f"json_route={json_route} html_route={html_route} "
            f"config_name={config_name} label={action.label}"
        )
    if not packet.next_actions:
        lines.append("- next_actions: none")
    return "\n".join(lines)


def _append_counts(lines: list[str], items: Sequence[FirstSendCount]) -> None:
    if not items:
        lines.append("- counts: none")
        return
    for item in items:
        lines.append(f"- {item.key}: {item.count}")


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"
