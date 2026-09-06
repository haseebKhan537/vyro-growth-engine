"""Read-only launch blockers remediation plan export.

Phase 43 turns the existing Phase 42 go-live readiness index blockers into
operator-friendly manual remediation steps. It reuses GoLiveReadinessIndexService
and never recalculates readiness. It never executes, applies settings, lifts
halt, enables outbound, calls providers, builds, publishes, deploys, or
changes live state. This plan is not permission to go live and is not an
execution surface.
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
from vyro_growth.domain import (
    FindingCode,
    FindingSeverity,
    NextActionCode,
    SettingsExecutionBlockerCode,
)
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
from vyro_growth.services.go_live_readiness_index import (
    CLI_COMMAND as INDEX_CLI_COMMAND,
)
from vyro_growth.services.go_live_readiness_index import (
    HTTP_ROUTE as INDEX_HTTP_ROUTE,
)
from vyro_growth.services.go_live_readiness_index import (
    GoLiveReadinessIndex,
    GoLiveReadinessIndexService,
    IndexChecklistItem,
    ReadinessSurfaceCard,
)
from vyro_growth.services.operator_halt import read_operator_halt
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata

logger = structlog.get_logger(__name__)

PACKET_KIND = "launch_blockers_remediation_plan"
PACKET_PURPOSE = "manual_owner_remediation_planning_only"
PLAN_NOT_PERMISSION_CODE = NextActionCode.LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
CLI_COMMAND = "launch-blockers-plan"
HTTP_ROUTE = "/internal/launch-blockers-plan"
HTML_ROUTE = "/internal/operator-launch-blockers-plan"
INDEX_HTML_ROUTE = "/internal/operator-go-live-readiness-index"
SECTION_PLAN = "launch_blockers_plan"
STEP_KINDS: tuple[str, ...] = (
    "configuration",
    "credential",
    "legal_compliance",
    "deployment",
    "provider_setup",
    "manual_review",
)
OWNER_APPROVAL_TYPES: tuple[str, ...] = (
    "none",
    "owner_review",
    "owner_approval_packet",
    "settings_change_request",
    "live_enablement_review",
)
RELATED_COMMANDS: tuple[str, ...] = (
    "go-live-readiness-index",
    "operator-command-center",
    "launch-readiness",
    "settings-execution-preflight",
    "owner-handoff-packet",
    "compliance-evidence-binder",
    "release-candidate-runbook",
    "release-artifact-manifest",
    CLI_COMMAND,
    "staged-rollout-plan",
    "owner-launch-dossier",
    "provider-setup-checklist",
    "system-status",
)
RELATED_ROUTES: tuple[str, ...] = (
    INDEX_HTML_ROUTE,
    INDEX_HTTP_ROUTE,
    "/internal/operator-dashboard",
    "/internal/operator-command-center",
    "/internal/launch-readiness",
    "/internal/operator-settings-execution-preflight",
    "/internal/settings-execution-preflight",
    "/internal/operator-owner-handoff-packet",
    "/internal/owner-handoff-packet",
    "/internal/operator-compliance-evidence-binder",
    "/internal/compliance-evidence-binder",
    "/internal/operator-release-candidate-runbook",
    "/internal/release-candidate-runbook",
    "/internal/operator-release-artifact-manifest",
    "/internal/release-artifact-manifest",
    "/internal/operator-audit-timeline",
    HTML_ROUTE,
    HTTP_ROUTE,
    "/internal/operator-staged-rollout-plan",
    "/internal/staged-rollout-plan",
    "/internal/operator-owner-launch-dossier",
    "/internal/owner-launch-dossier",
    "/internal/provider-setup-checklist",
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
_SURFACE_BY_SECTION = {
    "go_live_readiness_index": "go-live-readiness-index",
    "launch_blockers_plan": "launch-blockers-plan",
    "staged_rollout_plan": "staged-rollout-plan",
    "owner_launch_dossier": "owner-launch-dossier",
    "provider_setup_checklist": "provider-setup-checklist",
    "owner_handoff": "owner-handoff-packet",
    "owner_handoff_packet": "owner-handoff-packet",
    "launch_readiness": "launch-readiness",
    "settings_execution_preflight": "settings-execution-preflight",
    "settings_change_requests": "settings-execution-preflight",
    "compliance_evidence_binder": "compliance-evidence-binder",
    "release_candidate_runbook": "release-candidate-runbook",
    "release_artifact_manifest": "release-artifact-manifest",
    "source_provenance": "release-artifact-manifest",
    "artifact_inventory": "release-artifact-manifest",
    "operator_audit_timeline": "operator-audit-timeline",
    "operator_command_center": "operator-dashboard",
    "dashboard": "operator-dashboard",
}
StepKind = Literal[
    "configuration",
    "credential",
    "legal_compliance",
    "deployment",
    "provider_setup",
    "manual_review",
]
OwnerApprovalType = Literal[
    "none",
    "owner_review",
    "owner_approval_packet",
    "settings_change_request",
    "live_enablement_review",
]


@dataclass(frozen=True)
class RemediationAdvice:
    step_kind: StepKind
    owner_approval_type: OwnerApprovalType
    recommended_step: str
    config_name: str | None = None


@dataclass(frozen=True)
class RemediationStep:
    blocker_code: str
    surface_key: str
    surface_label: str
    current_status: str
    recommended_step: str
    owner_approval_type: str
    step_kind: str
    html_route: str | None
    json_route: str | None
    command_name: str | None
    config_name: str | None


@dataclass(frozen=True)
class RemediationGroup:
    group_key: str
    group_label: str
    group_kind: str
    overall_status: str
    step_count: str
    steps: tuple[RemediationStep, ...]


@dataclass(frozen=True)
class LaunchBlockersPlan:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
    no_execution: bool
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
    manual_review_only: bool
    plan_is_not_permission_to_go_live: bool
    plan_is_not_execution: bool
    index_is_not_permission_to_go_live: bool
    handoff_is_not_go_live: bool
    binder_is_not_go_live: bool
    runbook_is_not_deployment: bool
    manifest_is_not_a_build_or_deploy: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    outbound_enabled: bool
    live_providers_enabled: bool
    closed_provider_flag_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    cli_command: str
    http_route: str
    source_index_command: str
    source_index_route: str
    source_index_overall_status: str
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    groups: tuple[RemediationGroup, ...]
    steps: tuple[RemediationStep, ...]


class LaunchBlockersPlanService:
    """Map existing go-live readiness index blockers into a planning export."""

    def __init__(self, *, index_service: GoLiveReadinessIndexService | None = None) -> None:
        self.index_service = index_service or GoLiveReadinessIndexService()

    def build(self, db: Session, settings: Settings) -> LaunchBlockersPlan:
        halt_before = read_operator_halt(db)
        index = self.index_service.build(db, settings)
        halt_after = read_operator_halt(db)
        if halt_after != halt_before:
            raise RuntimeError("launch blockers plan must not change operator halt status")
        steps = _steps_from_index(index)
        groups = _group_steps(steps, index.surfaces)
        plan = LaunchBlockersPlan(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=_worst_status(
                index.overall_status,
                *(group.overall_status for group in groups),
            ),
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
            build_allowed=False,
            artifact_publish_allowed=False,
            container_build_attempted=False,
            artifact_publish_attempted=False,
            manual_review_only=True,
            plan_is_not_permission_to_go_live=True,
            plan_is_not_execution=True,
            index_is_not_permission_to_go_live=True,
            handoff_is_not_go_live=True,
            binder_is_not_go_live=True,
            runbook_is_not_deployment=True,
            manifest_is_not_a_build_or_deploy=True,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=index.live_providers_enabled,
            closed_provider_flag_names=index.closed_provider_flag_names,
            missing_credential_names=index.missing_credential_names,
            blocker_codes=_unique_sorted(
                (*index.blocker_codes, *(step.blocker_code for step in steps))
            ),
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
            source_index_command=INDEX_CLI_COMMAND,
            source_index_route=INDEX_HTTP_ROUTE,
            source_index_overall_status=index.overall_status,
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            local_git=index.local_git,
            groups=groups,
            steps=steps,
        )
        logger.info(
            "launch_blockers_plan_built",
            read_only=True,
            no_execution=True,
            overall_status=plan.overall_status,
            operator_halt_status=plan.operator_halt_status,
            outbound_enabled=plan.outbound_enabled,
            go_live_permitted=False,
            execution_allowed=False,
            deployment_allowed=False,
            settings_applied=False,
            halt_changed=False,
            owner_approved=False,
            plan_is_not_permission_to_go_live=True,
            plan_is_not_execution=True,
        )
        return plan


def _steps_from_index(index: GoLiveReadinessIndex) -> tuple[RemediationStep, ...]:
    selected: dict[tuple[str, str, str], RemediationStep] = {}
    surfaces = {card.key: card for card in index.surfaces}

    def add(
        code: str,
        *,
        surface_key: str,
        surface_label: str,
        current_status: str,
        html_route: str | None,
        json_route: str | None,
        command_name: str | None,
        config_name: str | None = None,
        advice: RemediationAdvice | None = None,
    ) -> None:
        cleaned = _safe_text(code)
        if not cleaned:
            return
        resolved = advice or _advice_for(cleaned, config_name=config_name)
        key = (surface_key, cleaned, resolved.config_name or "")
        current = selected.get(key)
        if current is not None and _STATUS_RANK.get(current.current_status, 0) >= _STATUS_RANK.get(
            current_status, 0
        ):
            return
        selected[key] = RemediationStep(
            blocker_code=cleaned,
            surface_key=_safe_text(surface_key) or SECTION_PLAN,
            surface_label=_safe_text(surface_label) or surface_key,
            current_status=_safe_text(current_status) or FindingSeverity.INFO.value,
            recommended_step=_safe_text(resolved.recommended_step),
            owner_approval_type=_safe_approval(resolved.owner_approval_type),
            step_kind=_safe_step_kind(resolved.step_kind),
            html_route=_safe_optional(html_route),
            json_route=_safe_optional(json_route),
            command_name=_safe_optional(command_name),
            config_name=_safe_optional(resolved.config_name or config_name),
        )

    add(
        PLAN_NOT_PERMISSION_CODE,
        surface_key="launch-blockers-plan",
        surface_label="Launch blockers remediation plan",
        current_status=FindingSeverity.INFO.value,
        html_route=HTML_ROUTE,
        json_route=HTTP_ROUTE,
        command_name=CLI_COMMAND,
        advice=RemediationAdvice(
            step_kind="manual_review",
            owner_approval_type="none",
            recommended_step=(
                "Inspect this launch blockers remediation plan at "
                f"{HTML_ROUTE} or {HTTP_ROUTE} or via `vyro-growth {CLI_COMMAND}`. "
                "Read-only planning view; it is not permission to go live "
                "and is not an execution surface."
            ),
        ),
    )
    add(
        EXECUTION_DISABLED_CODE,
        surface_key="launch-blockers-plan",
        surface_label="Launch blockers remediation plan",
        current_status=FindingSeverity.INFO.value,
        html_route=HTML_ROUTE,
        json_route=HTTP_ROUTE,
        command_name=CLI_COMMAND,
    )
    add(
        NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value,
        surface_key="go-live-readiness-index",
        surface_label="Go-live readiness index",
        current_status=index.overall_status,
        html_route=INDEX_HTML_ROUTE,
        json_route=INDEX_HTTP_ROUTE,
        command_name=INDEX_CLI_COMMAND,
    )
    for card in index.surfaces:
        for code in card.blocker_codes:
            add(
                code,
                surface_key=card.key,
                surface_label=card.label,
                current_status=card.overall_status,
                html_route=card.html_route,
                json_route=card.json_route,
                command_name=card.command_name,
            )
    for item in index.remaining_manual_owner_checklist:
        matched = _surface_for_checklist(item, surfaces)
        add(
            item.code,
            surface_key=(
                matched.key
                if matched is not None
                else _surface_key_for_section(item.source_section)
            ),
            surface_label=(
                matched.label
                if matched is not None
                else _surface_label_for_section(item.source_section)
            ),
            current_status=item.status or item.severity,
            html_route=(
                item.html_route if item.html_route else (matched.html_route if matched else None)
            ),
            json_route=(
                item.json_route if item.json_route else (matched.json_route if matched else None)
            ),
            command_name=(
                item.command_name
                if item.command_name
                else (matched.command_name if matched else None)
            ),
        )
    for name in index.missing_credential_names:
        add(
            FindingCode.MISSING_REQUIRED_CREDENTIAL.value,
            surface_key="credentials",
            surface_label="Required credentials",
            current_status="missing",
            html_route="/internal/launch-readiness",
            json_route="/internal/launch-readiness",
            command_name="launch-readiness",
            config_name=name,
            advice=_advice_for(FindingCode.MISSING_REQUIRED_CREDENTIAL.value, config_name=name),
        )
    for name in index.closed_provider_flag_names:
        add(
            SettingsExecutionBlockerCode.PROVIDER_LIVE_FLAG_FALSE.value,
            surface_key="provider_setup",
            surface_label="Provider setup",
            current_status="closed",
            html_route="/internal/launch-readiness",
            json_route="/internal/launch-readiness",
            command_name="launch-readiness",
            config_name=name,
            advice=_advice_for(
                SettingsExecutionBlockerCode.PROVIDER_LIVE_FLAG_FALSE.value,
                config_name=name,
            ),
        )
    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (
                -_STATUS_RANK.get(item.current_status, 0),
                item.surface_key,
                item.blocker_code,
                item.config_name or "",
            ),
        )
    )


def _group_steps(
    steps: Sequence[RemediationStep],
    surfaces: Sequence[ReadinessSurfaceCard],
) -> tuple[RemediationGroup, ...]:
    labels = {card.key: card.label for card in surfaces}
    labels.update(
        {
            "launch-blockers-plan": "Launch blockers remediation plan",
            "go-live-readiness-index": "Go-live readiness index",
            "staged-rollout-plan": "Staged go-live rollout plan",
            "owner-launch-dossier": "Owner launch dossier",
            "provider-setup-checklist": "Provider setup checklist",
            "credentials": "Required credentials",
            "provider_setup": "Provider setup",
        }
    )
    grouped: dict[str, list[RemediationStep]] = {}
    for step in steps:
        grouped.setdefault(step.surface_key, []).append(step)
    groups: list[RemediationGroup] = []
    for key in sorted(grouped):
        items = tuple(
            sorted(
                grouped[key],
                key=lambda item: (
                    -_STATUS_RANK.get(item.current_status, 0),
                    item.blocker_code,
                    item.config_name or "",
                ),
            )
        )
        groups.append(
            RemediationGroup(
                group_key=key,
                group_label=labels.get(key, items[0].surface_label),
                group_kind="category" if key in {"credentials", "provider_setup"} else "surface",
                overall_status=_worst_status(*(item.current_status for item in items)),
                step_count=str(len(items)),
                steps=items,
            )
        )
    return tuple(groups)


def _surface_for_checklist(
    item: IndexChecklistItem,
    surfaces: dict[str, ReadinessSurfaceCard],
) -> ReadinessSurfaceCard | None:
    if item.command_name:
        for card in surfaces.values():
            if card.command_name == item.command_name:
                return card
    mapped = _surface_key_for_section(item.source_section)
    return surfaces.get(mapped)


def _surface_key_for_section(source_section: str) -> str:
    return _SURFACE_BY_SECTION.get(source_section, "launch-blockers-plan")


def _surface_label_for_section(source_section: str) -> str:
    key = _surface_key_for_section(source_section)
    labels = {
        "launch-blockers-plan": "Launch blockers remediation plan",
        "go-live-readiness-index": "Go-live readiness index",
        "staged-rollout-plan": "Staged go-live rollout plan",
        "owner-launch-dossier": "Owner launch dossier",
        "provider-setup-checklist": "Provider setup checklist",
        "owner-handoff-packet": "Owner handoff packet",
        "launch-readiness": "Launch readiness",
        "settings-execution-preflight": "Settings execution preflight",
        "compliance-evidence-binder": "Compliance evidence binder",
        "release-candidate-runbook": "Release-candidate runbook",
        "release-artifact-manifest": "Release artifact manifest",
        "operator-audit-timeline": "Operator audit timeline",
        "operator-dashboard": "Operator dashboard / command center",
        "credentials": "Required credentials",
        "provider_setup": "Provider setup",
    }
    return labels.get(key, key)


def _advice_for(code: str, *, config_name: str | None = None) -> RemediationAdvice:
    named = _safe_optional(config_name)
    catalog = _ADVICE_CATALOG.get(code)
    if catalog is not None:
        recommended = catalog.recommended_step
        if "{config_name}" in recommended:
            recommended = recommended.format(config_name=named or "the named required credential")
        return RemediationAdvice(
            step_kind=catalog.step_kind,
            owner_approval_type=catalog.owner_approval_type,
            recommended_step=recommended,
            config_name=named or catalog.config_name,
        )
    return RemediationAdvice(
        step_kind="manual_review",
        owner_approval_type="owner_review",
        recommended_step=(
            "Review this blocker code on the existing read-only readiness "
            "surface. This plan does not execute, apply settings, lift halt, "
            "or permit go-live."
        ),
        config_name=named,
    )


def _safe_step_kind(value: str) -> str:
    cleaned = _safe_text(value)
    if cleaned in STEP_KINDS:
        return cleaned
    return "manual_review"


def _safe_approval(value: str) -> str:
    cleaned = _safe_text(value)
    if cleaned in OWNER_APPROVAL_TYPES:
        return cleaned
    return "none"


def _worst_status(*values: str) -> str:
    if not values:
        return FindingSeverity.INFO.value
    return max(values, key=lambda item: _STATUS_RANK.get(item, 0))


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    cleaned = [_safe_text(item) for item in values]
    return tuple(sorted({item for item in cleaned if item}))


def _safe_optional(value: object) -> str | None:
    text = _safe_text(value)
    return text or None


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    text = sanitize_operator_text(str(value))
    return text or ""


def _bool_text(value: object) -> str:
    return "true" if value else "false"


_ADVICE_CATALOG: dict[str, RemediationAdvice] = {
    FindingCode.OUTBOUND_ENABLED.value: RemediationAdvice(
        "configuration",
        "live_enablement_review",
        "Keep OUTBOUND_ENABLED=false until a later owner-approved settings-change "
        "request exists and a future execution phase is added. This plan does not "
        "enable outbound.",
        "OUTBOUND_ENABLED",
    ),
    FindingCode.LIVE_PROVIDER_ENABLED.value: RemediationAdvice(
        "provider_setup",
        "live_enablement_review",
        "Keep every live-provider flag disabled. Review closed flag names only; "
        "this plan does not enable providers.",
    ),
    FindingCode.LIVE_OUTBOUND_ARTIFACT.value: RemediationAdvice(
        "legal_compliance",
        "owner_review",
        "Inspect live outbound artifact counts on the operator dashboard and "
        "audit timeline. Do not send, enroll, book, or call from this plan.",
    ),
    FindingCode.CONFIG_NOT_READY.value: RemediationAdvice(
        "configuration",
        "none",
        "Run `vyro-growth check-config` and review missing required setting "
        "names only. Do not paste secret values into this plan.",
    ),
    FindingCode.DATABASE_UNAVAILABLE.value: RemediationAdvice(
        "configuration",
        "none",
        "Confirm DATABASE_URL is configured locally and PostgreSQL is reachable. "
        "This plan does not connect to live providers.",
        "DATABASE_URL",
    ),
    FindingCode.OPERATOR_HALT_UNAVAILABLE.value: RemediationAdvice(
        "configuration",
        "none",
        "Confirm operator halt can be read from the local database. This plan "
        "does not change halt state.",
    ),
    FindingCode.RECENT_FAILURES.value: RemediationAdvice(
        "manual_review",
        "owner_review",
        "Inspect sanitized recent-failure counts on the operator command center. "
        "Do not retry live provider work from this plan.",
    ),
    FindingCode.PENDING_OPERATOR_REVIEW.value: RemediationAdvice(
        "manual_review",
        "owner_review",
        "Review pending operator artifacts at /internal/operator-review-queue. "
        "Recording a decision does not execute the artifact.",
    ),
    FindingCode.OPERATOR_HALT_ACTIVE.value: RemediationAdvice(
        "configuration",
        "settings_change_request",
        "Keep operator halt active until a later owner halt-review request. "
        "This plan does not lift operator halt.",
    ),
    FindingCode.SAFE_DEFAULTS.value: RemediationAdvice(
        "configuration",
        "none",
        "Keep safe defaults: OUTBOUND_ENABLED=false, live-provider flags "
        "disabled, and no live owner-approved state.",
        "OUTBOUND_ENABLED",
    ),
    FindingCode.EXECUTION_PLANS_DRY_RUN.value: RemediationAdvice(
        "manual_review",
        "none",
        "Keep execution plans dry-run only. This plan does not execute approved "
        "items.",
    ),
    FindingCode.APPROVAL_PACKETS_DRY_RUN.value: RemediationAdvice(
        "manual_review",
        "owner_approval_packet",
        "Keep approval packets as owner-review records only. This plan does not "
        "execute packets.",
    ),
    FindingCode.SMOKE_GATE_MISSING.value: RemediationAdvice(
        "deployment",
        "none",
        "Restore the documented CI smoke-dry-run job and check-smoke-output "
        "gate. This plan does not deploy.",
    ),
    FindingCode.MISSING_REQUIRED_CREDENTIAL.value: RemediationAdvice(
        "credential",
        "settings_change_request",
        "Configure the named required credential {config_name} in local env "
        "later. Do not paste values here. This plan does not write secrets.",
    ),
    FindingCode.PENDING_OWNER_APPROVAL_PACKETS.value: RemediationAdvice(
        "manual_review",
        "owner_approval_packet",
        "Owner-review pending approval packets at "
        "/internal/operator-approval-packets. Recording a decision does not "
        "execute the packet.",
    ),
    FindingCode.ACTION_READINESS_BLOCKED.value: RemediationAdvice(
        "manual_review",
        "owner_review",
        "Inspect blocked action-readiness candidates at "
        "/internal/operator-action-readiness. This plan does not execute "
        "approved items.",
    ),
    FindingCode.PENDING_SETTINGS_CHANGE_REQUESTS.value: RemediationAdvice(
        "configuration",
        "settings_change_request",
        "Review pending settings-change requests at "
        "/internal/operator-settings-change-requests. Recording a decision "
        "does not apply settings.",
    ),
    NextActionCode.DISABLE_OUTBOUND.value: RemediationAdvice(
        "configuration",
        "live_enablement_review",
        "Disable outbound. Keep OUTBOUND_ENABLED=false. This plan does not "
        "enable outbound.",
        "OUTBOUND_ENABLED",
    ),
    NextActionCode.DISABLE_LIVE_PROVIDERS.value: RemediationAdvice(
        "provider_setup",
        "live_enablement_review",
        "Disable live-provider flags. Review flag names only; this plan does "
        "not call providers.",
    ),
    NextActionCode.INVESTIGATE_LIVE_ARTIFACTS.value: RemediationAdvice(
        "legal_compliance",
        "owner_review",
        "Investigate live outbound artifact counts on the operator dashboard "
        "and audit timeline. Do not send or enroll from this plan.",
    ),
    NextActionCode.RECORD_OPERATOR_HALT.value: RemediationAdvice(
        "configuration",
        "settings_change_request",
        "Record or confirm operator halt. This plan does not change halt state.",
    ),
    NextActionCode.REVIEW_FAILED_RUNS.value: RemediationAdvice(
        "manual_review",
        "owner_review",
        "Review sanitized failed-run counts on the operator command center. "
        "Do not retry live work from this plan.",
    ),
    NextActionCode.CHECK_RUNTIME_CONFIG.value: RemediationAdvice(
        "configuration",
        "none",
        "Run `vyro-growth check-config` and review setting names only.",
    ),
    NextActionCode.REVIEW_PENDING_ARTIFACTS.value: RemediationAdvice(
        "manual_review",
        "owner_review",
        "Review pending artifacts at /internal/operator-review-queue. "
        "Recording a decision does not execute the artifact.",
    ),
    NextActionCode.PLAN_APPROVED_EXECUTION.value: RemediationAdvice(
        "manual_review",
        "owner_approval_packet",
        "Keep approved execution planning dry-run only. This plan does not "
        "execute approved items.",
    ),
    NextActionCode.GENERATE_APPROVAL_PACKETS.value: RemediationAdvice(
        "manual_review",
        "owner_approval_packet",
        "Generate or inspect owner approval packets as records only. This "
        "plan does not execute packets.",
    ),
    NextActionCode.OWNER_REVIEW_APPROVAL_PACKETS.value: RemediationAdvice(
        "manual_review",
        "owner_approval_packet",
        "Owner-review live-readiness packets at "
        "/internal/operator-approval-packets. Do not execute underlying "
        "actions.",
    ),
    NextActionCode.INSPECT_ACTION_READINESS.value: RemediationAdvice(
        "manual_review",
        "owner_review",
        "Inspect the approved action readiness queue at "
        "/internal/operator-action-readiness. Read-only; do not execute.",
    ),
    NextActionCode.RUN_DISCOVERY_WHEN_READY.value: RemediationAdvice(
        "manual_review",
        "none",
        "Run bounded practice discovery later when ready. This plan does not "
        "start discovery or outbound.",
    ),
    NextActionCode.KEEP_OUTBOUND_DISABLED.value: RemediationAdvice(
        "configuration",
        "none",
        "Keep OUTBOUND_ENABLED=false. This plan does not enable outbound.",
        "OUTBOUND_ENABLED",
    ),
    NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value: RemediationAdvice(
        "provider_setup",
        "none",
        "Keep every live-provider flag disabled. This plan does not enable "
        "providers.",
    ),
    NextActionCode.KEEP_OPERATOR_HALT.value: RemediationAdvice(
        "configuration",
        "settings_change_request",
        "Keep operator halt active until a later explicit owner action. This "
        "plan does not lift halt.",
    ),
    NextActionCode.RESTORE_CI_SMOKE_GATE.value: RemediationAdvice(
        "deployment",
        "none",
        "Restore the documented CI smoke-dry-run job and check-smoke-output "
        "gate. This plan does not deploy.",
    ),
    NextActionCode.CONFIGURE_REQUIRED_CREDENTIALS.value: RemediationAdvice(
        "credential",
        "settings_change_request",
        "Configure named required credentials in local env later. Do not paste "
        "values here.",
    ),
    NextActionCode.REVIEW_SETTINGS_CHANGE_REQUESTS.value: RemediationAdvice(
        "configuration",
        "settings_change_request",
        "Review pending live settings change requests at "
        "/internal/operator-settings-change-requests. Recording a decision "
        "does not apply them.",
    ),
    NextActionCode.INSPECT_SETTINGS_EXECUTION_PREFLIGHT.value: RemediationAdvice(
        "configuration",
        "settings_change_request",
        "Inspect remaining settings-execution blockers at "
        "/internal/operator-settings-execution-preflight. Read-only dry-run "
        "view; do not execute.",
    ),
    NextActionCode.INSPECT_OPERATOR_AUDIT_TIMELINE.value: RemediationAdvice(
        "legal_compliance",
        "owner_review",
        "Inspect the operator activity audit timeline at "
        "/internal/operator-audit-timeline. Read-only; do not execute.",
    ),
    NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value: RemediationAdvice(
        "legal_compliance",
        "none",
        "Inspect the owner go-live handoff packet at "
        "/internal/operator-owner-handoff-packet. It is not permission to go "
        "live.",
    ),
    NextActionCode.BINDER_IS_NOT_GO_LIVE.value: RemediationAdvice(
        "legal_compliance",
        "none",
        "Inspect the compliance evidence binder at "
        "/internal/operator-compliance-evidence-binder. It is not permission "
        "to go live.",
    ),
    NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT.value: RemediationAdvice(
        "deployment",
        "none",
        "Inspect the release-candidate runbook at "
        "/internal/operator-release-candidate-runbook. It is not a deployment "
        "mechanism.",
    ),
    NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value: RemediationAdvice(
        "deployment",
        "none",
        "Inspect the release artifact manifest at "
        "/internal/operator-release-artifact-manifest. It is not a build or "
        "deploy.",
    ),
    NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value: RemediationAdvice(
        "manual_review",
        "none",
        "Inspect the go-live readiness index at "
        f"{INDEX_HTML_ROUTE} or via `vyro-growth {INDEX_CLI_COMMAND}`. "
        "It is not permission to go live and is not an execution surface.",
    ),
    PLAN_NOT_PERMISSION_CODE: RemediationAdvice(
        "manual_review",
        "none",
        "Inspect this launch blockers remediation plan at "
        f"{HTML_ROUTE} or {HTTP_ROUTE} or via `vyro-growth {CLI_COMMAND}`. "
        "Read-only planning view; it is not permission to go live and is "
        "not an execution surface.",
    ),
    NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value: RemediationAdvice(
        "manual_review",
        "none",
        "Inspect the staged go-live rollout plan at "
        "/internal/operator-staged-rollout-plan or "
        "/internal/staged-rollout-plan or via `vyro-growth "
        "staged-rollout-plan`. Read-only staged planning view; it is "
        "not permission to go live and is not an execution surface.",
    ),
    EXECUTION_DISABLED_CODE: RemediationAdvice(
        "configuration",
        "none",
        "Execution remains disabled in this phase. This plan does not execute, "
        "apply settings, or permit go-live.",
    ),
    SettingsExecutionBlockerCode.OUTBOUND_DISABLED.value: RemediationAdvice(
        "configuration",
        "none",
        "OUTBOUND_ENABLED remains false. This is the safe default and is not "
        "a defect to execute against.",
        "OUTBOUND_ENABLED",
    ),
    SettingsExecutionBlockerCode.PROVIDER_LIVE_FLAG_FALSE.value: RemediationAdvice(
        "provider_setup",
        "live_enablement_review",
        "Live-provider flag {config_name} remains false. Review the flag name "
        "only; this plan does not enable providers.",
    ),
    SettingsExecutionBlockerCode.MISSING_CREDENTIAL.value: RemediationAdvice(
        "credential",
        "settings_change_request",
        "Configure the named required credential {config_name} in local env "
        "later. Do not paste values here.",
    ),
    SettingsExecutionBlockerCode.PENDING_DECISION.value: RemediationAdvice(
        "configuration",
        "settings_change_request",
        "Owner-review the pending settings-change decision. Recording a "
        "decision does not apply settings.",
    ),
    SettingsExecutionBlockerCode.REJECTED_DECISION.value: RemediationAdvice(
        "configuration",
        "settings_change_request",
        "A settings-change decision was rejected. Record a later request if "
        "needed. This plan does not apply settings.",
    ),
    SettingsExecutionBlockerCode.NEEDS_CHANGES_DECISION.value: RemediationAdvice(
        "configuration",
        "settings_change_request",
        "A settings-change decision needs changes. Review the request record "
        "only. This plan does not apply settings.",
    ),
    SettingsExecutionBlockerCode.MISSING_OWNER_APPROVAL_PACKET_DECISION.value: RemediationAdvice(
        "manual_review",
        "owner_approval_packet",
        "Owner-review the required approval packet first. This plan does not "
        "execute packets.",
    ),
    SettingsExecutionBlockerCode.MISSING_EXPLICIT_OWNER_APPROVAL.value: RemediationAdvice(
        "manual_review",
        "owner_approval_packet",
        "Explicit owner approval is still missing. This plan does not set "
        "owner_approved or execute.",
    ),
    SettingsExecutionBlockerCode.FUTURE_EXECUTION_PHASE_ABSENT.value: RemediationAdvice(
        "configuration",
        "none",
        "No future execution phase exists. This plan does not create or "
        "enable one.",
    ),
}


def plan_payload(plan: LaunchBlockersPlan) -> dict[str, Any]:
    return {
        "generated_at": plan.generated_at.isoformat(),
        "packet_kind": plan.packet_kind,
        "purpose": plan.purpose,
        "overall_status": plan.overall_status,
        "read_only": True,
        "no_execution": True,
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
        "manual_review_only": True,
        "plan_is_not_permission_to_go_live": True,
        "plan_is_not_execution": True,
        "index_is_not_permission_to_go_live": True,
        "handoff_is_not_go_live": True,
        "binder_is_not_go_live": True,
        "runbook_is_not_deployment": True,
        "manifest_is_not_a_build_or_deploy": True,
        "operator_halt_status": plan.operator_halt_status,
        "operator_halt_before": plan.operator_halt_before,
        "operator_halt_after": plan.operator_halt_after,
        "outbound_enabled": plan.outbound_enabled,
        "live_providers_enabled": plan.live_providers_enabled,
        "closed_provider_flag_names": list(plan.closed_provider_flag_names),
        "missing_credential_names": list(plan.missing_credential_names),
        "blocker_codes": list(plan.blocker_codes),
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "source_index_command": INDEX_CLI_COMMAND,
        "source_index_route": INDEX_HTTP_ROUTE,
        "source_index_overall_status": plan.source_index_overall_status,
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
        "groups": [_group_payload(group) for group in plan.groups],
        "steps": [_step_payload(step) for step in plan.steps],
    }


def _group_payload(group: RemediationGroup) -> dict[str, Any]:
    return {
        "group_key": group.group_key,
        "group_label": group.group_label,
        "group_kind": group.group_kind,
        "overall_status": group.overall_status,
        "step_count": group.step_count,
        "steps": [_step_payload(step) for step in group.steps],
    }


def _step_payload(step: RemediationStep) -> dict[str, Any]:
    return {
        "blocker_code": step.blocker_code,
        "surface_key": step.surface_key,
        "surface_label": step.surface_label,
        "current_status": step.current_status,
        "recommended_step": step.recommended_step,
        "owner_approval_type": step.owner_approval_type,
        "step_kind": step.step_kind,
        "html_route": step.html_route,
        "json_route": step.json_route,
        "command_name": step.command_name,
        "config_name": step.config_name,
    }


def format_launch_blockers_plan(
    plan: LaunchBlockersPlan,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(plan_payload(plan))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(plan, payload)


def _format_markdown(plan: LaunchBlockersPlan, payload: dict[str, Any]) -> str:
    lines = [
        "# Launch blockers remediation plan",
        "",
        "This plan is a sanitized owner/operator remediation-planning export of "
        "existing go-live readiness index blockers. It is not permission to go "
        "live and is not an execution surface.",
        "",
        f"- overall: {payload['overall_status']}",
        f"- packet_kind: {payload['packet_kind']}",
        f"- purpose: {payload['purpose']}",
        f"- read_only: {_bool_text(payload['read_only'])}",
        f"- no_execution: {_bool_text(payload['no_execution'])}",
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
        (
            "- plan_is_not_permission_to_go_live: "
            f"{_bool_text(payload['plan_is_not_permission_to_go_live'])}"
        ),
        f"- plan_is_not_execution: {_bool_text(payload['plan_is_not_execution'])}",
        (
            "- index_is_not_permission_to_go_live: "
            f"{_bool_text(payload['index_is_not_permission_to_go_live'])}"
        ),
        f"- handoff_is_not_go_live: {_bool_text(payload['handoff_is_not_go_live'])}",
        f"- binder_is_not_go_live: {_bool_text(payload['binder_is_not_go_live'])}",
        f"- runbook_is_not_deployment: {_bool_text(payload['runbook_is_not_deployment'])}",
        (
            "- manifest_is_not_a_build_or_deploy: "
            f"{_bool_text(payload['manifest_is_not_a_build_or_deploy'])}"
        ),
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
        f"- source_index_command: {payload['source_index_command']}",
        f"- source_index_route: {payload['source_index_route']}",
        f"- source_index_overall_status: {payload['source_index_overall_status']}",
        f"- blocker_codes: {_format_codes(plan.blocker_codes)}",
        f"- missing_credential_names: {_format_codes(plan.missing_credential_names)}",
        f"- closed_provider_flag_names: {_format_codes(plan.closed_provider_flag_names)}",
        "",
        "## Live-blocking flags",
        f"- OUTBOUND_ENABLED={_bool_text(plan.outbound_enabled)}",
        f"- operator_halt_status={plan.operator_halt_status}",
        f"- live_providers_enabled={_bool_text(plan.live_providers_enabled)}",
        "- execution_allowed=false",
        "- go_live_permitted=false",
        "- deployment_allowed=false",
        "- settings_applied=false",
        "- halt_changed=false",
        "- owner_approved=false",
        "- plan_is_not_permission_to_go_live=true",
        "- plan_is_not_execution=true",
        f"- local_git_available: {_bool_text(plan.local_git.available)}",
        f"- current_branch: {plan.local_git.current_branch}",
        f"- current_sha: {plan.local_git.current_sha}",
        f"- working_tree_status: {plan.local_git.working_tree_status}",
        f"- git_provider_called: {_bool_text(plan.local_git.git_provider_called)}",
        f"- github_actions_called: {_bool_text(plan.local_git.github_actions_called)}",
        "",
        "## Remediation groups",
    ]
    for group in plan.groups:
        lines.extend(
            [
                f"### {group.group_label}",
                f"- group_key: {group.group_key}",
                f"- group_kind: {group.group_kind}",
                f"- overall_status: {group.overall_status}",
                f"- step_count: {group.step_count}",
            ]
        )
        for step in group.steps:
            html_route = step.html_route or "-"
            json_route = step.json_route or "-"
            command_name = step.command_name or "-"
            config_name = step.config_name or "-"
            lines.append(
                f"- [{step.current_status}] {step.blocker_code} "
                f"kind={step.step_kind} approval={step.owner_approval_type} "
                f"surface={step.surface_key} html_route={html_route} "
                f"json_route={json_route} command={command_name} "
                f"config_name={config_name} step={step.recommended_step}"
            )
    if not plan.groups:
        lines.append("- groups: none")
    return "\n".join(lines)


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"
