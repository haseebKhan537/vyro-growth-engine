"""Read-only operator supervised pilot candidate readiness HTML shell.

Phase 58 renders a sanitized view of the existing Phase 57 supervised
pilot candidate readiness export. It reuses SupervisedPilotCandidateService
and never recalculates candidate readiness. It never executes, builds,
publishes, deploys, applies settings, lifts halt, enables outbound, calls
providers, scrapes, selects candidates, spends, or changes live state.
This page is a candidate readiness review view only, not permission to
go live and not an execution surface.
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
from vyro_growth.services.supervised_pilot_candidates import (
    CandidateCount,
    CandidateNextAction,
    CandidateScopeRecommendation,
    SupervisedPilotCandidates,
    SupervisedPilotCandidateService,
)

logger = structlog.get_logger(__name__)


def render_supervised_pilot_candidates_error() -> str:
    return render_failure_page(
        page_id="operator-supervised-pilot-candidates-error",
        title="Supervised pilot candidate readiness unavailable",
        heading="Read-only supervised pilot candidate readiness unavailable",
        banner="Unable to load the supervised pilot candidate readiness export.",
        detail=(
            "The sanitized candidate-readiness review view could not be "
            "rendered. Retry after checking database connectivity and "
            "runtime config. This page is a candidate readiness review "
            "view only, not permission to go live and not an execution "
            "surface."
        ),
    )


def render_supervised_pilot_candidates(packet: SupervisedPilotCandidates) -> str:
    generated = html_escape(format_dt(packet.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Supervised pilot candidate readiness</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-supervised-pilot-candidates" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-go-live-permitted="false" data-deployment-allowed="false" '
        'data-build-allowed="false" data-artifact-publish-allowed="false" '
        'data-spend-allowed="false" data-no-execution="true" '
        'data-no-go-live="true" data-no-outbound="true" '
        'data-no-provider-calls="true" data-no-deployment="true" '
        'data-no-spend="true" data-manual-review-only="true" '
        'data-supervised-pilot-candidates-is-not-go-live="true" '
        'data-export-is-not-permission-to-go-live="true" '
        'data-export-is-not-execution="true" '
        'data-supervised-pilot-plan-is-not-go-live="true" '
        'data-rehearsal-outcome-report-is-not-go-live="true" '
        'data-go-live-rehearsal-checklist-is-not-go-live="true" '
        'data-provider-setup-checklist-is-not-go-live="true">\n'
        f"{_render_header(packet, generated)}\n"
        f"{render_operator_nav('supervised-pilot-candidates')}\n"
        f"{_render_related_links()}\n"
        f"{_render_live_blocking_flags(packet)}\n"
        f"{_render_candidate_scope(packet.candidate_scope)}\n"
        f"{_render_bucket_sections(packet)}\n"
        f"{_render_suppression_kill_switch(packet)}\n"
        f"{
            _render_codes_section(
                'missing-prerequisite-codes',
                'Missing prerequisite codes',
                packet.missing_prerequisite_codes,
                empty='No missing prerequisite codes.',
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


def build_operator_supervised_pilot_candidates_response(
    db: Session,
    settings: Settings,
    *,
    service: SupervisedPilotCandidateService | None = None,
) -> HTMLResponse:
    try:
        builder = service or SupervisedPilotCandidateService()
        packet = builder.build(db, settings)
        html = render_supervised_pilot_candidates(packet)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception(
            "operator_supervised_pilot_candidates_render_failed",
            read_only=True,
        )
        return HTMLResponse(
            content=render_supervised_pilot_candidates_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(packet: SupervisedPilotCandidates, generated: str) -> str:
    git = packet.local_git
    git_meta = (
        f" · git {html_escape(git.current_branch)}@{html_escape(git.current_sha)}"
        if git.available
        else " · local git unavailable"
    )
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Supervised pilot candidate readiness</h1>\n"
        '        <p class="lede">Read-only owner/operator review view of the '
        "existing supervised pilot candidate readiness export. Execution "
        "remains disabled. This page does not scrape, select candidates, "
        "contact, send, call, book, enroll, build, publish, deploy, apply "
        "settings, spend, or lift halt. OUTBOUND_ENABLED=false. "
        "go_live_permitted=false. execution_allowed=false. "
        "deployment_allowed=false. build_allowed=false. "
        "artifact_publish_allowed=false. spend_allowed=false. "
        "owner_approved=false. no_outbound=true. no_provider_calls=true. "
        "supervised_pilot_candidates_is_not_go_live=true. "
        "export_is_not_permission_to_go_live=true. "
        "export_is_not_execution=true. This page is a candidate readiness "
        "review view only, not permission to go live and not an execution "
        "surface.</p>\n"
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
    candidates_json_href = escape(SUPERVISED_PILOT_CANDIDATES_JSON_PATH)
    go_no_go_href = escape(OPERATOR_SUPERVISED_PILOT_GO_NO_GO_PATH)
    first_send_href = escape(OPERATOR_SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_PATH)
    control_map_href = escape(OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH)
    go_no_go_json_href = escape(SUPERVISED_PILOT_GO_NO_GO_JSON_PATH)
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
        f'      <a class="nav-link" href="{candidates_json_href}">JSON candidates</a>\n'
        f'      <a class="nav-link" href="{go_no_go_href}">Pilot go/no-go</a>\n'
        f'      <a class="nav-link" href="{go_no_go_json_href}">JSON go/no-go</a>\n'
        f'      <a class="nav-link" href="{first_send_href}">First-send preflight</a>\n'
        f'      <a class="nav-link" href="{first_send_json_href}">JSON first-send</a>\n'
        f'      <a class="nav-link" href="{control_map_href}">Rehearsal control map</a>\n'
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


def _render_live_blocking_flags(packet: SupervisedPilotCandidates) -> str:
    halt_unchanged = packet.operator_halt_before == packet.operator_halt_after
    return (
        '    <section class="status-strip" id="live-blocking-flags" '
        'aria-label="Live-blocking flags">\n'
        f"      {metric('Overall', packet.overall_status)}\n"
        f"      {metric('OUTBOUND_ENABLED', yes_no(packet.outbound_enabled))}\n"
        f"      {metric('Operator halt', packet.operator_halt_status)}\n"
        f"      {metric('Live providers', yes_no(packet.live_providers_enabled))}\n"
        f"      {metric('Go live permitted', yes_no(packet.go_live_permitted))}\n"
        f"      {metric('Execution allowed', yes_no(packet.execution_allowed))}\n"
        f"      {metric('Deployment allowed', yes_no(packet.deployment_allowed))}\n"
        f"      {metric('Build allowed', yes_no(packet.build_allowed))}\n"
        f"      {metric('Artifact publish allowed', yes_no(packet.artifact_publish_allowed))}\n"
        f"      {metric('Spend allowed', yes_no(packet.spend_allowed))}\n"
        f"      {metric('No outbound', yes_no(packet.no_outbound))}\n"
        f"      {metric('No provider calls', yes_no(packet.no_provider_calls))}\n"
        f"      {
            metric(
                'Supervised pilot candidates is not go-live',
                yes_no(packet.supervised_pilot_candidates_is_not_go_live),
            )
        }\n"
        f"      {
            metric(
                'Export is not permission to go live',
                yes_no(packet.export_is_not_permission_to_go_live),
            )
        }\n"
        f"      {metric('Export is not execution', yes_no(packet.export_is_not_execution))}\n"
        "    </section>\n"
        '    <section class="panel" id="candidate-gates">\n'
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
        f"        {metric('Dry-run only', yes_no(packet.dry_run_only))}\n"
        f"        {metric('Manual review only', yes_no(packet.manual_review_only))}\n"
        f"        {metric('Spend allowed', yes_no(packet.spend_allowed))}\n"
        f"        {metric('Executed', packet.executed)}\n"
        "      </div>\n"
        '      <p class="hint">Operator halt before and after must match. '
        "This page never shows practice names, provider names, NPI numbers, "
        "street addresses, emails, phones, websites, raw evidence snippets, "
        "message bodies, outreach drafts, PHI, patient data, secret values, "
        "environment values, API keys, tokens, or unsafe error text. "
        "OUTBOUND_ENABLED=false. go_live_permitted=false and "
        "execution_allowed=false. spend_allowed=false. This is a read-only "
        "candidate readiness review view, not permission to go live.</p>\n"
        "    </section>"
    )


def _render_candidate_scope(scope: CandidateScopeRecommendation) -> str:
    return (
        '    <section class="panel" id="candidate-scope">\n'
        "      <h2>Safe count-only candidate scope</h2>\n"
        '      <p class="hint">Planning counts only. These limits do not '
        "select, enroll, send, spend, scrape, or execute.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Suggested candidate count', scope.suggested_candidate_count)}\n"
        f"        {metric('Suggested max leads', scope.suggested_max_leads)}\n"
        f"        {metric('Suggested max drafts', scope.suggested_max_drafts)}\n"
        f"        {
            metric(
                'Suggested max manually reviewed sends',
                scope.suggested_max_manually_reviewed_sends,
            )
        }\n"
        f"        {metric('Suggested max daily activity', scope.suggested_max_daily_activity)}\n"
        f"        {metric('Ready for review count', scope.ready_for_review_count)}\n"
        f"        {metric('Blocked candidate count', scope.blocked_candidate_count)}\n"
        f"        {metric('Total candidate count', scope.total_candidate_count)}\n"
        "      </div>\n"
        "      <h3>Stop conditions</h3>\n"
        f"      {_render_codes(scope.stop_conditions, empty='No stop conditions.')}\n"
        f'      <p class="hint">{html_escape(scope.recommendation_summary)}</p>\n'
        "    </section>"
    )


def _render_bucket_sections(packet: SupervisedPilotCandidates) -> str:
    sections = (
        (
            "counts-by-readiness",
            "Candidate counts by readiness",
            packet.candidate_counts_by_readiness,
        ),
        (
            "counts-by-status",
            "Candidate counts by status",
            packet.candidate_counts_by_status,
        ),
        (
            "counts-by-stage",
            "Candidate counts by stage",
            packet.candidate_counts_by_stage,
        ),
        (
            "counts-by-source",
            "Candidate counts by source",
            packet.candidate_counts_by_source,
        ),
        (
            "counts-by-specialty",
            "Candidate counts by specialty category",
            packet.candidate_counts_by_specialty,
        ),
        (
            "counts-by-state",
            "Candidate counts by state",
            packet.candidate_counts_by_state,
        ),
        (
            "scoring-distribution",
            "Scoring distribution counts",
            packet.scoring_distribution,
        ),
        (
            "website-match-counts",
            "Website match counts",
            packet.website_match_counts,
        ),
        (
            "outreach-status-counts",
            "Outreach status counts",
            packet.outreach_status_counts,
        ),
        (
            "blocked-counts",
            "Blocked counts by generic reason",
            packet.blocked_counts,
        ),
    )
    return "\n".join(
        _render_count_section(section_id, heading, items) for section_id, heading, items in sections
    )


def _render_count_section(
    section_id: str,
    heading: str,
    items: tuple[CandidateCount, ...],
) -> str:
    return (
        f'    <section class="panel" id="{escape(section_id)}">\n'
        f"      <h2>{html_escape(heading)}</h2>\n"
        '      <p class="hint">Safe keys and counts only. Practice names, '
        "provider names, NPI numbers, emails, phones, websites, and raw "
        "evidence are never shown.</p>\n"
        f"      {_render_counts(items, empty='No counts in this bucket.')}\n"
        "    </section>"
    )


def _render_suppression_kill_switch(packet: SupervisedPilotCandidates) -> str:
    return (
        '    <section class="panel" id="suppression-kill-switch">\n'
        "      <h2>Suppression and kill-switch status rollups</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {
            metric(
                'Kill switch outbound disabled',
                yes_no(packet.kill_switch_outbound_disabled),
            )
        }\n"
        f"        {
            metric(
                'Kill switch operator halt active',
                yes_no(packet.kill_switch_operator_halt_active),
            )
        }\n"
        f"        {
            metric(
                'Kill switch live providers closed',
                yes_no(packet.kill_switch_live_providers_closed),
            )
        }\n"
        f"        {metric('Suppression record count', packet.suppression_record_count)}\n"
        "      </div>\n"
        "      <h3>Suppression counts by reason</h3>\n"
        f"      {
            _render_counts(
                packet.suppression_counts_by_reason,
                empty='No suppression reason counts.',
            )
        }\n"
        '      <p class="hint">Generic reasons and counts only. This page '
        "does not lift halt, enable outbound, or contact anyone.</p>\n"
        "    </section>"
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


def _render_blocker_gate_codes(packet: SupervisedPilotCandidates) -> str:
    return (
        '    <section class="panel" id="blocker-gate-codes">\n'
        "      <h2>Blocker and gate code rollups</h2>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(packet.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Gate codes</h3>\n"
        f"      {_render_codes(packet.gate_codes, empty='No gate codes.')}\n"
        "    </section>"
    )


def _render_missing_names(packet: SupervisedPilotCandidates) -> str:
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


def _render_closed_flags(packet: SupervisedPilotCandidates) -> str:
    return (
        '    <section class="panel" id="closed-provider-flags">\n'
        "      <h2>Closed provider and live flag names</h2>\n"
        f"      {_render_codes(packet.closed_provider_flag_names, empty='None closed.')}\n"
        "    </section>"
    )


def _render_source_references(packet: SupervisedPilotCandidates) -> str:
    rows = "".join(
        (
            _source_row(
                "Supervised pilot launch plan",
                packet.source_pilot_plan_command,
                packet.source_pilot_plan_route,
                packet.source_pilot_plan_overall_status,
                packet.source_pilot_plan_html_route,
            ),
            _source_row(
                "Rehearsal outcome report",
                packet.source_outcome_command,
                packet.source_outcome_route,
                packet.source_outcome_overall_status,
                OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH,
            ),
            _source_row(
                "Go-live rehearsal checklist",
                packet.source_rehearsal_command,
                packet.source_rehearsal_route,
                packet.source_rehearsal_overall_status,
                OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH,
            ),
            _source_row(
                "Launch readiness",
                packet.source_launch_readiness_command,
                packet.source_launch_readiness_route,
                packet.source_launch_readiness_overall_status,
                LAUNCH_READINESS_JSON_PATH,
            ),
            _source_row(
                "Go-live readiness index",
                packet.source_index_command,
                packet.source_index_route,
                packet.source_index_overall_status,
                OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
            ),
            _source_row(
                "Provider setup checklist",
                packet.source_provider_setup_command,
                packet.source_provider_setup_route,
                packet.source_provider_setup_overall_status,
                OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH,
            ),
        )
    )
    return (
        '    <section class="panel" id="source-references">\n'
        "      <h2>Source references</h2>\n"
        '      <p class="hint">This page reuses the existing Phase 57 '
        "supervised pilot candidate readiness payload. It does not "
        "recalculate candidate readiness or execute.</p>\n"
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


def _render_related_inventory(packet: SupervisedPilotCandidates) -> str:
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


def _render_next_actions(actions: tuple[CandidateNextAction, ...]) -> str:
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
        "spend, or lift halt.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _next_action_row(action: CandidateNextAction) -> str:
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


def _render_footer(packet: SupervisedPilotCandidates, generated: str) -> str:
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
        f"Executed={html_escape(packet.executed)}. "
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
        f"Supervised pilot candidates is not go-live="
        f"{yes_no(packet.supervised_pilot_candidates_is_not_go_live)}. "
        f"Export is not permission to go live="
        f"{yes_no(packet.export_is_not_permission_to_go_live)}. "
        f"Export is not execution={yes_no(packet.export_is_not_execution)}. "
        f"Supervised pilot plan is not go-live="
        f"{yes_no(packet.supervised_pilot_plan_is_not_go_live)}. "
        f"Rehearsal outcome report is not go-live="
        f"{yes_no(packet.rehearsal_outcome_report_is_not_go_live)}. "
        f"Go-live rehearsal checklist is not go-live="
        f"{yes_no(packet.go_live_rehearsal_checklist_is_not_go_live)}. "
        f"Provider setup checklist is not go-live="
        f"{yes_no(packet.provider_setup_checklist_is_not_go_live)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "build, publish, deploy, campaign, booking, call, spend, candidate "
        "selection, or contact controls on this page. This is a read-only "
        "candidate readiness review view, not permission to go live and not "
        "an execution surface. Current route "
        f"{html_escape(OPERATOR_SUPERVISED_PILOT_CANDIDATES_PATH)}.</p>\n"
        "    </footer>"
    )


def _render_counts(items: tuple[CandidateCount, ...], *, empty: str) -> str:
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
