"""Read-only supervised pilot first-send owner authorization packet export.

Phase 65 assembles sanitized owner-review evidence for a future supervised
pilot first-send. It reuses the Phase 63 launch rehearsal control map and
the Phase 61 first-send preflight as source material and never
recalculates readiness. It never executes, applies settings, lifts halt,
enables outbound, calls providers, scrapes, builds, publishes, deploys,
spends, records approvals, or changes live state. This packet is not
approval, not permission to send, not permission to go live, and not an
execution surface.
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
from vyro_growth.services.supervised_pilot_first_send_preflight import (
    CLI_COMMAND as FIRST_SEND_CLI_COMMAND,
)
from vyro_growth.services.supervised_pilot_first_send_preflight import (
    HTML_ROUTE as FIRST_SEND_HTML_ROUTE,
)
from vyro_growth.services.supervised_pilot_first_send_preflight import (
    HTTP_ROUTE as FIRST_SEND_HTTP_ROUTE,
)
from vyro_growth.services.supervised_pilot_go_no_go import (
    CLI_COMMAND as GO_NO_GO_CLI_COMMAND,
)
from vyro_growth.services.supervised_pilot_go_no_go import (
    HTML_ROUTE as GO_NO_GO_HTML_ROUTE,
)
from vyro_growth.services.supervised_pilot_go_no_go import (
    HTTP_ROUTE as GO_NO_GO_HTTP_ROUTE,
)
from vyro_growth.services.supervised_pilot_launch_rehearsal_control_map import (
    CLI_COMMAND as CONTROL_MAP_CLI_COMMAND,
)
from vyro_growth.services.supervised_pilot_launch_rehearsal_control_map import (
    HTML_ROUTE as CONTROL_MAP_HTML_ROUTE,
)
from vyro_growth.services.supervised_pilot_launch_rehearsal_control_map import (
    HTTP_ROUTE as CONTROL_MAP_HTTP_ROUTE,
)
from vyro_growth.services.supervised_pilot_launch_rehearsal_control_map import (
    ControlCount,
    SupervisedPilotLaunchRehearsalControlMap,
    SupervisedPilotLaunchRehearsalControlMapService,
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

logger = structlog.get_logger(__name__)

PACKET_KIND = "supervised_pilot_first_send_owner_authorization_packet"
PACKET_PURPOSE = "manual_owner_supervised_pilot_first_send_authorization_review_only"
PACKET_NOT_GO_LIVE_CODE = (
    NextActionCode.SUPERVISED_PILOT_FIRST_SEND_OWNER_AUTHORIZATION_PACKET_IS_NOT_GO_LIVE.value
)
PACKET_IS_NOT_APPROVAL_CODE = "this_packet_is_not_approval"
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
CLI_COMMAND = "supervised-pilot-first-send-owner-authorization-packet"
HTTP_ROUTE = "/internal/supervised-pilot-first-send-owner-authorization-packet"
RELATED_COMMANDS: tuple[str, ...] = (
    "launch-readiness",
    "go-live-readiness-index",
    "launch-blockers-plan",
    "staged-rollout-plan",
    "owner-launch-dossier",
    "provider-setup-checklist",
    "go-live-rehearsal-checklist",
    "rehearsal-outcome-report",
    PILOT_CLI_COMMAND,
    "supervised-pilot-candidates",
    GO_NO_GO_CLI_COMMAND,
    FIRST_SEND_CLI_COMMAND,
    CONTROL_MAP_CLI_COMMAND,
    "action-readiness",
    "settings-execution-preflight",
    "compliance-evidence-binder",
    "release-candidate-runbook",
    "release-artifact-manifest",
    "dashboard-summary",
    "check-config",
    "smoke-dry-run",
    CLI_COMMAND,
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
    "/internal/provider-setup-checklist",
    "/internal/operator-go-live-rehearsal-checklist",
    "/internal/go-live-rehearsal-checklist",
    "/internal/operator-rehearsal-outcome-report",
    "/internal/rehearsal-outcome-report",
    PILOT_HTML_ROUTE,
    PILOT_HTTP_ROUTE,
    "/internal/operator-supervised-pilot-candidates",
    "/internal/supervised-pilot-candidates",
    GO_NO_GO_HTML_ROUTE,
    GO_NO_GO_HTTP_ROUTE,
    FIRST_SEND_HTML_ROUTE,
    FIRST_SEND_HTTP_ROUTE,
    CONTROL_MAP_HTML_ROUTE,
    CONTROL_MAP_HTTP_ROUTE,
    "/internal/operator-action-readiness",
    "/internal/action-readiness",
    "/internal/operator-review-queue",
    "/internal/review-queue",
    "/internal/operator-approval-packets",
    "/internal/operator-settings-change-requests",
    "/internal/operator-settings-execution-preflight",
    "/internal/settings-execution-preflight",
    "/internal/operator-compliance-evidence-binder",
    "/internal/compliance-evidence-binder",
    "/internal/operator-release-candidate-runbook",
    "/internal/release-candidate-runbook",
    "/internal/operator-release-artifact-manifest",
    "/internal/release-artifact-manifest",
    HTTP_ROUTE,
)


@dataclass(frozen=True)
class AuthorizationCount:
    key: str
    count: int


@dataclass(frozen=True)
class AuthorizationNextAction:
    code: str
    status: str
    label: str
    command_name: str | None
    json_route: str | None
    html_route: str | None
    config_name: str | None


@dataclass(frozen=True)
class SupervisedPilotFirstSendOwnerAuthorizationPacket:
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
    no_first_send: bool
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
    this_packet_is_not_approval: bool
    authorization_granted: bool
    approval_records_created: bool
    approval_records_mutated: bool
    approval_decision_recorded: bool
    supervised_pilot_first_send_owner_authorization_packet_is_not_go_live: bool
    owner_authorization_packet_is_not_a_send: bool
    export_is_not_permission_to_send: bool
    export_is_not_permission_to_go_live: bool
    export_is_not_execution: bool
    first_send_preflight_is_not_a_send: bool
    supervised_pilot_first_send_preflight_is_not_go_live: bool
    supervised_pilot_launch_rehearsal_control_map_is_not_go_live: bool
    supervised_pilot_go_no_go_is_not_go_live: bool
    supervised_pilot_plan_is_not_go_live: bool
    supervised_pilot_candidates_is_not_go_live: bool
    rehearsal_outcome_report_is_not_go_live: bool
    go_live_rehearsal_checklist_is_not_go_live: bool
    provider_setup_checklist_is_not_go_live: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    source_control_map_overall_status: str
    source_first_send_overall_status: str
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
    blocking_control_count: int
    warning_control_count: int
    info_control_count: int
    control_counts_by_category: tuple[AuthorizationCount, ...]
    control_counts_by_status: tuple[AuthorizationCount, ...]
    blocking_control_codes: tuple[str, ...]
    expected_safe_assertion_count: int
    expected_safe_assertions_passed: int
    expected_safe_assertions_failed: int
    failed_safe_assertion_keys: tuple[str, ...]
    owner_decision_prerequisites: tuple[str, ...]
    remaining_owner_approval_types: tuple[str, ...]
    remaining_owner_approval_codes: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    missing_config_names: tuple[str, ...]
    missing_prerequisite_codes: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    gate_codes: tuple[str, ...]
    cli_command: str
    http_route: str
    source_control_map_command: str
    source_control_map_route: str
    source_control_map_html_route: str
    source_first_send_command: str
    source_first_send_route: str
    source_first_send_html_route: str
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
    next_actions: tuple[AuthorizationNextAction, ...]


class SupervisedPilotFirstSendOwnerAuthorizationPacketService:
    """Compose a sanitized owner-authorization packet from existing surfaces."""

    def __init__(
        self,
        *,
        control_map: SupervisedPilotLaunchRehearsalControlMapService | None = None,
    ) -> None:
        self.control_map = control_map or SupervisedPilotLaunchRehearsalControlMapService()

    def build(
        self, db: Session, settings: Settings
    ) -> SupervisedPilotFirstSendOwnerAuthorizationPacket:
        halt_before = read_operator_halt(db)
        control_map = self.control_map.build(db, settings)
        halt_after = read_operator_halt(db)
        if halt_after != halt_before:
            raise RuntimeError(
                "supervised pilot first-send owner authorization packet "
                "must not change operator halt status"
            )
        packet = _from_source(
            control_map,
            halt_before=halt_before,
            halt_after=halt_after,
        )
        logger.info(
            "supervised_pilot_first_send_owner_authorization_packet_built",
            read_only=True,
            no_execution=True,
            no_go_live=True,
            no_outbound=True,
            no_provider_calls=True,
            no_spend=True,
            no_first_send=True,
            overall_status=packet.overall_status,
            operator_halt_status=packet.operator_halt_status,
            outbound_enabled=packet.outbound_enabled,
            go_live_permitted=False,
            execution_allowed=False,
            first_send_allowed=False,
            first_send_executed=0,
            owner_approved=False,
            this_packet_is_not_approval=True,
            authorization_granted=False,
            approval_records_mutated=False,
            halt_changed=False,
            spend_allowed=False,
            executed=0,
            supervised_pilot_first_send_owner_authorization_packet_is_not_go_live=True,
        )
        return packet


def _from_source(
    control_map: SupervisedPilotLaunchRehearsalControlMap,
    *,
    halt_before: HaltStatus,
    halt_after: HaltStatus,
) -> SupervisedPilotFirstSendOwnerAuthorizationPacket:
    remaining_approval_codes = _unique_sorted(
        (
            *control_map.owner_decision_prerequisites,
            *control_map.remaining_owner_approval_types,
        )
    )
    return SupervisedPilotFirstSendOwnerAuthorizationPacket(
        generated_at=datetime.now(tz=UTC),
        packet_kind=PACKET_KIND,
        purpose=PACKET_PURPOSE,
        overall_status=_safe_text(control_map.overall_status) or FindingSeverity.INFO.value,
        read_only=True,
        no_execution=True,
        no_go_live=True,
        no_deployment=True,
        no_outbound=True,
        no_provider_calls=True,
        no_spend=True,
        no_first_send=True,
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
        outbound_enabled=control_map.outbound_enabled,
        live_providers_enabled=control_map.live_providers_enabled,
        manual_review_only=True,
        first_send_allowed=False,
        first_send_attempted=False,
        first_send_executed=0,
        sends_executed=0,
        suggested_max_first_sends=control_map.suggested_max_first_sends,
        this_packet_is_not_approval=True,
        authorization_granted=False,
        approval_records_created=False,
        approval_records_mutated=False,
        approval_decision_recorded=False,
        supervised_pilot_first_send_owner_authorization_packet_is_not_go_live=True,
        owner_authorization_packet_is_not_a_send=True,
        export_is_not_permission_to_send=True,
        export_is_not_permission_to_go_live=True,
        export_is_not_execution=True,
        first_send_preflight_is_not_a_send=True,
        supervised_pilot_first_send_preflight_is_not_go_live=True,
        supervised_pilot_launch_rehearsal_control_map_is_not_go_live=True,
        supervised_pilot_go_no_go_is_not_go_live=True,
        supervised_pilot_plan_is_not_go_live=True,
        supervised_pilot_candidates_is_not_go_live=True,
        rehearsal_outcome_report_is_not_go_live=True,
        go_live_rehearsal_checklist_is_not_go_live=True,
        provider_setup_checklist_is_not_go_live=True,
        operator_halt_status=halt_after.value,
        operator_halt_before=halt_before.value,
        operator_halt_after=halt_after.value,
        source_control_map_overall_status=control_map.overall_status,
        source_first_send_overall_status=control_map.source_first_send_overall_status,
        source_go_no_go_overall_status=control_map.source_go_no_go_overall_status,
        source_pilot_plan_overall_status=control_map.source_pilot_plan_overall_status,
        source_candidates_overall_status=control_map.source_candidates_overall_status,
        ready_for_review_count=control_map.ready_for_review_count,
        blocked_candidate_count=control_map.blocked_candidate_count,
        total_candidate_count=control_map.total_candidate_count,
        review_queue_pending_count=control_map.review_queue_pending_count,
        action_readiness_candidate_count=control_map.action_readiness_candidate_count,
        approval_packet_count=control_map.approval_packet_count,
        settings_request_count=control_map.settings_request_count,
        settings_request_pending_count=control_map.settings_request_pending_count,
        blocking_control_count=control_map.blocking_control_count,
        warning_control_count=control_map.warning_control_count,
        info_control_count=control_map.info_control_count,
        control_counts_by_category=_copy_counts(control_map.control_counts_by_category),
        control_counts_by_status=_copy_counts(control_map.control_counts_by_status),
        blocking_control_codes=tuple(control_map.blocking_control_codes),
        expected_safe_assertion_count=control_map.expected_safe_assertion_count,
        expected_safe_assertions_passed=control_map.expected_safe_assertions_passed,
        expected_safe_assertions_failed=control_map.expected_safe_assertions_failed,
        failed_safe_assertion_keys=tuple(control_map.failed_safe_assertion_keys),
        owner_decision_prerequisites=tuple(control_map.owner_decision_prerequisites),
        remaining_owner_approval_types=tuple(control_map.remaining_owner_approval_types),
        remaining_owner_approval_codes=remaining_approval_codes,
        closed_provider_flag_names=tuple(control_map.closed_provider_flag_names),
        missing_credential_names=tuple(control_map.missing_credential_names),
        missing_config_names=tuple(control_map.missing_config_names),
        missing_prerequisite_codes=tuple(control_map.missing_prerequisite_codes),
        blocker_codes=tuple(control_map.blocker_codes),
        gate_codes=tuple(control_map.gate_codes),
        cli_command=CLI_COMMAND,
        http_route=HTTP_ROUTE,
        source_control_map_command=CONTROL_MAP_CLI_COMMAND,
        source_control_map_route=CONTROL_MAP_HTTP_ROUTE,
        source_control_map_html_route=CONTROL_MAP_HTML_ROUTE,
        source_first_send_command=FIRST_SEND_CLI_COMMAND,
        source_first_send_route=FIRST_SEND_HTTP_ROUTE,
        source_first_send_html_route=FIRST_SEND_HTML_ROUTE,
        source_go_no_go_command=GO_NO_GO_CLI_COMMAND,
        source_go_no_go_route=GO_NO_GO_HTTP_ROUTE,
        source_go_no_go_html_route=GO_NO_GO_HTML_ROUTE,
        source_pilot_plan_command=PILOT_CLI_COMMAND,
        source_pilot_plan_route=PILOT_HTTP_ROUTE,
        source_pilot_plan_html_route=PILOT_HTML_ROUTE,
        source_candidates_command=control_map.source_candidates_command,
        source_candidates_route=control_map.source_candidates_route,
        source_candidates_html_route=control_map.source_candidates_html_route,
        related_commands=RELATED_COMMANDS,
        related_routes=RELATED_ROUTES,
        local_git=control_map.local_git,
        next_actions=_next_actions(control_map),
    )


def _copy_counts(items: Sequence[ControlCount]) -> tuple[AuthorizationCount, ...]:
    return tuple(
        AuthorizationCount(key=_safe_text(item.key), count=int(item.count)) for item in items
    )


def _next_actions(
    control_map: SupervisedPilotLaunchRehearsalControlMap,
) -> tuple[AuthorizationNextAction, ...]:
    return (
        _action(
            PACKET_NOT_GO_LIVE_CODE,
            FindingSeverity.INFO.value,
            (
                "This supervised pilot first-send owner authorization "
                "packet is a sanitized owner-review export. It is not "
                "approval, not permission to send, not permission to go "
                "live, and not an execution surface."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
        _action(
            PACKET_IS_NOT_APPROVAL_CODE,
            FindingSeverity.INFO.value,
            (
                "This packet does not record, mutate, or grant owner "
                "approval. Remaining approval type and code names are "
                "review-only."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
        _action(
            EXECUTION_DISABLED_CODE,
            FindingSeverity.INFO.value,
            (
                "Execution remains disabled. This packet does not run "
                "commands, apply settings, lift halt, enable outbound, "
                "deploy, build, publish, send, or spend."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
        _action(
            NextActionCode.SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_IS_NOT_GO_LIVE.value,
            FindingSeverity.INFO.value,
            (
                "Review the source launch rehearsal control map using "
                "counts, codes, and flag names only."
            ),
            command_name=CONTROL_MAP_CLI_COMMAND,
            json_route=CONTROL_MAP_HTTP_ROUTE,
            html_route=CONTROL_MAP_HTML_ROUTE,
        ),
        _action(
            NextActionCode.SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_IS_NOT_GO_LIVE.value,
            FindingSeverity.INFO.value,
            (
                "Review the source first-send preflight using counts, "
                "codes, and flag names only."
            ),
            command_name=FIRST_SEND_CLI_COMMAND,
            json_route=FIRST_SEND_HTTP_ROUTE,
            html_route=FIRST_SEND_HTML_ROUTE,
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
                "Review candidate readiness counts only. This packet "
                "does not select or contact candidates."
            ),
            command_name=control_map.source_candidates_command,
            json_route=control_map.source_candidates_route,
            html_route=control_map.source_candidates_html_route,
        ),
        _action(
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            FindingSeverity.INFO.value,
            (
                "Leave OUTBOUND_ENABLED=false. This packet does not "
                "enable outbound."
            ),
            command_name="launch-readiness",
            json_route="/internal/launch-readiness",
            config_name="OUTBOUND_ENABLED",
        ),
        _action(
            NextActionCode.KEEP_OPERATOR_HALT.value
            if control_map.operator_halt_status == HaltStatus.HALTED.value
            else NextActionCode.RECORD_OPERATOR_HALT.value,
            FindingSeverity.INFO.value,
            (
                "Keep operator halt unchanged. This packet reads halt "
                "status only and never lifts it."
            ),
            command_name="system-status",
            json_route="/internal/monitoring/status",
        ),
        _action(
            NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
            FindingSeverity.INFO.value,
            (
                "Keep live provider flags closed. This packet lists "
                "closed flag names only."
            ),
            command_name="provider-setup-checklist",
            json_route="/internal/provider-setup-checklist",
            html_route="/internal/operator-provider-setup-checklist",
        ),
        _action(
            NextActionCode.BINDER_IS_NOT_GO_LIVE.value,
            FindingSeverity.INFO.value,
            (
                "Review the compliance evidence binder by name only. "
                "This packet does not execute binder contents."
            ),
            command_name="compliance-evidence-binder",
            json_route="/internal/compliance-evidence-binder",
            html_route="/internal/operator-compliance-evidence-binder",
        ),
        _action(
            NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT.value,
            FindingSeverity.INFO.value,
            (
                "Review the release-candidate runbook by name only. "
                "This packet is not a deployment mechanism."
            ),
            command_name="release-candidate-runbook",
            json_route="/internal/release-candidate-runbook",
            html_route="/internal/operator-release-candidate-runbook",
        ),
        _action(
            NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value,
            FindingSeverity.INFO.value,
            (
                "Review the release artifact manifest by name only. "
                "This packet does not build or deploy."
            ),
            command_name="release-artifact-manifest",
            json_route="/internal/release-artifact-manifest",
            html_route="/internal/operator-release-artifact-manifest",
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
            "return_to_control_map_and_first_send_review",
            FindingSeverity.INFO.value
            if not _is_blocking(control_map.overall_status)
            else control_map.overall_status,
            (
                "Return to the launch rehearsal control map and "
                "first-send preflight when any source rollup is "
                "blocked. Do not treat this packet as approval, a "
                "send, or go-live."
            ),
            command_name=CONTROL_MAP_CLI_COMMAND,
            json_route=CONTROL_MAP_HTTP_ROUTE,
            html_route=CONTROL_MAP_HTML_ROUTE,
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
) -> AuthorizationNextAction:
    return AuthorizationNextAction(
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


def supervised_pilot_first_send_owner_authorization_packet_payload(
    packet: SupervisedPilotFirstSendOwnerAuthorizationPacket,
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
        "no_first_send": True,
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
        "this_packet_is_not_approval": True,
        "authorization_granted": False,
        "approval_records_created": False,
        "approval_records_mutated": False,
        "approval_decision_recorded": False,
        "supervised_pilot_first_send_owner_authorization_packet_is_not_go_live": True,
        "owner_authorization_packet_is_not_a_send": True,
        "export_is_not_permission_to_send": True,
        "export_is_not_permission_to_go_live": True,
        "export_is_not_execution": True,
        "first_send_preflight_is_not_a_send": True,
        "supervised_pilot_first_send_preflight_is_not_go_live": True,
        "supervised_pilot_launch_rehearsal_control_map_is_not_go_live": True,
        "supervised_pilot_go_no_go_is_not_go_live": True,
        "supervised_pilot_plan_is_not_go_live": True,
        "supervised_pilot_candidates_is_not_go_live": True,
        "rehearsal_outcome_report_is_not_go_live": True,
        "go_live_rehearsal_checklist_is_not_go_live": True,
        "provider_setup_checklist_is_not_go_live": True,
        "operator_halt_status": packet.operator_halt_status,
        "operator_halt_before": packet.operator_halt_before,
        "operator_halt_after": packet.operator_halt_after,
        "source_control_map_overall_status": packet.source_control_map_overall_status,
        "source_first_send_overall_status": packet.source_first_send_overall_status,
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
        "blocking_control_count": packet.blocking_control_count,
        "warning_control_count": packet.warning_control_count,
        "info_control_count": packet.info_control_count,
        "control_counts_by_category": [
            _count_payload(item) for item in packet.control_counts_by_category
        ],
        "control_counts_by_status": [
            _count_payload(item) for item in packet.control_counts_by_status
        ],
        "blocking_control_codes": list(packet.blocking_control_codes),
        "expected_safe_assertion_count": packet.expected_safe_assertion_count,
        "expected_safe_assertions_passed": packet.expected_safe_assertions_passed,
        "expected_safe_assertions_failed": packet.expected_safe_assertions_failed,
        "failed_safe_assertion_keys": list(packet.failed_safe_assertion_keys),
        "owner_decision_prerequisites": list(packet.owner_decision_prerequisites),
        "remaining_owner_approval_types": list(packet.remaining_owner_approval_types),
        "remaining_owner_approval_codes": list(packet.remaining_owner_approval_codes),
        "closed_provider_flag_names": list(packet.closed_provider_flag_names),
        "missing_credential_names": list(packet.missing_credential_names),
        "missing_config_names": list(packet.missing_config_names),
        "missing_prerequisite_codes": list(packet.missing_prerequisite_codes),
        "blocker_codes": list(packet.blocker_codes),
        "gate_codes": list(packet.gate_codes),
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "source_control_map_command": packet.source_control_map_command,
        "source_control_map_route": packet.source_control_map_route,
        "source_control_map_html_route": packet.source_control_map_html_route,
        "source_first_send_command": packet.source_first_send_command,
        "source_first_send_route": packet.source_first_send_route,
        "source_first_send_html_route": packet.source_first_send_html_route,
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


def _count_payload(item: AuthorizationCount) -> dict[str, Any]:
    return {"key": item.key, "count": item.count}


def _action_payload(action: AuthorizationNextAction) -> dict[str, Any]:
    return {
        "code": action.code,
        "status": action.status,
        "label": action.label,
        "command_name": action.command_name,
        "json_route": action.json_route,
        "html_route": action.html_route,
        "config_name": action.config_name,
    }


def format_supervised_pilot_first_send_owner_authorization_packet(
    packet: SupervisedPilotFirstSendOwnerAuthorizationPacket,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(
        supervised_pilot_first_send_owner_authorization_packet_payload(packet)
    )
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(packet, payload)


def _format_markdown(
    packet: SupervisedPilotFirstSendOwnerAuthorizationPacket,
    payload: dict[str, Any],
) -> str:
    lines = [
        "# Supervised pilot first-send owner authorization packet",
        "",
        "This export is a sanitized owner-authorization packet over the "
        "Phase 61 first-send preflight, Phase 63 launch rehearsal "
        "control map, supervised pilot go/no-go, plan, and candidates "
        "surfaces, owner approval packet and settings request rollups, "
        "launch blockers, readiness index, rehearsal checklist/outcome, "
        "provider setup checklist, compliance binder, release runbook, "
        "release artifact manifest, operator halt, and "
        "OUTBOUND_ENABLED=false proof. It reuses those services as "
        "source material and never executes commands, applies settings, "
        "lifts halt, enables outbound, deploys, builds, publishes, "
        "sends, spends, or mutates approval records. It is not "
        "approval, not permission to send, not permission to go live, "
        "and not an execution surface.",
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
        f"- no_first_send: {_bool_text(payload['no_first_send'])}",
        f"- dry_run_only: {_bool_text(payload['dry_run_only'])}",
        f"- executed: {payload['executed']}",
        f"- first_send_allowed: {_bool_text(payload['first_send_allowed'])}",
        f"- first_send_attempted: {_bool_text(payload['first_send_attempted'])}",
        f"- first_send_executed: {payload['first_send_executed']}",
        f"- sends_executed: {payload['sends_executed']}",
        f"- owner_approved: {_bool_text(payload['owner_approved'])}",
        f"- this_packet_is_not_approval: {_bool_text(payload['this_packet_is_not_approval'])}",
        f"- authorization_granted: {_bool_text(payload['authorization_granted'])}",
        f"- approval_records_created: {_bool_text(payload['approval_records_created'])}",
        f"- approval_records_mutated: {_bool_text(payload['approval_records_mutated'])}",
        (
            "- approval_decision_recorded: "
            f"{_bool_text(payload['approval_decision_recorded'])}"
        ),
        f"- settings_applied: {_bool_text(payload['settings_applied'])}",
        f"- halt_changed: {_bool_text(payload['halt_changed'])}",
        f"- live_action: {_bool_text(payload['live_action'])}",
        f"- execution_allowed: {_bool_text(payload['execution_allowed'])}",
        f"- go_live_permitted: {_bool_text(payload['go_live_permitted'])}",
        f"- deployment_allowed: {_bool_text(payload['deployment_allowed'])}",
        f"- spend_allowed: {_bool_text(payload['spend_allowed'])}",
        f"- manual_review_only: {_bool_text(payload['manual_review_only'])}",
        (
            "- supervised_pilot_first_send_owner_authorization_packet_is_not_go_live: "
            f"{_bool_text(payload['supervised_pilot_first_send_owner_authorization_packet_is_not_go_live'])}"
        ),
        (
            "- owner_authorization_packet_is_not_a_send: "
            f"{_bool_text(payload['owner_authorization_packet_is_not_a_send'])}"
        ),
        (
            "- export_is_not_permission_to_send: "
            f"{_bool_text(payload['export_is_not_permission_to_send'])}"
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
        f"- source_control_map_command: {payload['source_control_map_command']}",
        f"- source_first_send_command: {payload['source_first_send_command']}",
        f"- source_go_no_go_command: {payload['source_go_no_go_command']}",
        f"- source_pilot_plan_command: {payload['source_pilot_plan_command']}",
        f"- source_candidates_command: {payload['source_candidates_command']}",
        (
            "- source_control_map_overall_status: "
            f"{payload['source_control_map_overall_status']}"
        ),
        (
            "- source_first_send_overall_status: "
            f"{payload['source_first_send_overall_status']}"
        ),
        f"- source_go_no_go_overall_status: {payload['source_go_no_go_overall_status']}",
        (
            "- source_pilot_plan_overall_status: "
            f"{payload['source_pilot_plan_overall_status']}"
        ),
        (
            "- source_candidates_overall_status: "
            f"{payload['source_candidates_overall_status']}"
        ),
        f"- blocker_codes: {_format_codes(packet.blocker_codes)}",
        f"- gate_codes: {_format_codes(packet.gate_codes)}",
        f"- missing_prerequisite_codes: {_format_codes(packet.missing_prerequisite_codes)}",
        (
            "- owner_decision_prerequisites: "
            f"{_format_codes(packet.owner_decision_prerequisites)}"
        ),
        f"- remaining_owner_approval_types: {_format_codes(packet.remaining_owner_approval_types)}",
        f"- remaining_owner_approval_codes: {_format_codes(packet.remaining_owner_approval_codes)}",
        f"- missing_credential_names: {_format_codes(packet.missing_credential_names)}",
        f"- missing_config_names: {_format_codes(packet.missing_config_names)}",
        f"- closed_provider_flag_names: {_format_codes(packet.closed_provider_flag_names)}",
        f"- failed_safe_assertion_keys: {_format_codes(packet.failed_safe_assertion_keys)}",
        f"- blocking_control_codes: {_format_codes(packet.blocking_control_codes)}",
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
        "- no_first_send=true",
        "- no_deployment=true",
        "- manual_review_only=true",
        "- execution_allowed=false",
        "- first_send_allowed=false",
        "- first_send_attempted=false",
        "- first_send_executed=0",
        "- sends_executed=0",
        "- go_live_permitted=false",
        "- deployment_allowed=false",
        "- spend_allowed=false",
        "- settings_applied=false",
        "- halt_changed=false",
        "- owner_approved=false",
        "- this_packet_is_not_approval=true",
        "- authorization_granted=false",
        "- approval_records_created=false",
        "- approval_records_mutated=false",
        "- approval_decision_recorded=false",
        "- supervised_pilot_first_send_owner_authorization_packet_is_not_go_live=true",
        "- owner_authorization_packet_is_not_a_send=true",
        "- export_is_not_permission_to_send=true",
        "- export_is_not_permission_to_go_live=true",
        "- export_is_not_execution=true",
        f"- local_git_available: {_bool_text(packet.local_git.available)}",
        f"- current_branch: {packet.local_git.current_branch}",
        f"- current_sha: {packet.local_git.current_sha}",
        f"- working_tree_status: {packet.local_git.working_tree_status}",
        f"- git_provider_called: {_bool_text(packet.local_git.git_provider_called)}",
        f"- github_actions_called: {_bool_text(packet.local_git.github_actions_called)}",
        "",
        "## Control-map readiness rollups",
        f"- blocking_control_count: {packet.blocking_control_count}",
        f"- warning_control_count: {packet.warning_control_count}",
        f"- info_control_count: {packet.info_control_count}",
        "",
        "## Control counts by category",
    ]
    _append_counts(lines, packet.control_counts_by_category)
    lines.extend(["", "## Control counts by status"])
    _append_counts(lines, packet.control_counts_by_status)
    lines.extend(
        [
            "",
            "## Safe counts",
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
            "",
            "## Owner next actions",
        ]
    )
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


def _append_counts(lines: list[str], items: Sequence[AuthorizationCount]) -> None:
    if not items:
        lines.append("- counts: none")
        return
    for item in items:
        lines.append(f"- {item.key}: {item.count}")


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"
