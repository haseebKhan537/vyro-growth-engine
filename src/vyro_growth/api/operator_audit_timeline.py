"""Read-only operator activity audit timeline HTML.

Phase 34 renders existing activity, audit, and decision records as an
internal chronological HTML page. It never executes outbound, booking,
calling, publish, spend, deploy, or optimizer-apply actions and never
changes operator halt or live settings.
"""

from __future__ import annotations

from html import escape

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.operator_ui import (
    NO_STORE_HEADERS,
    OPERATOR_AUDIT_TIMELINE_PATH,
    OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
    OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
    OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH,
    OPERATOR_OWNER_HANDOFF_PACKET_PATH,
    OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
    OPERATOR_RELEASE_CANDIDATE_RUNBOOK_PATH,
    OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
    OPERATOR_UI_STYLES,
    filter_link,
    format_dt,
    html_escape,
    metric,
    render_failure_page,
    render_operator_nav,
    short_id,
    titleize,
    yes_no,
)
from vyro_growth.config import Settings
from vyro_growth.services.operator_audit_timeline import (
    AUDIT_WINDOWS,
    DEFAULT_ENTRY_LIMIT,
    AuditTimelineEntry,
    AuditWindow,
    OperatorAuditTimeline,
    OperatorAuditTimelineService,
    parse_event_type,
    parse_source,
    parse_status,
    parse_window,
)

logger = structlog.get_logger(__name__)

_WINDOW_LABELS: dict[AuditWindow, str] = {
    "all": "All time",
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
}


def render_operator_audit_timeline_error() -> str:
    return render_failure_page(
        page_id="operator-audit-timeline-error",
        title="Operator audit timeline unavailable",
        heading="Read-only operator audit timeline unavailable",
        banner="Unable to load the operator activity audit timeline.",
        detail=(
            "The sanitized activity audit timeline could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page does not execute anything."
        ),
    )


def render_operator_audit_timeline(result: OperatorAuditTimeline) -> str:
    generated = html_escape(format_dt(result.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Operator activity audit timeline</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-audit-timeline" data-read-only="true" '
        'data-dry-run-only="true" data-no-execution="true">\n'
        f"{_render_header(result, generated)}\n"
        f"{render_operator_nav('audit-timeline')}\n"
        f"{_render_related_links()}\n"
        f"{_render_filters(result)}\n"
        f"{_render_summary(result)}\n"
        f"{_render_entries(result)}\n"
        f"{_render_footer(result, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_audit_timeline_response(
    db: Session,
    settings: Settings,
    *,
    event_type: str | None = None,
    source: str | None = None,
    status: str | None = None,
    window: str | None = None,
    service: OperatorAuditTimelineService | None = None,
) -> HTMLResponse:
    try:
        active = service or OperatorAuditTimelineService(limit=DEFAULT_ENTRY_LIMIT)
        result = active.timeline(
            db,
            settings,
            event_type=parse_event_type(event_type),
            source=parse_source(source),
            status=parse_status(status),
            window=parse_window(window),
        )
        html = render_operator_audit_timeline(result)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_audit_timeline_render_failed", read_only=True)
        return HTMLResponse(
            content=render_operator_audit_timeline_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(result: OperatorAuditTimeline, generated: str) -> str:
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Operator activity audit timeline</h1>\n"
        '        <p class="lede">Read-only chronological view of existing '
        "activity, audit, and decision records. This page does not execute, "
        "approve, apply, enroll, call, book, publish, spend, or deploy.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · halt '
        f"{html_escape(result.operator_halt_status)} · shown "
        f"{html_escape(result.shown_count)} of "
        f"{html_escape(result.matching_count)}</p>\n"
        "    </header>"
    )


def _render_related_links() -> str:
    handoff_href = escape(OPERATOR_OWNER_HANDOFF_PACKET_PATH)
    binder_href = escape(OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH)
    runbook_href = escape(OPERATOR_RELEASE_CANDIDATE_RUNBOOK_PATH)
    manifest_href = escape(OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH)
    index_href = escape(OPERATOR_GO_LIVE_READINESS_INDEX_PATH)
    plan_href = escape(OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH)
    staged_href = escape(OPERATOR_STAGED_ROLLOUT_PLAN_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Related read-only surfaces">\n'
        f'      <a class="nav-link" href="{handoff_href}">Owner handoff</a>\n'
        f'      <a class="nav-link" href="{binder_href}">Compliance binder</a>\n'
        f'      <a class="nav-link" href="{runbook_href}">Release runbook</a>\n'
        f'      <a class="nav-link" href="{manifest_href}">Release manifest</a>\n'
        f'      <a class="nav-link" href="{index_href}">Go-live index</a>\n'
        f'      <a class="nav-link" href="{plan_href}">Launch blockers</a>\n'
        f'      <a class="nav-link" href="{staged_href}">Staged rollout</a>\n'
        "    </nav>"
    )


def _render_filters(result: OperatorAuditTimeline) -> str:
    event_links = [
        filter_link(
            _list_href(None, result.source, result.status, result.window),
            "All event types",
            current=result.event_type is None,
        )
    ]
    for name in result.available_event_types:
        event_links.append(
            filter_link(
                _list_href(name, result.source, result.status, result.window),
                name.replace("_", " "),
                current=result.event_type == name,
            )
        )
    source_links = [
        filter_link(
            _list_href(result.event_type, None, result.status, result.window),
            "All sources",
            current=result.source is None,
        )
    ]
    for name in result.available_sources:
        source_links.append(
            filter_link(
                _list_href(result.event_type, name, result.status, result.window),
                name.replace("_", " "),
                current=result.source == name,
            )
        )
    status_links = [
        filter_link(
            _list_href(result.event_type, result.source, None, result.window),
            "All statuses",
            current=result.status is None,
        )
    ]
    for name in result.available_statuses:
        status_links.append(
            filter_link(
                _list_href(result.event_type, result.source, name, result.window),
                name.replace("_", " "),
                current=result.status == name,
            )
        )
    window_links = []
    for name in AUDIT_WINDOWS:
        window_links.append(
            filter_link(
                _list_href(result.event_type, result.source, result.status, name),
                _WINDOW_LABELS[name],
                current=result.window == name,
            )
        )
    return (
        '    <nav class="filter-nav" aria-label="Event type filters">'
        f"{' '.join(event_links)}</nav>\n"
        '    <nav class="filter-nav" aria-label="Source filters">'
        f"{' '.join(source_links)}</nav>\n"
        '    <nav class="filter-nav" aria-label="Status and decision filters">'
        f"{' '.join(status_links)}</nav>\n"
        '    <nav class="filter-nav" aria-label="Date window filters">'
        f"{' '.join(window_links)}</nav>"
    )


def _list_href(
    event_type: str | None,
    source: str | None,
    status: str | None,
    window: AuditWindow,
) -> str:
    params: list[str] = []
    if event_type:
        params.append(f"event_type={event_type}")
    if source:
        params.append(f"source={source}")
    if status:
        params.append(f"status={status}")
    if window != "all":
        params.append(f"window={window}")
    if not params:
        return OPERATOR_AUDIT_TIMELINE_PATH
    return f"{OPERATOR_AUDIT_TIMELINE_PATH}?{'&'.join(params)}"


def _render_summary(result: OperatorAuditTimeline) -> str:
    return (
        '    <section class="status-strip" aria-label="Timeline counts">\n'
        f"      {metric('Matching', result.matching_count)}\n"
        f"      {metric('Shown', result.shown_count)}\n"
        f"      {metric('Truncated', yes_no(result.truncated))}\n"
        f"      {metric('Read only', yes_no(result.read_only))}\n"
        f"      {metric('No execution', yes_no(result.no_execution))}\n"
        f"      {metric('Executed', result.executed)}\n"
        f"      {metric('Outbound enabled', yes_no(result.outbound_enabled))}\n"
        f"      {metric('Operator halt', result.operator_halt_status)}\n"
        "    </section>\n"
        '    <section class="panel">\n'
        "      <h2>Safety posture</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Dry-run only', yes_no(result.dry_run_only))}\n"
        f"        {metric('Live action', yes_no(result.live_action))}\n"
        f"        {metric('Outbound attempted', yes_no(result.outbound_attempted))}\n"
        f"        {metric('Owner approved live', yes_no(result.owner_approved))}\n"
        f"        {metric('Settings applied', yes_no(result.settings_applied))}\n"
        f"        {metric('Halt changed', yes_no(result.halt_changed))}\n"
        f"        {metric('Halt before', result.operator_halt_before)}\n"
        f"        {metric('Halt after', result.operator_halt_after)}\n"
        "      </div>\n"
        '      <p class="hint">This page never shows secret values, environment '
        "values, API keys, tokens, message bodies, emails, phones, evidence "
        "snippets, PHI, or unsafe error text. Loading it does not write "
        "activity rows or change operator halt.</p>\n"
        "    </section>"
    )


def _render_entries(result: OperatorAuditTimeline) -> str:
    filtered = bool(result.event_type or result.source or result.status or result.window != "all")
    if not result.entries:
        if filtered:
            body = (
                '<p class="empty-state" id="empty-operator-audit-timeline">'
                "No activity, audit, or decision records match the current "
                "filters. This page does not create records or execute anything.</p>"
            )
        else:
            body = (
                '<p class="empty-state" id="empty-operator-audit-timeline">'
                "No activity, audit, or decision records yet. This read-only "
                "timeline does not start jobs, record decisions, or execute "
                "live actions.</p>"
            )
        return (
            '    <section class="panel">\n'
            "      <h2>Timeline</h2>\n"
            f"      {body}\n"
            "    </section>"
        )
    rows = "".join(_entry_row(item) for item in result.entries)
    truncated = (
        '<p class="hint">Showing the most recent sanitized entries. Older matching '
        "records remain stored and are not executed from this page.</p>\n"
        if result.truncated
        else ""
    )
    return (
        '    <section class="panel">\n'
        "      <h2>Timeline</h2>\n"
        f"      {truncated}"
        '      <table class="dense"><thead><tr>'
        "<th>When</th><th>Event</th><th>Source</th><th>Status</th>"
        "<th>IDs</th><th>Flags</th><th>Reason</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        "    </section>"
    )


def _entry_row(item: AuditTimelineEntry) -> str:
    ids = _id_summary(item)
    flags = (
        f"no-exec={yes_no(item.no_execution)} · "
        f"read-only={yes_no(item.read_only)} · "
        f"executed={yes_no(item.executed)}"
    )
    status = item.decision_status or item.status
    return (
        "<tr>"
        f"<td>{html_escape(format_dt(item.occurred_at))}</td>"
        f"<td>{titleize(item.event_type)}</td>"
        f"<td>{titleize(item.source_surface)}"
        f'<div class="meta">{html_escape(item.actor_label)}</div></td>'
        f"<td>{html_escape(status)}</td>"
        f'<td class="mono">{escape(ids)}</td>'
        f"<td>{html_escape(flags)}</td>"
        f"<td>{html_escape(item.reason_label)}</td>"
        "</tr>"
    )


def _id_summary(item: AuditTimelineEntry) -> str:
    parts: list[str] = []
    labeled = (
        ("lead", item.lead_id),
        ("org", item.organization_id),
        ("artifact", item.artifact_id),
        ("packet", item.packet_id),
        ("request", item.request_id),
        ("candidate", item.candidate_id),
        ("run", item.run_id),
    )
    for label, value in labeled:
        if value is None:
            continue
        parts.append(f"{label}={short_id(value)}")
    if item.artifact_type:
        parts.append(f"type={item.artifact_type}")
    return " · ".join(parts) if parts else "—"


def _render_footer(result: OperatorAuditTimeline, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={yes_no(result.read_only)}. "
        f"Dry-run only={yes_no(result.dry_run_only)}. "
        f"No execution={yes_no(result.no_execution)}. "
        f"Executed={html_escape(result.executed)}. "
        f"Settings applied={yes_no(result.settings_applied)}. "
        f"Halt changed={yes_no(result.halt_changed)}. "
        f"Owner approved={yes_no(result.owner_approved)}. "
        f"Live action={yes_no(result.live_action)}. "
        f"Outbound attempted={yes_no(result.outbound_attempted)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "deploy, campaign, booking, call, publish, or spend controls on this "
        "page. This is a read-only audit timeline, not permission to go live.</p>\n"
        "    </footer>"
    )
