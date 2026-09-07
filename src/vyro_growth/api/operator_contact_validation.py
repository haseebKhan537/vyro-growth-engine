"""Read-only operator contact-enrichment validation HTML shell.

Phase 72 renders a sanitized view of the existing Phase 71 contact
validation plan and report. It reuses ContactValidationService and never
recalculates funnel readiness. It never executes validation stages, calls
providers, selects or contacts prospects, sends email, enrolls campaigns,
places calls, books meetings, spends money, publishes, deploys, applies
settings, lifts halt, or enables outbound. This page is an aggregate-only
review view, not permission to run a supervised 200-practice validation
and not an execution surface.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    OPERATOR_UI_STYLES,
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
    HTML_ROUTE,
    MAX_COHORT_SIZE,
    PLAN_CLI_COMMAND,
    PLAN_HTTP_ROUTE,
    REPORT_CLI_COMMAND,
    REPORT_HTTP_ROUTE,
    ContactValidationError,
    ContactValidationFilters,
    ContactValidationPlan,
    ContactValidationReport,
    ContactValidationSegment,
    ContactValidationService,
    ContactValidationStage,
    OwnerReviewThreshold,
    ThresholdComparison,
)
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata

logger = structlog.get_logger(__name__)
COHORT_SIZE_PRESETS: tuple[int, ...] = (50, 100, 200)


@dataclass(frozen=True)
class ContactValidationNextStep:
    code: str
    status: str
    label: str
    command_name: str
    json_route: str | None
    html_route: str | None


def render_operator_contact_validation_error(*, invalid_filter: bool = False) -> str:
    if invalid_filter:
        detail = (
            "A query filter was rejected. Use a two-letter state code, "
            "safe city/specialty text, and max_cohort_size from 1 to 200. "
            "This page is an aggregate-only review view, not permission to "
            "run a supervised validation and not an execution surface."
        )
        banner = "Contact validation filters were rejected."
        heading = "Read-only contact validation filters rejected"
    else:
        detail = (
            "The sanitized contact-enrichment validation review view could "
            "not be rendered. Retry after checking database connectivity "
            "and runtime config. This page is an aggregate-only review "
            "view, not permission to run a supervised validation and not "
            "an execution surface."
        )
        banner = "Unable to load the operator contact validation view."
        heading = "Read-only contact validation unavailable"
    return render_failure_page(
        page_id="operator-contact-validation-error",
        title="Operator contact validation unavailable",
        heading=heading,
        banner=banner,
        detail=detail,
    )


def render_operator_contact_validation(
    plan: ContactValidationPlan,
    report: ContactValidationReport,
) -> str:
    generated = html_escape(format_dt(report.generated_at))
    next_steps = owner_next_step_labels(plan, report)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Operator contact validation</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-contact-validation" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-no-execution="true" data-no-outbound="true" '
        'data-no-provider-calls="true" data-no-spend="true" '
        'data-no-deployment="true" data-manual-review-only="true" '
        'data-contact-validation-is-not-outbound="true" '
        'data-contact-validation-is-not-live-send="true" '
        'data-supervised-validation-run-permitted="false" '
        'data-no-contact-found-is-failure="false">\n'
        f"{_render_header(plan, report, generated)}\n"
        f"{render_operator_nav('contact-validation')}\n"
        f"{_render_related_links()}\n"
        f"{_render_filters(report.segment)}\n"
        f"{_render_live_blocking_flags(plan, report)}\n"
        f"{_render_segment(report.segment)}\n"
        f"{_render_planned_stages(report.planned_stages)}\n"
        f"{_render_funnel(report)}\n"
        f"{_render_threshold_comparisons(report.threshold_comparisons)}\n"
        f"{_render_owner_review_thresholds(report.owner_review_thresholds)}\n"
        f"{_render_outcome_summaries(report)}\n"
        f"{_render_related_inventory(report)}\n"
        f"{_render_local_git(report.local_git)}\n"
        f"{_render_next_actions(next_steps)}\n"
        f"{_render_footer(plan, report, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_contact_validation_response(
    db: Session,
    settings: Settings,
    *,
    filters: ContactValidationFilters | None = None,
    service: ContactValidationService | None = None,
) -> HTMLResponse:
    try:
        builder = service or ContactValidationService()
        plan = builder.build_plan(db, settings, filters)
        report = builder.build_report(db, settings, filters)
        html = render_operator_contact_validation(plan, report)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except ContactValidationError:
        logger.info(
            "operator_contact_validation_invalid_filter",
            read_only=True,
        )
        return HTMLResponse(
            content=render_operator_contact_validation_error(invalid_filter=True),
            status_code=400,
            headers=NO_STORE_HEADERS,
        )
    except Exception:
        logger.exception("operator_contact_validation_render_failed", read_only=True)
        return HTMLResponse(
            content=render_operator_contact_validation_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def owner_next_step_labels(
    plan: ContactValidationPlan,
    report: ContactValidationReport,
) -> tuple[ContactValidationNextStep, ...]:
    funnel_code = (
        "funnel_ready_for_owner_review_only"
        if report.funnel_strong_enough_for_supervised_validation
        else "funnel_not_ready_for_supervised_validation"
    )
    funnel_label = (
        "Funnel thresholds passed for owner review only. "
        "supervised_validation_run_permitted remains false."
        if report.funnel_strong_enough_for_supervised_validation
        else (
            "Funnel is not yet strong enough for a supervised 200-practice "
            "validation run. This page does not execute that run."
        )
    )
    outbound_status = (
        FindingSeverity.INFO.value
        if not report.outbound_enabled
        else FindingSeverity.BLOCKED.value
    )
    halt_unchanged = report.operator_halt_before == report.operator_halt_after
    halt_status = (
        FindingSeverity.INFO.value if halt_unchanged else FindingSeverity.BLOCKED.value
    )
    return (
        ContactValidationNextStep(
            code="keep_outbound_disabled",
            status=outbound_status,
            label="Keep OUTBOUND_ENABLED=false. This page is not permission to enable outbound.",
            command_name=PLAN_CLI_COMMAND,
            json_route=PLAN_HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        ContactValidationNextStep(
            code="keep_operator_halt_unchanged",
            status=halt_status,
            label=(
                "Keep operator halt unchanged. This page never lifts halt "
                "or applies settings."
            ),
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        ContactValidationNextStep(
            code="review_contact_validation_plan",
            status=plan.overall_status,
            label=(
                "Review the sanitized contact-validation plan. Planned stages "
                "are existing route/command names only and are not executed."
            ),
            command_name=PLAN_CLI_COMMAND,
            json_route=PLAN_HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        ContactValidationNextStep(
            code="review_contact_validation_report",
            status=report.overall_status,
            label=(
                "Review aggregate funnel counts and rates from stored local "
                "data. This page does not call providers."
            ),
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        ContactValidationNextStep(
            code=funnel_code,
            status=report.overall_status,
            label=funnel_label,
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        ContactValidationNextStep(
            code="no_contact_found_is_normal_outcome",
            status=FindingSeverity.INFO.value,
            label=(
                "NO_CONTACT_FOUND is a normal outcome, not a failure. "
                "Queued human phone-verification remains review-only."
            ),
            command_name="list-phone-verification",
            json_route="/internal/phone-verification/tasks",
            html_route=HTML_ROUTE,
        ),
        ContactValidationNextStep(
            code="supervised_validation_run_not_permitted",
            status=FindingSeverity.INFO.value,
            label=(
                "supervised_validation_run_permitted=false. Do not execute a "
                "200-practice validation run, send email, enroll campaigns, "
                "or place calls from this page."
            ),
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
    )


def _render_header(
    plan: ContactValidationPlan,
    report: ContactValidationReport,
    generated: str,
) -> str:
    git = report.local_git
    git_meta = (
        f" · git {html_escape(git.current_branch)}@{html_escape(git.current_sha)}"
        if git.available
        else " · local git unavailable"
    )
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Operator contact validation</h1>\n"
        '        <p class="lede">Read-only aggregate view of the Phase 71 '
        "contact-enrichment validation plan and report. This page reuses "
        "ContactValidationService and does not execute stages, call "
        "providers, select or contact prospects, send email, enroll "
        "campaigns, place calls, autodial, use AI voice, book meetings, "
        "create Meet links, launch ads, spend, publish, deploy, apply "
        "settings, or lift halt. OUTBOUND_ENABLED=false. "
        "execution_allowed=false. owner_approved=false. "
        "supervised_validation_run_permitted=false. "
        "no_outbound=true. no_provider_calls=true. "
        "contact_validation_is_not_outbound=true. "
        "contact_validation_is_not_live_send=true. "
        "NO_CONTACT_FOUND is a normal outcome. This page is an "
        "aggregate-only review view, not permission to run a supervised "
        "200-practice validation and not an execution surface.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · plan '
        f"{html_escape(plan.overall_status)} · report "
        f"{html_escape(report.overall_status)} · halt "
        f"{html_escape(report.operator_halt_status)} · "
        f"{html_escape(report.packet_kind)} · {html_escape(report.purpose)}"
        f"{git_meta}</p>\n"
        "    </header>"
    )


def _render_related_links() -> str:
    dashboard_href = escape(OPERATOR_DASHBOARD_PATH)
    plan_json_href = escape(CONTACT_VALIDATION_PLAN_JSON_PATH)
    report_json_href = escape(CONTACT_VALIDATION_REPORT_JSON_PATH)
    metrics_href = escape("/internal/contact-enrichment/metrics")
    email_metrics_href = escape("/internal/email-verification/metrics")
    phone_href = escape("/internal/phone-verification/tasks")
    control_map_href = escape(OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Linked readiness surfaces">\n'
        f'      <a class="nav-link" href="{dashboard_href}">Dashboard</a>\n'
        f'      <a class="nav-link" href="{plan_json_href}">JSON plan</a>\n'
        f'      <a class="nav-link" href="{report_json_href}">JSON report</a>\n'
        f'      <a class="nav-link" href="{metrics_href}">Contact metrics JSON</a>\n'
        f'      <a class="nav-link" href="{email_metrics_href}">Email metrics JSON</a>\n'
        f'      <a class="nav-link" href="{phone_href}">Phone verification JSON</a>\n'
        f'      <a class="nav-link" href="{control_map_href}">Rehearsal control map</a>\n'
        "    </nav>"
    )


def _render_filters(segment: ContactValidationSegment) -> str:
    links = [
        filter_link(
            _filter_href(segment, max_cohort_size=size),
            f"max {size}",
            current=segment.max_cohort_size == size,
        )
        for size in COHORT_SIZE_PRESETS
        if 1 <= size <= MAX_COHORT_SIZE
    ]
    return (
        '    <nav class="filter-nav" aria-label="Safe cohort size filters">\n'
        f'      {" ".join(links)}\n'
        "    </nav>"
    )


def _filter_href(segment: ContactValidationSegment, *, max_cohort_size: int) -> str:
    params: dict[str, str] = {}
    if segment.state:
        params["state"] = segment.state
    if segment.city:
        params["city"] = segment.city
    if segment.specialty:
        params["specialty"] = segment.specialty
    elif segment.taxonomy_description:
        params["taxonomy_description"] = segment.taxonomy_description
    if max_cohort_size != DEFAULT_COHORT_SIZE:
        params["max_cohort_size"] = str(max_cohort_size)
    if not params:
        return OPERATOR_CONTACT_VALIDATION_PATH
    return f"{OPERATOR_CONTACT_VALIDATION_PATH}?{urlencode(params)}"


def _render_live_blocking_flags(
    plan: ContactValidationPlan,
    report: ContactValidationReport,
) -> str:
    halt_unchanged = report.operator_halt_before == report.operator_halt_after
    live_flag_rows = "".join(
        (
            "<tr>"
            f'<td class="mono">{html_escape(name)}</td>'
            f"<td>{yes_no(enabled)}</td>"
            "</tr>"
        )
        for name, enabled in report.live_providers.items()
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
        f"      {metric('Plan status', plan.overall_status)}\n"
        f"      {metric('Report status', report.overall_status)}\n"
        f"      {metric('OUTBOUND_ENABLED', yes_no(report.outbound_enabled))}\n"
        f"      {metric('Operator halt', report.operator_halt_status)}\n"
        f"      {metric('Execution allowed', yes_no(report.execution_allowed))}\n"
        f"      {metric('No outbound', yes_no(report.no_outbound))}\n"
        f"      {metric('No provider calls', yes_no(report.no_provider_calls))}\n"
        f"      {
            metric(
                'Supervised validation permitted',
                yes_no(report.supervised_validation_run_permitted),
            )
        }\n"
        "    </section>\n"
        '    <section class="panel" id="validation-flags">\n'
        "      <h2>Read-only flags and halt proof</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Packet kind', report.packet_kind)}\n"
        f"        {metric('Purpose', report.purpose)}\n"
        f"        {metric('OUTBOUND_ENABLED', yes_no(report.outbound_enabled))}\n"
        f"        {metric('Operator halt', report.operator_halt_status)}\n"
        f"        {metric('Halt before', report.operator_halt_before)}\n"
        f"        {metric('Halt after', report.operator_halt_after)}\n"
        f"        {metric('Halt unchanged', yes_no(halt_unchanged))}\n"
        f"        {metric('Halt changed', yes_no(report.halt_changed))}\n"
        f"        {metric('Live providers enabled', yes_no(report.live_providers_enabled))}\n"
        f"        {metric('Decision-maker live', yes_no(report.decision_maker_live_enabled))}\n"
        f"        {
            metric(
                'Email verification live',
                yes_no(report.email_verification_live_enabled),
            )
        }\n"
        f"        {
            metric(
                'Email verification SMTP',
                yes_no(report.email_verification_smtp_enabled),
            )
        }\n"
        f"        {metric('Settings applied', yes_no(report.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(report.owner_approved))}\n"
        f"        {metric('Read only', yes_no(report.read_only))}\n"
        f"        {metric('Dry-run only', yes_no(report.dry_run_only))}\n"
        f"        {metric('No execution', yes_no(report.no_execution))}\n"
        f"        {metric('No outbound', yes_no(report.no_outbound))}\n"
        f"        {metric('No provider calls', yes_no(report.no_provider_calls))}\n"
        f"        {metric('No spend', yes_no(report.no_spend))}\n"
        f"        {metric('No deployment', yes_no(report.no_deployment))}\n"
        f"        {metric('Manual review only', yes_no(report.manual_review_only))}\n"
        f"        {metric('Outbound attempted', yes_no(report.outbound_attempted))}\n"
        f"        {metric('Live call attempted', yes_no(report.live_call_attempted))}\n"
        f"        {
            metric(
                'Live provider calls attempted',
                yes_no(report.live_provider_calls_attempted),
            )
        }\n"
        f"        {metric('SMTP attempted', yes_no(report.smtp_attempted))}\n"
        f"        {metric('Autodial attempted', yes_no(report.autodial_attempted))}\n"
        f"        {metric('Campaign enrolled', yes_no(report.campaign_enrolled))}\n"
        f"        {metric('Booking attempted', yes_no(report.booking_attempted))}\n"
        f"        {metric('Meet link created', yes_no(report.meet_link_created))}\n"
        f"        {metric('Ads launched', yes_no(report.ads_launched))}\n"
        f"        {metric('Spend attempted', yes_no(report.spend_attempted))}\n"
        f"        {metric('Campaign launched', yes_no(report.campaign_launched))}\n"
        f"        {
            metric(
                'Scoring thresholds changed',
                yes_no(report.scoring_thresholds_changed),
            )
        }\n"
        f"        {
            metric(
                'Contact validation is not outbound',
                yes_no(report.contact_validation_is_not_outbound),
            )
        }\n"
        f"        {
            metric(
                'Contact validation is not a live send',
                yes_no(report.contact_validation_is_not_live_send),
            )
        }\n"
        f"        {
            metric(
                'Supervised validation permitted',
                yes_no(report.supervised_validation_run_permitted),
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


def _render_segment(segment: ContactValidationSegment) -> str:
    return (
        '    <section class="panel" id="target-segment">\n'
        "      <h2>Target segment and planned cohort size</h2>\n"
        '      <p class="hint">State abbreviations, city/specialty labels, '
        "and counts only. Practice names, NPI numbers, street addresses, "
        "emails, and phones are never shown. max_cohort_size is capped at "
        f"{html_escape(MAX_COHORT_SIZE)}.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('State', segment.state)}\n"
        f"        {metric('City', segment.city)}\n"
        f"        {metric('Specialty', segment.specialty)}\n"
        f"        {metric('Taxonomy description', segment.taxonomy_description)}\n"
        f"        {metric('Max cohort size', segment.max_cohort_size)}\n"
        f"        {
            metric(
                'Organizations matching filters',
                segment.organizations_matching_filters,
            )
        }\n"
        f"        {metric('Planned cohort size', segment.planned_cohort_size)}\n"
        "      </div>\n"
        "    </section>"
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


def _render_funnel(report: ContactValidationReport) -> str:
    return (
        '    <section class="panel" id="funnel-counts">\n'
        "      <h2>Funnel counts and rates</h2>\n"
        '      <p class="hint">Aggregate counts and rates copied from the '
        "Phase 71 report. This page does not recalculate readiness or call "
        "providers.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Organizations considered', report.organizations_considered)}\n"
        f"        {
            metric(
                'Official website verified',
                report.official_website_verified_count,
            )
        }\n"
        f"        {
            metric(
                'Official website ambiguous',
                report.official_website_ambiguous_count,
            )
        }\n"
        f"        {
            metric(
                'Official website no-match',
                report.official_website_no_match_count,
            )
        }\n"
        f"        {
            metric(
                'Official website unknown',
                report.official_website_unknown_count,
            )
        }\n"
        f"        {metric('Staff facts found', report.staff_facts_found_count)}\n"
        f"        {metric('Job-posting intent', report.job_posting_intent_count)}\n"
        f"        {
            metric(
                'Decision-maker candidates',
                report.decision_maker_candidates_found_count,
            )
        }\n"
        f"        {metric('Business email found', report.business_email_found_count)}\n"
        f"        {metric('Verified email', report.verified_email_count)}\n"
        f"        {
            metric(
                'Verified decision-maker-role email',
                report.verified_decision_maker_role_email_count,
            )
        }\n"
        f"        {metric('Provider errors', report.provider_error_count)}\n"
        f"        {
            metric(
                'Official website verified rate',
                report.official_website_verified_rate,
            )
        }\n"
        f"        {metric('Staff facts rate', report.staff_facts_found_rate)}\n"
        f"        {metric('Job-posting intent rate', report.job_posting_intent_rate)}\n"
        f"        {
            metric(
                'Decision-maker candidate rate',
                report.decision_maker_candidates_found_rate,
            )
        }\n"
        f"        {metric('Business email rate', report.business_email_found_rate)}\n"
        f"        {metric('Verified email rate', report.verified_email_rate)}\n"
        f"        {
            metric(
                'Verified decision-maker-role email rate',
                report.verified_decision_maker_role_email_rate,
            )
        }\n"
        f"        {metric('Provider error rate', report.provider_error_rate)}\n"
        f"        {
            metric(
                'Funnel strong enough for supervised validation',
                yes_no(report.funnel_strong_enough_for_supervised_validation),
            )
        }\n"
        "      </div>\n"
        "      <h3>Website match counts</h3>\n"
        f"      {_render_count_map(report.website_match_counts, empty='No website match counts.')}\n"
        "      <h3>Run counts by source</h3>\n"
        f"      {_render_count_map(report.run_counts_by_source, empty='No run counts.')}\n"
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
        "      <h2>Threshold comparison rows</h2>\n"
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


def _render_outcome_summaries(report: ContactValidationReport) -> str:
    return (
        '    <section class="panel" id="outcome-summaries">\n'
        "      <h2>NO_CONTACT_FOUND, NO_VERIFIED_EMAIL, and human phone-queue</h2>\n"
        '      <p class="hint">Counts and rates only. NO_CONTACT_FOUND is a '
        "normal outcome, not a failure. This page does not place calls, "
        "autodial, or use AI voice.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('NO_CONTACT_FOUND count', report.no_contact_found_count)}\n"
        f"        {metric('NO_CONTACT_FOUND rate', report.no_contact_found_rate)}\n"
        f"        {metric('NO_VERIFIED_EMAIL count', report.no_verified_email_count)}\n"
        f"        {metric('NO_VERIFIED_EMAIL rate', report.no_verified_email_rate)}\n"
        f"        {
            metric(
                'Queued human phone-verification count',
                report.queued_human_phone_verification_count,
            )
        }\n"
        f"        {
            metric(
                'Queued human phone-verification rate',
                report.queued_human_phone_verification_rate,
            )
        }\n"
        f"        {
            metric(
                'NO_CONTACT_FOUND is normal',
                yes_no(report.no_contact_found_is_normal_outcome),
            )
        }\n"
        f"        {
            metric(
                'NO_CONTACT_FOUND is failure',
                yes_no(report.no_contact_found_is_failure),
            )
        }\n"
        "      </div>\n"
        "      <h3>Phone verification by status</h3>\n"
        f"      {
            _render_count_map(
                report.phone_verification_by_status,
                empty='No queued human phone-verification statuses.',
            )
        }\n"
        "    </section>"
    )


def _render_related_inventory(report: ContactValidationReport) -> str:
    return (
        '    <section class="panel" id="related-routes">\n'
        "      <h2>Related safe routes</h2>\n"
        f"      {_render_route_links(report.related_routes, empty='No related routes.')}\n"
        "    </section>\n"
        '    <section class="panel" id="related-commands">\n'
        "      <h2>Related CLI commands</h2>\n"
        f"      {_render_codes(report.related_commands, empty='No related commands.')}\n"
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


def _render_next_actions(actions: tuple[ContactValidationNextStep, ...]) -> str:
    if not actions:
        body = '<p class="empty-state">No owner next steps.</p>'
    else:
        rows = "".join(_next_action_row(action) for action in actions)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Status</th><th>Command</th><th>Route</th>"
            "<th>Label</th>"
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


def _next_action_row(action: ContactValidationNextStep) -> str:
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
        f"<td>{html_escape(action.label)}</td>"
        "</tr>"
    )


def _render_footer(
    plan: ContactValidationPlan,
    report: ContactValidationReport,
    generated: str,
) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Plan status="
        f"{html_escape(plan.overall_status)}. Report status="
        f"{html_escape(report.overall_status)}. "
        f"Read-only={yes_no(report.read_only)}. "
        f"Manual review only={yes_no(report.manual_review_only)}. "
        f"Dry-run only={yes_no(report.dry_run_only)}. "
        f"No execution={yes_no(report.no_execution)}. "
        f"No outbound={yes_no(report.no_outbound)}. "
        f"No provider calls={yes_no(report.no_provider_calls)}. "
        f"No deployment={yes_no(report.no_deployment)}. "
        f"No spend={yes_no(report.no_spend)}. "
        f"Outbound attempted={yes_no(report.outbound_attempted)}. "
        f"Live call attempted={yes_no(report.live_call_attempted)}. "
        f"Live provider calls attempted="
        f"{yes_no(report.live_provider_calls_attempted)}. "
        f"SMTP attempted={yes_no(report.smtp_attempted)}. "
        f"Autodial attempted={yes_no(report.autodial_attempted)}. "
        f"Campaign enrolled={yes_no(report.campaign_enrolled)}. "
        f"Booking attempted={yes_no(report.booking_attempted)}. "
        f"Meet link created={yes_no(report.meet_link_created)}. "
        f"Ads launched={yes_no(report.ads_launched)}. "
        f"Settings applied={yes_no(report.settings_applied)}. "
        f"Halt changed={yes_no(report.halt_changed)}. "
        f"Owner approved={yes_no(report.owner_approved)}. "
        f"Execution allowed={yes_no(report.execution_allowed)}. "
        f"Supervised validation run permitted="
        f"{yes_no(report.supervised_validation_run_permitted)}. "
        f"Contact validation is not outbound="
        f"{yes_no(report.contact_validation_is_not_outbound)}. "
        f"Contact validation is not a live send="
        f"{yes_no(report.contact_validation_is_not_live_send)}. "
        f"NO_CONTACT_FOUND is failure="
        f"{yes_no(report.no_contact_found_is_failure)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "build, publish, deploy, campaign, booking, call, spend, candidate "
        "selection, send, or contact controls on this page. This is a "
        "read-only aggregate review view, not permission to run a "
        "supervised 200-practice validation, and not an execution surface. "
        "Current route "
        f"{html_escape(OPERATOR_CONTACT_VALIDATION_PATH)}.</p>\n"
        "    </footer>"
    )


def _render_count_map(items: dict[str, int], *, empty: str) -> str:
    present = [(key, count) for key, count in items.items() if key]
    if not present:
        return f'<p class="empty-state">{escape(empty)}</p>'
    rows = "".join(
        (
            "<tr>"
            f'<td class="mono">{html_escape(key)}</td>'
            f"<td>{html_escape(count)}</td>"
            "</tr>"
        )
        for key, count in present
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
        case FindingSeverity.BLOCKED.value | "failed" | "closed" | "missing":
            return "severity-blocked"
        case FindingSeverity.WARNING.value:
            return "severity-warning"
        case FindingSeverity.INFO.value | "ready_for_owner_review" | "passed" | "open":
            return "severity-info"
        case _:
            return "severity-info"
