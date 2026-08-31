"""Owner approval packet HTML drilldown and decision-record form.

Phase 23 renders stored owner approval packets as internal HTML pages and
lets an operator record approved/rejected/needs_changes on a detail page.
Recording a decision never executes a packet and never sends email, enrolls
campaigns, generates sendable replies, books meetings, creates video-meet
links, places calls, publishes content, launches ads, spends money, deploys,
applies optimizer recommendations, or changes live/scoring/campaign/provider/
deployment settings or operator halt state. `owner_approved` remains false.
"""

from __future__ import annotations

from html import escape
from uuid import UUID

import structlog
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from vyro_growth.api.approval_packets import (
    ApprovalPacketResponse,
    ApprovalPacketRunResponse,
    approval_packet_run_to_response,
    empty_approval_packet_response,
    packet_to_response,
)
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
    APPROVAL_PACKETS_JSON_PATH,
    NO_STORE_HEADERS,
    OPERATOR_APPROVAL_PACKETS_PATH,
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
from vyro_growth.domain import ExecutionPlanType, PreflightStatus
from vyro_growth.services.approval_packets import (
    ApprovalPacketError,
    ApprovalPacketRunResult,
    ApprovalPacketService,
    ApprovalPacketView,
)
from vyro_growth.services.review_queue import MAX_NOTES_LENGTH, sanitize_operator_text

logger = structlog.get_logger(__name__)

_PLAN_FAMILIES: tuple[str, ...] = tuple(item.value for item in ExecutionPlanType)
_PREFLIGHT_STATUSES: tuple[str, ...] = tuple(item.value for item in PreflightStatus)
OPERATOR_UI_PACKET_DECISION_SOURCE = "operator_ui"


def parse_plan_family(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    if cleaned in _PLAN_FAMILIES:
        return cleaned
    return None


def parse_preflight_status(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    if cleaned in _PREFLIGHT_STATUSES:
        return cleaned
    return None


def packet_href(packet_id: UUID) -> str:
    return f"{OPERATOR_APPROVAL_PACKETS_PATH}/{packet_id}"


def packet_decision_href(packet_id: UUID) -> str:
    return f"{OPERATOR_APPROVAL_PACKETS_PATH}/{packet_id}/decision"


def packet_recorded_href(packet_id: UUID) -> str:
    return f"{OPERATOR_APPROVAL_PACKETS_PATH}/{packet_id}?decision_recorded=1"


def finding_counts(packet: ApprovalPacketResponse) -> tuple[int, int, int]:
    blocked = warning = info = 0
    for item in packet.findings:
        severity = str(item.get("severity", ""))
        match severity:
            case "blocked":
                blocked += 1
            case "warning":
                warning += 1
            case "info":
                info += 1
            case _:
                continue
    return blocked, warning, info


def render_approval_packets_error() -> str:
    return render_failure_page(
        page_id="operator-approval-packets-error",
        title="Approval packets unavailable",
        heading="Read-only approval packets unavailable",
        banner="Unable to load owner approval packets.",
        detail=(
            "The sanitized approval-packet list could not be rendered. "
            "Retry after checking database connectivity and runtime config."
        ),
    )


def render_approval_packet_missing() -> str:
    return render_failure_page(
        page_id="operator-approval-packets-missing",
        title="Approval packet not found",
        heading="Approval packet not found",
        banner="No matching owner approval packet is available.",
        detail=(
            "The requested packet id is unknown or no longer present. "
            "This page does not invent facts or execute any action."
        ),
    )


def render_approval_packet_list(
    run: ApprovalPacketRunResponse,
    *,
    plan_family: str | None,
    preflight_status: str | None,
    packets: list[ApprovalPacketResponse],
) -> str:
    generated = html_escape(format_dt(run.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Owner approval packets</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-approval-packets" data-read-only="true">\n'
        f"{_render_list_header(run, generated)}\n"
        f"{render_operator_nav('approval-packets')}\n"
        f"{_render_filters(plan_family, preflight_status)}\n"
        f"{_render_summary(run)}\n"
        f"{_render_packets(packets, plan_family=plan_family, preflight_status=preflight_status)}\n"
        f"{_render_list_footer(run, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def render_approval_packet_detail(
    packet: ApprovalPacketResponse,
    *,
    decision_recorded: bool = False,
    form_error: str | None = None,
    form_values: DecisionFormValues | None = None,
) -> str:
    generated = html_escape(format_dt(packet.generated_at))
    blocked, warning, info = finding_counts(packet)
    decision = packet.decision
    decision_block = (
        (
            '      <div class="metric-grid">\n'
            f"        {metric('Decision', decision.decision)}\n"
            f"        {metric('Reviewer', decision.reviewer)}\n"
            f"        {metric('Source', decision.source)}\n"
            f"        {metric('Decided at', format_dt(decision.decided_at))}\n"
            f"        {metric('Executed', yes_no(packet.executed))}\n"
            f"        {metric('Owner approved', yes_no(packet.owner_approved))}\n"
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
        _render_decision_saved_banner(packet)
        if decision_recorded and decision is not None
        else ""
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Approval packet</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-approval-packet" data-decision-record-only="true" '
        'data-execution="false">\n'
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Approval packet</h1>\n"
        '        <p class="lede">Decision-record only. No execution.</p>\n'
        "      </div>\n"
        f'      <p class="meta">Generated {generated}</p>\n'
        "    </header>\n"
        f"{saved_banner}"
        f"{render_operator_nav('approval-packets')}\n"
        '    <section class="panel">\n'
        "      <h2>Safe detail</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Packet id', short_id(packet.id))}\n"
        f"        {metric('Plan family', packet.plan_family)}\n"
        f"        {metric('Artifact type', packet.source_artifact_type)}\n"
        f"        {metric('Artifact id', short_id(packet.source_artifact_id))}\n"
        f"        {metric('Execution plan id', short_id(packet.source_execution_plan_id))}\n"
        f"        {metric('Preflight status', packet.preflight_status)}\n"
        f"        {metric('Dry-run only', yes_no(packet.dry_run_only))}\n"
        f"        {metric('No execution', yes_no(packet.no_execution))}\n"
        f"        {metric('Executed', yes_no(packet.executed))}\n"
        f"        {metric('Owner approved', yes_no(packet.owner_approved))}\n"
        f"        {metric('Owner approval required', yes_no(packet.owner_approval_required))}\n"
        f"        {metric('Decision', decision.decision if decision else 'none')}\n"
        f"        {metric('Blocked findings', blocked)}\n"
        f"        {metric('Warning findings', warning)}\n"
        f"        {metric('Info findings', info)}\n"
        "      </div>\n"
        f'      <p class="hint">Proposed action: {html_escape(packet.proposed_action)}</p>\n'
        "      <h3>Preflight checklist</h3>\n"
        f"      {_render_checklist(packet.preflight_checklist)}\n"
        "      <h3>Missing prerequisites</h3>\n"
        f"      {_render_checklist(packet.missing_prerequisites, empty='None missing.')}\n"
        "      <h3>Findings</h3>\n"
        f"      {_render_findings(packet.findings)}\n"
        "      <h3>Required owner decision labels</h3>\n"
        f"      {_render_decisions(packet.required_owner_decisions)}\n"
        "      <h3>Recorded owner decision</h3>\n"
        f"      {decision_block}\n"
        "    </section>\n"
        f"{_render_decision_form(packet, form_error=form_error, form_values=form_values)}\n"
        '    <p><a class="nav-link" href="'
        f'{escape(OPERATOR_APPROVAL_PACKETS_PATH)}">Back to approval packets</a></p>\n'
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_approval_packets_response(
    db: Session,
    settings: Settings,
    *,
    plan_family: str | None = None,
    preflight_status: str | None = None,
    service: ApprovalPacketService | None = None,
) -> HTMLResponse:
    del settings
    try:
        parsed_family = parse_plan_family(plan_family)
        parsed_status = parse_preflight_status(preflight_status)
        planner = service or ApprovalPacketService()
        latest = planner.latest(db)
        run = _run_to_response(latest)
        packets = [
            packet
            for packet in run.packets
            if (parsed_family is None or packet.plan_family == parsed_family)
            and (parsed_status is None or packet.preflight_status == parsed_status)
        ]
        html = render_approval_packet_list(
            run,
            plan_family=parsed_family,
            preflight_status=parsed_status,
            packets=packets,
        )
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_approval_packets_render_failed", read_only=True)
        return HTMLResponse(
            content=render_approval_packets_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def build_operator_approval_packet_response(
    db: Session,
    settings: Settings,
    *,
    packet_id: str,
    decision_recorded: bool = False,
    service: ApprovalPacketService | None = None,
) -> HTMLResponse:
    del settings
    try:
        try:
            parsed_id = UUID(packet_id)
        except ValueError:
            parsed_id = None
        if parsed_id is None:
            return HTMLResponse(
                content=render_approval_packet_missing(),
                status_code=404,
                headers=NO_STORE_HEADERS,
            )
        planner = service or ApprovalPacketService()
        packet = planner.get_packet(db, parsed_id)
        if packet is None:
            return HTMLResponse(
                content=render_approval_packet_missing(),
                status_code=404,
                headers=NO_STORE_HEADERS,
            )
        html = render_approval_packet_detail(
            packet_to_response(packet),
            decision_recorded=decision_recorded,
        )
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_approval_packet_render_failed", execution=False)
        return HTMLResponse(
            content=render_approval_packets_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def build_operator_approval_packet_decision_response(
    db: Session,
    settings: Settings,
    *,
    packet_id: str,
    form_body: bytes,
    service: ApprovalPacketService | None = None,
) -> HTMLResponse | RedirectResponse:
    del settings
    try:
        parsed_id = UUID(packet_id)
    except ValueError:
        parsed_id = None
    if parsed_id is None:
        return HTMLResponse(
            content=render_approval_packet_missing(),
            status_code=404,
            headers=NO_STORE_HEADERS,
        )
    planner = service or ApprovalPacketService()
    try:
        packet = planner.get_packet(db, parsed_id)
        if packet is None:
            return HTMLResponse(
                content=render_approval_packet_missing(),
                status_code=404,
                headers=NO_STORE_HEADERS,
            )
        if len(form_body) > MAX_FORM_BYTES:
            return _decision_form_error(
                packet,
                GENERIC_FORM_ERROR,
                form_values=DecisionFormValues(),
            )
        form = parse_urlencoded_form(form_body)
        decision = parse_form_decision(form.get("decision"))
        reviewer_raw = _clip(form.get("reviewer"), MAX_REVIEWER_LENGTH)
        notes_raw = _clip(form.get("reviewer_notes"), MAX_NOTES_LENGTH)
        form_values = DecisionFormValues(
            decision=decision,
            reviewer=sanitize_operator_text(reviewer_raw) or "",
            reviewer_notes=sanitize_operator_text(notes_raw) or "",
        )
        if decision is None:
            return _decision_form_error(packet, GENERIC_DECISION_ERROR, form_values=form_values)
        if _same_recorded_decision(packet, decision, reviewer_raw, notes_raw):
            return _decision_recorded_redirect(parsed_id)
        try:
            planner.record_decision(
                db,
                packet_id=parsed_id,
                decision=decision,
                reviewer=reviewer_raw,
                source=OPERATOR_UI_PACKET_DECISION_SOURCE,
                reviewer_notes=notes_raw,
            )
        except ApprovalPacketError as exc:
            logger.info(
                "operator_approval_packet_decision_rejected",
                code=exc.code,
                execution=False,
            )
            return _decision_service_error(exc, packet)
        return _decision_recorded_redirect(parsed_id)
    except Exception:
        logger.exception("operator_approval_packet_decision_failed", execution=False)
        return HTMLResponse(
            content=render_approval_packets_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _run_to_response(result: ApprovalPacketRunResult | None) -> ApprovalPacketRunResponse:
    if result is None:
        return empty_approval_packet_response()
    return approval_packet_run_to_response(result)


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:limit]


def _same_recorded_decision(
    packet: ApprovalPacketView,
    decision: str,
    reviewer: str | None,
    notes: str | None,
) -> bool:
    existing = packet.decision
    if existing is None:
        return False
    reviewer_name = sanitize_operator_text(reviewer) or "operator"
    notes_value = sanitize_operator_text(notes)
    return (
        existing.decision == decision
        and existing.reviewer == reviewer_name
        and existing.reviewer_notes == notes_value
    )


def _decision_recorded_redirect(packet_id: UUID) -> RedirectResponse:
    return RedirectResponse(
        url=packet_recorded_href(packet_id),
        status_code=303,
        headers=NO_STORE_HEADERS,
    )


def _decision_form_error(
    packet: ApprovalPacketView,
    message: str,
    *,
    form_values: DecisionFormValues | None = None,
) -> HTMLResponse:
    html = render_approval_packet_detail(
        packet_to_response(packet),
        form_error=message,
        form_values=form_values,
    )
    return HTMLResponse(content=html, status_code=400, headers=NO_STORE_HEADERS)


def _decision_service_error(
    exc: ApprovalPacketError,
    packet: ApprovalPacketView,
) -> HTMLResponse:
    match exc.code:
        case "packet_not_found" | "artifact_not_found":
            return HTMLResponse(
                content=render_approval_packet_missing(),
                status_code=404,
                headers=NO_STORE_HEADERS,
            )
        case "invalid_decision":
            return _decision_form_error(packet, GENERIC_DECISION_ERROR)
        case _:
            return _decision_form_error(packet, GENERIC_FORM_ERROR)


def _render_decision_saved_banner(packet: ApprovalPacketResponse) -> str:
    decision = packet.decision
    if decision is None:
        return ""
    notes = (
        f'      <p class="hint">Owner notes: {html_escape(decision.reviewer_notes)}</p>\n'
        if decision.reviewer_notes
        else ""
    )
    return (
        '    <div class="success-banner" id="decision-recorded">\n'
        "      <p>Decision recorded. No execution was attempted.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Decision', decision.decision)}\n"
        f"        {metric('Reviewer', decision.reviewer)}\n"
        f"        {metric('Source', decision.source)}\n"
        f"        {metric('Decided at', format_dt(decision.decided_at))}\n"
        f"        {metric('Executed', yes_no(packet.executed))}\n"
        f"        {metric('Owner approved', yes_no(packet.owner_approved))}\n"
        f"        {metric('Outbound attempted', 'no')}\n"
        "      </div>\n"
        f"{notes}"
        "    </div>\n"
    )


def _render_decision_form(
    packet: ApprovalPacketResponse,
    *,
    form_error: str | None = None,
    form_values: DecisionFormValues | None = None,
) -> str:
    action = packet_decision_href(packet.id)
    selected = (
        form_values.decision
        if form_values is not None and form_values.decision is not None
        else (packet.decision.decision if packet.decision is not None else "")
    )
    reviewer = (
        form_values.reviewer
        if form_values is not None
        else (packet.decision.reviewer if packet.decision is not None else "")
    )
    notes = (
        form_values.reviewer_notes
        if form_values is not None
        else (packet.decision.reviewer_notes if packet.decision is not None else "")
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
        "execute the packet, send email, enroll campaigns, book meetings, place "
        "calls, publish content, launch ads, spend money, deploy, change operator "
        "halt state, or mark the packet as live owner-approved.</p>\n"
        f"{error_html}"
        f'      <form method="post" action="{escape(action)}" '
        'id="operator-approval-packet-decision-form" autocomplete="off">\n'
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
        '      <p class="hint">This form records a decision only. There is no execute '
        "control.</p>\n"
        "    </section>"
    )


def _owner_approved_count(run: ApprovalPacketRunResponse) -> int:
    return sum(1 for item in run.packets if item.owner_approved)


def _render_list_header(run: ApprovalPacketRunResponse, generated: str) -> str:
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Owner approval packets</h1>\n"
        '        <p class="lede">Read-only preflight packets. No execution.</p>\n'
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · latest run '
        f"{html_escape(run.status)}</p>\n"
        "    </header>"
    )


def _render_filters(plan_family: str | None, preflight_status: str | None) -> str:
    family_links = [
        filter_link(
            _list_href(None, preflight_status),
            "All families",
            current=plan_family is None,
        )
    ]
    for name in _PLAN_FAMILIES:
        family_links.append(
            filter_link(
                _list_href(name, preflight_status),
                name.replace("_", " "),
                current=plan_family == name,
            )
        )
    status_links = [
        filter_link(
            _list_href(plan_family, None),
            "All preflight",
            current=preflight_status is None,
        )
    ]
    for name in _PREFLIGHT_STATUSES:
        status_links.append(
            filter_link(
                _list_href(plan_family, name),
                name.replace("_", " "),
                current=preflight_status == name,
            )
        )
    json_href = escape(APPROVAL_PACKETS_JSON_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Plan family filters">'
        f"{' '.join(family_links)}</nav>\n"
        '    <nav class="filter-nav" aria-label="Preflight status filters">'
        f"{' '.join(status_links)}\n"
        f'      <a class="nav-link nav-json" href="{json_href}">JSON packets</a>\n'
        "    </nav>"
    )


def _list_href(plan_family: str | None, preflight_status: str | None) -> str:
    params: list[str] = []
    if plan_family:
        params.append(f"plan_family={plan_family}")
    if preflight_status:
        params.append(f"preflight_status={preflight_status}")
    if not params:
        return OPERATOR_APPROVAL_PACKETS_PATH
    return f"{OPERATOR_APPROVAL_PACKETS_PATH}?{'&'.join(params)}"


def _render_summary(run: ApprovalPacketRunResponse) -> str:
    families: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for packet in run.packets:
        families[packet.plan_family] = families.get(packet.plan_family, 0) + 1
        statuses[packet.preflight_status] = statuses.get(packet.preflight_status, 0) + 1
    family_items = "".join(
        f"<li><span>{titleize(key)}</span><strong>{html_escape(count)}</strong></li>"
        for key, count in sorted(families.items())
    ) or '<li class="empty">No plan families.</li>'
    status_items = "".join(
        f"<li><span>{titleize(key)}</span><strong>{html_escape(count)}</strong></li>"
        for key, count in sorted(statuses.items())
    ) or '<li class="empty">No preflight statuses.</li>'
    return (
        '    <section class="status-strip" aria-label="Packet counts">\n'
        f"      {metric('Packets', run.packet_count)}\n"
        f"      {metric('Executed', run.executed_count)}\n"
        f"      {metric('Dry-run only', yes_no(run.dry_run_only))}\n"
        f"      {metric('No execution', yes_no(run.no_execution))}\n"
        f"      {metric('Outbound attempted', yes_no(run.outbound_attempted))}\n"
        "    </section>\n"
        '    <section class="panel">\n'
        "      <h2>Latest run</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Run status', run.status)}\n"
        f"        {metric('Visible packets', len(run.packets))}\n"
        f"        {metric('Owner approved', _owner_approved_count(run))}\n"
        "      </div>\n"
        "      <h3>Plan families</h3>\n"
        f'      <ul class="kv-list">{family_items}</ul>\n'
        "      <h3>Preflight status</h3>\n"
        f'      <ul class="kv-list">{status_items}</ul>\n'
        "    </section>"
    )


def _render_packets(
    packets: list[ApprovalPacketResponse],
    *,
    plan_family: str | None,
    preflight_status: str | None,
) -> str:
    if not packets:
        if plan_family or preflight_status:
            body = (
                '<p class="empty-state" id="empty-approval-packets">No approval packets '
                "match the current filters. This page does not generate packets or "
                "execute plans.</p>"
            )
        else:
            body = (
                '<p class="empty-state" id="empty-approval-packets">No owner approval '
                "packets or preflight rows yet. Generation is a separate dry-run "
                "command and is not started from this page.</p>"
            )
        return (
            '    <section class="panel">\n'
            "      <h2>Packets</h2>\n"
            f"      {body}\n"
            "    </section>"
        )
    rows = "".join(_packet_row(packet) for packet in packets)
    return (
        '    <section class="panel">\n'
        "      <h2>Packets</h2>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Family</th><th>Packet</th><th>Artifact</th><th>Preflight</th>"
        "<th>Decision</th><th>Findings</th><th>Action</th><th>Flags</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        "    </section>"
    )


def _packet_row(packet: ApprovalPacketResponse) -> str:
    href = packet_href(packet.id)
    blocked, warning, info = finding_counts(packet)
    decision = packet.decision.decision if packet.decision is not None else "none"
    flags = (
        f"dry-run={yes_no(packet.dry_run_only)} · "
        f"no-exec={yes_no(packet.no_execution)} · "
        f"executed={yes_no(packet.executed)}"
    )
    return (
        "<tr>"
        f"<td>{titleize(packet.plan_family)}</td>"
        f'<td class="mono"><a class="row-link" href="{href}">'
        f"{html_escape(short_id(packet.id))}</a></td>"
        f"<td>{titleize(packet.source_artifact_type)}</td>"
        f"<td>{html_escape(packet.preflight_status)}</td>"
        f"<td>{html_escape(decision)}</td>"
        f"<td>blocked={blocked} · warning={warning} · info={info}</td>"
        f"<td>{html_escape(packet.proposed_action)}</td>"
        f"<td>{html_escape(flags)}</td>"
        "</tr>"
    )


def _render_checklist(
    items: list[dict[str, object]],
    *,
    empty: str = "No checklist items.",
) -> str:
    if not items:
        return f'<p class="empty-state">{escape(empty)}</p>'
    rows = []
    for item in items:
        code = html_escape(item.get("code"))
        label = html_escape(item.get("label"))
        met = html_escape(item.get("met")) if "met" in item else escape("—")
        rows.append(f"<tr><td class=\"mono\">{code}</td><td>{label}</td><td>{met}</td></tr>")
    return (
        '<table class="dense"><thead><tr>'
        "<th>Code</th><th>Label</th><th>Met</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _render_findings(items: list[dict[str, object]]) -> str:
    if not items:
        return '<p class="empty-state">No blocked, warning, or info findings.</p>'
    rows = []
    for item in items:
        severity = str(item.get("severity") or "info")
        rows.append(
            f'<tr class="severity-{escape(severity)}">'
            f"<td>{html_escape(severity)}</td>"
            f"<td class=\"mono\">{html_escape(item.get('code'))}</td>"
            f"<td>{html_escape(item.get('message'))}</td>"
            "</tr>"
        )
    return (
        '<table class="dense"><thead><tr>'
        "<th>Severity</th><th>Code</th><th>Message</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _render_decisions(items: list[str]) -> str:
    if not items:
        return '<p class="empty-state">No required owner decision labels.</p>'
    rows = "".join(f"<li>{html_escape(item)}</li>" for item in items)
    return f'<ul class="plain">{rows}</ul>'


def _render_list_footer(run: ApprovalPacketRunResponse, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only=yes. "
        f"Executed={html_escape(run.executed_count)}. "
        f"Outbound attempted={yes_no(run.outbound_attempted)}. "
        f"Call attempted={yes_no(run.live_call_attempted)}. "
        f"Recommendation applied={yes_no(run.recommendation_applied)}. "
        f"Spend attempted={yes_no(run.spend_attempted)}. "
        f"Campaign launched={yes_no(run.campaign_launched)}. "
        f"Pages published={yes_no(run.pages_published)}. "
        f"Ads launched={yes_no(run.ads_launched)}. "
        "There are no approve, reject, or execute controls on this page.</p>\n"
        "    </footer>"
    )
