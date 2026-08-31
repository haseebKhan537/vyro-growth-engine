"""Read-only operator review-queue HTML drilldown.

Phase 21 renders pending and decided dry-run review artifacts as internal
HTML pages. It never records a new decision, never executes an artifact, and
never sends email, enrolls campaigns, generates sendable replies, books
meetings, creates video-meet links, places calls, publishes content, launches
ads, spends money, deploys, applies optimizer recommendations, or changes
live/scoring/campaign/provider/deployment settings or operator halt state.
"""

from __future__ import annotations

from html import escape
from typing import Literal, Never
from uuid import UUID

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.operator_ui import (
    NO_STORE_HEADERS,
    OPERATOR_REVIEW_QUEUE_PATH,
    OPERATOR_UI_STYLES,
    REVIEW_QUEUE_JSON_PATH,
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
from vyro_growth.api.review_queue import (
    ReviewItemResponse,
    ReviewQueueResponse,
    build_review_queue_response,
    review_item_to_response,
)
from vyro_growth.config import Settings
from vyro_growth.domain import ReviewArtifactType, ReviewItemStatus
from vyro_growth.services.review_queue import ReviewQueueService

logger = structlog.get_logger(__name__)

ReviewStatusFilter = Literal[
    "all",
    "pending",
    "decided",
    "approved",
    "rejected",
    "needs_changes",
]
_STATUS_FILTERS: tuple[ReviewStatusFilter, ...] = (
    "all",
    "pending",
    "decided",
    "approved",
    "rejected",
    "needs_changes",
)
_STATUS_LABELS: dict[ReviewStatusFilter, str] = {
    "all": "All",
    "pending": "Pending",
    "decided": "Decided",
    "approved": "Approved",
    "rejected": "Rejected",
    "needs_changes": "Needs changes",
}
_ARTIFACT_TYPES: tuple[str, ...] = tuple(item.value for item in ReviewArtifactType)


def _unreachable(value: object) -> Never:
    raise RuntimeError(f"unhandled review status filter: {value!r}")


def parse_review_status_filter(
    value: str | None,
    *,
    include_decided: bool,
) -> ReviewStatusFilter:
    match value:
        case "all" | "pending" | "decided" | "approved" | "rejected" | "needs_changes":
            return value
        case None:
            return "all" if include_decided else "pending"
        case _:
            return "all" if include_decided else "pending"


def parse_review_artifact_type(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    if cleaned in _ARTIFACT_TYPES:
        return cleaned
    return None


def status_requires_decided(status: ReviewStatusFilter) -> bool:
    match status:
        case "pending":
            return False
        case "all" | "decided" | "approved" | "rejected" | "needs_changes":
            return True
        case _:
            return _unreachable(status)


def item_matches_status(item: ReviewItemResponse, status: ReviewStatusFilter) -> bool:
    match status:
        case "all":
            return True
        case "pending":
            return item.status == ReviewItemStatus.PENDING_OPERATOR_REVIEW.value
        case "decided":
            return item.status != ReviewItemStatus.PENDING_OPERATOR_REVIEW.value
        case "approved":
            return item.status == ReviewItemStatus.APPROVED.value
        case "rejected":
            return item.status == ReviewItemStatus.REJECTED.value
        case "needs_changes":
            return item.status == ReviewItemStatus.NEEDS_CHANGES.value
        case _:
            return _unreachable(status)


def review_item_href(artifact_type: str, artifact_id: UUID) -> str:
    return f"{OPERATOR_REVIEW_QUEUE_PATH}/{escape(artifact_type)}/{artifact_id}"


def render_review_queue_error() -> str:
    return render_failure_page(
        page_id="operator-review-queue-error",
        title="Review queue unavailable",
        heading="Read-only review queue unavailable",
        banner="Unable to load the review queue.",
        detail=(
            "The sanitized review-queue list could not be rendered. "
            "Retry after checking database connectivity and runtime config."
        ),
    )


def render_review_item_missing() -> str:
    return render_failure_page(
        page_id="operator-review-queue-missing",
        title="Review item not found",
        heading="Review item not found",
        banner="No matching dry-run review artifact is available.",
        detail=(
            "The requested artifact type or id is unknown, not reviewable, "
            "or no longer present. This page does not invent facts or execute "
            "any action."
        ),
    )


def render_review_queue_list(
    queue: ReviewQueueResponse,
    *,
    artifact_type: str | None,
    status: ReviewStatusFilter,
    include_decided: bool,
    items: list[ReviewItemResponse],
) -> str:
    generated = html_escape(format_dt(queue.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Operator review queue</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-review-queue" data-read-only="true">\n'
        f"{_render_list_header(queue, generated)}\n"
        f"{render_operator_nav('review-queue')}\n"
        f"{_render_filters(artifact_type, status, include_decided)}\n"
        f"{_render_summary(queue)}\n"
        f"{_render_items(items, artifact_type=artifact_type, status=status)}\n"
        f"{_render_list_footer(queue, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def render_review_item_detail(item: ReviewItemResponse) -> str:
    generated = html_escape(format_dt(item.created_at))
    decision = item.decision
    decision_block = (
        (
            '      <div class="metric-grid">\n'
            f"        {metric('Decision', decision.decision)}\n"
            f"        {metric('Reviewer', decision.reviewer)}\n"
            f"        {metric('Source', decision.source)}\n"
            f"        {metric('Decided at', format_dt(decision.decided_at))}\n"
            "      </div>\n"
            + (
                f'      <p class="hint">Reviewer notes: '
                f"{html_escape(decision.reviewer_notes)}</p>\n"
                if decision.reviewer_notes
                else ""
            )
        )
        if decision is not None
        else '<p class="empty-state">No recorded decision yet. This page does not add one.</p>'
    )
    labels = "".join(f"<li>{titleize(label)}</li>" for label in item.risk_labels)
    if not labels:
        labels = '<li class="empty">No risk labels.</li>'
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Review item</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-review-item" data-read-only="true">\n'
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Review item</h1>\n"
        '        <p class="lede">Read-only dry-run artifact. No execution.</p>\n'
        "      </div>\n"
        f'      <p class="meta">Created {generated}</p>\n'
        "    </header>\n"
        f"{render_operator_nav('review-queue')}\n"
        '    <section class="panel">\n'
        "      <h2>Safe detail</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Artifact type', item.artifact_type)}\n"
        f"        {metric('Artifact id', short_id(item.artifact_id))}\n"
        f"        {metric('Status', item.status)}\n"
        f"        {metric('Decision', decision.decision if decision else 'none')}\n"
        f"        {metric('Lead id', short_id(item.lead_id))}\n"
        f"        {metric('Organization id', short_id(item.organization_id))}\n"
        f"        {metric('Created', format_dt(item.created_at))}\n"
        f"        {metric('Executable later', yes_no(item.executable_later))}\n"
        f"        {metric('Executed', yes_no(item.executed))}\n"
        f"        {metric('Dry-run', 'yes')}\n"
        f"        {metric('No execution', 'yes')}\n"
        "      </div>\n"
        f'      <p class="hint">Title: {html_escape(item.title)}</p>\n'
        f'      <p class="hint">Summary: {html_escape(item.summary)}</p>\n'
        "      <h3>Risk labels</h3>\n"
        f'      <ul class="plain">{labels}</ul>\n'
        "      <h3>Recorded decision</h3>\n"
        f"      {decision_block}\n"
        '      <p class="hint">There are no approve, reject, or execute controls '
        "on this page.</p>\n"
        "    </section>\n"
        '    <p><a class="nav-link" href="'
        f'{escape(OPERATOR_REVIEW_QUEUE_PATH)}">Back to review queue</a></p>\n'
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_review_queue_response(
    db: Session,
    settings: Settings,
    *,
    artifact_type: str | None = None,
    status: str | None = None,
    include_decided: bool = False,
    service: ReviewQueueService | None = None,
) -> HTMLResponse:
    try:
        parsed_type = parse_review_artifact_type(artifact_type)
        parsed_status = parse_review_status_filter(status, include_decided=include_decided)
        need_decided = include_decided or status_requires_decided(parsed_status)
        queue = build_review_queue_response(
            db,
            settings,
            include_decided=need_decided,
            artifact_type=parsed_type,
            service=service,
        )
        items = [item for item in queue.items if item_matches_status(item, parsed_status)]
        html = render_review_queue_list(
            queue,
            artifact_type=parsed_type,
            status=parsed_status,
            include_decided=need_decided,
            items=items,
        )
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_review_queue_render_failed", read_only=True)
        return HTMLResponse(
            content=render_review_queue_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def build_operator_review_item_response(
    db: Session,
    settings: Settings,
    *,
    artifact_type: str,
    artifact_id: str,
    service: ReviewQueueService | None = None,
) -> HTMLResponse:
    try:
        parsed_type = parse_review_artifact_type(artifact_type)
        try:
            parsed_id = UUID(artifact_id)
        except ValueError:
            parsed_id = None
        if parsed_type is None or parsed_id is None:
            return HTMLResponse(
                content=render_review_item_missing(),
                status_code=404,
                headers=NO_STORE_HEADERS,
            )
        queue = service or ReviewQueueService()
        item = queue.get_item(
            db,
            settings,
            artifact_type=parsed_type,
            artifact_id=parsed_id,
        )
        if item is None:
            return HTMLResponse(
                content=render_review_item_missing(),
                status_code=404,
                headers=NO_STORE_HEADERS,
            )
        html = render_review_item_detail(review_item_to_response(item))
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_review_item_render_failed", read_only=True)
        return HTMLResponse(
            content=render_review_queue_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_list_header(queue: ReviewQueueResponse, generated: str) -> str:
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Review queue</h1>\n"
        '        <p class="lede">Read-only dry-run artifacts. No execution.</p>\n'
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · halt '
        f"{html_escape(queue.operator_halt_status)}</p>\n"
        "    </header>"
    )


def _render_filters(
    artifact_type: str | None,
    status: ReviewStatusFilter,
    include_decided: bool,
) -> str:
    type_links = [
        filter_link(
            _list_href(None, status, include_decided),
            "All types",
            current=artifact_type is None,
        )
    ]
    for name in _ARTIFACT_TYPES:
        type_links.append(
            filter_link(
                _list_href(name, status, include_decided),
                name.replace("_", " "),
                current=artifact_type == name,
            )
        )
    status_links = [
        filter_link(
            _list_href(artifact_type, name, include_decided or status_requires_decided(name)),
            _STATUS_LABELS[name],
            current=status == name,
        )
        for name in _STATUS_FILTERS
    ]
    decided_href = _list_href(artifact_type, status, not include_decided)
    decided_label = "Hide decided" if include_decided else "Include decided"
    json_href = escape(REVIEW_QUEUE_JSON_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Artifact type filters">'
        f"{' '.join(type_links)}</nav>\n"
        '    <nav class="filter-nav" aria-label="Status filters">'
        f"{' '.join(status_links)} "
        f"{filter_link(decided_href, decided_label, current=include_decided)}\n"
        f'      <a class="nav-link nav-json" href="{json_href}">JSON queue</a>\n'
        "    </nav>"
    )


def _list_href(
    artifact_type: str | None,
    status: ReviewStatusFilter,
    include_decided: bool,
) -> str:
    params: list[str] = []
    if artifact_type:
        params.append(f"artifact_type={artifact_type}")
    if status != "pending":
        params.append(f"status={status}")
    if include_decided:
        params.append("include_decided=true")
    if not params:
        return OPERATOR_REVIEW_QUEUE_PATH
    return f"{OPERATOR_REVIEW_QUEUE_PATH}?{'&'.join(params)}"


def _render_summary(queue: ReviewQueueResponse) -> str:
    by_type = "".join(
        f"<li><span>{titleize(key)}</span><strong>{html_escape(count)}</strong></li>"
        for key, count in sorted(queue.by_artifact_type.items())
    )
    if not by_type:
        by_type = '<li class="empty">No artifact types in this view.</li>'
    return (
        '    <section class="status-strip" aria-label="Review counts">\n'
        f"      {metric('Pending', queue.pending_count)}\n"
        f"      {metric('Decided', queue.decided_count)}\n"
        f"      {metric('Executed', queue.executed_count)}\n"
        f"      {metric('Outbound attempted', yes_no(queue.outbound_attempted))}\n"
        f"      {metric('Mode', 'read-only')}\n"
        "    </section>\n"
        '    <section class="panel">\n'
        "      <h2>Visible by type</h2>\n"
        f'      <ul class="kv-list">{by_type}</ul>\n'
        "    </section>"
    )


def _render_items(
    items: list[ReviewItemResponse],
    *,
    artifact_type: str | None,
    status: ReviewStatusFilter,
) -> str:
    if not items:
        if artifact_type or status not in {"pending", "all"}:
            body = (
                '<p class="empty-state" id="empty-review-queue">No review items match '
                "the current filters. This page does not create artifacts or record "
                "decisions.</p>"
            )
        else:
            body = (
                '<p class="empty-state" id="empty-review-queue">No pending review items. '
                "Dry-run artifacts appear here after they are stored. This page does "
                "not start jobs or execute approved items.</p>"
            )
        return (
            '    <section class="panel">\n'
            "      <h2>Items</h2>\n"
            f"      {body}\n"
            "    </section>"
        )
    rows = "".join(_item_row(item) for item in items)
    return (
        '    <section class="panel">\n'
        "      <h2>Items</h2>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Type</th><th>Artifact</th><th>Status</th><th>Decision</th>"
        "<th>Created</th><th>Title</th><th>Flags</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        "    </section>"
    )


def _item_row(item: ReviewItemResponse) -> str:
    href = review_item_href(item.artifact_type, item.artifact_id)
    decision = item.decision.decision if item.decision is not None else "none"
    flags = (
        f"dry-run · later={yes_no(item.executable_later)} · "
        f"executed={yes_no(item.executed)}"
    )
    return (
        "<tr>"
        f"<td>{titleize(item.artifact_type)}</td>"
        f'<td class="mono"><a class="row-link" href="{href}">'
        f"{html_escape(short_id(item.artifact_id))}</a></td>"
        f"<td>{html_escape(item.status)}</td>"
        f"<td>{html_escape(decision)}</td>"
        f"<td>{html_escape(format_dt(item.created_at))}</td>"
        f"<td>{html_escape(item.title)}</td>"
        f"<td>{html_escape(flags)}</td>"
        "</tr>"
    )


def _render_list_footer(queue: ReviewQueueResponse, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only=yes. "
        f"Executed={html_escape(queue.executed_count)}. "
        f"Outbound attempted={yes_no(queue.outbound_attempted)}. "
        f"Call attempted={yes_no(queue.live_call_attempted)}. "
        f"Recommendation applied={yes_no(queue.recommendation_applied)}. "
        "There are no approve, reject, or execute controls on this page.</p>\n"
        "    </footer>"
    )
