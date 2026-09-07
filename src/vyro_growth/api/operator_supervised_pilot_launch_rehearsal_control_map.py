"""Read-only operator supervised pilot launch rehearsal control map HTML shell.

Phase 64 renders a sanitized view of the existing Phase 63 supervised
pilot launch rehearsal control map. It reuses
SupervisedPilotLaunchRehearsalControlMapService and never recalculates
readiness. It never executes, builds, publishes, deploys, applies
settings, lifts halt, enables outbound, calls providers, scrapes,
selects candidates, spends, or changes live state. This page is a
control-map review view only, not a script runner, not permission to
send, not permission to go live, and not an execution surface.
"""

from __future__ import annotations

from html import escape

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.operator_ui import (
    COMPLIANCE_EVIDENCE_BINDER_JSON_PATH,
    GO_LIVE_READINESS_INDEX_JSON_PATH,
    GO_LIVE_REHEARSAL_CHECKLIST_JSON_PATH,
    LAUNCH_BLOCKERS_PLAN_JSON_PATH,
    LAUNCH_READINESS_JSON_PATH,
    NO_STORE_HEADERS,
    OPERATOR_AUDIT_TIMELINE_PATH,
    OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
    OPERATOR_DASHBOARD_PATH,
    OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
    OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH,
    OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH,
    OPERATOR_OWNER_HANDOFF_PACKET_PATH,
    OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
    OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH,
    OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH,
    OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
    OPERATOR_RELEASE_CANDIDATE_RUNBOOK_PATH,
    OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
    OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
    OPERATOR_SUPERVISED_PILOT_CANDIDATES_PATH,
    OPERATOR_SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_PATH,
    OPERATOR_SUPERVISED_PILOT_GO_NO_GO_PATH,
    OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH,
    OPERATOR_SUPERVISED_PILOT_PLAN_PATH,
    OPERATOR_UI_STYLES,
    OWNER_HANDOFF_JSON_PATH,
    OWNER_LAUNCH_DOSSIER_JSON_PATH,
    PROVIDER_SETUP_CHECKLIST_JSON_PATH,
    REHEARSAL_OUTCOME_REPORT_JSON_PATH,
    RELEASE_ARTIFACT_MANIFEST_JSON_PATH,
    RELEASE_CANDIDATE_RUNBOOK_JSON_PATH,
    SETTINGS_EXECUTION_PREFLIGHT_JSON_PATH,
    STAGED_ROLLOUT_PLAN_JSON_PATH,
    SUPERVISED_PILOT_CANDIDATES_JSON_PATH,
    SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_JSON_PATH,
    SUPERVISED_PILOT_GO_NO_GO_JSON_PATH,
    SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_JSON_PATH,
    SUPERVISED_PILOT_PLAN_JSON_PATH,
    format_dt,
    html_escape,
    metric,
    render_failure_page,
    render_operator_nav,
    yes_no,
)
from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.supervised_pilot_launch_rehearsal_control_map import (
    ControlCount,
    ControlNextAction,
    ControlNode,
    SupervisedPilotLaunchRehearsalControlMap,
    SupervisedPilotLaunchRehearsalControlMapService,
)

logger = structlog.get_logger(__name__)


def render_supervised_pilot_launch_rehearsal_control_map_error() -> str:
    return render_failure_page(
        page_id="operator-supervised-pilot-launch-rehearsal-control-map-error",
        title="Supervised pilot launch rehearsal control map unavailable",
        heading="Read-only supervised pilot launch rehearsal control map unavailable",
        banner="Unable to load the supervised pilot launch rehearsal control map.",
        detail=(
            "The sanitized launch rehearsal control map review view could "
            "not be rendered. Retry after checking database connectivity "
            "and runtime config. This page is a control-map review view "
            "only, not a script runner, not permission to send, not "
            "permission to go live, and not an execution surface."
        ),
    )


def render_supervised_pilot_launch_rehearsal_control_map(
    packet: SupervisedPilotLaunchRehearsalControlMap,
) -> str:
    generated = html_escape(format_dt(packet.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Supervised pilot launch rehearsal control map</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-supervised-pilot-launch-rehearsal-control-map" '
        'data-read-only="true" data-dry-run-only="true" '
        'data-execution-allowed="false" data-go-live-permitted="false" '
        'data-deployment-allowed="false" data-build-allowed="false" '
        'data-artifact-publish-allowed="false" data-spend-allowed="false" '
        'data-no-execution="true" data-no-go-live="true" '
        'data-no-outbound="true" data-no-provider-calls="true" '
        'data-no-deployment="true" data-no-spend="true" '
        'data-no-first-send="true" data-manual-review-only="true" '
        'data-first-send-allowed="false" data-first-send-attempted="false" '
        'data-supervised-pilot-launch-rehearsal-control-map-is-not-go-live="true" '
        'data-rehearsal-control-map-is-not-a-script-runner="true" '
        'data-control-map-is-not-execution="true" '
        'data-first-send-preflight-is-not-a-send="true" '
        'data-export-is-not-permission-to-go-live="true" '
        'data-export-is-not-execution="true" '
        'data-supervised-pilot-first-send-preflight-is-not-go-live="true" '
        'data-supervised-pilot-go-no-go-is-not-go-live="true" '
        'data-supervised-pilot-plan-is-not-go-live="true" '
        'data-supervised-pilot-candidates-is-not-go-live="true" '
        'data-rehearsal-outcome-report-is-not-go-live="true" '
        'data-go-live-rehearsal-checklist-is-not-go-live="true" '
        'data-provider-setup-checklist-is-not-go-live="true">\n'
        f"{_render_header(packet, generated)}\n"
        f"{render_operator_nav('supervised-pilot-launch-rehearsal-control-map')}\n"
        f"{_render_related_links()}\n"
        f"{_render_live_blocking_flags(packet)}\n"
        f"{_render_source_rollups(packet)}\n"
        f"{_render_candidate_queue_counts(packet)}\n"
        f"{_render_control_counts(packet)}\n"
        f"{_render_expected_safe_assertions(packet)}\n"
        f"{_render_control_nodes(packet)}\n"
        f"{
            _render_codes_section(
                'owner-decision-prerequisites',
                'Owner decision prerequisite codes',
                packet.owner_decision_prerequisites,
                empty='No owner decision prerequisite codes.',
            )
        }\n"
        f"{
            _render_codes_section(
                'remaining-owner-approvals',
                'Remaining owner approval types',
                packet.remaining_owner_approval_types,
                empty='No remaining owner approval types.',
            )
        }\n"
        f"{_render_blocker_gate_codes(packet)}\n"
        f"{_render_missing_names(packet)}\n"
        f"{_render_closed_flags(packet)}\n"
        f"{_render_source_references(packet)}\n"
        f"{_render_related_inventory(packet)}\n"
        f"{_render_local_git(packet.local_git)}\n"
        f"{_render_next_actions(packet.next_actions)}\n"
        f"{_render_footer(packet, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_supervised_pilot_launch_rehearsal_control_map_response(
    db: Session,
    settings: Settings,
    *,
    service: SupervisedPilotLaunchRehearsalControlMapService | None = None,
) -> HTMLResponse:
    try:
        builder = service or SupervisedPilotLaunchRehearsalControlMapService()
        packet = builder.build(db, settings)
        html = render_supervised_pilot_launch_rehearsal_control_map(packet)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception(
            "operator_supervised_pilot_launch_rehearsal_control_map_render_failed",
            read_only=True,
        )
        return HTMLResponse(
            content=render_supervised_pilot_launch_rehearsal_control_map_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(
    packet: SupervisedPilotLaunchRehearsalControlMap, generated: str
) -> str:
    git = packet.local_git
    git_meta = (
        f" · git {html_escape(git.current_branch)}@{html_escape(git.current_sha)}"
        if git.available
        else " · local git unavailable"
    )
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Supervised pilot launch rehearsal control map</h1>\n"
        '        <p class="lede">Read-only owner/operator review view of the '
        "existing supervised pilot launch rehearsal control map. Execution "
        "remains disabled. This page does not scrape, select candidates, "
        "contact, send, call, book, enroll, build, publish, deploy, apply "
        "settings, spend, or lift halt. OUTBOUND_ENABLED=false. "
        "go_live_permitted=false. execution_allowed=false. "
        "first_send_allowed=false. first_send_attempted=false. "
        "first_send_executed=0. sends_executed=0. "
        "deployment_allowed=false. build_allowed=false. "
        "artifact_publish_allowed=false. spend_allowed=false. "
        "owner_approved=false. no_outbound=true. no_provider_calls=true. "
        "no_first_send=true. "
        "supervised_pilot_launch_rehearsal_control_map_is_not_go_live=true. "
        "rehearsal_control_map_is_not_a_script_runner=true. "
        "control_map_is_not_execution=true. "
        "export_is_not_permission_to_go_live=true. "
        "export_is_not_execution=true. This page is a control-map "
        "review view only, not a script runner, not permission to send, "
        "not permission to go live, and not an execution surface.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · overall '
        f"{html_escape(packet.overall_status)} · halt "
        f"{html_escape(packet.operator_halt_status)} · "
        f"{html_escape(packet.packet_kind)} · {html_escape(packet.purpose)}"
        f"{git_meta}</p>\n"
        "    </header>"
    )


def _render_related_links() -> str:
    dashboard_href = escape(OPERATOR_DASHBOARD_PATH)
    index_href = escape(OPERATOR_GO_LIVE_READINESS_INDEX_PATH)
    index_json_href = escape(GO_LIVE_READINESS_INDEX_JSON_PATH)
    blockers_href = escape(OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH)
    blockers_json_href = escape(LAUNCH_BLOCKERS_PLAN_JSON_PATH)
    staged_href = escape(OPERATOR_STAGED_ROLLOUT_PLAN_PATH)
    staged_json_href = escape(STAGED_ROLLOUT_PLAN_JSON_PATH)
    dossier_href = escape(OPERATOR_OWNER_LAUNCH_DOSSIER_PATH)
    dossier_json_href = escape(OWNER_LAUNCH_DOSSIER_JSON_PATH)
    checklist_href = escape(OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH)
    checklist_json_href = escape(PROVIDER_SETUP_CHECKLIST_JSON_PATH)
    rehearsal_href = escape(OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH)
    rehearsal_json_href = escape(GO_LIVE_REHEARSAL_CHECKLIST_JSON_PATH)
    outcome_href = escape(OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH)
    outcome_json_href = escape(REHEARSAL_OUTCOME_REPORT_JSON_PATH)
    plan_href = escape(OPERATOR_SUPERVISED_PILOT_PLAN_PATH)
    plan_json_href = escape(SUPERVISED_PILOT_PLAN_JSON_PATH)
    candidates_href = escape(OPERATOR_SUPERVISED_PILOT_CANDIDATES_PATH)
    candidates_json_href = escape(SUPERVISED_PILOT_CANDIDATES_JSON_PATH)
    go_no_go_href = escape(OPERATOR_SUPERVISED_PILOT_GO_NO_GO_PATH)
    go_no_go_json_href = escape(SUPERVISED_PILOT_GO_NO_GO_JSON_PATH)
    first_send_href = escape(OPERATOR_SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_PATH)
    first_send_json_href = escape(SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_JSON_PATH)
    control_map_json_href = escape(SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_JSON_PATH)
    launch_href = escape(LAUNCH_READINESS_JSON_PATH)
    preflight_href = escape(OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH)
    preflight_json_href = escape(SETTINGS_EXECUTION_PREFLIGHT_JSON_PATH)
    handoff_href = escape(OPERATOR_OWNER_HANDOFF_PACKET_PATH)
    handoff_json_href = escape(OWNER_HANDOFF_JSON_PATH)
    binder_href = escape(OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH)
    binder_json_href = escape(COMPLIANCE_EVIDENCE_BINDER_JSON_PATH)
    runbook_href = escape(OPERATOR_RELEASE_CANDIDATE_RUNBOOK_PATH)
    runbook_json_href = escape(RELEASE_CANDIDATE_RUNBOOK_JSON_PATH)
    manifest_href = escape(OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH)
    manifest_json_href = escape(RELEASE_ARTIFACT_MANIFEST_JSON_PATH)
    timeline_href = escape(OPERATOR_AUDIT_TIMELINE_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Linked readiness surfaces">\n'
        f'      <a class="nav-link" href="{dashboard_href}">Dashboard</a>\n'
        f'      <a class="nav-link" href="{index_href}">Go-live index</a>\n'
        f'      <a class="nav-link" href="{index_json_href}">JSON index</a>\n'
        f'      <a class="nav-link" href="{blockers_href}">Launch blockers</a>\n'
        f'      <a class="nav-link" href="{blockers_json_href}">JSON blockers</a>\n'
        f'      <a class="nav-link" href="{staged_href}">Staged rollout</a>\n'
        f'      <a class="nav-link" href="{staged_json_href}">JSON staged plan</a>\n'
        f'      <a class="nav-link" href="{dossier_href}">Owner launch dossier</a>\n'
        f'      <a class="nav-link" href="{dossier_json_href}">JSON dossier</a>\n'
        f'      <a class="nav-link" href="{checklist_href}">Provider setup</a>\n'
        f'      <a class="nav-link" href="{checklist_json_href}">JSON checklist</a>\n'
        f'      <a class="nav-link" href="{rehearsal_href}">Go-live rehearsal</a>\n'
        f'      <a class="nav-link" href="{rehearsal_json_href}">JSON rehearsal</a>\n'
        f'      <a class="nav-link" href="{outcome_href}">Rehearsal outcome</a>\n'
        f'      <a class="nav-link" href="{outcome_json_href}">JSON outcome</a>\n'
        f'      <a class="nav-link" href="{plan_href}">Supervised pilot</a>\n'
        f'      <a class="nav-link" href="{plan_json_href}">JSON pilot plan</a>\n'
        f'      <a class="nav-link" href="{candidates_href}">Pilot candidates</a>\n'
        f'      <a class="nav-link" href="{candidates_json_href}">JSON candidates</a>\n'
        f'      <a class="nav-link" href="{go_no_go_href}">Pilot go/no-go</a>\n'
        f'      <a class="nav-link" href="{go_no_go_json_href}">JSON go/no-go</a>\n'
        f'      <a class="nav-link" href="{first_send_href}">First-send preflight</a>\n'
        f'      <a class="nav-link" href="{first_send_json_href}">JSON first-send</a>\n'
        f'      <a class="nav-link" href="{control_map_json_href}">JSON control map</a>\n'
        f'      <a class="nav-link" href="{launch_href}">Launch readiness JSON</a>\n'
        f'      <a class="nav-link" href="{preflight_href}">Settings preflight</a>\n'
        f'      <a class="nav-link" href="{preflight_json_href}">JSON preflight</a>\n'
        f'      <a class="nav-link" href="{handoff_href}">Owner handoff</a>\n'
        f'      <a class="nav-link" href="{handoff_json_href}">JSON handoff</a>\n'
        f'      <a class="nav-link" href="{binder_href}">Compliance binder</a>\n'
        f'      <a class="nav-link" href="{binder_json_href}">JSON binder</a>\n'
        f'      <a class="nav-link" href="{runbook_href}">Release runbook</a>\n'
        f'      <a class="nav-link" href="{runbook_json_href}">JSON runbook</a>\n'
        f'      <a class="nav-link" href="{manifest_href}">Release manifest</a>\n'
        f'      <a class="nav-link" href="{manifest_json_href}">JSON manifest</a>\n'
        f'      <a class="nav-link" href="{timeline_href}">Audit timeline</a>\n'
        "    </nav>"
    )


def _render_live_blocking_flags(packet: SupervisedPilotLaunchRehearsalControlMap) -> str:
    halt_unchanged = packet.operator_halt_before == packet.operator_halt_after
    return (
        '    <section class="status-strip" id="live-blocking-flags" '
        'aria-label="Live-blocking flags">\n'
        f"      {metric('Overall', packet.overall_status)}\n"
        f"      {metric('OUTBOUND_ENABLED', yes_no(packet.outbound_enabled))}\n"
        f"      {metric('Operator halt', packet.operator_halt_status)}\n"
        f"      {metric('First send allowed', yes_no(packet.first_send_allowed))}\n"
        f"      {metric('First send attempted', yes_no(packet.first_send_attempted))}\n"
        f"      {metric('First send executed', packet.first_send_executed)}\n"
        f"      {metric('Sends executed', packet.sends_executed)}\n"
        f"      {metric('Go live permitted', yes_no(packet.go_live_permitted))}\n"
        f"      {metric('Execution allowed', yes_no(packet.execution_allowed))}\n"
        f"      {metric('No outbound', yes_no(packet.no_outbound))}\n"
        f"      {metric('No provider calls', yes_no(packet.no_provider_calls))}\n"
        f"      {metric('No first send', yes_no(packet.no_first_send))}\n"
        f"      {
            metric(
                'Control map is not a script runner',
                yes_no(packet.rehearsal_control_map_is_not_a_script_runner),
            )
        }\n"
        f"      {
            metric(
                'Control map is not go-live',
                yes_no(packet.supervised_pilot_launch_rehearsal_control_map_is_not_go_live),
            )
        }\n"
        "    </section>\n"
        '    <section class="panel" id="control-map-flags">\n'
        "      <h2>Read-only flags and halt proof</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Packet kind', packet.packet_kind)}\n"
        f"        {metric('Purpose', packet.purpose)}\n"
        f"        {
            metric(
                'OUTBOUND_ENABLED',
                'false' if not packet.outbound_enabled else 'true',
            )
        }\n"
        f"        {metric('Operator halt', packet.operator_halt_status)}\n"
        f"        {metric('Halt before', packet.operator_halt_before)}\n"
        f"        {metric('Halt after', packet.operator_halt_after)}\n"
        f"        {metric('Halt unchanged', yes_no(halt_unchanged))}\n"
        f"        {metric('Halt changed', yes_no(packet.halt_changed))}\n"
        f"        {metric('Live providers enabled', yes_no(packet.live_providers_enabled))}\n"
        f"        {metric('Settings applied', yes_no(packet.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(packet.owner_approved))}\n"
        f"        {metric('Live action', yes_no(packet.live_action))}\n"
        f"        {metric('Read only', yes_no(packet.read_only))}\n"
        f"        {metric('No execution', yes_no(packet.no_execution))}\n"
        f"        {metric('No go-live', yes_no(packet.no_go_live))}\n"
        f"        {metric('No outbound', yes_no(packet.no_outbound))}\n"
        f"        {metric('No provider calls', yes_no(packet.no_provider_calls))}\n"
        f"        {metric('No deployment', yes_no(packet.no_deployment))}\n"
        f"        {metric('No spend', yes_no(packet.no_spend))}\n"
        f"        {metric('No first send', yes_no(packet.no_first_send))}\n"
        f"        {metric('Dry-run only', yes_no(packet.dry_run_only))}\n"
        f"        {metric('Manual review only', yes_no(packet.manual_review_only))}\n"
        f"        {metric('First send allowed', yes_no(packet.first_send_allowed))}\n"
        f"        {metric('First send attempted', yes_no(packet.first_send_attempted))}\n"
        f"        {metric('First send executed', packet.first_send_executed)}\n"
        f"        {metric('Sends executed', packet.sends_executed)}\n"
        f"        {metric('Spend allowed', yes_no(packet.spend_allowed))}\n"
        f"        {metric('Executed', packet.executed)}\n"
        "      </div>\n"
        '      <p class="hint">Operator halt before and after must match. '
        "This page never shows practice names, provider names, NPI numbers, "
        "street addresses, emails, phones, websites, raw evidence snippets, "
        "message bodies, outreach drafts, PHI, patient data, secret values, "
        "environment values, API keys, tokens, or unsafe error text. "
        "OUTBOUND_ENABLED=false. first_send_allowed=false. "
        "go_live_permitted=false and execution_allowed=false. "
        "spend_allowed=false. This is a read-only control-map "
        "review view, not a script runner, not permission to send, and "
        "not permission to go live.</p>\n"
        "    </section>"
    )


def _render_source_rollups(packet: SupervisedPilotLaunchRehearsalControlMap) -> str:
    return (
        '    <section class="panel" id="source-rollups">\n'
        "      <h2>Source first-send, go/no-go, pilot-plan, and candidate rollups</h2>\n"
        '      <p class="hint">Overall statuses copied from the existing '
        "Phase 63 control map. This page does not recalculate readiness.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Source first-send', packet.source_first_send_overall_status)}\n"
        f"        {metric('Source go/no-go', packet.source_go_no_go_overall_status)}\n"
        f"        {metric('Source pilot plan', packet.source_pilot_plan_overall_status)}\n"
        f"        {metric('Source candidates', packet.source_candidates_overall_status)}\n"
        f"        {metric('Suggested max first sends', packet.suggested_max_first_sends)}\n"
        "      </div>\n"
        "    </section>"
    )


def _render_candidate_queue_counts(packet: SupervisedPilotLaunchRehearsalControlMap) -> str:
    return (
        '    <section class="panel" id="candidate-queue-counts">\n'
        "      <h2>Candidate, review, action, settings, and approval counts</h2>\n"
        '      <p class="hint">Counts only. Practice names, provider names, '
        "NPI numbers, emails, phones, and websites are never shown.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Ready for review count', packet.ready_for_review_count)}\n"
        f"        {metric('Blocked candidate count', packet.blocked_candidate_count)}\n"
        f"        {metric('Total candidate count', packet.total_candidate_count)}\n"
        f"        {metric('Review queue pending count', packet.review_queue_pending_count)}\n"
        f"        {
            metric(
                'Action readiness candidate count',
                packet.action_readiness_candidate_count,
            )
        }\n"
        f"        {metric('Approval packet count', packet.approval_packet_count)}\n"
        f"        {metric('Settings request count', packet.settings_request_count)}\n"
        f"        {
            metric(
                'Settings request pending count',
                packet.settings_request_pending_count,
            )
        }\n"
        "      </div>\n"
        "    </section>"
    )


def _render_control_counts(packet: SupervisedPilotLaunchRehearsalControlMap) -> str:
    return (
        '    <section class="panel" id="control-counts">\n'
        "      <h2>Control counts by category and status</h2>\n"
        '      <p class="hint">Counts and statuses only. This page does not '
        "recalculate readiness.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Blocking control count', packet.blocking_control_count)}\n"
        f"        {metric('Warning control count', packet.warning_control_count)}\n"
        f"        {metric('Info control count', packet.info_control_count)}\n"
        "      </div>\n"
        "      <h3>Counts by category</h3>\n"
        f"      {
            _render_counts(
                packet.control_counts_by_category,
                empty='No control category counts.',
            )
        }\n"
        "      <h3>Counts by status</h3>\n"
        f"      {
            _render_counts(
                packet.control_counts_by_status,
                empty='No control status counts.',
            )
        }\n"
        "    </section>"
    )


def _render_expected_safe_assertions(packet: SupervisedPilotLaunchRehearsalControlMap) -> str:
    return (
        '    <section class="panel" id="expected-safe-assertions">\n'
        "      <h2>Expected safe assertions</h2>\n"
        '      <p class="hint">Pass/fail counts and failed keys only. This '
        "page does not recalculate readiness or execute checks.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Expected count', packet.expected_safe_assertion_count)}\n"
        f"        {metric('Passed', packet.expected_safe_assertions_passed)}\n"
        f"        {metric('Failed', packet.expected_safe_assertions_failed)}\n"
        "      </div>\n"
        "      <h3>Failed safe assertion keys</h3>\n"
        f"      {
            _render_codes(
                packet.failed_safe_assertion_keys,
                empty='No failed safe assertion keys.',
            )
        }\n"
        "    </section>"
    )


def _render_control_nodes(packet: SupervisedPilotLaunchRehearsalControlMap) -> str:
    if not packet.control_nodes:
        body = '<p class="empty-state">No control map rows.</p>'
    else:
        rows = "".join(_node_row(node) for node in packet.control_nodes)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Category</th><th>Status</th><th>Blocking</th>"
            "<th>Command</th><th>Route</th><th>Label</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="control-map-rows">\n'
        "      <h2>Control map rows</h2>\n"
        '      <p class="hint">Codes, categories, statuses, labels, blocking '
        "flags, and related route/command names only. These rows do not "
        "execute or send.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _node_row(node: ControlNode) -> str:
    route = node.html_route or node.json_route
    route_cell = (
        f'<a class="row-link mono" href="{escape(route)}">{html_escape(route)}</a>'
        if route
        else html_escape("—")
    )
    return (
        f'<tr class="{_status_class(node.status)}">'
        f'<td class="mono">{html_escape(node.code)}</td>'
        f'<td class="mono">{html_escape(node.category)}</td>'
        f"<td>{html_escape(node.status)}</td>"
        f"<td>{yes_no(node.blocking)}</td>"
        f'<td class="mono">{html_escape(node.command_name)}</td>'
        f"<td>{route_cell}</td>"
        f"<td>{html_escape(node.label)}</td>"
        "</tr>"
    )


def _render_codes_section(
    section_id: str,
    heading: str,
    codes: tuple[str, ...],
    *,
    empty: str,
) -> str:
    return (
        f'    <section class="panel" id="{escape(section_id)}">\n'
        f"      <h2>{html_escape(heading)}</h2>\n"
        f"      {_render_codes(codes, empty=empty)}\n"
        "    </section>"
    )


def _render_blocker_gate_codes(packet: SupervisedPilotLaunchRehearsalControlMap) -> str:
    return (
        '    <section class="panel" id="blocker-gate-codes">\n'
        "      <h2>Blocker, gate, and blocking control codes</h2>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(packet.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Gate codes</h3>\n"
        f"      {_render_codes(packet.gate_codes, empty='No gate codes.')}\n"
        "      <h3>Blocking control codes</h3>\n"
        f"      {
            _render_codes(
                packet.blocking_control_codes,
                empty='No blocking control codes.',
            )
        }\n"
        "    </section>"
    )


def _render_missing_names(packet: SupervisedPilotLaunchRehearsalControlMap) -> str:
    return (
        '    <section class="panel" id="missing-names">\n'
        "      <h2>Missing credential and config names</h2>\n"
        "      <h3>Missing credential names</h3>\n"
        f"      {_render_codes(packet.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Missing config names</h3>\n"
        f"      {_render_codes(packet.missing_config_names, empty='None missing.')}\n"
        '      <p class="hint">Names only. Values are never shown.</p>\n'
        "    </section>"
    )


def _render_closed_flags(packet: SupervisedPilotLaunchRehearsalControlMap) -> str:
    return (
        '    <section class="panel" id="closed-provider-flags">\n'
        "      <h2>Closed provider and live flag names</h2>\n"
        f"      {_render_codes(packet.closed_provider_flag_names, empty='None closed.')}\n"
        "    </section>"
    )


def _render_source_references(packet: SupervisedPilotLaunchRehearsalControlMap) -> str:
    rows = "".join(
        (
            _source_row(
                "Supervised pilot first-send preflight",
                packet.source_first_send_command,
                packet.source_first_send_route,
                packet.source_first_send_overall_status,
                packet.source_first_send_html_route,
            ),
            _source_row(
                "Supervised pilot go/no-go",
                packet.source_go_no_go_command,
                packet.source_go_no_go_route,
                packet.source_go_no_go_overall_status,
                packet.source_go_no_go_html_route,
            ),
            _source_row(
                "Supervised pilot launch plan",
                packet.source_pilot_plan_command,
                packet.source_pilot_plan_route,
                packet.source_pilot_plan_overall_status,
                packet.source_pilot_plan_html_route,
            ),
            _source_row(
                "Supervised pilot candidates",
                packet.source_candidates_command,
                packet.source_candidates_route,
                packet.source_candidates_overall_status,
                packet.source_candidates_html_route,
            ),
        )
    )
    return (
        '    <section class="panel" id="source-references">\n'
        "      <h2>Source references</h2>\n"
        '      <p class="hint">This page reuses the existing Phase 63 '
        "supervised pilot launch rehearsal control map payload. It does "
        "not recalculate readiness or execute.</p>\n"
        '<table class="dense"><thead><tr>'
        "<th>Source</th><th>Command</th><th>JSON route</th><th>Overall status</th>"
        "<th>HTML route</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        "    </section>"
    )


def _source_row(
    label: str,
    command: str | None,
    json_route: str | None,
    overall_status: str,
    html_route: str | None,
) -> str:
    json_cell = (
        f'<a class="row-link mono" href="{escape(json_route)}">{html_escape(json_route)}</a>'
        if json_route
        else html_escape("—")
    )
    html_cell = (
        f'<a class="row-link mono" href="{escape(html_route)}">{html_escape(html_route)}</a>'
        if html_route
        else html_escape("—")
    )
    return (
        f'<tr class="{_status_class(overall_status)}">'
        f"<td>{html_escape(label)}</td>"
        f'<td class="mono">{html_escape(command)}</td>'
        f"<td>{json_cell}</td>"
        f"<td>{html_escape(overall_status)}</td>"
        f"<td>{html_cell}</td>"
        "</tr>"
    )


def _render_related_inventory(packet: SupervisedPilotLaunchRehearsalControlMap) -> str:
    return (
        '    <section class="panel" id="related-routes">\n'
        "      <h2>Related safe routes</h2>\n"
        f"      {_render_route_links(packet.related_routes, empty='No related routes.')}\n"
        "    </section>\n"
        '    <section class="panel" id="related-commands">\n'
        "      <h2>Related CLI commands</h2>\n"
        f"      {_render_codes(packet.related_commands, empty='No related commands.')}\n"
        "    </section>"
    )


def _render_local_git(git: LocalGitMetadata) -> str:
    return (
        '    <section class="panel" id="local-git">\n'
        "      <h2>Safe local git metadata</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Available', yes_no(git.available))}\n"
        f"        {metric('Current branch', git.current_branch)}\n"
        f"        {metric('Current SHA', git.current_sha)}\n"
        f"        {metric('Working tree', git.working_tree_status)}\n"
        f"        {metric('Git provider called', yes_no(git.git_provider_called))}\n"
        f"        {metric('GitHub Actions called', yes_no(git.github_actions_called))}\n"
        "      </div>\n"
        '      <p class="hint">Local git metadata is branch name and SHA only. '
        "Remotes, commit messages, author emails, and secret values are never "
        "shown. GitHub Actions are not called.</p>\n"
        "    </section>"
    )


def _render_next_actions(actions: tuple[ControlNextAction, ...]) -> str:
    if not actions:
        body = '<p class="empty-state">No owner next steps.</p>'
    else:
        rows = "".join(_next_action_row(action) for action in actions)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Status</th><th>Command</th><th>Route</th>"
            "<th>Config name</th><th>Label</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="owner-next-steps">\n'
        "      <h2>Non-executable owner next steps</h2>\n"
        '      <p class="hint">These labels are review reminders only. They do '
        "not execute, approve, select candidates, contact, apply, deploy, "
        "send, spend, or lift halt.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _next_action_row(action: ControlNextAction) -> str:
    route = action.html_route or action.json_route
    route_cell = (
        f'<a class="row-link mono" href="{escape(route)}">{html_escape(route)}</a>'
        if route
        else html_escape("—")
    )
    return (
        f'<tr class="{_status_class(action.status)}">'
        f'<td class="mono">{html_escape(action.code)}</td>'
        f"<td>{html_escape(action.status)}</td>"
        f'<td class="mono">{html_escape(action.command_name)}</td>'
        f"<td>{route_cell}</td>"
        f'<td class="mono">{html_escape(action.config_name)}</td>'
        f"<td>{html_escape(action.label)}</td>"
        "</tr>"
    )


def _render_footer(packet: SupervisedPilotLaunchRehearsalControlMap, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={yes_no(packet.read_only)}. "
        f"Manual review only={yes_no(packet.manual_review_only)}. "
        f"Dry-run only={yes_no(packet.dry_run_only)}. "
        f"No execution={yes_no(packet.no_execution)}. "
        f"No go-live={yes_no(packet.no_go_live)}. "
        f"No outbound={yes_no(packet.no_outbound)}. "
        f"No provider calls={yes_no(packet.no_provider_calls)}. "
        f"No deployment={yes_no(packet.no_deployment)}. "
        f"No spend={yes_no(packet.no_spend)}. "
        f"No first send={yes_no(packet.no_first_send)}. "
        f"Executed={html_escape(packet.executed)}. "
        f"First send allowed={yes_no(packet.first_send_allowed)}. "
        f"First send attempted={yes_no(packet.first_send_attempted)}. "
        f"First send executed={html_escape(packet.first_send_executed)}. "
        f"Sends executed={html_escape(packet.sends_executed)}. "
        f"Settings applied={yes_no(packet.settings_applied)}. "
        f"Halt changed={yes_no(packet.halt_changed)}. "
        f"Owner approved={yes_no(packet.owner_approved)}. "
        f"Live action={yes_no(packet.live_action)}. "
        f"Execution allowed={yes_no(packet.execution_allowed)}. "
        f"Go live permitted={yes_no(packet.go_live_permitted)}. "
        f"Deployment allowed={yes_no(packet.deployment_allowed)}. "
        f"Build allowed={yes_no(packet.build_allowed)}. "
        f"Artifact publish allowed={yes_no(packet.artifact_publish_allowed)}. "
        f"Spend allowed={yes_no(packet.spend_allowed)}. "
        f"Supervised pilot launch rehearsal control map is not go-live="
        f"{yes_no(packet.supervised_pilot_launch_rehearsal_control_map_is_not_go_live)}. "
        f"Rehearsal control map is not a script runner="
        f"{yes_no(packet.rehearsal_control_map_is_not_a_script_runner)}. "
        f"Control map is not execution={yes_no(packet.control_map_is_not_execution)}. "
        f"First-send preflight is not a send="
        f"{yes_no(packet.first_send_preflight_is_not_a_send)}. "
        f"Export is not permission to go live="
        f"{yes_no(packet.export_is_not_permission_to_go_live)}. "
        f"Export is not execution={yes_no(packet.export_is_not_execution)}. "
        f"Supervised pilot first-send preflight is not go-live="
        f"{yes_no(packet.supervised_pilot_first_send_preflight_is_not_go_live)}. "
        f"Supervised pilot go/no-go is not go-live="
        f"{yes_no(packet.supervised_pilot_go_no_go_is_not_go_live)}. "
        f"Supervised pilot plan is not go-live="
        f"{yes_no(packet.supervised_pilot_plan_is_not_go_live)}. "
        f"Supervised pilot candidates is not go-live="
        f"{yes_no(packet.supervised_pilot_candidates_is_not_go_live)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "build, publish, deploy, campaign, booking, call, spend, candidate "
        "selection, send, or contact controls on this page. This is a "
        "read-only control-map review view, not a script runner, not "
        "permission to send, not permission to go live, and not an "
        "execution surface. Current route "
        f"{html_escape(OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH)}.</p>\n"
        "    </footer>"
    )


def _render_counts(items: tuple[ControlCount, ...], *, empty: str) -> str:
    present = [item for item in items if item.key]
    if not present:
        return f'<p class="empty-state">{escape(empty)}</p>'
    rows = "".join(
        (
            "<tr>"
            f'<td class="mono">{html_escape(item.key)}</td>'
            f"<td>{html_escape(item.count)}</td>"
            "</tr>"
        )
        for item in present
    )
    return (
        '<table class="dense"><thead><tr>'
        "<th>Key</th><th>Count</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _render_codes(codes: tuple[str, ...] | list[str], *, empty: str) -> str:
    unique = [code for code in dict.fromkeys(codes) if code]
    if not unique:
        return f'<p class="empty-state">{escape(empty)}</p>'
    rows = "".join(f'<li class="mono">{html_escape(code)}</li>' for code in unique)
    return f'<ul class="plain">{rows}</ul>'


def _render_route_links(routes: tuple[str, ...] | list[str], *, empty: str) -> str:
    unique = [route for route in dict.fromkeys(routes) if route]
    if not unique:
        return f'<p class="empty-state">{escape(empty)}</p>'
    rows = "".join(
        f'<li class="mono"><a class="row-link" href="{escape(route)}">{html_escape(route)}</a></li>'
        for route in unique
    )
    return f'<ul class="plain">{rows}</ul>'


def _status_class(status: str) -> str:
    match status:
        case FindingSeverity.BLOCKED.value | "closed" | "missing":
            return "severity-blocked"
        case FindingSeverity.WARNING.value:
            return "severity-warning"
        case FindingSeverity.INFO.value | "ready_for_owner_review" | "open":
            return "severity-info"
        case _:
            return "severity-info"
