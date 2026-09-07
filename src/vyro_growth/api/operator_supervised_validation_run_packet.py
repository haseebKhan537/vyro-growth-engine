"""Read-only operator supervised validation run-packet HTML shell.

Phase 74 renders a sanitized view of the existing Phase 73 supervised
validation owner approval/run packet. It reuses
SupervisedValidationRunPacketService and never recalculates funnel
readiness. It never executes supervised validation, grants approval,
calls providers, selects or contacts prospects, sends email, enrolls
campaigns, places calls, books meetings, spends money, publishes,
deploys, applies settings, lifts halt, or enables outbound. This page
is an aggregate-only review view, not permission to run a supervised
200-practice validation and not an execution surface.
"""

from __future__ import annotations

from html import escape
from urllib.parse import urlencode

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.operator_ui import (
    CONTACT_VALIDATION_PLAN_JSON_PATH,
    CONTACT_VALIDATION_REPORT_JSON_PATH,
    NO_STORE_HEADERS,
    OPERATOR_CONTACT_VALIDATION_PATH,
    OPERATOR_DASHBOARD_PATH,
    OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH,
    OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH,
    OPERATOR_UI_STYLES,
    SUPERVISED_VALIDATION_RUN_PACKET_JSON_PATH,
    filter_link,
    format_dt,
    html_escape,
    metric,
    render_failure_page,
    render_operator_nav,
    yes_no,
)
from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity
from vyro_growth.services.contact_validation import (
    DEFAULT_COHORT_SIZE,
    MAX_COHORT_SIZE,
    ContactValidationError,
    ContactValidationFilters,
    ContactValidationStage,
    OwnerReviewThreshold,
    ThresholdComparison,
)
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.supervised_validation_run_packet import (
    NamedPresence,
    OwnerDecisionItem,
    OwnerNextStep,
    PrerequisiteItem,
    StatusCount,
    SupervisedValidationRunPacket,
    SupervisedValidationRunPacketService,
)

logger = structlog.get_logger(__name__)
COHORT_SIZE_PRESETS: tuple[int, ...] = (50, 100, 200)


def render_operator_supervised_validation_run_packet_error(
    *,
    invalid_filter: bool = False,
) -> str:
    if invalid_filter:
        detail = (
            "A query filter was rejected. Use a two-letter state code, "
            "safe city/specialty text, and max_cohort_size from 1 to 200. "
            "This page is an aggregate-only review view, not permission to "
            "run a supervised validation and not an execution surface."
        )
        banner = "Supervised validation run packet filters were rejected."
        heading = "Read-only supervised validation run packet filters rejected"
    else:
        detail = (
            "The sanitized supervised validation owner approval/run packet "
            "review view could not be rendered. Retry after checking "
            "database connectivity and runtime config. This page is an "
            "aggregate-only review view, not permission to run a supervised "
            "validation and not an execution surface."
        )
        banner = "Unable to load the operator supervised validation run packet."
        heading = "Read-only supervised validation run packet unavailable"
    return render_failure_page(
        page_id="operator-supervised-validation-run-packet-error",
        title="Operator supervised validation run packet unavailable",
        heading=heading,
        banner=banner,
        detail=detail,
    )


def render_operator_supervised_validation_run_packet(
    packet: SupervisedValidationRunPacket,
) -> str:
    generated = html_escape(format_dt(packet.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Operator supervised validation run packet</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-supervised-validation-run-packet" '
        'data-read-only="true" data-dry-run-only="true" '
        'data-execution-allowed="false" data-no-execution="true" '
        'data-no-outbound="true" data-no-provider-calls="true" '
        'data-no-send="true" data-no-call="true" data-no-book="true" '
        'data-no-spend="true" data-no-deploy="true" '
        'data-no-autodial="true" data-no-ai-voice="true" '
        'data-manual-review-only="true" '
        'data-contact-validation-is-not-outbound="true" '
        'data-contact-validation-is-not-live-send="true" '
        'data-supervised-validation-run-packet-is-not-execution="true" '
        'data-export-is-not-permission-to-run="true" '
        'data-supervised-validation-run-permitted="false" '
        'data-owner-approved="false" '
        'data-no-contact-found-is-failure="false">\n'
        f"{_render_header(packet, generated)}\n"
        f"{render_operator_nav('supervised-validation-run-packet')}\n"
        f"{_render_related_links()}\n"
        f"{_render_filters(packet)}\n"
        f"{_render_live_blocking_flags(packet)}\n"
        f"{_render_segment(packet)}\n"
        f"{_render_prerequisites(packet.prerequisites)}\n"
        f"{_render_owner_decisions(packet.required_owner_decisions)}\n"
        f"{_render_credentials_and_configs(packet)}\n"
        f"{_render_planned_stages(packet.planned_stages)}\n"
        f"{_render_funnel(packet)}\n"
        f"{_render_threshold_comparisons(packet.threshold_comparisons)}\n"
        f"{_render_owner_review_thresholds(packet.owner_review_thresholds)}\n"
        f"{_render_outcome_summaries(packet)}\n"
        f"{_render_status_counts(packet)}\n"
        f"{_render_related_inventory(packet)}\n"
        f"{_render_local_git(packet.local_git)}\n"
        f"{_render_next_actions(packet.next_actions)}\n"
        f"{_render_footer(packet, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_supervised_validation_run_packet_response(
    db: Session,
    settings: Settings,
    *,
    filters: ContactValidationFilters | None = None,
    service: SupervisedValidationRunPacketService | None = None,
) -> HTMLResponse:
    try:
        builder = service or SupervisedValidationRunPacketService()
        packet = builder.build(db, settings, filters)
        html = render_operator_supervised_validation_run_packet(packet)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except ContactValidationError:
        logger.info(
            "operator_supervised_validation_run_packet_invalid_filter",
            read_only=True,
        )
        return HTMLResponse(
            content=render_operator_supervised_validation_run_packet_error(
                invalid_filter=True
            ),
            status_code=400,
            headers=NO_STORE_HEADERS,
        )
    except Exception:
        logger.exception(
            "operator_supervised_validation_run_packet_render_failed",
            read_only=True,
        )
        return HTMLResponse(
            content=render_operator_supervised_validation_run_packet_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(packet: SupervisedValidationRunPacket, generated: str) -> str:
    git = packet.local_git
    git_meta = (
        f" · git {html_escape(git.current_branch)}@{html_escape(git.current_sha)}"
        if git.available
        else " · local git unavailable"
    )
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Operator supervised validation run packet</h1>\n"
        '        <p class="lede">Read-only aggregate view of the Phase 73 '
        "supervised validation owner approval/run packet. This page reuses "
        "SupervisedValidationRunPacketService and does not execute the run, "
        "grant approval, call providers, select or contact prospects, send "
        "email, enroll campaigns, place calls, autodial, use AI voice, book "
        "meetings, create Meet links, launch ads, spend, publish, deploy, "
        "apply settings, or lift halt. OUTBOUND_ENABLED=false. "
        "execution_allowed=false. owner_approved=false. "
        "supervised_validation_run_permitted=false. "
        "no_outbound=true. no_provider_calls=true. no_send=true. "
        "no_call=true. no_book=true. no_spend=true. no_deploy=true. "
        "contact_validation_is_not_outbound=true. "
        "contact_validation_is_not_live_send=true. "
        "supervised_validation_run_packet_is_not_execution=true. "
        "export_is_not_permission_to_run=true. NO_CONTACT_FOUND is a normal "
        "outcome. NO_VERIFIED_EMAIL is a normal outcome. This page is an "
        "aggregate-only review view, not permission to run a supervised "
        "200-practice validation and not an execution surface.</p>\n"
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
    packet_json_href = escape(SUPERVISED_VALIDATION_RUN_PACKET_JSON_PATH)
    contact_href = escape(OPERATOR_CONTACT_VALIDATION_PATH)
    plan_json_href = escape(CONTACT_VALIDATION_PLAN_JSON_PATH)
    report_json_href = escape(CONTACT_VALIDATION_REPORT_JSON_PATH)
    metrics_href = escape("/internal/contact-enrichment/metrics")
    email_metrics_href = escape("/internal/email-verification/metrics")
    phone_href = escape("/internal/phone-verification/tasks")
    control_map_href = escape(OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Linked readiness surfaces">\n'
        f'      <a class="nav-link" href="{dashboard_href}">Dashboard</a>\n'
        f'      <a class="nav-link" href="{packet_json_href}">JSON run packet</a>\n'
        f'      <a class="nav-link" href="{contact_href}">Contact validation</a>\n'
        f'      <a class="nav-link" href="{plan_json_href}">JSON plan</a>\n'
        f'      <a class="nav-link" href="{report_json_href}">JSON report</a>\n'
        f'      <a class="nav-link" href="{metrics_href}">Contact metrics JSON</a>\n'
        f'      <a class="nav-link" href="{email_metrics_href}">Email metrics JSON</a>\n'
        f'      <a class="nav-link" href="{phone_href}">Phone verification JSON</a>\n'
        f'      <a class="nav-link" href="{control_map_href}">Rehearsal control map</a>\n'
        "    </nav>"
    )


def _render_filters(packet: SupervisedValidationRunPacket) -> str:
    links = [
        filter_link(
            _filter_href(packet, max_cohort_size=size),
            f"max {size}",
            current=packet.max_cohort_size == size,
        )
        for size in COHORT_SIZE_PRESETS
        if 1 <= size <= MAX_COHORT_SIZE
    ]
    return (
        '    <nav class="filter-nav" aria-label="Safe cohort size filters">\n'
        f'      {" ".join(links)}\n'
        "    </nav>"
    )


def _filter_href(packet: SupervisedValidationRunPacket, *, max_cohort_size: int) -> str:
    params: dict[str, str] = {}
    if packet.segment_state:
        params["state"] = packet.segment_state
    if packet.segment_city:
        params["city"] = packet.segment_city
    if packet.segment_specialty:
        params["specialty"] = packet.segment_specialty
    elif packet.segment_taxonomy_description:
        params["taxonomy_description"] = packet.segment_taxonomy_description
    if max_cohort_size != DEFAULT_COHORT_SIZE:
        params["max_cohort_size"] = str(max_cohort_size)
    if not params:
        return OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH
    return f"{OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH}?{urlencode(params)}"


def _render_live_blocking_flags(packet: SupervisedValidationRunPacket) -> str:
    live_flag_rows = "".join(
        (
            "<tr>"
            f'<td class="mono">{html_escape(name)}</td>'
            f"<td>{yes_no(enabled)}</td>"
            "</tr>"
        )
        for name, enabled in packet.live_providers.items()
    )
    live_flags_body = (
        '<table class="dense"><thead><tr><th>Flag</th><th>Enabled</th>'
        f"</tr></thead><tbody>{live_flag_rows}</tbody></table>"
        if live_flag_rows
        else '<p class="empty-state">No live-provider flags.</p>'
    )
    return (
        '    <section class="status-strip" id="live-blocking-flags" '
        'aria-label="Live-blocking flags">\n'
        f"      {metric('Overall', packet.overall_status)}\n"
        f"      {metric('Packet kind', packet.packet_kind)}\n"
        f"      {metric('Purpose', packet.purpose)}\n"
        f"      {metric('OUTBOUND_ENABLED', yes_no(packet.outbound_enabled))}\n"
        f"      {metric('Operator halt', packet.operator_halt_status)}\n"
        f"      {metric('Execution allowed', yes_no(packet.execution_allowed))}\n"
        f"      {metric('Owner approved', yes_no(packet.owner_approved))}\n"
        f"      {metric('No outbound', yes_no(packet.no_outbound))}\n"
        f"      {metric('No provider calls', yes_no(packet.no_provider_calls))}\n"
        f"      {
            metric(
                'Supervised validation permitted',
                yes_no(packet.supervised_validation_run_permitted),
            )
        }\n"
        "    </section>\n"
        '    <section class="panel" id="packet-flags">\n'
        "      <h2>Read-only flags and halt proof</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Packet kind', packet.packet_kind)}\n"
        f"        {metric('Purpose', packet.purpose)}\n"
        f"        {metric('OUTBOUND_ENABLED', yes_no(packet.outbound_enabled))}\n"
        f"        {metric('Operator halt', packet.operator_halt_status)}\n"
        f"        {metric('Halt before', packet.operator_halt_before)}\n"
        f"        {metric('Halt after', packet.operator_halt_after)}\n"
        f"        {metric('Halt unchanged', yes_no(packet.operator_halt_unchanged))}\n"
        f"        {metric('Halt changed', yes_no(packet.halt_changed))}\n"
        f"        {metric('Live providers enabled', yes_no(packet.live_providers_enabled))}\n"
        f"        {metric('Decision-maker live', yes_no(packet.decision_maker_live_enabled))}\n"
        f"        {
            metric(
                'Email verification live',
                yes_no(packet.email_verification_live_enabled),
            )
        }\n"
        f"        {
            metric(
                'Email verification SMTP',
                yes_no(packet.email_verification_smtp_enabled),
            )
        }\n"
        f"        {metric('Settings applied', yes_no(packet.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(packet.owner_approved))}\n"
        f"        {metric('Read only', yes_no(packet.read_only))}\n"
        f"        {metric('Dry-run only', yes_no(packet.dry_run_only))}\n"
        f"        {metric('No execution', yes_no(packet.no_execution))}\n"
        f"        {metric('No outbound', yes_no(packet.no_outbound))}\n"
        f"        {metric('No provider calls', yes_no(packet.no_provider_calls))}\n"
        f"        {metric('No send', yes_no(packet.no_send))}\n"
        f"        {metric('No call', yes_no(packet.no_call))}\n"
        f"        {metric('No book', yes_no(packet.no_book))}\n"
        f"        {metric('No spend', yes_no(packet.no_spend))}\n"
        f"        {metric('No deploy', yes_no(packet.no_deploy))}\n"
        f"        {metric('No autodial', yes_no(packet.no_autodial))}\n"
        f"        {metric('No AI voice', yes_no(packet.no_ai_voice))}\n"
        f"        {metric('Manual review only', yes_no(packet.manual_review_only))}\n"
        f"        {metric('Outbound attempted', yes_no(packet.outbound_attempted))}\n"
        f"        {metric('Live call attempted', yes_no(packet.live_call_attempted))}\n"
        f"        {
            metric(
                'Live provider calls attempted',
                yes_no(packet.live_provider_calls_attempted),
            )
        }\n"
        f"        {metric('SMTP attempted', yes_no(packet.smtp_attempted))}\n"
        f"        {metric('Autodial attempted', yes_no(packet.autodial_attempted))}\n"
        f"        {metric('Campaign enrolled', yes_no(packet.campaign_enrolled))}\n"
        f"        {metric('Booking attempted', yes_no(packet.booking_attempted))}\n"
        f"        {metric('Meet link created', yes_no(packet.meet_link_created))}\n"
        f"        {metric('Ads launched', yes_no(packet.ads_launched))}\n"
        f"        {metric('Spend attempted', yes_no(packet.spend_attempted))}\n"
        f"        {metric('Campaign launched', yes_no(packet.campaign_launched))}\n"
        f"        {
            metric(
                'Scoring thresholds changed',
                yes_no(packet.scoring_thresholds_changed),
            )
        }\n"
        f"        {
            metric(
                'Contact validation is not outbound',
                yes_no(packet.contact_validation_is_not_outbound),
            )
        }\n"
        f"        {
            metric(
                'Contact validation is not a live send',
                yes_no(packet.contact_validation_is_not_live_send),
            )
        }\n"
        f"        {
            metric(
                'Packet is not execution',
                yes_no(packet.supervised_validation_run_packet_is_not_execution),
            )
        }\n"
        f"        {
            metric(
                'Export is not permission to run',
                yes_no(packet.export_is_not_permission_to_run),
            )
        }\n"
        f"        {
            metric(
                'Supervised validation permitted',
                yes_no(packet.supervised_validation_run_permitted),
            )
        }\n"
        "      </div>\n"
        '      <p class="hint">Operator halt before and after must match. '
        "This page never shows practice names, provider names, NPI numbers, "
        "street addresses, emails, phones, websites, raw evidence snippets, "
        "message bodies, outreach drafts, PHI, patient data, secret values, "
        "environment values, API keys, tokens, or unsafe error text. "
        "OUTBOUND_ENABLED=false. execution_allowed=false. "
        "owner_approved=false. supervised_validation_run_permitted=false. "
        "This is a read-only aggregate review view, not permission to "
        "contact prospects and not an execution surface.</p>\n"
        "    </section>\n"
        '    <section class="panel" id="live-provider-flags">\n'
        "      <h2>Live provider flag booleans</h2>\n"
        '      <p class="hint">Booleans only. Flag names and true/false. '
        "Secret values are never shown. CI/defaults keep every flag "
        "false.</p>\n"
        f"      {live_flags_body}\n"
        "    </section>"
    )


def _render_segment(packet: SupervisedValidationRunPacket) -> str:
    return (
        '    <section class="panel" id="target-segment">\n'
        "      <h2>Target segment and planned cohort size</h2>\n"
        '      <p class="hint">State abbreviations, city/specialty labels, '
        "and counts only. Practice names, NPI numbers, street addresses, "
        "emails, and phones are never shown. max_cohort_size is capped at "
        f"{html_escape(MAX_COHORT_SIZE)}.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('State', packet.segment_state)}\n"
        f"        {metric('City', packet.segment_city)}\n"
        f"        {metric('Specialty', packet.segment_specialty)}\n"
        f"        {metric('Taxonomy description', packet.segment_taxonomy_description)}\n"
        f"        {metric('Max cohort size', packet.max_cohort_size)}\n"
        f"        {
            metric(
                'Organizations matching filters',
                packet.organizations_matching_filters,
            )
        }\n"
        f"        {metric('Planned cohort size', packet.planned_cohort_size)}\n"
        "      </div>\n"
        "    </section>"
    )


def _render_prerequisites(items: tuple[PrerequisiteItem, ...]) -> str:
    if not items:
        body = '<p class="empty-state">No prerequisite checklist rows.</p>'
    else:
        rows = "".join(_prerequisite_row(item) for item in items)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Status</th><th>Blocking</th><th>Command</th>"
            "<th>Route</th><th>Label</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="prerequisite-checklist">\n'
        "      <h2>Prerequisite checklist</h2>\n"
        '      <p class="hint">Codes, statuses, labels, blocking flags, and '
        "related route/command names only. These rows do not execute or "
        "grant approval.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _prerequisite_row(item: PrerequisiteItem) -> str:
    route = item.html_route or item.json_route
    route_cell = (
        f'<a class="row-link mono" href="{escape(route)}">{html_escape(route)}</a>'
        if route
        else html_escape("—")
    )
    return (
        f'<tr class="{_status_class(item.status)}">'
        f'<td class="mono">{html_escape(item.code)}</td>'
        f"<td>{html_escape(item.status)}</td>"
        f"<td>{yes_no(item.blocking)}</td>"
        f'<td class="mono">{html_escape(item.command_name)}</td>'
        f"<td>{route_cell}</td>"
        f"<td>{html_escape(item.label)}</td>"
        "</tr>"
    )


def _render_owner_decisions(items: tuple[OwnerDecisionItem, ...]) -> str:
    if not items:
        body = '<p class="empty-state">No required owner decisions.</p>'
    else:
        rows = "".join(_decision_row(item) for item in items)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Name</th><th>Granted</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="required-owner-decisions">\n'
        "      <h2>Required owner decisions</h2>\n"
        '      <p class="hint">Codes and names only. granted remains false. '
        "This page has no approval or rejection controls.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _decision_row(item: OwnerDecisionItem) -> str:
    return (
        "<tr>"
        f'<td class="mono">{html_escape(item.code)}</td>'
        f"<td>{html_escape(item.name)}</td>"
        f"<td>{yes_no(item.granted)}</td>"
        "</tr>"
    )


def _render_credentials_and_configs(packet: SupervisedValidationRunPacket) -> str:
    return (
        '    <section class="panel" id="required-credentials">\n'
        "      <h2>Required credential names</h2>\n"
        '      <p class="hint">Names and present/missing booleans only. '
        "Values, secrets, tokens, and raw env contents are never shown.</p>\n"
        f"      {_render_presence(packet.required_credentials, empty='No required credentials.')}\n"
        "      <h3>Missing credential names</h3>\n"
        f"      {_render_codes(packet.missing_credential_names, empty='None missing.')}\n"
        "    </section>\n"
        '    <section class="panel" id="required-configs">\n'
        "      <h2>Required config names</h2>\n"
        '      <p class="hint">Config names and present/missing booleans '
        "only. Live flag values stay false in CI/defaults.</p>\n"
        f"      {_render_presence(packet.required_configs, empty='No required configs.')}\n"
        "      <h3>Missing config names</h3>\n"
        f"      {_render_codes(packet.missing_config_names, empty='None missing.')}\n"
        "    </section>"
    )


def _render_presence(items: tuple[NamedPresence, ...], *, empty: str) -> str:
    if not items:
        return f'<p class="empty-state">{escape(empty)}</p>'
    rows = "".join(
        (
            "<tr>"
            f'<td class="mono">{html_escape(item.name)}</td>'
            f"<td>{yes_no(item.present)}</td>"
            "</tr>"
        )
        for item in items
    )
    return (
        '<table class="dense"><thead><tr>'
        "<th>Name</th><th>Present</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _render_planned_stages(stages: tuple[ContactValidationStage, ...]) -> str:
    if not stages:
        body = '<p class="empty-state">No planned stages.</p>'
    else:
        rows = "".join(_stage_row(stage) for stage in stages)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Command</th><th>Route</th><th>Mode</th>"
            "<th>Executed</th><th>Live provider called</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="planned-stages">\n'
        "      <h2>Planned existing stages</h2>\n"
        '      <p class="hint">Route and command names only. These rows do '
        "not execute discovery, enrichment, verification, or phone-queue "
        "stages.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _stage_row(stage: ContactValidationStage) -> str:
    route_cell = (
        f'<a class="row-link mono" href="{escape(stage.json_route)}">'
        f"{html_escape(stage.json_route)}</a>"
        if stage.json_route
        else html_escape("—")
    )
    return (
        "<tr>"
        f'<td class="mono">{html_escape(stage.code)}</td>'
        f'<td class="mono">{html_escape(stage.command_name)}</td>'
        f"<td>{route_cell}</td>"
        f"<td>{html_escape(stage.mode)}</td>"
        f"<td>{yes_no(stage.executed)}</td>"
        f"<td>{yes_no(stage.live_provider_called)}</td>"
        "</tr>"
    )


def _render_funnel(packet: SupervisedValidationRunPacket) -> str:
    funnel = packet.funnel
    return (
        '    <section class="panel" id="funnel-counts">\n'
        "      <h2>Phase 71 funnel counts and rates</h2>\n"
        '      <p class="hint">Aggregate counts and rates copied from the '
        "Phase 73 packet / Phase 71 report. This page does not recalculate "
        "readiness or call providers.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Organizations considered', funnel.organizations_considered)}\n"
        f"        {
            metric(
                'Official website verified',
                funnel.official_website_verified_count,
            )
        }\n"
        f"        {
            metric(
                'Official website ambiguous',
                funnel.official_website_ambiguous_count,
            )
        }\n"
        f"        {
            metric(
                'Official website no-match',
                funnel.official_website_no_match_count,
            )
        }\n"
        f"        {
            metric(
                'Official website unknown',
                funnel.official_website_unknown_count,
            )
        }\n"
        f"        {metric('Staff facts found', funnel.staff_facts_found_count)}\n"
        f"        {metric('Job-posting intent', funnel.job_posting_intent_count)}\n"
        f"        {
            metric(
                'Decision-maker candidates',
                funnel.decision_maker_candidates_found_count,
            )
        }\n"
        f"        {metric('Business email found', funnel.business_email_found_count)}\n"
        f"        {metric('Verified email', funnel.verified_email_count)}\n"
        f"        {
            metric(
                'Verified decision-maker-role email',
                funnel.verified_decision_maker_role_email_count,
            )
        }\n"
        f"        {metric('Provider errors', funnel.provider_error_count)}\n"
        f"        {
            metric(
                'Official website verified rate',
                funnel.official_website_verified_rate,
            )
        }\n"
        f"        {metric('Staff facts rate', funnel.staff_facts_found_rate)}\n"
        f"        {metric('Job-posting intent rate', funnel.job_posting_intent_rate)}\n"
        f"        {
            metric(
                'Decision-maker candidate rate',
                funnel.decision_maker_candidates_found_rate,
            )
        }\n"
        f"        {metric('Business email rate', funnel.business_email_found_rate)}\n"
        f"        {metric('Verified email rate', funnel.verified_email_rate)}\n"
        f"        {
            metric(
                'Verified decision-maker-role email rate',
                funnel.verified_decision_maker_role_email_rate,
            )
        }\n"
        f"        {metric('Provider error rate', funnel.provider_error_rate)}\n"
        f"        {
            metric(
                'Funnel strong enough for supervised validation',
                yes_no(packet.funnel_strong_enough_for_supervised_validation),
            )
        }\n"
        "      </div>\n"
        "    </section>"
    )


def _render_threshold_comparisons(items: tuple[ThresholdComparison, ...]) -> str:
    if not items:
        body = '<p class="empty-state">No threshold comparison rows.</p>'
    else:
        rows = "".join(_comparison_row(item) for item in items)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Metric</th><th>Status</th><th>Blocking</th>"
            "<th>NO_CONTACT_FOUND is failure</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="threshold-comparisons">\n'
        "      <h2>Threshold comparison statuses</h2>\n"
        '      <p class="hint">Metric, code, and status only. These owner-review '
        "thresholds are not applied to live settings or scoring.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _comparison_row(item: ThresholdComparison) -> str:
    status = "passed" if item.passed else "failed"
    return (
        f'<tr class="{_status_class(status)}">'
        f'<td class="mono">{html_escape(item.code)}</td>'
        f'<td class="mono">{html_escape(item.metric)}</td>'
        f"<td>{html_escape(status)}</td>"
        f"<td>{yes_no(item.blocking)}</td>"
        f"<td>{yes_no(item.no_contact_found_is_failure)}</td>"
        "</tr>"
    )


def _render_owner_review_thresholds(items: tuple[OwnerReviewThreshold, ...]) -> str:
    if not items:
        body = '<p class="empty-state">No owner-review thresholds.</p>'
    else:
        rows = "".join(_threshold_row(item) for item in items)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Metric</th><th>Applied to live settings</th>"
            "<th>Scoring thresholds changed</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="owner-review-thresholds">\n'
        "      <h2>Owner-review thresholds</h2>\n"
        '      <p class="hint">Codes and metrics only. Threshold fields are '
        "review metadata and must not change live settings or scoring.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _threshold_row(item: OwnerReviewThreshold) -> str:
    return (
        "<tr>"
        f'<td class="mono">{html_escape(item.code)}</td>'
        f'<td class="mono">{html_escape(item.metric)}</td>'
        f"<td>{yes_no(item.applied_to_live_settings)}</td>"
        f"<td>{yes_no(item.scoring_thresholds_changed)}</td>"
        "</tr>"
    )


def _render_outcome_summaries(packet: SupervisedValidationRunPacket) -> str:
    funnel = packet.funnel
    return (
        '    <section class="panel" id="outcome-summaries">\n'
        "      <h2>NO_CONTACT_FOUND and NO_VERIFIED_EMAIL</h2>\n"
        '      <p class="hint">Counts and rates only. NO_CONTACT_FOUND and '
        "NO_VERIFIED_EMAIL are normal outcomes, not failures. This page "
        "does not place calls, autodial, use AI voice, or send email.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('NO_CONTACT_FOUND count', funnel.no_contact_found_count)}\n"
        f"        {metric('NO_CONTACT_FOUND rate', funnel.no_contact_found_rate)}\n"
        f"        {metric('NO_VERIFIED_EMAIL count', funnel.no_verified_email_count)}\n"
        f"        {metric('NO_VERIFIED_EMAIL rate', funnel.no_verified_email_rate)}\n"
        f"        {
            metric(
                'Queued human phone-verification count',
                funnel.queued_human_phone_verification_count,
            )
        }\n"
        f"        {
            metric(
                'Queued human phone-verification rate',
                funnel.queued_human_phone_verification_rate,
            )
        }\n"
        f"        {
            metric(
                'NO_CONTACT_FOUND is normal',
                yes_no(packet.no_contact_found_is_normal_outcome),
            )
        }\n"
        f"        {
            metric(
                'NO_CONTACT_FOUND is failure',
                yes_no(packet.no_contact_found_is_failure),
            )
        }\n"
        f"        {
            metric(
                'NO_VERIFIED_EMAIL is normal',
                yes_no(packet.no_verified_email_is_normal_outcome),
            )
        }\n"
        f"        {
            metric(
                'NO_VERIFIED_EMAIL is failure',
                yes_no(packet.no_verified_email_is_failure),
            )
        }\n"
        "      </div>\n"
        "    </section>"
    )


def _render_status_counts(packet: SupervisedValidationRunPacket) -> str:
    return (
        '    <section class="panel" id="status-code-counts">\n'
        "      <h2>Blocked, warning, and info code counts</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Blocked code count', packet.blocked_code_count)}\n"
        f"        {metric('Warning code count', packet.warning_code_count)}\n"
        f"        {metric('Info code count', packet.info_code_count)}\n"
        "      </div>\n"
        "      <h3>Counts by status</h3>\n"
        f"      {_render_status_count_rows(packet.status_counts, empty='No status counts.')}\n"
        "    </section>"
    )


def _render_status_count_rows(items: tuple[StatusCount, ...], *, empty: str) -> str:
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


def _render_related_inventory(packet: SupervisedValidationRunPacket) -> str:
    return (
        '    <section class="panel" id="source-references">\n'
        "      <h2>Source references</h2>\n"
        '      <p class="hint">This page reuses the existing Phase 73 packet. '
        "It does not recalculate readiness or execute.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Source plan command', packet.source_plan_command)}\n"
        f"        {metric('Source plan route', packet.source_plan_route)}\n"
        f"        {metric('Source plan status', packet.source_plan_overall_status)}\n"
        f"        {metric('Source report command', packet.source_report_command)}\n"
        f"        {metric('Source report route', packet.source_report_route)}\n"
        f"        {metric('Source report status', packet.source_report_overall_status)}\n"
        f"        {metric('Source HTML route', packet.source_html_route)}\n"
        f"        {metric('CLI command', packet.cli_command)}\n"
        f"        {metric('JSON route', packet.http_route)}\n"
        f"        {metric('HTML route', packet.html_route)}\n"
        "      </div>\n"
        "    </section>\n"
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


def _render_next_actions(actions: tuple[OwnerNextStep, ...]) -> str:
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


def _next_action_row(action: OwnerNextStep) -> str:
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


def _render_footer(packet: SupervisedValidationRunPacket, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Overall status="
        f"{html_escape(packet.overall_status)}. "
        f"Read-only={yes_no(packet.read_only)}. "
        f"Manual review only={yes_no(packet.manual_review_only)}. "
        f"Dry-run only={yes_no(packet.dry_run_only)}. "
        f"No execution={yes_no(packet.no_execution)}. "
        f"No outbound={yes_no(packet.no_outbound)}. "
        f"No provider calls={yes_no(packet.no_provider_calls)}. "
        f"No send={yes_no(packet.no_send)}. "
        f"No call={yes_no(packet.no_call)}. "
        f"No book={yes_no(packet.no_book)}. "
        f"No deploy={yes_no(packet.no_deploy)}. "
        f"No spend={yes_no(packet.no_spend)}. "
        f"No autodial={yes_no(packet.no_autodial)}. "
        f"No AI voice={yes_no(packet.no_ai_voice)}. "
        f"Outbound attempted={yes_no(packet.outbound_attempted)}. "
        f"Live call attempted={yes_no(packet.live_call_attempted)}. "
        f"Live provider calls attempted="
        f"{yes_no(packet.live_provider_calls_attempted)}. "
        f"SMTP attempted={yes_no(packet.smtp_attempted)}. "
        f"Autodial attempted={yes_no(packet.autodial_attempted)}. "
        f"Campaign enrolled={yes_no(packet.campaign_enrolled)}. "
        f"Booking attempted={yes_no(packet.booking_attempted)}. "
        f"Meet link created={yes_no(packet.meet_link_created)}. "
        f"Ads launched={yes_no(packet.ads_launched)}. "
        f"Settings applied={yes_no(packet.settings_applied)}. "
        f"Halt changed={yes_no(packet.halt_changed)}. "
        f"Owner approved={yes_no(packet.owner_approved)}. "
        f"Execution allowed={yes_no(packet.execution_allowed)}. "
        f"Supervised validation run permitted="
        f"{yes_no(packet.supervised_validation_run_permitted)}. "
        f"Packet is not execution="
        f"{yes_no(packet.supervised_validation_run_packet_is_not_execution)}. "
        f"Export is not permission to run="
        f"{yes_no(packet.export_is_not_permission_to_run)}. "
        f"Contact validation is not outbound="
        f"{yes_no(packet.contact_validation_is_not_outbound)}. "
        f"Contact validation is not a live send="
        f"{yes_no(packet.contact_validation_is_not_live_send)}. "
        f"NO_CONTACT_FOUND is failure="
        f"{yes_no(packet.no_contact_found_is_failure)}. "
        f"NO_VERIFIED_EMAIL is failure="
        f"{yes_no(packet.no_verified_email_is_failure)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "build, publish, deploy, campaign, booking, call, spend, candidate "
        "selection, send, approval, or contact controls on this page. This "
        "is a read-only aggregate review view, not permission to run a "
        "supervised 200-practice validation, and not an execution surface. "
        "Current route "
        f"{html_escape(OPERATOR_SUPERVISED_VALIDATION_RUN_PACKET_PATH)}.</p>\n"
        "    </footer>"
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
        case FindingSeverity.BLOCKED.value | "failed" | "closed" | "missing":
            return "severity-blocked"
        case FindingSeverity.WARNING.value:
            return "severity-warning"
        case FindingSeverity.INFO.value | "ready_for_owner_review" | "passed" | "open":
            return "severity-info"
        case _:
            return "severity-info"
