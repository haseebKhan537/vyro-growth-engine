"""Read-only approved action readiness HTML queue.

Phase 24 renders stored review, plan, packet, and packet-decision records as
internal HTML pages. It never generates artifacts, never executes an approved
item or packet, and never changes live/scoring/campaign/provider/deployment
settings or operator halt state.
"""

from __future__ import annotations

from html import escape
from typing import Never
from uuid import UUID

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.action_readiness import (
    ActionReadinessCandidateResponse,
    ActionReadinessQueueResponse,
    build_action_readiness_response,
    candidate_to_response,
)
from vyro_growth.api.operator_ui import (
    ACTION_READINESS_JSON_PATH,
    NO_STORE_HEADERS,
    OPERATOR_ACTION_READINESS_PATH,
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
from vyro_growth.domain import (
    ActionDecisionStatus,
    ActionReadinessBlockerStatus,
    ActionReadinessStatus,
    ExecutionPlanType,
)
from vyro_growth.services.action_readiness import ActionReadinessService

logger = structlog.get_logger(__name__)

_PLAN_FAMILIES: tuple[str, ...] = tuple(item.value for item in ExecutionPlanType)
_READINESS_STATUSES: tuple[str, ...] = tuple(item.value for item in ActionReadinessStatus)
_BLOCKER_STATUSES: tuple[str, ...] = tuple(item.value for item in ActionReadinessBlockerStatus)
_DECISION_STATUSES: tuple[str, ...] = tuple(item.value for item in ActionDecisionStatus)


def parse_plan_family(value: str | None) -> str | None:
    return _parse_allowed(value, _PLAN_FAMILIES)


def parse_readiness_status(value: str | None) -> str | None:
    return _parse_allowed(value, _READINESS_STATUSES)


def parse_blocker_status(value: str | None) -> str | None:
    return _parse_allowed(value, _BLOCKER_STATUSES)


def parse_decision_status(value: str | None) -> str | None:
    return _parse_allowed(value, _DECISION_STATUSES)


def candidate_href(candidate_id: UUID) -> str:
    return f"{OPERATOR_ACTION_READINESS_PATH}/{candidate_id}"


def render_action_readiness_error() -> str:
    return render_failure_page(
        page_id="operator-action-readiness-error",
        title="Action readiness unavailable",
        heading="Read-only action readiness unavailable",
        banner="Unable to load the approved action readiness queue.",
        detail=(
            "The sanitized readiness queue could not be rendered. "
            "Retry after checking database connectivity and runtime config."
        ),
    )


def render_action_readiness_missing() -> str:
    return render_failure_page(
        page_id="operator-action-readiness-missing",
        title="Readiness candidate not found",
        heading="Readiness candidate not found",
        banner="No matching approved-action candidate is available.",
        detail=(
            "The requested candidate id is unknown or no longer present. "
            "This page does not invent facts or execute any action."
        ),
    )


def render_action_readiness_list(
    queue: ActionReadinessQueueResponse,
    *,
    plan_family: str | None,
    readiness_status: str | None,
    blocker_status: str | None,
    decision_status: str | None,
    candidates: list[ActionReadinessCandidateResponse],
) -> str:
    generated = html_escape(format_dt(queue.generated_at))
    candidates_html = _render_candidates(
        candidates,
        plan_family=plan_family,
        readiness_status=readiness_status,
        blocker_status=blocker_status,
        decision_status=decision_status,
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Approved action readiness</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-action-readiness" data-read-only="true">\n'
        f"{_render_list_header(queue, generated)}\n"
        f"{render_operator_nav('action-readiness')}\n"
        f"{_render_filters(plan_family, readiness_status, blocker_status, decision_status)}\n"
        f"{_render_summary(queue)}\n"
        f"{candidates_html}\n"
        f"{_render_list_footer(queue, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def render_action_readiness_detail(item: ActionReadinessCandidateResponse) -> str:
    generated = html_escape(format_dt(item.generated_at))
    owner_action_metric = metric(
        "Explicit owner action required",
        yes_no(item.explicit_live_owner_action_required),
    )
    missing_codes = item.missing_approval_codes + item.missing_prerequisite_codes
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Action readiness candidate</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-action-readiness-item" data-read-only="true">\n'
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Action readiness candidate</h1>\n"
        '        <p class="lede">Read-only readiness view. Explicit owner action is '
        "still required before any future live execution. No execution.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated}</p>\n'
        "    </header>\n"
        f"{render_operator_nav('action-readiness')}\n"
        '    <section class="panel">\n'
        "      <h2>Safe detail</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Candidate id', short_id(item.candidate_id))}\n"
        f"        {metric('Plan family', item.plan_family)}\n"
        f"        {metric('Artifact type', item.artifact_type)}\n"
        f"        {metric('Artifact id', short_id(item.artifact_id))}\n"
        f"        {metric('Execution plan id', short_id(item.execution_plan_id))}\n"
        f"        {metric('Approval packet id', short_id(item.approval_packet_id))}\n"
        f"        {metric('Review decision', item.review_decision_status)}\n"
        f"        {metric('Packet decision', item.packet_decision_status)}\n"
        f"        {metric('Preflight status', item.preflight_status)}\n"
        f"        {metric('Readiness', item.readiness_status)}\n"
        f"        {metric('Blocker status', item.blocker_status)}\n"
        f"        {metric('Dry-run only', yes_no(item.dry_run_only))}\n"
        f"        {metric('No execution', yes_no(item.no_execution))}\n"
        f"        {metric('Executed', yes_no(item.executed))}\n"
        f"        {metric('Live action', yes_no(item.live_action))}\n"
        f"        {metric('Owner approved live', yes_no(item.owner_approved))}\n"
        f"        {owner_action_metric}\n"
        "      </div>\n"
        f'      <p class="hint">Label: {html_escape(item.sanitized_label)}</p>\n'
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(item.blocker_codes, empty='No extra blocker codes.')}\n"
        "      <h3>Missing approval or prerequisite codes</h3>\n"
        f"      {_render_codes(missing_codes, empty='None missing.')}\n"
        '      <p class="hint">This page has no execute, send, enroll, book, call, '
        "publish, spend, or deploy controls. A ready-like status still requires a "
        "future explicit owner action before live execution.</p>\n"
        "    </section>\n"
        '    <p><a class="nav-link" href="'
        f'{escape(OPERATOR_ACTION_READINESS_PATH)}">Back to readiness queue</a></p>\n'
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_action_readiness_response(
    db: Session,
    settings: Settings,
    *,
    plan_family: str | None = None,
    readiness_status: str | None = None,
    blocker_status: str | None = None,
    decision_status: str | None = None,
    service: ActionReadinessService | None = None,
) -> HTMLResponse:
    try:
        parsed_family = parse_plan_family(plan_family)
        parsed_readiness = parse_readiness_status(readiness_status)
        parsed_blocker = parse_blocker_status(blocker_status)
        parsed_decision = parse_decision_status(decision_status)
        queue = build_action_readiness_response(
            db,
            settings,
            plan_family=parsed_family,
            readiness_status=parsed_readiness,
            blocker_status=parsed_blocker,
            decision_status=parsed_decision,
            service=service,
        )
        html = render_action_readiness_list(
            queue,
            plan_family=parsed_family,
            readiness_status=parsed_readiness,
            blocker_status=parsed_blocker,
            decision_status=parsed_decision,
            candidates=queue.candidates,
        )
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_action_readiness_render_failed", read_only=True)
        return HTMLResponse(
            content=render_action_readiness_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def build_operator_action_readiness_item_response(
    db: Session,
    settings: Settings,
    *,
    candidate_id: str,
    service: ActionReadinessService | None = None,
) -> HTMLResponse:
    try:
        try:
            parsed_id = UUID(candidate_id)
        except ValueError:
            parsed_id = None
        if parsed_id is None:
            return HTMLResponse(
                content=render_action_readiness_missing(),
                status_code=404,
                headers=NO_STORE_HEADERS,
            )
        queue = service or ActionReadinessService()
        item = queue.get_candidate(db, settings, parsed_id)
        if item is None:
            return HTMLResponse(
                content=render_action_readiness_missing(),
                status_code=404,
                headers=NO_STORE_HEADERS,
            )
        html = render_action_readiness_detail(candidate_to_response(item))
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_action_readiness_item_render_failed", read_only=True)
        return HTMLResponse(
            content=render_action_readiness_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _parse_allowed(value: str | None, allowed: tuple[str, ...]) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    if cleaned in allowed:
        return cleaned
    return None


def _render_list_header(queue: ActionReadinessQueueResponse, generated: str) -> str:
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Approved action readiness</h1>\n"
        '        <p class="lede">Read-only queue over stored review, plan, and packet '
        "records. Ready-like items still require a future explicit owner action. "
        "No execution.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · halt '
        f"{html_escape(queue.operator_halt_status)}</p>\n"
        "    </header>"
    )


def _render_filters(
    plan_family: str | None,
    readiness_status: str | None,
    blocker_status: str | None,
    decision_status: str | None,
) -> str:
    family_links = [
        filter_link(
            _list_href(None, readiness_status, blocker_status, decision_status),
            "All families",
            current=plan_family is None,
        )
    ]
    for name in _PLAN_FAMILIES:
        family_links.append(
            filter_link(
                _list_href(name, readiness_status, blocker_status, decision_status),
                name.replace("_", " "),
                current=plan_family == name,
            )
        )
    readiness_links = [
        filter_link(
            _list_href(plan_family, None, blocker_status, decision_status),
            "All readiness",
            current=readiness_status is None,
        )
    ]
    for name in _READINESS_STATUSES:
        readiness_links.append(
            filter_link(
                _list_href(plan_family, name, blocker_status, decision_status),
                name.replace("_", " "),
                current=readiness_status == name,
            )
        )
    blocker_links = [
        filter_link(
            _list_href(plan_family, readiness_status, None, decision_status),
            "All blockers",
            current=blocker_status is None,
        )
    ]
    for name in _BLOCKER_STATUSES:
        blocker_links.append(
            filter_link(
                _list_href(plan_family, readiness_status, name, decision_status),
                name.replace("_", " "),
                current=blocker_status == name,
            )
        )
    decision_links = [
        filter_link(
            _list_href(plan_family, readiness_status, blocker_status, None),
            "All decisions",
            current=decision_status is None,
        )
    ]
    for name in _DECISION_STATUSES:
        decision_links.append(
            filter_link(
                _list_href(plan_family, readiness_status, blocker_status, name),
                name.replace("_", " "),
                current=decision_status == name,
            )
        )
    json_href = escape(ACTION_READINESS_JSON_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Plan family filters">'
        f"{' '.join(family_links)}</nav>\n"
        '    <nav class="filter-nav" aria-label="Readiness status filters">'
        f"{' '.join(readiness_links)}</nav>\n"
        '    <nav class="filter-nav" aria-label="Blocker status filters">'
        f"{' '.join(blocker_links)}</nav>\n"
        '    <nav class="filter-nav" aria-label="Decision status filters">'
        f"{' '.join(decision_links)}\n"
        f'      <a class="nav-link nav-json" href="{json_href}">JSON queue</a>\n'
        "    </nav>"
    )


def _list_href(
    plan_family: str | None,
    readiness_status: str | None,
    blocker_status: str | None,
    decision_status: str | None,
) -> str:
    params: list[str] = []
    if plan_family:
        params.append(f"plan_family={plan_family}")
    if readiness_status:
        params.append(f"readiness_status={readiness_status}")
    if blocker_status:
        params.append(f"blocker_status={blocker_status}")
    if decision_status:
        params.append(f"decision_status={decision_status}")
    if not params:
        return OPERATOR_ACTION_READINESS_PATH
    return f"{OPERATOR_ACTION_READINESS_PATH}?{'&'.join(params)}"


def _render_summary(queue: ActionReadinessQueueResponse) -> str:
    readiness_items = _kv_items(queue.by_readiness_status, empty="No readiness statuses.")
    family_items = _kv_items(queue.by_plan_family, empty="No plan families.")
    owner_action_metric = metric(
        "Explicit owner action required",
        yes_no(queue.explicit_live_owner_action_required),
    )
    return (
        '    <section class="status-strip" aria-label="Readiness counts">\n'
        f"      {metric('Candidates', queue.candidate_count)}\n"
        f"      {metric('Executed', queue.executed_count)}\n"
        f"      {metric('Dry-run only', yes_no(queue.dry_run_only))}\n"
        f"      {metric('No execution', yes_no(queue.no_execution))}\n"
        f"      {metric('Live action', yes_no(queue.live_action))}\n"
        f"      {owner_action_metric}\n"
        "    </section>\n"
        '    <section class="panel">\n'
        "      <h2>Queue summary</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Operator halt', queue.operator_halt_status)}\n"
        f"        {metric('Read-only', yes_no(queue.read_only))}\n"
        f"        {metric('Outbound attempted', yes_no(queue.outbound_attempted))}\n"
        "      </div>\n"
        "      <h3>Readiness status</h3>\n"
        f'      <ul class="kv-list">{readiness_items}</ul>\n'
        "      <h3>Plan families</h3>\n"
        f'      <ul class="kv-list">{family_items}</ul>\n'
        "    </section>"
    )


def _kv_items(counts: dict[str, int], *, empty: str) -> str:
    items = "".join(
        f"<li><span>{titleize(key)}</span><strong>{html_escape(count)}</strong></li>"
        for key, count in sorted(counts.items())
    )
    return items or f'<li class="empty">{escape(empty)}</li>'


def _render_candidates(
    candidates: list[ActionReadinessCandidateResponse],
    *,
    plan_family: str | None,
    readiness_status: str | None,
    blocker_status: str | None,
    decision_status: str | None,
) -> str:
    filtered = bool(plan_family or readiness_status or blocker_status or decision_status)
    if not candidates:
        if filtered:
            body = (
                '<p class="empty-state" id="empty-action-readiness">No readiness '
                "candidates match the current filters. This page does not generate "
                "plans or execute actions.</p>"
            )
        else:
            body = (
                '<p class="empty-state" id="empty-action-readiness">No approved-action '
                "readiness candidates yet. This queue only combines stored review, "
                "plan, and packet records and does not execute them.</p>"
            )
        return (
            '    <section class="panel">\n'
            "      <h2>Candidates</h2>\n"
            f"      {body}\n"
            "    </section>"
        )
    rows = "".join(_candidate_row(item) for item in candidates)
    return (
        '    <section class="panel">\n'
        "      <h2>Candidates</h2>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Family</th><th>Candidate</th><th>Label</th><th>Artifact</th><th>Review</th>"
        "<th>Packet</th><th>Preflight</th><th>Readiness</th><th>Flags</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        "    </section>"
    )


def _candidate_row(item: ActionReadinessCandidateResponse) -> str:
    href = candidate_href(item.candidate_id)
    flags = (
        f"dry-run={yes_no(item.dry_run_only)} · "
        f"no-exec={yes_no(item.no_execution)} · "
        f"executed={yes_no(item.executed)} · "
        f"live={yes_no(item.live_action)}"
    )
    return (
        f'<tr class="{_readiness_class(item.readiness_status)}">'
        f"<td>{titleize(item.plan_family)}</td>"
        f'<td class="mono"><a class="row-link" href="{href}">'
        f"{html_escape(short_id(item.candidate_id))}</a></td>"
        f"<td>{html_escape(item.sanitized_label)}</td>"
        f"<td>{titleize(item.artifact_type)}</td>"
        f"<td>{html_escape(item.review_decision_status)}</td>"
        f"<td>{html_escape(item.packet_decision_status)}</td>"
        f"<td>{html_escape(item.preflight_status)}</td>"
        f"<td>{html_escape(item.readiness_status)}</td>"
        f"<td>{html_escape(flags)}</td>"
        "</tr>"
    )


def _readiness_class(status: str) -> str:
    match status:
        case (
            ActionReadinessStatus.BLOCKED.value
            | ActionReadinessStatus.MISSING_REVIEW_DECISION.value
            | ActionReadinessStatus.MISSING_OWNER_PACKET_DECISION.value
            | ActionReadinessStatus.PREFLIGHT_BLOCKED.value
            | ActionReadinessStatus.APPROVED_BUT_HALTED.value
        ):
            return "severity-blocked"
        case ActionReadinessStatus.READY_PENDING_EXPLICIT_LIVE_OWNER_ACTION.value:
            return "severity-warning"
        case _:
            return _unreachable_status(status)


def _render_codes(codes: list[str], *, empty: str) -> str:
    unique = [code for code in dict.fromkeys(codes) if code]
    if not unique:
        return f'<p class="empty-state">{escape(empty)}</p>'
    rows = "".join(f"<li>{html_escape(code)}</li>" for code in unique)
    return f'<ul class="plain">{rows}</ul>'


def _render_list_footer(queue: ActionReadinessQueueResponse, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={yes_no(queue.read_only)}. "
        f"Executed={html_escape(queue.executed_count)}. "
        f"Outbound attempted={yes_no(queue.outbound_attempted)}. "
        f"Call attempted={yes_no(queue.live_call_attempted)}. "
        f"Recommendation applied={yes_no(queue.recommendation_applied)}. "
        f"Spend attempted={yes_no(queue.spend_attempted)}. "
        f"Campaign launched={yes_no(queue.campaign_launched)}. "
        f"Pages published={yes_no(queue.pages_published)}. "
        f"Ads launched={yes_no(queue.ads_launched)}. "
        "There are no execute, send, enroll, book, call, publish, spend, or "
        "deploy controls on this page. Ready-like items still require a future "
        "explicit owner action before live execution.</p>\n"
        "    </footer>"
    )


def _unreachable_status(value: str) -> Never:
    raise RuntimeError(f"unhandled readiness status: {value!r}")
