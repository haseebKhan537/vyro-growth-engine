"""Owner-approval-required supervised 200-practice validation run gate.

Phase 77 evaluates whether a future bounded contact-enrichment validation run
is allowed. It reuses the Phase 76 live-provider setup checklist, Phase 73
supervised validation packet, Phase 71 contact-validation plan/report,
launch readiness, settings preflight, and compliance binder. It never
recalculates those sources of truth. Default behavior is refusal. It never
executes validation, grants approval, writes state, calls providers, sends
email, enrolls campaigns, places calls, autodials, uses AI voice, books
meetings, creates Meet links, launches ads, spends, publishes, deploys,
applies settings, lifts halt, or enables outbound. This gate is not
permission to run a supervised validation and not an execution surface.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import NextActionCode
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
from vyro_growth.services.contact_validation import (
    BLOCKED_STATUS,
    INFO_STATUS,
    MAX_COHORT_SIZE,
    OVERALL_STATUSES,
    PLAN_CLI_COMMAND,
    PLAN_HTTP_ROUTE,
    REPORT_CLI_COMMAND,
    REPORT_HTTP_ROUTE,
    WARNING_STATUS,
    ContactValidationFilters,
)
from vyro_growth.services.contact_validation import HTML_ROUTE as CONTACT_VALIDATION_HTML_ROUTE
from vyro_growth.services.live_provider_setup_checklist import (
    CLI_COMMAND as LIVE_PROVIDER_CLI_COMMAND,
)
from vyro_growth.services.live_provider_setup_checklist import (
    HTTP_ROUTE as LIVE_PROVIDER_HTTP_ROUTE,
)
from vyro_growth.services.live_provider_setup_checklist import (
    CompliancePrerequisite,
    LiveProviderSetupChecklist,
    LiveProviderSetupChecklistService,
    NamedPresence,
    ValidationRunConstraint,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.supervised_validation_run_packet import (
    CLI_COMMAND as VALIDATION_PACKET_CLI_COMMAND,
)
from vyro_growth.services.supervised_validation_run_packet import (
    HTML_ROUTE as VALIDATION_PACKET_HTML_ROUTE,
)
from vyro_growth.services.supervised_validation_run_packet import (
    HTTP_ROUTE as VALIDATION_PACKET_HTTP_ROUTE,
)
from vyro_growth.services.supervised_validation_run_packet import (
    OwnerDecisionItem,
    SupervisedValidationRunPacket,
    SupervisedValidationRunPacketService,
)

logger = structlog.get_logger(__name__)

PACKET_KIND = "supervised_validation_run_gate"
PACKET_PURPOSE = "manual_owner_supervised_validation_run_gate_refusal_only"
CLI_COMMAND = "supervised-validation-run"
HTTP_ROUTE = "/internal/supervised-validation-run"
GATE_NOT_EXECUTION_CODE = NextActionCode.SUPERVISED_VALIDATION_RUN_GATE_IS_NOT_EXECUTION.value
DRY_RUN_MODE = "dry_run"
EXECUTE_REQUESTED_MODE = "execute_requested"
UNSAFE_APPROVAL_CODE_RE = re.compile(r"[@:]|\b(?:sk|rk)-", re.IGNORECASE)
RELATED_COMMANDS: tuple[str, ...] = (
    CLI_COMMAND,
    VALIDATION_PACKET_CLI_COMMAND,
    LIVE_PROVIDER_CLI_COMMAND,
    PLAN_CLI_COMMAND,
    REPORT_CLI_COMMAND,
    "launch-readiness",
    "settings-execution-preflight",
    "compliance-evidence-binder",
    "final-safety-audit",
)
RELATED_ROUTES: tuple[str, ...] = (
    HTTP_ROUTE,
    VALIDATION_PACKET_HTTP_ROUTE,
    VALIDATION_PACKET_HTML_ROUTE,
    LIVE_PROVIDER_HTTP_ROUTE,
    PLAN_HTTP_ROUTE,
    REPORT_HTTP_ROUTE,
    CONTACT_VALIDATION_HTML_ROUTE,
    "/internal/launch-readiness",
    "/internal/settings-execution-preflight",
    "/internal/compliance-evidence-binder",
    "/internal/final-safety-audit",
)


@dataclass(frozen=True)
class SupervisedValidationRunGateOptions:
    dry_run: bool = True
    execute_requested: bool = False
    owner_approval_code_present: bool = False
    confirm_operator_halt_unchanged: bool = False


@dataclass(frozen=True)
class RunGate:
    code: str
    status: str
    label: str
    blocking: bool
    passed: bool
    command_name: str | None
    json_route: str | None
    html_route: str | None


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
class SupervisedValidationRunGate:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    requested_mode: str
    dry_run: bool
    execute_requested: bool
    run_requested: bool
    run_executed: bool
    run_refused: bool
    gate_passed: bool
    read_only: bool
    dry_run_only: bool
    no_execution: bool
    no_outbound: bool
    no_provider_calls: bool
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
    live_provider_setup_checklist_is_not_go_live: bool
    supervised_validation_run_gate_is_not_execution: bool
    export_is_not_permission_to_run: bool
    supervised_validation_run_permitted: bool
    credential_values_included: bool
    owner_approval_code_present: bool
    owner_approval_code_exported: bool
    confirm_operator_halt_unchanged: bool
    source_live_provider_command: str
    source_live_provider_route: str
    source_live_provider_overall_status: str
    source_validation_packet_command: str
    source_validation_packet_route: str
    source_validation_packet_overall_status: str
    source_plan_command: str
    source_plan_route: str
    source_report_command: str
    source_report_route: str
    source_html_route: str
    source_launch_readiness_command: str
    source_launch_readiness_route: str
    source_launch_readiness_overall_status: str
    source_preflight_command: str
    source_preflight_route: str
    source_preflight_overall_status: str
    source_binder_command: str
    source_binder_route: str
    source_binder_overall_status: str
    segment_state: str | None
    segment_city: str | None
    segment_specialty: str | None
    segment_taxonomy_description: str | None
    max_cohort_size: int
    planned_cohort_size: int
    organizations_matching_filters: int
    gates: tuple[RunGate, ...]
    refusal_reason_codes: tuple[str, ...]
    blocking_gate_count: int
    passed_gate_count: int
    required_owner_decisions: tuple[OwnerDecisionItem, ...]
    required_credentials: tuple[NamedPresence, ...]
    missing_credential_names: tuple[str, ...]
    compliance_prerequisites: tuple[CompliancePrerequisite, ...]
    validation_run_constraints: tuple[ValidationRunConstraint, ...]
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    cli_command: str
    http_route: str
    next_actions: tuple[OwnerNextStep, ...]


class SupervisedValidationRunGateService:
    """Evaluate a future supervised validation run. Never executes it."""

    def __init__(
        self,
        *,
        live_provider: LiveProviderSetupChecklistService | None = None,
        validation_packet: SupervisedValidationRunPacketService | None = None,
    ) -> None:
        packet = validation_packet or SupervisedValidationRunPacketService()
        self.validation_packet = packet
        self.live_provider = live_provider or LiveProviderSetupChecklistService(
            validation_packet=packet
        )

    def evaluate(
        self,
        db: Session,
        settings: Settings,
        filters: ContactValidationFilters | None = None,
        options: SupervisedValidationRunGateOptions | None = None,
    ) -> SupervisedValidationRunGate:
        request = options or SupervisedValidationRunGateOptions()
        halt_before = read_operator_halt(db)
        checklist = self.live_provider.build(db, settings)
        packet = self.validation_packet.build(db, settings, filters)
        halt_after = read_operator_halt(db)
        _assert_halt_unchanged(halt_before, halt_after)
        dry_run = True if request.execute_requested is not True else False
        if request.dry_run:
            dry_run = True
        execute_requested = bool(request.execute_requested) and not dry_run
        gates = _gates(
            packet=packet,
            checklist=checklist,
            settings=settings,
            dry_run=dry_run,
            execute_requested=execute_requested,
            owner_approval_code_present=request.owner_approval_code_present,
            confirm_operator_halt_unchanged=request.confirm_operator_halt_unchanged,
            halt_before=halt_before,
            halt_after=halt_after,
        )
        refusal_codes = tuple(item.code for item in gates if item.blocking and not item.passed)
        next_actions = _next_actions(
            packet=packet,
            checklist=checklist,
            dry_run=dry_run,
            execute_requested=execute_requested,
        )
        result = SupervisedValidationRunGate(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=BLOCKED_STATUS,
            requested_mode=DRY_RUN_MODE if dry_run else EXECUTE_REQUESTED_MODE,
            dry_run=dry_run,
            execute_requested=execute_requested,
            run_requested=execute_requested,
            run_executed=False,
            run_refused=True,
            gate_passed=False,
            read_only=True,
            dry_run_only=True,
            no_execution=True,
            no_outbound=True,
            no_provider_calls=True,
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
            live_providers_enabled=packet.live_providers_enabled,
            live_providers=dict(packet.live_providers),
            contact_validation_is_not_outbound=True,
            contact_validation_is_not_live_send=True,
            supervised_validation_run_packet_is_not_execution=True,
            live_provider_setup_checklist_is_not_go_live=True,
            supervised_validation_run_gate_is_not_execution=True,
            export_is_not_permission_to_run=True,
            supervised_validation_run_permitted=False,
            credential_values_included=False,
            owner_approval_code_present=request.owner_approval_code_present,
            owner_approval_code_exported=False,
            confirm_operator_halt_unchanged=request.confirm_operator_halt_unchanged,
            source_live_provider_command=LIVE_PROVIDER_CLI_COMMAND,
            source_live_provider_route=LIVE_PROVIDER_HTTP_ROUTE,
            source_live_provider_overall_status=checklist.overall_status,
            source_validation_packet_command=VALIDATION_PACKET_CLI_COMMAND,
            source_validation_packet_route=VALIDATION_PACKET_HTTP_ROUTE,
            source_validation_packet_overall_status=packet.overall_status,
            source_plan_command=PLAN_CLI_COMMAND,
            source_plan_route=PLAN_HTTP_ROUTE,
            source_report_command=REPORT_CLI_COMMAND,
            source_report_route=REPORT_HTTP_ROUTE,
            source_html_route=CONTACT_VALIDATION_HTML_ROUTE,
            source_launch_readiness_command=checklist.source_launch_readiness_command,
            source_launch_readiness_route=checklist.source_launch_readiness_route,
            source_launch_readiness_overall_status=(
                checklist.source_launch_readiness_overall_status
            ),
            source_preflight_command=checklist.source_preflight_command,
            source_preflight_route=checklist.source_preflight_route,
            source_preflight_overall_status=checklist.source_preflight_overall_status,
            source_binder_command=checklist.source_binder_command,
            source_binder_route=checklist.source_binder_route,
            source_binder_overall_status=checklist.source_binder_overall_status,
            segment_state=packet.segment_state,
            segment_city=packet.segment_city,
            segment_specialty=packet.segment_specialty,
            segment_taxonomy_description=packet.segment_taxonomy_description,
            max_cohort_size=packet.max_cohort_size,
            planned_cohort_size=packet.planned_cohort_size,
            organizations_matching_filters=packet.organizations_matching_filters,
            gates=gates,
            refusal_reason_codes=refusal_codes,
            blocking_gate_count=sum(1 for item in gates if item.blocking and not item.passed),
            passed_gate_count=sum(1 for item in gates if item.passed),
            required_owner_decisions=packet.required_owner_decisions,
            required_credentials=tuple(
                NamedPresence(name=item.name, present=item.present)
                for item in packet.required_credentials
            ),
            missing_credential_names=packet.missing_credential_names,
            compliance_prerequisites=checklist.compliance_prerequisites,
            validation_run_constraints=checklist.validation_run_constraints,
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            local_git=packet.local_git,
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
            next_actions=next_actions,
        )
        _checked_status(result.overall_status)
        logger.info(
            "supervised_validation_run_gate_evaluated",
            read_only=True,
            no_execution=True,
            no_provider_calls=True,
            dry_run=True,
            execute_requested=execute_requested,
            run_executed=False,
            run_refused=True,
            gate_passed=False,
            overall_status=result.overall_status,
            operator_halt_status=result.operator_halt_status,
            outbound_enabled=result.outbound_enabled,
            owner_approved=False,
            validation_permitted=False,
            supervised_validation_run_permitted=False,
            halt_changed=False,
            supervised_validation_run_gate_is_not_execution=True,
        )
        return result


def owner_approval_code_present(raw: str | None) -> bool:
    """Return whether a non-empty safe approval code was supplied. Never returns the value."""
    if raw is None:
        return False
    text = str(raw).strip()
    if not text or len(text) > 128:
        return False
    if UNSAFE_APPROVAL_CODE_RE.search(text):
        return False
    return True


def supervised_validation_run_gate_payload(
    packet: SupervisedValidationRunGate,
) -> dict[str, Any]:
    return {
        "generated_at": packet.generated_at.isoformat(),
        "packet_kind": packet.packet_kind,
        "purpose": packet.purpose,
        "overall_status": packet.overall_status,
        "requested_mode": packet.requested_mode,
        "dry_run": True,
        "execute_requested": packet.execute_requested,
        "run_requested": packet.run_requested,
        "run_executed": False,
        "run_refused": True,
        "gate_passed": False,
        "read_only": True,
        "dry_run_only": True,
        "no_execution": True,
        "no_outbound": True,
        "no_provider_calls": True,
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
        "outbound_enabled": packet.outbound_enabled,
        "operator_halt_status": packet.operator_halt_status,
        "operator_halt_before": packet.operator_halt_before,
        "operator_halt_after": packet.operator_halt_after,
        "operator_halt_unchanged": packet.operator_halt_unchanged,
        "live_providers_enabled": packet.live_providers_enabled,
        "live_providers": dict(packet.live_providers),
        "contact_validation_is_not_outbound": True,
        "contact_validation_is_not_live_send": True,
        "supervised_validation_run_packet_is_not_execution": True,
        "live_provider_setup_checklist_is_not_go_live": True,
        "supervised_validation_run_gate_is_not_execution": True,
        "export_is_not_permission_to_run": True,
        "supervised_validation_run_permitted": False,
        "credential_values_included": False,
        "owner_approval_code_present": packet.owner_approval_code_present,
        "owner_approval_code_exported": False,
        "confirm_operator_halt_unchanged": packet.confirm_operator_halt_unchanged,
        "source_live_provider_command": packet.source_live_provider_command,
        "source_live_provider_route": packet.source_live_provider_route,
        "source_live_provider_overall_status": packet.source_live_provider_overall_status,
        "source_validation_packet_command": packet.source_validation_packet_command,
        "source_validation_packet_route": packet.source_validation_packet_route,
        "source_validation_packet_overall_status": packet.source_validation_packet_overall_status,
        "source_plan_command": packet.source_plan_command,
        "source_plan_route": packet.source_plan_route,
        "source_report_command": packet.source_report_command,
        "source_report_route": packet.source_report_route,
        "source_html_route": packet.source_html_route,
        "source_launch_readiness_command": packet.source_launch_readiness_command,
        "source_launch_readiness_route": packet.source_launch_readiness_route,
        "source_launch_readiness_overall_status": (packet.source_launch_readiness_overall_status),
        "source_preflight_command": packet.source_preflight_command,
        "source_preflight_route": packet.source_preflight_route,
        "source_preflight_overall_status": packet.source_preflight_overall_status,
        "source_binder_command": packet.source_binder_command,
        "source_binder_route": packet.source_binder_route,
        "source_binder_overall_status": packet.source_binder_overall_status,
        "segment": {
            "state": packet.segment_state,
            "city": packet.segment_city,
            "specialty": packet.segment_specialty,
            "taxonomy_description": packet.segment_taxonomy_description,
            "max_cohort_size": packet.max_cohort_size,
            "planned_cohort_size": packet.planned_cohort_size,
            "organizations_matching_filters": packet.organizations_matching_filters,
        },
        "gates": [_gate_payload(item) for item in packet.gates],
        "refusal_reason_codes": list(packet.refusal_reason_codes),
        "blocking_gate_count": packet.blocking_gate_count,
        "passed_gate_count": packet.passed_gate_count,
        "required_owner_decisions": [
            {"code": item.code, "name": item.name, "granted": False}
            for item in packet.required_owner_decisions
        ],
        "required_credentials": [
            {"name": item.name, "present": item.present} for item in packet.required_credentials
        ],
        "missing_credential_names": list(packet.missing_credential_names),
        "compliance_prerequisites": [
            {
                "code": item.code,
                "status": item.status,
                "label": item.label,
                "blocking": item.blocking,
                "documented": item.documented,
            }
            for item in packet.compliance_prerequisites
        ],
        "validation_run_constraints": [
            {
                "code": item.code,
                "label": item.label,
                "limit": item.limit,
                "required": item.required,
            }
            for item in packet.validation_run_constraints
        ],
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
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "next_actions": [_action_payload(item) for item in packet.next_actions],
    }


def format_supervised_validation_run_gate(
    packet: SupervisedValidationRunGate,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(supervised_validation_run_gate_payload(packet))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(payload)


def _gates(
    *,
    packet: SupervisedValidationRunPacket,
    checklist: LiveProviderSetupChecklist,
    settings: Settings,
    dry_run: bool,
    execute_requested: bool,
    owner_approval_code_present: bool,
    confirm_operator_halt_unchanged: bool,
    halt_before: HaltStatus,
    halt_after: HaltStatus,
) -> tuple[RunGate, ...]:
    specialty_present = bool(packet.segment_specialty or packet.segment_taxonomy_description)
    state_present = bool(packet.segment_state)
    cohort_ok = 1 <= packet.max_cohort_size <= MAX_COHORT_SIZE
    credentials_ready = not packet.missing_credential_names
    outbound_ok = not settings.outbound_enabled
    live_closed = not packet.live_providers_enabled
    halt_unchanged = halt_before is halt_after
    halt_honored = halt_after is HaltStatus.HALTED
    compliance_blocking = any(item.blocking for item in checklist.compliance_prerequisites)
    suppression_ok = any(
        item.code == "suppression_controls" and item.documented
        for item in checklist.compliance_prerequisites
    )
    opt_out_ok = any(
        item.code == "opt_out_unsubscribe" and item.documented
        for item in checklist.compliance_prerequisites
    )
    gates = (
        _gate(
            "this_phase_does_not_execute",
            BLOCKED_STATUS,
            (
                "This phase is a refusal/preflight gate only. It does not execute a "
                "supervised 200-practice validation run."
            ),
            blocking=True,
            passed=False,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
        _gate(
            "dry_run_refusal_only",
            INFO_STATUS if dry_run else BLOCKED_STATUS,
            (
                "Default CLI/HTTP behavior is dry-run/refusal. Live execution requires a "
                "later owner-approved phase and is refused here."
            ),
            blocking=not dry_run,
            passed=dry_run,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
        _gate(
            "explicit_owner_approval",
            INFO_STATUS if owner_approval_code_present else BLOCKED_STATUS,
            (
                "An explicit owner approval record/code is required before a later run. "
                "This gate never sets owner_approved or supervised_validation_run_permitted."
            ),
            blocking=not owner_approval_code_present,
            passed=owner_approval_code_present,
            command_name=VALIDATION_PACKET_CLI_COMMAND,
            json_route=VALIDATION_PACKET_HTTP_ROUTE,
            html_route=VALIDATION_PACKET_HTML_ROUTE,
        ),
        _gate(
            "max_cohort_size",
            INFO_STATUS if cohort_ok else BLOCKED_STATUS,
            (
                "The planned cohort must stay at or below 200 practices. "
                "This gate does not select or export prospects."
            ),
            blocking=not cohort_ok,
            passed=cohort_ok,
            command_name=PLAN_CLI_COMMAND,
            json_route=PLAN_HTTP_ROUTE,
        ),
        _gate(
            "one_target_state",
            INFO_STATUS if state_present else BLOCKED_STATUS,
            (
                "A later supervised validation must use one target state. "
                "This gate does not select or export prospects."
            ),
            blocking=not state_present,
            passed=state_present,
            command_name=PLAN_CLI_COMMAND,
            json_route=PLAN_HTTP_ROUTE,
        ),
        _gate(
            "one_target_specialty",
            INFO_STATUS if specialty_present else BLOCKED_STATUS,
            (
                "A later supervised validation must use one target specialty or taxonomy. "
                "This gate does not select or export prospects."
            ),
            blocking=not specialty_present,
            passed=specialty_present,
            command_name=PLAN_CLI_COMMAND,
            json_route=PLAN_HTTP_ROUTE,
        ),
        _gate(
            "credential_readiness",
            INFO_STATUS if credentials_ready else WARNING_STATUS,
            (
                "Named enrichment credentials must be present locally later. This gate "
                "lists names and present/missing booleans only and never verifies values."
            ),
            blocking=False,
            passed=credentials_ready,
            command_name=LIVE_PROVIDER_CLI_COMMAND,
            json_route=LIVE_PROVIDER_HTTP_ROUTE,
        ),
        _gate(
            "suppression_opt_out_prerequisites",
            BLOCKED_STATUS if compliance_blocking else INFO_STATUS,
            (
                "Keep suppression and opt-out controls in place. This gate does not send "
                "mail or contact anyone."
            ),
            blocking=compliance_blocking,
            passed=suppression_ok and opt_out_ok and not compliance_blocking,
            command_name="compliance-evidence-binder",
            json_route="/internal/compliance-evidence-binder",
        ),
        _gate(
            "outbound_disabled",
            INFO_STATUS if outbound_ok else BLOCKED_STATUS,
            "Keep OUTBOUND_ENABLED=false. Enrichment validation is not outbound.",
            blocking=not outbound_ok,
            passed=outbound_ok,
            command_name="launch-readiness",
            json_route="/internal/launch-readiness",
        ),
        _gate(
            "operator_halt_safeguard",
            INFO_STATUS if halt_unchanged and halt_honored else WARNING_STATUS,
            (
                "Operator halt is read and left unchanged. This gate never lifts halt. "
                "A later live run still requires an explicit owner halt decision."
            ),
            blocking=not halt_unchanged,
            passed=halt_unchanged,
            command_name="system-status",
            json_route="/internal/monitoring/status",
        ),
        _gate(
            "operator_halt_confirmation",
            INFO_STATUS if confirm_operator_halt_unchanged else WARNING_STATUS,
            (
                "An explicit operator halt-unchanged confirmation is required before a "
                "later run. This gate never changes halt state."
            ),
            blocking=execute_requested and not confirm_operator_halt_unchanged,
            passed=confirm_operator_halt_unchanged,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
        _gate(
            "live_provider_flags_closed",
            INFO_STATUS if live_closed else BLOCKED_STATUS,
            (
                "Live-provider flags remain closed unless a later owner-approved phase "
                "configures them. This gate does not enable providers or call them."
            ),
            blocking=not live_closed,
            passed=live_closed,
            command_name=LIVE_PROVIDER_CLI_COMMAND,
            json_route=LIVE_PROVIDER_HTTP_ROUTE,
        ),
        _gate(
            "execute_requested_refused_in_this_phase",
            INFO_STATUS if not execute_requested else BLOCKED_STATUS,
            (
                "Any execute/live request is refused in this phase. "
                "supervised_validation_run_permitted stays false."
            ),
            blocking=execute_requested,
            passed=not execute_requested,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
        _gate(
            "no_sending_during_enrichment_validation",
            INFO_STATUS,
            (
                "Do not send email, enroll campaigns, place calls, or book meetings "
                "during enrichment validation."
            ),
            blocking=False,
            passed=True,
            command_name=VALIDATION_PACKET_CLI_COMMAND,
            json_route=VALIDATION_PACKET_HTTP_ROUTE,
        ),
    )
    return gates


def _next_actions(
    *,
    packet: SupervisedValidationRunPacket,
    checklist: LiveProviderSetupChecklist,
    dry_run: bool,
    execute_requested: bool,
) -> tuple[OwnerNextStep, ...]:
    actions = [
        _action(
            GATE_NOT_EXECUTION_CODE,
            INFO_STATUS,
            (
                "This supervised validation run gate is a sanitized refusal/preflight "
                "export only. It is not permission to run validation and not an "
                "execution surface."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
        _action(
            "supervised_validation_run_not_permitted",
            BLOCKED_STATUS,
            (
                "supervised_validation_run_permitted=false, validation_permitted=false, "
                "and owner_approved=false. Do not execute a 200-practice validation run "
                "from this gate."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
        _action(
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            INFO_STATUS if not packet.outbound_enabled else BLOCKED_STATUS,
            "Verify OUTBOUND_ENABLED remains false. This gate does not enable outbound.",
            command_name="launch-readiness",
            json_route="/internal/launch-readiness",
            config_name="OUTBOUND_ENABLED",
        ),
        _action(
            NextActionCode.KEEP_OPERATOR_HALT.value,
            INFO_STATUS,
            "Verify operator halt remains unchanged. This gate does not lift halt.",
            command_name="system-status",
            json_route="/internal/monitoring/status",
        ),
        _action(
            NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
            INFO_STATUS,
            (
                "Keep every live-provider flag disabled until a later owner-approved "
                "phase. This gate does not enable providers."
            ),
            command_name=LIVE_PROVIDER_CLI_COMMAND,
            json_route=LIVE_PROVIDER_HTTP_ROUTE,
        ),
        _action(
            "review_supervised_validation_run_packet",
            _bucket_status(packet.overall_status),
            (
                "Review the supervised validation owner run packet. That packet does not "
                "execute the run or grant approval."
            ),
            command_name=VALIDATION_PACKET_CLI_COMMAND,
            json_route=VALIDATION_PACKET_HTTP_ROUTE,
            html_route=VALIDATION_PACKET_HTML_ROUTE,
        ),
        _action(
            NextActionCode.LIVE_PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value,
            _bucket_status(checklist.overall_status),
            (
                "Review the owner live-provider setup checklist. Credential names only; "
                "it is not permission to go live."
            ),
            command_name=LIVE_PROVIDER_CLI_COMMAND,
            json_route=LIVE_PROVIDER_HTTP_ROUTE,
        ),
        _action(
            "later_owner_approval_required_before_supervised_run",
            INFO_STATUS,
            (
                "A later separately approved phase is required before any real 200-practice "
                "validation run. This gate refuses execution."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
    ]
    if execute_requested:
        actions.append(
            _action(
                "execute_requested_refused_in_this_phase",
                BLOCKED_STATUS,
                (
                    "Live/execute mode was requested and refused. This phase has no "
                    "execution path for a supervised validation run."
                ),
                command_name=CLI_COMMAND,
                json_route=HTTP_ROUTE,
            )
        )
    elif dry_run:
        actions.append(
            _action(
                "dry_run_preflight_complete",
                INFO_STATUS,
                "Dry-run/preflight completed. No providers were called and no run executed.",
                command_name=CLI_COMMAND,
                json_route=HTTP_ROUTE,
            )
        )
    return tuple(actions)


def _gate(
    code: str,
    status: str,
    label: str,
    *,
    blocking: bool,
    passed: bool,
    command_name: str | None = None,
    json_route: str | None = None,
    html_route: str | None = None,
) -> RunGate:
    return RunGate(
        code=_safe_text(code),
        status=_bucket_status(status),
        label=_safe_text(label),
        blocking=blocking,
        passed=passed,
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
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


def _gate_payload(item: RunGate) -> dict[str, Any]:
    return {
        "code": item.code,
        "status": item.status,
        "label": item.label,
        "blocking": item.blocking,
        "passed": item.passed,
        "command_name": item.command_name,
        "json_route": item.json_route,
        "html_route": item.html_route,
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


def _format_markdown(payload: dict[str, Any]) -> str:
    gates = payload["gates"]
    reasons = ", ".join(payload["refusal_reason_codes"]) or "-"
    lines = [
        "# Supervised validation run gate",
        "",
        (
            "This gate is a sanitized owner-approval-required refusal/preflight over "
            "existing live-provider setup, supervised-validation packet, "
            "contact-validation, launch-readiness, settings-preflight, and "
            "compliance-binder surfaces. It never executes a supervised validation."
        ),
        "",
        (
            f"status={payload['overall_status']} "
            f"kind={payload['packet_kind']} "
            f"purpose={payload['purpose']}"
        ),
        f"- generated_at: {payload['generated_at']}",
        f"- requested_mode: {payload['requested_mode']}",
        f"- dry_run: {_bool_text(payload['dry_run'])}",
        f"- execute_requested: {_bool_text(payload['execute_requested'])}",
        f"- run_executed: {_bool_text(payload['run_executed'])}",
        f"- run_refused: {_bool_text(payload['run_refused'])}",
        f"- gate_passed: {_bool_text(payload['gate_passed'])}",
        (
            f"- operator_halt_before={payload['operator_halt_before']} "
            f"status={payload['operator_halt_status']} "
            f"after={payload['operator_halt_after']} "
            f"unchanged={_bool_text(payload['operator_halt_unchanged'])}"
        ),
        f"- outbound_enabled: {_bool_text(payload['outbound_enabled'])}",
        f"- live_providers_enabled: {_bool_text(payload['live_providers_enabled'])}",
        f"- owner_approved: {_bool_text(payload['owner_approved'])}",
        (
            "- supervised_validation_run_permitted: "
            f"{_bool_text(payload['supervised_validation_run_permitted'])}"
        ),
        (f"- owner_approval_code_present: {_bool_text(payload['owner_approval_code_present'])}"),
        f"- cli_command: {payload['cli_command']}",
        f"- http_route: {payload['http_route']}",
        f"- source_live_provider_command: {payload['source_live_provider_command']}",
        (f"- source_validation_packet_command: {payload['source_validation_packet_command']}"),
        (
            "- segment: "
            f"state={payload['segment']['state'] or '-'} "
            f"specialty={payload['segment']['specialty'] or '-'} "
            f"max_cohort_size={payload['segment']['max_cohort_size']}"
        ),
        (
            f"- blocking_gate_count: {payload['blocking_gate_count']} "
            f"passed_gate_count={payload['passed_gate_count']}"
        ),
        f"- refusal_reason_codes: {reasons}",
        "",
        "Gates:",
    ]
    if isinstance(gates, Sequence):
        for item in gates:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('code')} status={item.get('status')} "
                f"blocking={_bool_text(item.get('blocking'))} "
                f"passed={_bool_text(item.get('passed'))}"
            )
    lines.extend(
        [
            "",
            (
                "This gate keeps execution_allowed=false, owner_approved=false, "
                "validation_permitted=false, and supervised_validation_run_permitted=false. "
                "OUTBOUND_ENABLED remains false. A later owner-approved phase is required "
                "before any real 200-practice validation run."
            ),
        ]
    )
    return "\n".join(lines)


def _checked_status(status: str) -> str:
    cleaned = _safe_text(status)
    if cleaned not in OVERALL_STATUSES:
        return BLOCKED_STATUS
    return cleaned


def _bucket_status(status: str) -> str:
    match _safe_text(status):
        case "ready_for_owner_review" | "info" | "execution_gates_closed":
            return INFO_STATUS
        case "blocked" | "dry_run_blocked":
            return BLOCKED_STATUS
        case "warning" | "pending_decision" | "missing_explicit_owner_approval":
            return WARNING_STATUS
        case _:
            return INFO_STATUS


def _assert_halt_unchanged(before: HaltStatus, after: HaltStatus) -> None:
    if after is not before:
        raise RuntimeError("supervised validation run gate must not change operator halt")


def _safe_optional(value: str | None) -> str | None:
    cleaned = _safe_text(value) if value is not None else ""
    return cleaned or None


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    text = sanitize_operator_text(str(value))
    return text or ""


def _bool_text(value: object) -> str:
    return "true" if value is True else "false"
