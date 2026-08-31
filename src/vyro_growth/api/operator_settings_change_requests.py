"""Settings change request HTML drilldown and decision-record form.

Phase 29 renders Phase 28 live settings change requests as internal HTML
pages and lets an operator record approved/rejected/needs_changes on a
detail page. Recording a decision never applies settings, lifts halt, sets
live owner-approved state, or executes a request. It never sends email,
enrolls campaigns, generates sendable replies, books meetings, creates
video-meet links, places calls, publishes content, launches ads, spends
money, deploys, or calls live providers.
"""

from __future__ import annotations

from html import escape
from uuid import UUID

import structlog
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from vyro_growth.api.operator_review_queue import (
    DECISION_VALUES,
    GENERIC_DECISION_ERROR,
    GENERIC_FORM_ERROR,
    MAX_FORM_BYTES,
    MAX_REVIEWER_LENGTH,
    DecisionFormValues,
    parse_form_decision,
    parse_urlencoded_form,
)
from vyro_growth.api.operator_ui import (
    LAUNCH_READINESS_JSON_PATH,
    NO_STORE_HEADERS,
    OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH,
    OPERATOR_UI_STYLES,
    SETTINGS_CHANGE_JSON_PATH,
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
from vyro_growth.api.settings_change_requests import (
    SettingsChangeRequestListResponse,
    SettingsChangeRequestResponse,
    build_settings_change_list_response,
    request_to_response,
)
from vyro_growth.config import Settings
from vyro_growth.domain import (
    SettingsChangeDecisionStatus,
    SettingsChangeRequestStatus,
    SettingsChangeRequestType,
)
from vyro_growth.services.review_queue import MAX_NOTES_LENGTH, sanitize_operator_text
from vyro_growth.services.settings_change_requests import (
    SettingsChangeRequestError,
    SettingsChangeRequestService,
    SettingsChangeRequestView,
)

logger = structlog.get_logger(__name__)

_REQUEST_TYPES: tuple[str, ...] = tuple(item.value for item in SettingsChangeRequestType)
_REQUEST_STATUSES: tuple[str, ...] = tuple(item.value for item in SettingsChangeRequestStatus)
_DECISION_STATUSES: tuple[str, ...] = tuple(item.value for item in SettingsChangeDecisionStatus)
OPERATOR_UI_SETTINGS_DECISION_SOURCE = "operator_ui"


def parse_request_type(value: str | None) -> str | None:
    return _parse_allowed(value, _REQUEST_TYPES)


def parse_request_status(value: str | None) -> str | None:
    return _parse_allowed(value, _REQUEST_STATUSES)


def parse_owner_decision_status(value: str | None) -> str | None:
    return _parse_allowed(value, _DECISION_STATUSES)


def request_href(request_id: UUID) -> str:
    return f"{OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH}/{request_id}"


def request_decision_href(request_id: UUID) -> str:
    return f"{OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH}/{request_id}/decision"


def request_recorded_href(request_id: UUID) -> str:
    return f"{OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH}/{request_id}?decision_recorded=1"


def render_settings_change_error() -> str:
    return render_failure_page(
        page_id="operator-settings-change-requests-error",
        title="Settings change requests unavailable",
        heading="Record-only settings change requests unavailable",
        banner="Unable to load live settings change requests.",
        detail=(
            "The sanitized settings-change request list could not be rendered. "
            "Retry after checking database connectivity and runtime config."
        ),
    )


def render_settings_change_missing() -> str:
    return render_failure_page(
        page_id="operator-settings-change-requests-missing",
        title="Settings change request not found",
        heading="Settings change request not found",
        banner="No matching live settings change request is available.",
        detail=(
            "The requested id is unknown or no longer present. "
            "This page does not invent facts, apply settings, or execute any action."
        ),
    )


def render_settings_change_list(
    queue: SettingsChangeRequestListResponse,
    *,
    request_type: str | None,
    status: str | None,
    owner_decision_status: str | None,
    requests: list[SettingsChangeRequestResponse],
) -> str:
    generated = html_escape(format_dt(queue.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Live settings change requests</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-settings-change-requests" data-record-only="true" '
        'data-read-only="true">\n'
        f"{_render_list_header(queue, generated)}\n"
        f"{render_operator_nav('settings-change-requests')}\n"
        f"{_render_filters(request_type, status, owner_decision_status)}\n"
        f"{_render_summary(queue)}\n"
        f"{_render_requests(
            requests,
            request_type=request_type,
            status=status,
            owner_decision_status=owner_decision_status,
        )}\n"
        f"{_render_list_footer(queue, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def render_settings_change_detail(
    item: SettingsChangeRequestResponse,
    *,
    decision_recorded: bool = False,
    form_error: str | None = None,
    form_values: DecisionFormValues | None = None,
) -> str:
    generated = html_escape(format_dt(item.requested_at))
    decision = item.decision
    decision_block = (
        (
            '      <div class="metric-grid">\n'
            f"        {metric('Decision', decision.decision)}\n"
            f"        {metric('Reviewer', decision.reviewer)}\n"
            f"        {metric('Source', decision.source)}\n"
            f"        {metric('Decided at', format_dt(decision.decided_at))}\n"
            f"        {metric('Executed', yes_no(decision.executed))}\n"
            f"        {metric('Settings applied', yes_no(decision.settings_applied))}\n"
            f"        {metric('Owner approved', yes_no(decision.owner_approved))}\n"
            f"        {metric('Halt changed', yes_no(decision.halt_changed))}\n"
            f"        {metric('Live action', yes_no(decision.live_action))}\n"
            f"        {metric('No execution', yes_no(decision.no_execution))}\n"
            "      </div>\n"
            + (
                f'      <p class="hint">Owner notes: '
                f"{html_escape(decision.reviewer_notes)}</p>\n"
                if decision.reviewer_notes
                else ""
            )
        )
        if decision is not None
        else '<p class="empty-state">No recorded owner decision yet.</p>'
    )
    saved_banner = (
        _render_decision_saved_banner(item) if decision_recorded and decision is not None else ""
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Settings change request</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-settings-change-request" data-decision-record-only="true" '
        'data-execution="false" data-settings-applied="false">\n'
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Settings change request</h1>\n"
        '        <p class="lede">Decision-record only. No settings are applied.</p>\n'
        "      </div>\n"
        f'      <p class="meta">Requested {generated}</p>\n'
        "    </header>\n"
        f"{saved_banner}"
        f"{render_operator_nav('settings-change-requests')}\n"
        '    <section class="panel">\n'
        "      <h2>Safe detail</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Request id', short_id(item.request_id))}\n"
        f"        {metric('Request type', item.request_type)}\n"
        f"        {metric('Status', item.status)}\n"
        f"        {metric('Owner decision status', item.owner_decision_status)}\n"
        f"        {metric('Desired boolean', item.desired_boolean)}\n"
        f"        {metric('Desired status', item.desired_status)}\n"
        f"        {metric('Finding code', item.finding_code)}\n"
        f"        {metric('Next action code', item.next_action_code)}\n"
        f"        {metric('Source', item.source)}\n"
        f"        {metric('Requested at', format_dt(item.requested_at))}\n"
        f"        {metric('Record only', yes_no(item.record_only))}\n"
        f"        {metric('No execution', yes_no(item.no_execution))}\n"
        f"        {metric('Executed', yes_no(item.executed))}\n"
        f"        {metric('Settings applied', yes_no(item.settings_applied))}\n"
        f"        {metric('Halt changed', yes_no(item.halt_changed))}\n"
        f"        {metric('Owner approved', yes_no(item.owner_approved))}\n"
        f"        {metric('Live action', yes_no(item.live_action))}\n"
        f"        {metric('Operator halt', item.operator_halt_status)}\n"
        "      </div>\n"
        "      <h3>Requested setting names</h3>\n"
        f"      {_render_setting_names(item.requested_setting_names)}\n"
        "      <h3>Recorded owner decision</h3>\n"
        f"      {decision_block}\n"
        '      <p class="hint">This page never shows secret values, environment '
        "values, API keys, tokens, message bodies, emails, phones, evidence "
        "snippets, or unsafe error text.</p>\n"
        "    </section>\n"
        f"{_render_decision_form(item, form_error=form_error, form_values=form_values)}\n"
        '    <p><a class="nav-link" href="'
        f'{escape(OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH)}">'
        "Back to settings requests</a></p>\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_settings_change_list_response(
    db: Session,
    settings: Settings,
    *,
    request_type: str | None = None,
    status: str | None = None,
    owner_decision_status: str | None = None,
    service: SettingsChangeRequestService | None = None,
) -> HTMLResponse:
    try:
        parsed_type = parse_request_type(request_type)
        parsed_status = parse_request_status(status)
        parsed_decision = parse_owner_decision_status(owner_decision_status)
        queue = build_settings_change_list_response(
            db,
            settings,
            status=parsed_status,
            request_type=parsed_type,
            owner_decision_status=parsed_decision,
            service=service,
        )
        html = render_settings_change_list(
            queue,
            request_type=parsed_type,
            status=parsed_status,
            owner_decision_status=parsed_decision,
            requests=queue.requests,
        )
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_settings_change_list_render_failed", read_only=True)
        return HTMLResponse(
            content=render_settings_change_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def build_operator_settings_change_detail_response(
    db: Session,
    settings: Settings,
    *,
    request_id: str,
    decision_recorded: bool = False,
    service: SettingsChangeRequestService | None = None,
) -> HTMLResponse:
    try:
        try:
            parsed_id = UUID(request_id)
        except ValueError:
            parsed_id = None
        if parsed_id is None:
            return HTMLResponse(
                content=render_settings_change_missing(),
                status_code=404,
                headers=NO_STORE_HEADERS,
            )
        queue = service or SettingsChangeRequestService()
        item = queue.get_request(db, settings, parsed_id)
        if item is None:
            return HTMLResponse(
                content=render_settings_change_missing(),
                status_code=404,
                headers=NO_STORE_HEADERS,
            )
        html = render_settings_change_detail(
            request_to_response(item),
            decision_recorded=decision_recorded,
        )
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_settings_change_detail_render_failed", execution=False)
        return HTMLResponse(
            content=render_settings_change_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def build_operator_settings_change_decision_response(
    db: Session,
    settings: Settings,
    *,
    request_id: str,
    form_body: bytes,
    service: SettingsChangeRequestService | None = None,
) -> HTMLResponse | RedirectResponse:
    try:
        parsed_id = UUID(request_id)
    except ValueError:
        parsed_id = None
    if parsed_id is None:
        return HTMLResponse(
            content=render_settings_change_missing(),
            status_code=404,
            headers=NO_STORE_HEADERS,
        )
    queue = service or SettingsChangeRequestService()
    try:
        item = queue.get_request(db, settings, parsed_id)
        if item is None:
            return HTMLResponse(
                content=render_settings_change_missing(),
                status_code=404,
                headers=NO_STORE_HEADERS,
            )
        if len(form_body) > MAX_FORM_BYTES:
            return _decision_form_error(
                item,
                GENERIC_FORM_ERROR,
                form_values=DecisionFormValues(),
            )
        form = parse_urlencoded_form(form_body)
        decision = parse_form_decision(form.get("decision"))
        reviewer_raw = _clip(form.get("reviewer"), MAX_REVIEWER_LENGTH)
        notes_raw = _clip(form.get("reviewer_notes"), MAX_NOTES_LENGTH)
        reviewer = sanitize_operator_text(reviewer_raw) or ""
        notes = sanitize_operator_text(notes_raw) or ""
        form_values = DecisionFormValues(
            decision=decision,
            reviewer=reviewer,
            reviewer_notes=notes,
        )
        if decision is None:
            return _decision_form_error(item, GENERIC_DECISION_ERROR, form_values=form_values)
        if _same_recorded_decision(item, decision, reviewer_raw, notes_raw):
            return _decision_recorded_redirect(parsed_id)
        try:
            queue.record_decision(
                db,
                settings,
                request_id=parsed_id,
                decision=decision,
                reviewer=reviewer or None,
                source=OPERATOR_UI_SETTINGS_DECISION_SOURCE,
                reviewer_notes=notes or None,
            )
        except SettingsChangeRequestError as exc:
            logger.info(
                "operator_settings_change_decision_rejected",
                code=exc.code,
                execution=False,
                settings_applied=False,
            )
            return _decision_service_error(exc, item)
        return _decision_recorded_redirect(parsed_id)
    except Exception:
        logger.exception("operator_settings_change_decision_failed", execution=False)
        return HTMLResponse(
            content=render_settings_change_error(),
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


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:limit]


def _same_recorded_decision(
    item: SettingsChangeRequestView,
    decision: str,
    reviewer: str | None,
    notes: str | None,
) -> bool:
    existing = item.decision
    if existing is None:
        return False
    reviewer_name = sanitize_operator_text(reviewer) or "operator"
    notes_value = sanitize_operator_text(notes)
    return (
        existing.decision == decision
        and existing.reviewer == reviewer_name
        and existing.reviewer_notes == notes_value
    )


def _decision_recorded_redirect(request_id: UUID) -> RedirectResponse:
    return RedirectResponse(
        url=request_recorded_href(request_id),
        status_code=303,
        headers=NO_STORE_HEADERS,
    )


def _decision_form_error(
    item: SettingsChangeRequestView,
    message: str,
    *,
    form_values: DecisionFormValues | None = None,
) -> HTMLResponse:
    html = render_settings_change_detail(
        request_to_response(item),
        form_error=message,
        form_values=form_values,
    )
    return HTMLResponse(content=html, status_code=400, headers=NO_STORE_HEADERS)


def _decision_service_error(
    exc: SettingsChangeRequestError,
    item: SettingsChangeRequestView,
) -> HTMLResponse:
    match exc.code:
        case "not_found":
            return HTMLResponse(
                content=render_settings_change_missing(),
                status_code=404,
                headers=NO_STORE_HEADERS,
            )
        case "invalid_decision":
            return _decision_form_error(item, GENERIC_DECISION_ERROR)
        case "secret_value_rejected":
            return _decision_form_error(item, GENERIC_FORM_ERROR)
        case _:
            return _decision_form_error(item, GENERIC_FORM_ERROR)


def _render_decision_saved_banner(item: SettingsChangeRequestResponse) -> str:
    decision = item.decision
    if decision is None:
        return ""
    notes = (
        f'      <p class="hint">Owner notes: {html_escape(decision.reviewer_notes)}</p>\n'
        if decision.reviewer_notes
        else ""
    )
    return (
        '    <div class="success-banner" id="decision-recorded">\n'
        "      <p>Decision recorded. No settings were applied and no execution "
        "was attempted.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Decision', decision.decision)}\n"
        f"        {metric('Reviewer', decision.reviewer)}\n"
        f"        {metric('Source', decision.source)}\n"
        f"        {metric('Decided at', format_dt(decision.decided_at))}\n"
        f"        {metric('Executed', yes_no(item.executed))}\n"
        f"        {metric('Settings applied', yes_no(item.settings_applied))}\n"
        f"        {metric('Halt changed', yes_no(item.halt_changed))}\n"
        f"        {metric('Owner approved', yes_no(item.owner_approved))}\n"
        f"        {metric('Live action', yes_no(item.live_action))}\n"
        f"        {metric('Outbound attempted', yes_no(item.outbound_attempted))}\n"
        "      </div>\n"
        f"{notes}"
        "    </div>\n"
    )


def _render_decision_form(
    item: SettingsChangeRequestResponse,
    *,
    form_error: str | None = None,
    form_values: DecisionFormValues | None = None,
) -> str:
    action = request_decision_href(item.request_id)
    selected = (
        form_values.decision
        if form_values is not None and form_values.decision is not None
        else (item.decision.decision if item.decision is not None else "")
    )
    reviewer = (
        form_values.reviewer
        if form_values is not None
        else (item.decision.reviewer if item.decision is not None else "")
    )
    notes = (
        form_values.reviewer_notes
        if form_values is not None
        else (item.decision.reviewer_notes if item.decision is not None else "")
    )
    error_html = (
        f'      <p class="banner" id="decision-form-error">{html_escape(form_error)}</p>\n'
        if form_error
        else ""
    )
    options: list[str] = []
    for value in DECISION_VALUES:
        mark = " selected" if selected == value else ""
        options.append(f'<option value="{escape(value)}"{mark}>{escape(value)}</option>')
    return (
        '    <section class="panel" id="decision-form">\n'
        "      <h2>Record owner decision</h2>\n"
        '      <p class="hint">Records an owner/operator decision only. This does not '
        "apply the setting, enable outbound, lift operator halt, execute the "
        "request, send email, enroll campaigns, book meetings, place calls, "
        "publish content, launch ads, spend money, deploy, or mark live "
        "owner-approved.</p>\n"
        f"{error_html}"
        f'      <form method="post" action="{escape(action)}" '
        'id="operator-settings-change-decision-form" autocomplete="off">\n'
        '        <div class="form-grid">\n'
        "          <label>Decision\n"
        '            <select name="decision" required>\n'
        f"              {''.join(options)}\n"
        "            </select>\n"
        "          </label>\n"
        "          <label>Owner / reviewer\n"
        f'            <input name="reviewer" maxlength="{MAX_REVIEWER_LENGTH}" '
        f'value="{html_escape(reviewer, empty="")}" autocomplete="off">\n'
        "          </label>\n"
        "          <label>Notes\n"
        f'            <textarea name="reviewer_notes" maxlength="{MAX_NOTES_LENGTH}">'
        f"{html_escape(notes, empty="")}</textarea>\n"
        "          </label>\n"
        '          <button type="submit">Record decision</button>\n'
        "        </div>\n"
        "      </form>\n"
        '      <p class="hint">This form records a decision only. There is no apply, '
        "execute, enable outbound, or lift-halt control.</p>\n"
        "    </section>"
    )


def _render_list_header(queue: SettingsChangeRequestListResponse, generated: str) -> str:
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Live settings change requests</h1>\n"
        '        <p class="lede">Record-only owner review queue. No settings are '
        "applied and no live action is executed.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · halt '
        f"{html_escape(queue.operator_halt_status)}</p>\n"
        "    </header>"
    )


def _render_filters(
    request_type: str | None,
    status: str | None,
    owner_decision_status: str | None,
) -> str:
    type_links = [
        filter_link(
            _list_href(None, status, owner_decision_status),
            "All types",
            current=request_type is None,
        )
    ]
    for name in _REQUEST_TYPES:
        type_links.append(
            filter_link(
                _list_href(name, status, owner_decision_status),
                name.replace("_", " "),
                current=request_type == name,
            )
        )
    status_links = [
        filter_link(
            _list_href(request_type, None, owner_decision_status),
            "All statuses",
            current=status is None,
        )
    ]
    for name in _REQUEST_STATUSES:
        status_links.append(
            filter_link(
                _list_href(request_type, name, owner_decision_status),
                name.replace("_", " "),
                current=status == name,
            )
        )
    decision_links = [
        filter_link(
            _list_href(request_type, status, None),
            "All decisions",
            current=owner_decision_status is None,
        )
    ]
    for name in _DECISION_STATUSES:
        decision_links.append(
            filter_link(
                _list_href(request_type, status, name),
                name.replace("_", " "),
                current=owner_decision_status == name,
            )
        )
    json_href = escape(SETTINGS_CHANGE_JSON_PATH)
    launch_href = escape(LAUNCH_READINESS_JSON_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Request type filters">'
        f"{' '.join(type_links)}</nav>\n"
        '    <nav class="filter-nav" aria-label="Status filters">'
        f"{' '.join(status_links)}</nav>\n"
        '    <nav class="filter-nav" aria-label="Owner decision filters">'
        f"{' '.join(decision_links)}\n"
        f'      <a class="nav-link nav-json" href="{json_href}">JSON queue</a>\n'
        f'      <a class="nav-link" href="{launch_href}">Launch readiness JSON</a>\n'
        "    </nav>"
    )


def _list_href(
    request_type: str | None,
    status: str | None,
    owner_decision_status: str | None,
) -> str:
    params: list[str] = []
    if request_type:
        params.append(f"request_type={request_type}")
    if status:
        params.append(f"status={status}")
    if owner_decision_status:
        params.append(f"owner_decision_status={owner_decision_status}")
    if not params:
        return OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH
    return f"{OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH}?{'&'.join(params)}"


def _render_summary(queue: SettingsChangeRequestListResponse) -> str:
    type_items = _kv_items(queue.by_request_type, empty="No request types.")
    status_items = _kv_items(queue.by_status, empty="No statuses.")
    decision_items = _kv_items(queue.by_decision_status, empty="No decision statuses.")
    return (
        '    <section class="status-strip" aria-label="Settings change counts">\n'
        f"      {metric('Requests', queue.request_count)}\n"
        f"      {metric('Pending', queue.pending_count)}\n"
        f"      {metric('Decided', queue.decided_count)}\n"
        f"      {metric('Executed', queue.executed)}\n"
        f"      {metric('Record only', yes_no(queue.record_only))}\n"
        f"      {metric('No execution', yes_no(queue.no_execution))}\n"
        f"      {metric('Settings applied', yes_no(queue.settings_applied))}\n"
        f"      {metric('Halt changed', yes_no(queue.halt_changed))}\n"
        f"      {metric('Live action', yes_no(queue.live_action))}\n"
        "    </section>\n"
        '    <section class="panel">\n'
        "      <h2>Queue summary</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Operator halt', queue.operator_halt_status)}\n"
        f"        {metric('Owner approved', yes_no(queue.owner_approved))}\n"
        f"        {metric('Outbound attempted', yes_no(queue.outbound_attempted))}\n"
        "      </div>\n"
        "      <h3>By request type</h3>\n"
        f'      <ul class="kv-list">{type_items}</ul>\n'
        "      <h3>By status</h3>\n"
        f'      <ul class="kv-list">{status_items}</ul>\n'
        "      <h3>By owner decision</h3>\n"
        f'      <ul class="kv-list">{decision_items}</ul>\n'
        "    </section>"
    )


def _kv_items(counts: dict[str, int], *, empty: str) -> str:
    items = "".join(
        f"<li><span>{titleize(key)}</span><strong>{html_escape(count)}</strong></li>"
        for key, count in sorted(counts.items())
    )
    return items or f'<li class="empty">{escape(empty)}</li>'


def _render_requests(
    requests: list[SettingsChangeRequestResponse],
    *,
    request_type: str | None,
    status: str | None,
    owner_decision_status: str | None,
) -> str:
    filtered = bool(request_type or status or owner_decision_status)
    if not requests:
        if filtered:
            body = (
                '<p class="empty-state" id="empty-settings-change-requests">No settings '
                "change requests match the current filters. This page does not create "
                "requests or apply settings.</p>"
            )
        else:
            body = (
                '<p class="empty-state" id="empty-settings-change-requests">No live '
                "settings change requests yet. Propose or create them from CLI or JSON. "
                "This page does not apply settings or execute live actions.</p>"
            )
        return (
            '    <section class="panel">\n'
            "      <h2>Requests</h2>\n"
            f"      {body}\n"
            "    </section>"
        )
    rows = "".join(_request_row(item) for item in requests)
    return (
        '    <section class="panel">\n'
        "      <h2>Requests</h2>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Type</th><th>Request</th><th>Status</th><th>Owner decision</th>"
        "<th>Setting names</th><th>Desired</th><th>Finding</th><th>Flags</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        "    </section>"
    )


def _request_row(item: SettingsChangeRequestResponse) -> str:
    href = request_href(item.request_id)
    desired = _desired_label(item)
    flags = (
        f"record-only={yes_no(item.record_only)} · "
        f"no-exec={yes_no(item.no_execution)} · "
        f"applied={yes_no(item.settings_applied)}"
    )
    names = ", ".join(item.requested_setting_names) if item.requested_setting_names else "—"
    return (
        "<tr>"
        f"<td>{titleize(item.request_type)}</td>"
        f'<td class="mono"><a class="row-link" href="{href}">'
        f"{html_escape(short_id(item.request_id))}</a></td>"
        f"<td>{html_escape(item.status)}</td>"
        f"<td>{html_escape(item.owner_decision_status)}</td>"
        f'<td class="mono">{html_escape(names)}</td>'
        f"<td>{html_escape(desired)}</td>"
        f"<td>{html_escape(item.finding_code)}</td>"
        f"<td>{html_escape(flags)}</td>"
        "</tr>"
    )


def _desired_label(item: SettingsChangeRequestResponse) -> str:
    if item.desired_status:
        return item.desired_status
    if item.desired_boolean is True:
        return "true"
    if item.desired_boolean is False:
        return "false"
    return "—"


def _render_setting_names(names: list[str]) -> str:
    unique = [name for name in names if name]
    if not unique:
        return '<p class="empty-state">No requested setting names.</p>'
    rows = "".join(f'<li class="mono">{html_escape(name)}</li>' for name in unique)
    return f'<ul class="plain">{rows}</ul>'


def _render_list_footer(queue: SettingsChangeRequestListResponse, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Record-only={yes_no(queue.record_only)}. "
        f"No execution={yes_no(queue.no_execution)}. "
        f"Executed={html_escape(queue.executed)}. "
        f"Settings applied={yes_no(queue.settings_applied)}. "
        f"Halt changed={yes_no(queue.halt_changed)}. "
        f"Owner approved={yes_no(queue.owner_approved)}. "
        f"Live action={yes_no(queue.live_action)}. "
        f"Outbound attempted={yes_no(queue.outbound_attempted)}. "
        "There are no apply, execute, enable outbound, or lift-halt controls "
        "on this page. Decision recording is audit-only.</p>\n"
        "    </footer>"
    )
