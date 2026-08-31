"""Read-only operator dashboard UI shell.

Phase 20 renders the sanitized Phase 19 command-center summary as an
internal HTML page. It never sends email, enrolls campaigns, generates
sendable replies, books meetings, creates video-meet links, places calls,
publishes content, launches ads, spends money, deploys, applies optimizer
recommendations, or changes live/scoring/campaign/provider/deployment
settings or operator halt state.
"""

from __future__ import annotations

from html import escape
from typing import Literal
from uuid import UUID

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.command_center import (
    ApprovalPacketSummaryResponse,
    CommandCenterResponse,
    FindingCountsResponse,
    NextActionResponse,
    OutstandingReviewResponse,
    PipelineCountsResponse,
    build_command_center_response,
)
from vyro_growth.api.monitoring import (
    LatestJobStatusResponse,
    MonitoringReadinessResponse,
    MonitoringSafetyResponse,
    OperationalFindingResponse,
    SanitizedFailureResponse,
)
from vyro_growth.api.operator_ui import (
    OPERATOR_APPROVAL_PACKETS_PATH,
    OPERATOR_REVIEW_QUEUE_PATH,
)
from vyro_growth.config import Settings
from vyro_growth.observability import sanitize_operator_text
from vyro_growth.services.command_center import OperatorCommandCenterService

logger = structlog.get_logger(__name__)

OPERATOR_DASHBOARD_PATH = "/internal/operator-dashboard"
COMMAND_CENTER_JSON_PATH = "/internal/operator-command-center"
_NO_STORE = {"Cache-Control": "no-store"}
DashboardSection = Literal[
    "all",
    "safety",
    "pipeline",
    "runs",
    "review",
    "packets",
    "findings",
    "actions",
]
_DASHBOARD_SECTIONS: tuple[DashboardSection, ...] = (
    "all",
    "safety",
    "pipeline",
    "runs",
    "review",
    "packets",
    "findings",
    "actions",
)
_SECTION_LABELS: dict[DashboardSection, str] = {
    "all": "All",
    "safety": "Safety",
    "pipeline": "Pipeline",
    "runs": "Runs",
    "review": "Review",
    "packets": "Packets",
    "findings": "Findings",
    "actions": "Next actions",
}
_PIPELINE_FIELDS: tuple[tuple[str, str], ...] = (
    ("organizations", "Organizations"),
    ("leads", "Leads"),
    ("discovery_runs", "Discovery runs"),
    ("website_enrichment_runs", "Website enrichment"),
    ("decision_maker_contacts", "Decision-maker contacts"),
    ("latest_scores", "Latest scores"),
    ("personalization_drafts", "Personalization drafts"),
    ("outreach_plans_planned", "Outreach plans"),
    ("reply_classifications", "Reply classifications"),
    ("booking_plans", "Booking plans"),
    ("voice_qualification_plans", "Voice plans"),
    ("optimizer_recommendations", "Optimizer recommendations"),
    ("channel_plans", "Channel plans"),
    ("content_briefs", "Content briefs"),
    ("execution_plans", "Execution plans"),
    ("approval_packets", "Approval packets"),
)
_FAILURE_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Operator dashboard unavailable</title>
  <style>
    :root { color-scheme: dark; }
    body {
      margin: 0; font: 13px/1.45 ui-sans-serif, system-ui, sans-serif;
      background: #14161a; color: #e6e8eb;
    }
    main { max-width: 40rem; margin: 4rem auto; padding: 0 1.25rem; }
    h1 { font-size: 1.1rem; font-weight: 600; margin: 0 0 0.5rem; }
    p { margin: 0.4rem 0; color: #8b929c; }
    .banner {
      border: 1px solid #5a2a2a; background: #2a1616; color: #e8c4c4;
      padding: 0.75rem 0.9rem; border-radius: 4px; margin-bottom: 1rem;
    }
  </style>
</head>
<body>
  <main id="operator-dashboard-error">
    <div class="banner">Unable to load the operator dashboard.</div>
    <h1>Read-only view unavailable</h1>
    <p>The sanitized command-center summary could not be rendered.
    No pipeline rows were written and no outbound, booking, calling,
    publish, spend, or deploy action was executed.</p>
    <p>Retry after checking database connectivity and runtime config. Operator
    halt state was not changed.</p>
  </main>
</body>
</html>
"""


def parse_dashboard_section(value: str | None) -> DashboardSection:
    match value:
        case (
            "all"
            | "safety"
            | "pipeline"
            | "runs"
            | "review"
            | "packets"
            | "findings"
            | "actions"
        ):
            return value
        case None:
            return "all"
        case _:
            return "all"


def render_operator_dashboard_error() -> str:
    return _FAILURE_PAGE


def render_operator_dashboard(
    summary: CommandCenterResponse,
    *,
    section: DashboardSection = "all",
) -> str:
    title = "Operator dashboard"
    generated = _safe(_format_dt(summary.generated_at))
    findings = _render_findings(summary.finding_counts, summary.findings)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{escape(title)}</title>\n"
        f"{_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-dashboard" data-read-only="true">\n'
        f"{_render_header(summary, section)}\n"
        f"{_render_status_strip(summary)}\n"
        f"{_maybe(section, 'safety', _render_safety(summary.safety, summary.readiness))}\n"
        f"{_maybe(section, 'pipeline', _render_pipeline(summary.pipeline))}\n"
        f"{_maybe(section, 'runs', _render_runs(summary.latest_runs, summary.recent_failures))}\n"
        f"{_maybe(section, 'review', _render_review(summary.outstanding_review))}\n"
        f"{_maybe(section, 'packets', _render_packets(summary.approval_packets))}\n"
        f"{_maybe(section, 'findings', findings)}\n"
        f"{_maybe(section, 'actions', _render_actions(summary.next_actions))}\n"
        f"{_render_footer(summary, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_dashboard_response(
    db: Session,
    settings: Settings,
    *,
    section: str | None = None,
    service: OperatorCommandCenterService | None = None,
) -> HTMLResponse:
    try:
        summary = build_command_center_response(db, settings, service=service)
        html = render_operator_dashboard(summary, section=parse_dashboard_section(section))
        return HTMLResponse(content=html, status_code=200, headers=_NO_STORE)
    except Exception:
        logger.exception("operator_dashboard_render_failed", read_only=True)
        return HTMLResponse(
            content=render_operator_dashboard_error(),
            status_code=500,
            headers=_NO_STORE,
        )


def _maybe(section: DashboardSection, name: DashboardSection, markup: str) -> str:
    if section in {"all", name}:
        return markup
    return ""


def _render_header(summary: CommandCenterResponse, section: DashboardSection) -> str:
    links = []
    for name in _DASHBOARD_SECTIONS:
        label = _SECTION_LABELS[name]
        href = (
            OPERATOR_DASHBOARD_PATH
            if name == "all"
            else f"{OPERATOR_DASHBOARD_PATH}?section={name}"
        )
        current = ' aria-current="page"' if name == section else ""
        cls = "nav-link is-current" if name == section else "nav-link"
        links.append(f'<a class="{cls}" href="{escape(href)}"{current}>{escape(label)}</a>')
    json_href = escape(COMMAND_CENTER_JSON_PATH)
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Operator dashboard</h1>\n"
        '        <p class="lede">Read-only command-center view. No execution.</p>\n'
        "      </div>\n"
        f'      <p class="meta">Generated {_safe(_format_dt(summary.generated_at))}</p>\n'
        "    </header>\n"
        '    <nav class="section-nav" aria-label="Operator surfaces">'
        f'<a class="nav-link is-current" href="{escape(OPERATOR_DASHBOARD_PATH)}" '
        'aria-current="page">Dashboard</a> '
        f'<a class="nav-link" href="{escape(OPERATOR_REVIEW_QUEUE_PATH)}">'
        "Review queue</a> "
        f'<a class="nav-link" href="{escape(OPERATOR_APPROVAL_PACKETS_PATH)}">'
        "Approval packets</a>\n"
        "    </nav>\n"
        f'    <nav class="section-nav" aria-label="Dashboard sections">{" ".join(links)}\n'
        f'      <a class="nav-link nav-json" href="{json_href}">JSON summary</a>\n'
        "    </nav>"
    )


def _render_status_strip(summary: CommandCenterResponse) -> str:
    severity = summary.overall_severity
    halt = summary.safety.operator_halt_status
    outbound = "disabled" if not summary.safety.outbound_enabled else "enabled"
    ready = "ready" if summary.readiness.ready_for_manual_rollout else "not ready"
    return (
        f'    <section class="status-strip severity-{escape(severity)}" '
        'id="overall-status" aria-label="Overall status">\n'
        f'      <div class="pill severity-{escape(severity)}">'
        f'<span class="lbl">Overall</span> {_safe(severity)}</div>\n'
        f'      <div class="pill"><span class="lbl">Readiness</span> {_safe(ready)}</div>\n'
        f'      <div class="pill flag-{"off" if outbound == "disabled" else "on"}">'
        f'<span class="lbl">Outbound</span> {_safe(outbound)}</div>\n'
        f'      <div class="pill"><span class="lbl">Operator halt</span> {_safe(halt)}</div>\n'
        '      <div class="pill"><span class="lbl">Mode</span> read-only</div>\n'
        "    </section>"
    )


def _render_safety(
    safety: MonitoringSafetyResponse, readiness: MonitoringReadinessResponse
) -> str:
    provider_flags = "".join(
        f"<li><span>{_titleize(key)}</span><strong>{_flag(value)}</strong></li>"
        for key, value in sorted(safety.live_providers.items())
    )
    if not provider_flags:
        provider_flags = "<li class=\"empty\">No live-provider flags reported.</li>"
    issues = "".join(f"<li>{_safe(issue)}</li>" for issue in readiness.config_issues)
    if not issues:
        issues = "<li class=\"empty\">No config issues.</li>"
    halt_reason = (
        f"<p class=\"hint\">Halt reason: {_safe(safety.operator_halt_reason)}</p>"
        if safety.operator_halt_reason
        else ""
    )
    return (
        '    <section id="safety" class="panel">\n'
        "      <h2>Safety and readiness</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {_metric('Outbound', 'disabled' if not safety.outbound_enabled else 'enabled')}\n"
        f"        {_metric('Settings halt', _flag(safety.outbound_halted_settings))}\n"
        f"        {_metric('Operator halt', safety.operator_halt_status)}\n"
        f"        {_metric('Live providers', _flag(safety.live_providers_enabled))}\n"
        f"        {_metric('Calendar events', safety.live_calendar_events)}\n"
        f"        {_metric('Video-meet links', safety.live_meet_links)}\n"
        f"        {_metric('Phone calls', safety.live_phone_calls)}\n"
        f"        {_metric('Live send attempts', safety.live_send_attempted_enrollments)}\n"
        f"        {_metric('Environment', readiness.environment)}\n"
        f"        {_metric('Database', readiness.database)}\n"
        f"        {_metric('Config', 'ok' if readiness.config_ok else 'not ready')}\n"
        f"        {_metric('Manual rollout', _yes(readiness.ready_for_manual_rollout))}\n"
        "      </div>\n"
        f"      {halt_reason}\n"
        "      <h3>Live-provider flags</h3>\n"
        f'      <ul class="kv-list">{provider_flags}</ul>\n'
        "      <h3>Config issues</h3>\n"
        f'      <ul class="plain">{issues}</ul>\n'
        "    </section>"
    )


def _render_pipeline(pipeline: PipelineCountsResponse) -> str:
    if _pipeline_empty(pipeline):
        return (
            '    <section id="pipeline" class="panel">\n'
            "      <h2>Pipeline</h2>\n"
            '      <p class="empty-state" id="empty-pipeline">No pipeline activity yet. '
            "Counts stay at zero until a dry-run job writes stored rows. "
            "This page does not start discovery or any other job.</p>\n"
            "    </section>"
        )
    cards = "\n".join(
        f"        {_metric(label, getattr(pipeline, field))}" for field, label in _PIPELINE_FIELDS
    )
    return (
        '    <section id="pipeline" class="panel">\n'
        "      <h2>Pipeline counts</h2>\n"
        f'      <div class="metric-grid">\n{cards}\n      </div>\n'
        "    </section>"
    )


def _render_runs(
    runs: list[LatestJobStatusResponse],
    failures: list[SanitizedFailureResponse],
) -> str:
    if not runs:
        body = (
            '<p class="empty-state" id="empty-runs">No latest-run rows. '
            "Phases remain unseen until a stored job writes an audit row.</p>"
        )
    elif all(run.status == "not_started" or run.status is None for run in runs):
        body = (
            '<p class="empty-state" id="empty-runs">No jobs have started. '
            "Latest-run status is not_started for every phase.</p>"
            + _runs_table(runs)
        )
    else:
        body = _runs_table(runs)
    if not failures:
        fail_block = '<p class="empty-state">No recent sanitized failures.</p>'
    else:
        rows = "".join(
            "<tr>"
            f"<td>{_titleize(item.phase)}</td>"
            f"<td>{_safe(item.status)}</td>"
            f"<td>{_safe(_format_dt(item.occurred_at))}</td>"
            f"<td>{_safe(item.error_message, empty='redacted or none')}</td>"
            "</tr>"
            for item in failures
        )
        fail_block = (
            '<table class="dense"><thead><tr>'
            "<th>Phase</th><th>Status</th><th>When</th><th>Sanitized error</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section id="runs" class="panel">\n'
        "      <h2>Latest run statuses</h2>\n"
        f"      {body}\n"
        "      <h3>Recent failures</h3>\n"
        f"      {fail_block}\n"
        "    </section>"
    )


def _runs_table(runs: list[LatestJobStatusResponse]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{_titleize(run.phase)}</td>"
        f"<td>{_safe(run.status, empty='not started')}</td>"
        f"<td>{_safe(_format_dt(run.started_at))}</td>"
        f"<td>{_safe(_format_dt(run.finished_at))}</td>"
        f"<td class=\"mono\">{_safe(_short_id(run.run_id))}</td>"
        "</tr>"
        for run in runs
    )
    return (
        '<table class="dense"><thead><tr>'
        "<th>Phase</th><th>Status</th><th>Started</th><th>Finished</th><th>Run</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _render_review(review: OutstandingReviewResponse) -> str:
    if review.pending_count == 0 and review.decided_count == 0:
        extra = (
            '<p class="empty-state" id="empty-review">No outstanding review items. '
            "Pending dry-run artifacts will appear here after they are stored.</p>"
        )
    else:
        extra = ""
    by_type = "".join(
        f"<li><span>{_titleize(key)}</span><strong>{_safe(count)}</strong></li>"
        for key, count in sorted(review.by_artifact_type.items())
    )
    if not by_type:
        by_type = '<li class="empty">No pending artifact types.</li>'
    return (
        '    <section id="review" class="panel">\n'
        "      <h2>Outstanding review</h2>\n"
        f'      <p class="hint"><a class="nav-link" href="{escape(OPERATOR_REVIEW_QUEUE_PATH)}">'
        "Open review queue</a> — read-only list and detail. No approve or execute controls.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {_metric('Pending', review.pending_count)}\n"
        f"        {_metric('Decided', review.decided_count)}\n"
        f"        {_metric('Approved', review.approved_count)}\n"
        f"        {_metric('Rejected', review.rejected_count)}\n"
        f"        {_metric('Needs changes', review.needs_changes_count)}\n"
        f"        {_metric('Executed', review.executed_count)}\n"
        "      </div>\n"
        f"      {extra}\n"
        "      <h3>Pending by type</h3>\n"
        f'      <ul class="kv-list">{by_type}</ul>\n'
        "    </section>"
    )


def _render_packets(packets: ApprovalPacketSummaryResponse) -> str:
    if packets.packets == 0:
        extra = (
            '<p class="empty-state" id="empty-packets">No owner approval packets or '
            "preflight rows yet. Generation is a separate dry-run command and is "
            "not started from this page.</p>"
        )
    else:
        extra = ""
    preflight = "".join(
        f"<li><span>{_titleize(key)}</span><strong>{_safe(count)}</strong></li>"
        for key, count in sorted(packets.by_preflight_status.items())
    )
    if not preflight:
        preflight = '<li class="empty">No preflight statuses.</li>'
    families = "".join(
        f"<li><span>{_titleize(key)}</span><strong>{_safe(count)}</strong></li>"
        for key, count in sorted(packets.by_plan_family.items())
    )
    if not families:
        families = '<li class="empty">No plan families.</li>'
    return (
        '    <section id="packets" class="panel">\n'
        "      <h2>Approval packets and preflight</h2>\n"
        f'      <p class="hint"><a class="nav-link" '
        f'href="{escape(OPERATOR_APPROVAL_PACKETS_PATH)}">'
        "Open approval packets</a> — read-only list and detail. "
        "No approve or execute controls.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {_metric('Packets', packets.packets)}\n"
        f"        {_metric('Owner approved', packets.owner_approved)}\n"
        f"        {_metric('Executed', packets.executed)}\n"
        f"        {_metric('Latest run', packets.latest_run_status)}\n"
        "      </div>\n"
        f"      {extra}\n"
        "      <h3>Preflight status</h3>\n"
        f'      <ul class="kv-list">{preflight}</ul>\n'
        "      <h3>Plan families</h3>\n"
        f'      <ul class="kv-list">{families}</ul>\n'
        "    </section>"
    )


def _render_findings(
    counts: FindingCountsResponse, findings: list[OperationalFindingResponse]
) -> str:
    if counts.total == 0:
        body = (
            '<p class="empty-state" id="empty-findings">No blocked, warning, or info '
            "findings. The command-center summary is empty of operational alerts.</p>"
        )
    else:
        items = "".join(
            f'<li class="finding severity-{escape(item.severity)}">'
            f'<span class="pill severity-{escape(item.severity)}">{_safe(item.severity)}</span> '
            f"<strong>{_titleize(item.code)}</strong>"
            f"{' · ' + _titleize(item.phase) if item.phase else ''} "
            f"<span>{_safe(item.message)}</span></li>"
            for item in findings
        )
        body = f'<ul class="findings">{items}</ul>'
    return (
        '    <section id="findings" class="panel">\n'
        "      <h2>Blocked / warning / info</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {_metric('Blocked', counts.blocked)}\n"
        f"        {_metric('Warning', counts.warning)}\n"
        f"        {_metric('Info', counts.info)}\n"
        f"        {_metric('Total', counts.total)}\n"
        "      </div>\n"
        f"      {body}\n"
        "    </section>"
    )


def _render_actions(actions: list[NextActionResponse]) -> str:
    if not actions:
        body = (
            '<p class="empty-state" id="empty-actions">No next-action labels. '
            "This page never executes an action.</p>"
        )
    else:
        items = "".join(
            f'<li class="action severity-{escape(item.severity)}">'
            f'<span class="pill severity-{escape(item.severity)}">{_safe(item.severity)}</span> '
            f"<span>{_safe(item.label)}</span></li>"
            for item in actions
        )
        body = f'<ul class="actions" id="next-actions">{items}</ul>'
    return (
        '    <section id="actions" class="panel">\n'
        "      <h2>Safe next-action labels</h2>\n"
        '      <p class="hint">Labels only. This page has no execute, send, enroll, '
        "book, call, publish, spend, or deploy controls.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _render_footer(summary: CommandCenterResponse, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={_yes(summary.read_only)}. "
        f"Executed={_safe(summary.executed_count)}. "
        f"Outbound attempted={_yes(summary.outbound_attempted)}. "
        f"Call attempted={_yes(summary.live_call_attempted)}. "
        f"Recommendation applied={_yes(summary.recommendation_applied)}. "
        f"Spend attempted={_yes(summary.spend_attempted)}. "
        f"Campaign launched={_yes(summary.campaign_launched)}. "
        f"Pages published={_yes(summary.pages_published)}. "
        f"Ads launched={_yes(summary.ads_launched)}.</p>\n"
        "    </footer>"
    )


def _pipeline_empty(pipeline: PipelineCountsResponse) -> bool:
    return all(getattr(pipeline, field) == 0 for field, _label in _PIPELINE_FIELDS)


def _metric(label: str, value: object) -> str:
    return (
        f'<div class="metric"><span class="lbl">{escape(label)}</span>'
        f"<strong>{_safe(value)}</strong></div>"
    )


def _titleize(value: str | None) -> str:
    if not value:
        return escape("—")
    cleaned = sanitize_operator_text(value.replace("_", " ")) or value
    return escape(cleaned)


def _flag(value: bool) -> str:
    return "on" if value else "off"


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def _short_id(value: UUID | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _format_dt(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text.replace("+00:00", "Z")


def _safe(value: object, *, empty: str = "—") -> str:
    if value is None:
        return escape(empty)
    if isinstance(value, bool):
        return escape(_yes(value))
    sanitized = sanitize_operator_text(str(value))
    if sanitized is None or sanitized == "":
        return escape(empty)
    return escape(sanitized)


_STYLES = """  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: #14161a;
      color: #e6e8eb;
      font: 12.5px/1.45 ui-sans-serif, system-ui, sans-serif;
    }
    main { max-width: 72rem; margin: 0 auto; padding: 1rem 1.1rem 2rem; }
    h1 { font-size: 1.15rem; font-weight: 650; margin: 0; }
    h2 { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em;
         margin: 0 0 0.65rem; color: #c5cad1; }
    h3 { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em;
         margin: 0.85rem 0 0.35rem; color: #8b929c; }
    .lede, .hint, .meta, .footnote p { color: #8b929c; margin: 0.2rem 0 0; }
    .page-header { display: flex; justify-content: space-between; gap: 1rem;
      align-items: baseline; margin-bottom: 0.65rem; }
    .section-nav { display: flex; flex-wrap: wrap; gap: 0.35rem; margin: 0 0 0.75rem; }
    .nav-link {
      color: #c5cad1; text-decoration: none; border: 1px solid #2a2f38;
      background: #1c1f26; padding: 0.2rem 0.5rem; border-radius: 3px;
    }
    .nav-link.is-current { border-color: #5b6b7c; color: #fff; }
    .nav-json { margin-left: auto; }
    .status-strip {
      display: flex; flex-wrap: wrap; gap: 0.4rem; padding: 0.55rem 0.65rem;
      border: 1px solid #2a2f38; background: #1c1f26; border-radius: 4px;
      margin-bottom: 0.75rem;
    }
    .pill { border: 1px solid #2a2f38; border-radius: 3px; padding: 0.15rem 0.45rem; }
    .pill .lbl, .metric .lbl { display: block; color: #8b929c; font-size: 0.68rem;
      text-transform: uppercase; letter-spacing: 0.04em; }
    .severity-blocked { border-color: #6d3030; }
    .severity-warning { border-color: #6d5a24; }
    .severity-info { border-color: #2f4458; }
    .flag-off { border-color: #2f4a38; }
    .flag-on { border-color: #6d3030; }
    .panel {
      border: 1px solid #2a2f38; background: #1c1f26; border-radius: 4px;
      padding: 0.7rem 0.8rem 0.85rem; margin-bottom: 0.65rem;
    }
    .metric-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr));
      gap: 0.45rem;
    }
    .metric { border: 1px solid #262b33; border-radius: 3px; padding: 0.35rem 0.45rem; }
    .metric strong { font-size: 0.95rem; font-weight: 650; }
    table.dense { width: 100%; border-collapse: collapse; }
    table.dense th, table.dense td {
      text-align: left; padding: 0.28rem 0.35rem; border-bottom: 1px solid #262b33;
      vertical-align: top;
    }
    table.dense th { color: #8b929c; font-weight: 550; }
    .kv-list, .plain, .findings, .actions { list-style: none; margin: 0; padding: 0; }
    .kv-list li, .plain li { display: flex; justify-content: space-between; gap: 1rem;
      padding: 0.18rem 0; border-bottom: 1px solid #22262d; }
    .empty, .empty-state { color: #8b929c; }
    .empty-state { margin: 0.15rem 0 0; }
    .finding, .action { padding: 0.28rem 0; border-bottom: 1px solid #22262d; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.72rem; }
    .footnote { margin-top: 0.4rem; }
  </style>"""
