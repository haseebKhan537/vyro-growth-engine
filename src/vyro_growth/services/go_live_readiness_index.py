"""Read-only operator go-live readiness index.

Phase 41 consolidates existing owner/operator readiness, evidence, runbook,
manifest, and audit surfaces into one sanitized index. It never executes,
builds, publishes, deploys, applies settings, lifts halt, enables outbound,
calls providers, or changes live state. This index is not permission to go
live and is not an execution surface.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from vyro_growth.config import Settings, any_live_provider_enabled
from vyro_growth.domain import FindingSeverity, NextActionCode
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
from vyro_growth.services.command_center import (
    CommandCenterSummary,
    OperatorCommandCenterService,
)
from vyro_growth.services.operator_audit_timeline import (
    OperatorAuditTimeline,
    OperatorAuditTimelineService,
)
from vyro_growth.services.operator_halt import read_operator_halt
from vyro_growth.services.owner_handoff import OwnerHandoffPacket, OwnerHandoffPacketService
from vyro_growth.services.release_artifact_manifest import (
    LocalGitMetadata,
    ReleaseArtifactManifest,
    ReleaseArtifactManifestService,
)

logger = structlog.get_logger(__name__)

PACKET_KIND = "operator_go_live_readiness_index"
PACKET_PURPOSE = "manual_owner_review_index_only"
INDEX_NOT_PERMISSION_CODE = NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
SECTION_INDEX = "go_live_readiness_index"
CLI_COMMAND = "go-live-readiness-index"
HTTP_ROUTE = "/internal/go-live-readiness-index"
HTML_ROUTE = "/internal/operator-go-live-readiness-index"
RELATED_COMMANDS: tuple[str, ...] = (
    "operator-command-center",
    "launch-readiness",
    "settings-execution-preflight",
    "owner-handoff-packet",
    "compliance-evidence-binder",
    "release-candidate-runbook",
    "release-artifact-manifest",
    CLI_COMMAND,
    "launch-blockers-plan",
    "staged-rollout-plan",
    "owner-launch-dossier",
    "provider-setup-checklist",
    "go-live-rehearsal-checklist",
    "rehearsal-outcome-report",
    "supervised-pilot-plan",
    "supervised-pilot-candidates",
    "supervised-pilot-go-no-go",
    "supervised-pilot-first-send-preflight",
    "system-status",
)
RELATED_ROUTES: tuple[str, ...] = (
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
    "/internal/operator-supervised-pilot-plan",
    "/internal/supervised-pilot-plan",
    "/internal/operator-supervised-pilot-candidates",
    "/internal/supervised-pilot-candidates",
    "/internal/operator-supervised-pilot-go-no-go",
    "/internal/supervised-pilot-go-no-go",
    "/internal/operator-supervised-pilot-first-send-preflight",
    "/internal/supervised-pilot-first-send-preflight",
)
_SEVERITY_RANK = {
    FindingSeverity.INFO.value: 0,
    FindingSeverity.WARNING.value: 1,
    FindingSeverity.BLOCKED.value: 2,
}
_STATUS_RANK = {
    FindingSeverity.INFO.value: 0,
    "ready_for_owner_review": 1,
    FindingSeverity.WARNING.value: 2,
    FindingSeverity.BLOCKED.value: 3,
}


@dataclass(frozen=True)
class IndexCount:
    label: str
    value: str


@dataclass(frozen=True)
class ReadinessSurfaceCard:
    key: str
    label: str
    html_route: str
    json_route: str | None
    command_name: str | None
    overall_status: str
    counts: tuple[IndexCount, ...]
    blocker_codes: tuple[str, ...]
    flag_states: tuple[str, ...]


@dataclass(frozen=True)
class IndexChecklistItem:
    code: str
    severity: str
    source_section: str
    status: str
    html_route: str | None
    json_route: str | None
    command_name: str | None
    label: str


@dataclass(frozen=True)
class GoLiveReadinessIndex:
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
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    surfaces: tuple[ReadinessSurfaceCard, ...]
    remaining_manual_owner_checklist: tuple[IndexChecklistItem, ...]


class GoLiveReadinessIndexService:
    """Compose existing read-only summaries into one owner-review index."""

    def __init__(
        self,
        *,
        command_center: OperatorCommandCenterService | None = None,
        owner_handoff: OwnerHandoffPacketService | None = None,
        audit_timeline: OperatorAuditTimelineService | None = None,
        manifest: ReleaseArtifactManifestService | None = None,
    ) -> None:
        self.command_center = command_center or OperatorCommandCenterService()
        self.owner_handoff = owner_handoff or OwnerHandoffPacketService()
        self.audit_timeline = audit_timeline or OperatorAuditTimelineService()
        self.manifest = manifest or ReleaseArtifactManifestService()

    def build(self, db: Session, settings: Settings) -> GoLiveReadinessIndex:
        halt_before = read_operator_halt(db)
        command_center = self.command_center.summarize(db, settings)
        handoff = self.owner_handoff.build(db, settings)
        timeline = self.audit_timeline.timeline(db, settings)
        manifest = self.manifest.build(db, settings)
        halt_after = read_operator_halt(db)
        if halt_after != halt_before:
            raise RuntimeError("go-live readiness index must not change operator halt status")
        surfaces = _surface_cards(command_center, handoff, timeline, manifest)
        items = _remaining_checklist(command_center, handoff, manifest)
        overall = _worst_status(
            command_center.overall_severity.value,
            handoff.overall_status,
            manifest.overall_status,
        )
        index = GoLiveReadinessIndex(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=overall,
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
            index_is_not_permission_to_go_live=True,
            handoff_is_not_go_live=True,
            binder_is_not_go_live=True,
            runbook_is_not_deployment=True,
            manifest_is_not_a_build_or_deploy=True,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=any_live_provider_enabled(settings),
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
            closed_provider_flag_names=_unique_sorted(
                (
                    *handoff.closed_provider_flag_names,
                    *manifest.closed_provider_flag_names,
                )
            ),
            missing_credential_names=_unique_sorted(
                (
                    *handoff.missing_credential_names,
                    *manifest.missing_credential_names,
                )
            ),
            blocker_codes=_unique_sorted((*handoff.blocker_codes, *manifest.blocker_codes)),
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            local_git=manifest.source_provenance.local_git,
            surfaces=surfaces,
            remaining_manual_owner_checklist=items,
        )
        logger.info(
            "go_live_readiness_index_built",
            read_only=True,
            no_execution=True,
            overall_status=index.overall_status,
            operator_halt_status=index.operator_halt_status,
            outbound_enabled=index.outbound_enabled,
            go_live_permitted=False,
            execution_allowed=False,
            deployment_allowed=False,
            build_allowed=False,
            artifact_publish_allowed=False,
            index_is_not_permission_to_go_live=True,
        )
        return index


def _surface_cards(
    command_center: CommandCenterSummary,
    handoff: OwnerHandoffPacket,
    timeline: OperatorAuditTimeline,
    manifest: ReleaseArtifactManifest,
) -> tuple[ReadinessSurfaceCard, ...]:
    launch = handoff.launch_readiness
    preflight = handoff.settings_execution_preflight
    packets = handoff.owner_approval_packets
    reused = manifest.reused_summaries
    return (
        ReadinessSurfaceCard(
            key="operator-dashboard",
            label="Operator dashboard / command center",
            html_route="/internal/operator-dashboard",
            json_route="/internal/operator-command-center",
            command_name="operator-command-center",
            overall_status=_safe_text(command_center.overall_severity.value),
            counts=(
                IndexCount("Review pending", str(command_center.outstanding_review.pending_count)),
                IndexCount("Approval packets", str(command_center.approval_packets.packets)),
                IndexCount("Findings", str(command_center.finding_counts.total)),
                IndexCount("Blocked findings", str(command_center.finding_counts.blocked)),
            ),
            blocker_codes=_unique_sorted(
                item.code.value
                for item in command_center.findings
                if item.severity is FindingSeverity.BLOCKED
            ),
            flag_states=(
                f"outbound_enabled={_bool_text(command_center.safety.outbound_enabled)}",
                "execution_allowed=false",
            ),
        ),
        ReadinessSurfaceCard(
            key="launch-readiness",
            label="Launch readiness",
            html_route="/internal/launch-readiness",
            json_route="/internal/launch-readiness",
            command_name="launch-readiness",
            overall_status=_safe_text(launch.overall_status),
            counts=(
                IndexCount("Pending packets", str(launch.pending_owner_approval_packets)),
                IndexCount("Action candidates", str(launch.action_readiness_candidate_count)),
                IndexCount("Action blocked", str(launch.action_readiness_blocked_count)),
                IndexCount(
                    "Pending settings requests",
                    str(launch.pending_settings_change_request_count),
                ),
            ),
            blocker_codes=tuple(launch.blocker_codes),
            flag_states=(
                f"outbound_enabled={_bool_text(launch.outbound_enabled)}",
                f"live_providers_enabled={_bool_text(launch.live_providers_enabled)}",
                "owner_approved=false",
                "live_action=false",
            ),
        ),
        ReadinessSurfaceCard(
            key="settings-execution-preflight",
            label="Settings execution preflight",
            html_route="/internal/operator-settings-execution-preflight",
            json_route="/internal/settings-execution-preflight",
            command_name="settings-execution-preflight",
            overall_status=_safe_text(preflight.overall_status),
            counts=(
                IndexCount("Requests", str(preflight.request_count)),
                IndexCount("Pending decisions", str(preflight.pending_decision_count)),
                IndexCount("Blocked", str(preflight.blocked_count)),
                IndexCount("Executable", str(preflight.executable_count)),
            ),
            blocker_codes=tuple(preflight.blocker_codes),
            flag_states=(
                "execution_allowed=false",
                "settings_applied=false",
                "dry_run_only=true",
            ),
        ),
        ReadinessSurfaceCard(
            key="owner-handoff-packet",
            label="Owner handoff packet",
            html_route="/internal/operator-owner-handoff-packet",
            json_route="/internal/owner-handoff-packet",
            command_name="owner-handoff-packet",
            overall_status=_safe_text(handoff.overall_status),
            counts=(
                IndexCount("Packets", str(packets.packet_count)),
                IndexCount("Pending packets", str(packets.pending_count)),
                IndexCount(
                    "Settings requests",
                    str(handoff.settings_change_requests.request_count),
                ),
                IndexCount(
                    "Action candidates",
                    str(handoff.approved_action_readiness.candidate_count),
                ),
            ),
            blocker_codes=tuple(handoff.blocker_codes),
            flag_states=(
                "go_live_permitted=false",
                "execution_allowed=false",
                "handoff_is_not_permission_to_go_live=true",
            ),
        ),
        ReadinessSurfaceCard(
            key="compliance-evidence-binder",
            label="Compliance evidence binder",
            html_route="/internal/operator-compliance-evidence-binder",
            json_route="/internal/compliance-evidence-binder",
            command_name="compliance-evidence-binder",
            overall_status=_safe_text(manifest.overall_status),
            counts=(
                IndexCount(
                    "Preflight blocked",
                    str(reused.settings_preflight_blocked_count),
                ),
                IndexCount(
                    "Audit matching",
                    str(reused.audit_timeline_matching_count),
                ),
            ),
            blocker_codes=tuple(reused.launch_readiness_blocker_codes),
            flag_states=(
                "go_live_permitted=false",
                "execution_allowed=false",
                f"binder_is_not_go_live={_bool_text(reused.binder_is_not_go_live)}",
            ),
        ),
        ReadinessSurfaceCard(
            key="release-candidate-runbook",
            label="Release-candidate runbook",
            html_route="/internal/operator-release-candidate-runbook",
            json_route="/internal/release-candidate-runbook",
            command_name="release-candidate-runbook",
            overall_status=_safe_text(manifest.overall_status),
            counts=(
                IndexCount(
                    "Preflight blocked",
                    str(reused.settings_preflight_blocked_count),
                ),
            ),
            blocker_codes=tuple(manifest.blocker_codes),
            flag_states=(
                "go_live_permitted=false",
                "execution_allowed=false",
                "deployment_allowed=false",
                f"runbook_is_not_deployment={_bool_text(reused.runbook_is_not_deployment)}",
            ),
        ),
        ReadinessSurfaceCard(
            key="release-artifact-manifest",
            label="Release artifact manifest",
            html_route="/internal/operator-release-artifact-manifest",
            json_route="/internal/release-artifact-manifest",
            command_name="release-artifact-manifest",
            overall_status=_safe_text(manifest.overall_status),
            counts=(
                IndexCount("Artifacts", str(len(manifest.artifact_inventory))),
                IndexCount("Migrations", str(len(manifest.migration_inventory))),
                IndexCount("Runtime commands", str(len(manifest.runtime_command_inventory))),
            ),
            blocker_codes=tuple(manifest.blocker_codes),
            flag_states=(
                "build_allowed=false",
                "artifact_publish_allowed=false",
                "deployment_allowed=false",
                "manifest_is_not_a_build_or_deploy=true",
            ),
        ),
        ReadinessSurfaceCard(
            key="operator-audit-timeline",
            label="Operator audit timeline",
            html_route="/internal/operator-audit-timeline",
            json_route=None,
            command_name=None,
            overall_status=_safe_text(timeline.operator_halt_status),
            counts=(
                IndexCount("Matching events", str(timeline.matching_count)),
                IndexCount("Shown events", str(timeline.shown_count)),
            ),
            blocker_codes=(),
            flag_states=(
                "read_only=true",
                "no_execution=true",
                f"outbound_enabled={_bool_text(timeline.outbound_enabled)}",
            ),
        ),
    )


def _remaining_checklist(
    command_center: CommandCenterSummary,
    handoff: OwnerHandoffPacket,
    manifest: ReleaseArtifactManifest,
) -> tuple[IndexChecklistItem, ...]:
    selected: dict[str, IndexChecklistItem] = {}

    def add(
        code: str,
        severity: str,
        source_section: str,
        *,
        status: str = "open",
        html_route: str | None = None,
        json_route: str | None = None,
        command_name: str | None = None,
        label: str | None = None,
    ) -> None:
        cleaned = _safe_text(code)
        if not cleaned:
            return
        current = selected.get(cleaned)
        if current is not None and _SEVERITY_RANK.get(current.severity, 0) >= _SEVERITY_RANK.get(
            severity, 0
        ):
            return
        routes = _routes_for_section(source_section)
        selected[cleaned] = IndexChecklistItem(
            code=cleaned,
            severity=_safe_text(severity) or FindingSeverity.INFO.value,
            source_section=_safe_text(source_section) or SECTION_INDEX,
            status=_safe_text(status) or "open",
            html_route=html_route or routes[0],
            json_route=json_route or routes[1],
            command_name=command_name or routes[2],
            label=_safe_text(label) or cleaned,
        )

    add(
        INDEX_NOT_PERMISSION_CODE,
        FindingSeverity.INFO.value,
        SECTION_INDEX,
        html_route=HTML_ROUTE,
        label=(
            "Inspect the go-live readiness index at "
            f"{HTML_ROUTE}. Read-only owner-review view; it is not "
            "permission to go live and is not an execution surface."
        ),
    )
    add(EXECUTION_DISABLED_CODE, FindingSeverity.INFO.value, SECTION_INDEX)
    add(
        NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value,
        FindingSeverity.INFO.value,
        "owner_handoff",
    )
    add(
        NextActionCode.BINDER_IS_NOT_GO_LIVE.value,
        FindingSeverity.INFO.value,
        "compliance_evidence_binder",
    )
    add(
        NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT.value,
        FindingSeverity.INFO.value,
        "release_candidate_runbook",
    )
    add(
        NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value,
        FindingSeverity.INFO.value,
        "release_artifact_manifest",
    )
    add(
        NextActionCode.LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION.value,
        FindingSeverity.INFO.value,
        "launch_blockers_plan",
        html_route="/internal/operator-launch-blockers-plan",
        json_route="/internal/launch-blockers-plan",
        command_name="launch-blockers-plan",
        label=(
            "Inspect the launch blockers remediation plan at "
            "/internal/operator-launch-blockers-plan or "
            "/internal/launch-blockers-plan or via `vyro-growth "
            "launch-blockers-plan`. Read-only planning view; it is not "
            "permission to go live and is not an execution surface."
        ),
    )
    add(
        NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value,
        FindingSeverity.INFO.value,
        "staged_rollout_plan",
        html_route="/internal/operator-staged-rollout-plan",
        json_route="/internal/staged-rollout-plan",
        command_name="staged-rollout-plan",
        label=(
            "Inspect the staged go-live rollout plan at "
            "/internal/operator-staged-rollout-plan or "
            "/internal/staged-rollout-plan or via `vyro-growth "
            "staged-rollout-plan`. Read-only staged planning view; it "
            "is not permission to go live and is not an execution surface."
        ),
    )
    add(
        NextActionCode.OWNER_LAUNCH_DOSSIER_IS_NOT_GO_LIVE.value,
        FindingSeverity.INFO.value,
        "owner_launch_dossier",
        html_route="/internal/operator-owner-launch-dossier",
        json_route="/internal/owner-launch-dossier",
        command_name="owner-launch-dossier",
        label=(
            "Inspect the owner launch dossier at "
            "/internal/operator-owner-launch-dossier or "
            "/internal/owner-launch-dossier or via `vyro-growth "
            "owner-launch-dossier`. Read-only owner-review view; it "
            "is not permission to go live and is not an execution surface."
        ),
    )
    add(
        NextActionCode.PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value,
        FindingSeverity.INFO.value,
        "provider_setup_checklist",
        html_route="/internal/operator-provider-setup-checklist",
        json_route="/internal/provider-setup-checklist",
        command_name="provider-setup-checklist",
        label=(
            "Inspect the provider setup checklist at "
            "/internal/operator-provider-setup-checklist or "
            "/internal/provider-setup-checklist or via `vyro-growth "
            "provider-setup-checklist`. Read-only credential/setup "
            "review view; it is not permission to go live and is "
            "not an execution surface."
        ),
    )
    add(
        NextActionCode.GO_LIVE_REHEARSAL_CHECKLIST_IS_NOT_GO_LIVE.value,
        FindingSeverity.INFO.value,
        "go_live_rehearsal_checklist",
        html_route="/internal/operator-go-live-rehearsal-checklist",
        json_route="/internal/go-live-rehearsal-checklist",
        command_name="go-live-rehearsal-checklist",
        label=(
            "Inspect the go-live rehearsal checklist at "
            "/internal/operator-go-live-rehearsal-checklist or "
            "/internal/go-live-rehearsal-checklist or via `vyro-growth "
            "go-live-rehearsal-checklist`. Manual rehearsal review view "
            "only; it is not a script runner, not permission to go live, "
            "and is not an execution surface."
        ),
    )
    add(
        NextActionCode.REHEARSAL_OUTCOME_REPORT_IS_NOT_GO_LIVE.value,
        FindingSeverity.INFO.value,
        "rehearsal_outcome_report",
        html_route="/internal/operator-rehearsal-outcome-report",
        json_route="/internal/rehearsal-outcome-report",
        command_name="rehearsal-outcome-report",
        label=(
            "Inspect the rehearsal outcome report at "
            "/internal/operator-rehearsal-outcome-report or "
            "/internal/rehearsal-outcome-report or via `vyro-growth "
            "rehearsal-outcome-report`. Compact outcome review view "
            "only; it is not permission to go live and is not an "
            "execution surface."
        ),
    )
    add(
        NextActionCode.SUPERVISED_PILOT_PLAN_IS_NOT_GO_LIVE.value,
        FindingSeverity.INFO.value,
        "supervised_pilot_plan",
        html_route="/internal/operator-supervised-pilot-plan",
        json_route="/internal/supervised-pilot-plan",
        command_name="supervised-pilot-plan",
        label=(
            "Inspect the supervised pilot launch plan at "
            "/internal/operator-supervised-pilot-plan or "
            "/internal/supervised-pilot-plan or via `vyro-growth "
            "supervised-pilot-plan`. Supervised pilot planning export "
            "only; it is not permission to go live and is not an "
            "execution surface."
        ),
    )
    add(
        NextActionCode.SUPERVISED_PILOT_CANDIDATES_IS_NOT_GO_LIVE.value,
        FindingSeverity.INFO.value,
        "supervised_pilot_candidates",
        html_route="/internal/operator-supervised-pilot-candidates",
        json_route="/internal/supervised-pilot-candidates",
        command_name="supervised-pilot-candidates",
        label=(
            "Inspect the supervised pilot candidate readiness export at "
            "/internal/operator-supervised-pilot-candidates or "
            "/internal/supervised-pilot-candidates or via `vyro-growth "
            "supervised-pilot-candidates`. Candidate readiness review "
            "only; it is not permission to go live and is not an "
            "execution surface."
        ),
    )
    add(
        NextActionCode.SUPERVISED_PILOT_GO_NO_GO_IS_NOT_GO_LIVE.value,
        FindingSeverity.INFO.value,
        "supervised_pilot_go_no_go",
        html_route="/internal/operator-supervised-pilot-go-no-go",
        json_route="/internal/supervised-pilot-go-no-go",
        command_name="supervised-pilot-go-no-go",
        label=(
            "Inspect the supervised pilot go/no-go packet at "
            "/internal/operator-supervised-pilot-go-no-go or "
            "/internal/supervised-pilot-go-no-go or via `vyro-growth "
            "supervised-pilot-go-no-go`. Go/no-go review view only; "
            "it is not permission to go live and is not an execution "
            "surface."
        ),
    )
    add(
        NextActionCode.SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_IS_NOT_GO_LIVE.value,
        FindingSeverity.INFO.value,
        "supervised_pilot_first_send_preflight",
        html_route="/internal/operator-supervised-pilot-first-send-preflight",
        json_route="/internal/supervised-pilot-first-send-preflight",
        command_name="supervised-pilot-first-send-preflight",
        label=(
            "Inspect the supervised pilot first-send preflight at "
            "/internal/supervised-pilot-first-send-preflight or via "
            "`vyro-growth supervised-pilot-first-send-preflight`. "
            "First-send preflight review only; it is not permission to "
            "send, not permission to go live, and not an execution "
            "surface."
        ),
    )
    for handoff_item in handoff.remaining_manual_owner_checklist:
        add(
            handoff_item.code,
            handoff_item.severity,
            handoff_item.source_section,
            status=handoff_item.status,
        )
    for manifest_item in manifest.remaining_manual_owner_checklist:
        add(
            manifest_item.code,
            manifest_item.severity,
            manifest_item.source_section,
            status=manifest_item.status,
        )
    for action in command_center.next_actions:
        add(
            action.code,
            action.severity,
            action.phase or SECTION_INDEX,
            label=action.label,
        )
    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (-_SEVERITY_RANK.get(item.severity, 0), item.code),
        )
    )


def _routes_for_section(source_section: str) -> tuple[str | None, str | None, str | None]:
    match source_section:
        case "go_live_readiness_index":
            return (HTML_ROUTE, HTTP_ROUTE, CLI_COMMAND)
        case "launch_blockers_plan":
            return (
                "/internal/operator-launch-blockers-plan",
                "/internal/launch-blockers-plan",
                "launch-blockers-plan",
            )
        case "staged_rollout_plan":
            return (
                "/internal/operator-staged-rollout-plan",
                "/internal/staged-rollout-plan",
                "staged-rollout-plan",
            )
        case "owner_launch_dossier":
            return (
                "/internal/operator-owner-launch-dossier",
                "/internal/owner-launch-dossier",
                "owner-launch-dossier",
            )
        case "provider_setup_checklist":
            return (
                "/internal/operator-provider-setup-checklist",
                "/internal/provider-setup-checklist",
                "provider-setup-checklist",
            )
        case "go_live_rehearsal_checklist":
            return (
                "/internal/operator-go-live-rehearsal-checklist",
                "/internal/go-live-rehearsal-checklist",
                "go-live-rehearsal-checklist",
            )
        case "rehearsal_outcome_report":
            return (
                "/internal/operator-rehearsal-outcome-report",
                "/internal/rehearsal-outcome-report",
                "rehearsal-outcome-report",
            )
        case "supervised_pilot_plan":
            return (
                "/internal/operator-supervised-pilot-plan",
                "/internal/supervised-pilot-plan",
                "supervised-pilot-plan",
            )
        case "supervised_pilot_candidates":
            return (
                "/internal/operator-supervised-pilot-candidates",
                "/internal/supervised-pilot-candidates",
                "supervised-pilot-candidates",
            )
        case "supervised_pilot_go_no_go":
            return (
                "/internal/operator-supervised-pilot-go-no-go",
                "/internal/supervised-pilot-go-no-go",
                "supervised-pilot-go-no-go",
            )
        case "supervised_pilot_first_send_preflight":
            return (
                "/internal/operator-supervised-pilot-first-send-preflight",
                "/internal/supervised-pilot-first-send-preflight",
                "supervised-pilot-first-send-preflight",
            )
        case "owner_handoff" | "owner_handoff_packet":
            return (
                "/internal/operator-owner-handoff-packet",
                "/internal/owner-handoff-packet",
                "owner-handoff-packet",
            )
        case "launch_readiness":
            return ("/internal/launch-readiness", "/internal/launch-readiness", "launch-readiness")
        case "settings_execution_preflight" | "settings_change_requests":
            return (
                "/internal/operator-settings-execution-preflight",
                "/internal/settings-execution-preflight",
                "settings-execution-preflight",
            )
        case "compliance_evidence_binder":
            return (
                "/internal/operator-compliance-evidence-binder",
                "/internal/compliance-evidence-binder",
                "compliance-evidence-binder",
            )
        case "release_candidate_runbook":
            return (
                "/internal/operator-release-candidate-runbook",
                "/internal/release-candidate-runbook",
                "release-candidate-runbook",
            )
        case "release_artifact_manifest" | "source_provenance" | "artifact_inventory":
            return (
                "/internal/operator-release-artifact-manifest",
                "/internal/release-artifact-manifest",
                "release-artifact-manifest",
            )
        case "operator_audit_timeline":
            return ("/internal/operator-audit-timeline", None, None)
        case "operator_command_center" | "dashboard":
            return (
                "/internal/operator-dashboard",
                "/internal/operator-command-center",
                "operator-command-center",
            )
        case _:
            return (HTML_ROUTE, None, None)


def _worst_status(*values: str) -> str:
    return max(values, key=lambda item: _STATUS_RANK.get(item, 0))


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    cleaned = [_safe_text(item) for item in values]
    return tuple(sorted({item for item in cleaned if item}))


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    text = sanitize_operator_text(str(value))
    return text or ""


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def index_payload(index: GoLiveReadinessIndex) -> dict[str, Any]:
    return {
        "generated_at": index.generated_at.isoformat(),
        "packet_kind": index.packet_kind,
        "purpose": index.purpose,
        "overall_status": index.overall_status,
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
        "index_is_not_permission_to_go_live": True,
        "handoff_is_not_go_live": True,
        "binder_is_not_go_live": True,
        "runbook_is_not_deployment": True,
        "manifest_is_not_a_build_or_deploy": True,
        "operator_halt_status": index.operator_halt_status,
        "operator_halt_before": index.operator_halt_before,
        "operator_halt_after": index.operator_halt_after,
        "outbound_enabled": index.outbound_enabled,
        "live_providers_enabled": index.live_providers_enabled,
        "closed_provider_flag_names": list(index.closed_provider_flag_names),
        "missing_credential_names": list(index.missing_credential_names),
        "blocker_codes": list(index.blocker_codes),
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "related_commands": list(index.related_commands),
        "related_routes": list(index.related_routes),
        "local_git": {
            "available": index.local_git.available,
            "current_branch": index.local_git.current_branch,
            "current_sha": index.local_git.current_sha,
            "working_tree_status": index.local_git.working_tree_status,
            "git_provider_called": False,
            "github_actions_called": False,
        },
        "surfaces": [
            {
                "key": card.key,
                "label": card.label,
                "html_route": card.html_route,
                "json_route": card.json_route,
                "command_name": card.command_name,
                "overall_status": card.overall_status,
                "counts": [{"label": item.label, "value": item.value} for item in card.counts],
                "blocker_codes": list(card.blocker_codes),
                "flag_states": list(card.flag_states),
            }
            for card in index.surfaces
        ],
        "remaining_manual_owner_checklist": [
            {
                "code": item.code,
                "severity": item.severity,
                "source_section": item.source_section,
                "status": item.status,
                "html_route": item.html_route,
                "json_route": item.json_route,
                "command_name": item.command_name,
                "label": item.label,
            }
            for item in index.remaining_manual_owner_checklist
        ],
    }


def format_go_live_readiness_index(
    index: GoLiveReadinessIndex,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(index_payload(index))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(index, payload)


def _format_markdown(index: GoLiveReadinessIndex, payload: dict[str, Any]) -> str:
    lines = [
        "# Go-live readiness index",
        "",
        "This index is a sanitized owner/operator review export of existing "
        "readiness, evidence, runbook, manifest, and audit surfaces. It is not "
        "permission to go live and is not an execution surface.",
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
        f"- html_route: {HTML_ROUTE}",
        f"- blocker_codes: {_format_codes(index.blocker_codes)}",
        f"- missing_credential_names: {_format_codes(index.missing_credential_names)}",
        f"- closed_provider_flag_names: {_format_codes(index.closed_provider_flag_names)}",
        "",
        "## Live-blocking flags",
        f"- OUTBOUND_ENABLED={_bool_text(index.outbound_enabled)}",
        f"- operator_halt_status={index.operator_halt_status}",
        f"- live_providers_enabled={_bool_text(index.live_providers_enabled)}",
        "- execution_allowed=false",
        "- go_live_permitted=false",
        "- deployment_allowed=false",
        "- build_allowed=false",
        "- artifact_publish_allowed=false",
        "- index_is_not_permission_to_go_live=true",
        f"- local_git_available: {_bool_text(index.local_git.available)}",
        f"- current_branch: {index.local_git.current_branch}",
        f"- current_sha: {index.local_git.current_sha}",
        f"- working_tree_status: {index.local_git.working_tree_status}",
        f"- git_provider_called: {_bool_text(index.local_git.git_provider_called)}",
        f"- github_actions_called: {_bool_text(index.local_git.github_actions_called)}",
        "",
        "## Readiness surfaces",
    ]
    for card in index.surfaces:
        json_route = card.json_route or "-"
        command_name = card.command_name or "-"
        lines.extend(
            [
                f"### {card.label}",
                f"- key: {card.key}",
                f"- overall_status: {card.overall_status}",
                f"- html_route: {card.html_route}",
                f"- json_route: {json_route}",
                f"- command_name: {command_name}",
                f"- counts: {_format_counts(card.counts)}",
                f"- blocker_codes: {_format_codes(card.blocker_codes)}",
                f"- flag_states: {_format_codes(card.flag_states)}",
            ]
        )
    lines.extend(["", "## Remaining unresolved blockers and manual owner checklist"])
    if index.remaining_manual_owner_checklist:
        for item in index.remaining_manual_owner_checklist:
            json_route = item.json_route or "-"
            command_name = item.command_name or "-"
            html_route = item.html_route or "-"
            lines.append(
                f"- [{item.status}] {item.code} severity={item.severity} "
                f"source={item.source_section} html_route={html_route} "
                f"json_route={json_route} command={command_name} label={item.label}"
            )
    else:
        lines.append("- checklist: none")
    return "\n".join(lines)


def _format_counts(values: Sequence[IndexCount]) -> str:
    if not values:
        return "-"
    return "; ".join(f"{item.label}={item.value}" for item in values)


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"
