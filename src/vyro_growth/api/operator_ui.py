"""Shared read-only HTML helpers for internal operator UI pages.

These helpers never execute outbound, booking, calling, publish, spend,
deploy, or optimizer-apply actions. They only escape and sanitize text for
server-rendered operator views.
"""

from __future__ import annotations

from html import escape
from typing import Literal
from uuid import UUID

from vyro_growth.observability import sanitize_operator_text

OPERATOR_DASHBOARD_PATH = "/internal/operator-dashboard"
OPERATOR_REVIEW_QUEUE_PATH = "/internal/operator-review-queue"
OPERATOR_APPROVAL_PACKETS_PATH = "/internal/operator-approval-packets"
OPERATOR_ACTION_READINESS_PATH = "/internal/operator-action-readiness"
OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH = "/internal/operator-settings-change-requests"
OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH = "/internal/operator-settings-execution-preflight"
OPERATOR_OWNER_HANDOFF_PACKET_PATH = "/internal/operator-owner-handoff-packet"
COMMAND_CENTER_JSON_PATH = "/internal/operator-command-center"
REVIEW_QUEUE_JSON_PATH = "/internal/review-queue"
APPROVAL_PACKETS_JSON_PATH = "/internal/approval-packets"
ACTION_READINESS_JSON_PATH = "/internal/action-readiness"
SETTINGS_CHANGE_JSON_PATH = "/internal/settings-change-requests"
SETTINGS_EXECUTION_PREFLIGHT_JSON_PATH = "/internal/settings-execution-preflight"
LAUNCH_READINESS_JSON_PATH = "/internal/launch-readiness"
OWNER_HANDOFF_JSON_PATH = "/internal/owner-handoff-packet"
NO_STORE_HEADERS = {"Cache-Control": "no-store"}

OperatorSurface = Literal[
    "dashboard",
    "review-queue",
    "approval-packets",
    "action-readiness",
    "settings-change-requests",
    "settings-execution-preflight",
    "owner-handoff-packet",
]

_SURFACE_LABELS: dict[OperatorSurface, str] = {
    "dashboard": "Dashboard",
    "review-queue": "Review queue",
    "approval-packets": "Approval packets",
    "action-readiness": "Action readiness",
    "settings-change-requests": "Settings requests",
    "settings-execution-preflight": "Settings preflight",
    "owner-handoff-packet": "Owner handoff",
}
_SURFACE_HREFS: dict[OperatorSurface, str] = {
    "dashboard": OPERATOR_DASHBOARD_PATH,
    "review-queue": OPERATOR_REVIEW_QUEUE_PATH,
    "approval-packets": OPERATOR_APPROVAL_PACKETS_PATH,
    "action-readiness": OPERATOR_ACTION_READINESS_PATH,
    "settings-change-requests": OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH,
    "settings-execution-preflight": OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
    "owner-handoff-packet": OPERATOR_OWNER_HANDOFF_PACKET_PATH,
}


def html_escape(value: object, *, empty: str = "—") -> str:
    if value is None:
        return escape(empty)
    if isinstance(value, bool):
        return escape("yes" if value else "no")
    sanitized = sanitize_operator_text(str(value))
    if sanitized is None or sanitized == "":
        return escape(empty)
    return escape(sanitized)


def titleize(value: str | None) -> str:
    if not value:
        return escape("—")
    cleaned = sanitize_operator_text(value.replace("_", " ")) or value
    return escape(cleaned)


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def format_dt(value: object) -> str | None:
    if value is None:
        return None
    return str(value).replace("+00:00", "Z")


def short_id(value: UUID | None) -> str | None:
    if value is None:
        return None
    return str(value)


def metric(label: str, value: object) -> str:
    return (
        f'<div class="metric"><span class="lbl">{escape(label)}</span>'
        f"<strong>{html_escape(value)}</strong></div>"
    )


def filter_link(href: str, label: str, *, current: bool) -> str:
    cls = "nav-link is-current" if current else "nav-link"
    current_attr = ' aria-current="page"' if current else ""
    return f'<a class="{cls}" href="{escape(href)}"{current_attr}>{escape(label)}</a>'


def render_operator_nav(current: OperatorSurface) -> str:
    surfaces: tuple[OperatorSurface, ...] = (
        "dashboard",
        "review-queue",
        "approval-packets",
        "action-readiness",
        "settings-change-requests",
        "settings-execution-preflight",
        "owner-handoff-packet",
    )
    links = []
    for name in surfaces:
        label = _SURFACE_LABELS[name]
        href = _SURFACE_HREFS[name]
        links.append(filter_link(href, label, current=name == current))
    return (
        '    <nav class="section-nav" aria-label="Operator surfaces">'
        f"{' '.join(links)}\n"
        "    </nav>"
    )


def render_failure_page(
    *,
    page_id: str,
    title: str,
    heading: str,
    banner: str,
    detail: str,
) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{escape(title)}</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        f'  <main id="{escape(page_id)}">\n'
        f'    <div class="banner">{escape(banner)}</div>\n'
        f"    <h1>{escape(heading)}</h1>\n"
        f"    <p>{escape(detail)}</p>\n"
        "    <p>No pipeline rows were written and no outbound, booking, calling, "
        "publish, spend, or deploy action was executed. Operator halt state was "
        "not changed.</p>\n"
        f'    <p><a class="nav-link" href="{escape(OPERATOR_DASHBOARD_PATH)}">'
        "Back to dashboard</a></p>\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


OPERATOR_UI_STYLES = """  <style>
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
    .section-nav, .filter-nav { display: flex; flex-wrap: wrap; gap: 0.35rem;
      margin: 0 0 0.75rem; }
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
    .banner {
      border: 1px solid #5a2a2a; background: #2a1616; color: #e8c4c4;
      padding: 0.75rem 0.9rem; border-radius: 4px; margin-bottom: 1rem;
    }
    a.row-link { color: #9ec3e6; text-decoration: none; }
    .success-banner {
      border: 1px solid #2f4a38; background: #16241c; color: #c4e8d0;
      padding: 0.75rem 0.9rem; border-radius: 4px; margin-bottom: 1rem;
    }
    .form-grid { display: grid; gap: 0.55rem; max-width: 28rem; }
    .form-grid label { display: grid; gap: 0.2rem; color: #c5cad1; }
    .form-grid input, .form-grid select, .form-grid textarea {
      background: #14161a; color: #e6e8eb; border: 1px solid #2a2f38;
      border-radius: 3px; padding: 0.35rem 0.45rem; font: inherit;
    }
    .form-grid textarea { min-height: 4.5rem; }
    .form-grid button[type="submit"] {
      justify-self: start; background: #2a3340; color: #fff;
      border: 1px solid #5b6b7c; border-radius: 3px; padding: 0.35rem 0.7rem;
      font: inherit; cursor: pointer;
    }
  </style>"""
