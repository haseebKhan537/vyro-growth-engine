from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html import unescape
from typing import Any

from vyro_growth.domain import JobIntentCode, JobRecencyStatus, JobRoleCategory, WebsiteFactType
from vyro_growth.observability import contains_phi_indicator
from vyro_growth.providers.website import (
    EVIDENCE_SNIPPET_MAX_LENGTH,
    ExtractedFact,
    PublicPage,
    clip_text,
    is_blocked_public_path,
    is_directory_host,
    is_job_board_host,
    is_job_page_url,
)

JOB_SIGNAL_PROVIDER_NAME = "job_signal"
JOB_SIGNAL_EXTRACTOR_VERSION = "job-posting-jsonld-v1"
POINTS_JOB_SIGNAL = 15
JOB_SIGNAL_EXPIRY_DAYS = 90
FRESH_MAX_DAYS = 29
AGING_MAX_DAYS = 59
STALE_MAX_DAYS = 89
BILLING_JOB_INTENT_CODES = frozenset(
    {
        JobIntentCode.BILLING_HIRING,
        JobIntentCode.CODING_HIRING,
        JobIntentCode.DENIALS_HIRING,
        JobIntentCode.RCM_HIRING,
        JobIntentCode.AR_HIRING,
    }
)
JOB_POSTING_MAX_PER_PAGE = 10
TITLE_MAX_LENGTH = 120
JSON_LD_MAX_BYTES = 200_000
JOB_POSTING_TYPE_NAMES = frozenset(
    {
        "jobposting",
        "https://schema.org/jobposting",
        "http://schema.org/jobposting",
    }
)
JSON_LD_SCRIPT_RE = re.compile(
    r"<script\b(?=[^>]*\btype\s*=\s*['\"]application/ld\+json['\"])[^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
DENIALS_PHRASES = (
    "denial management",
    "denials specialist",
    "denials analyst",
    "claim appeals",
    "appeals specialist",
    "denials",
)
CODING_PHRASES = (
    "medical coder",
    "medical coding",
    "coding specialist",
    "coding manager",
    "coding supervisor",
    "health information coder",
    "icd-10",
    "cpt coder",
)
RCM_PHRASES = (
    "revenue cycle",
    "revenue-cycle",
    " rcm ",
    "rcm manager",
    "rcm specialist",
    "rcm coordinator",
)
AR_PHRASES = (
    "accounts receivable",
    "account receivable",
    "a/r specialist",
    "a/r manager",
    "ar specialist",
    "ar manager",
    "ar coordinator",
)
BILLING_PHRASES = (
    "medical biller",
    "medical billing",
    "billing specialist",
    "billing manager",
    "billing coordinator",
    "billing clerk",
    "billing analyst",
    "patient accounts",
    "claims specialist",
    "charge entry",
)
MANAGER_TOKENS = ("manager", "director", "supervisor", "lead")
PHI_PHRASES = (
    "patient diagnosis",
    "patient name",
    "diagnosed with",
    "prescription",
    "medical record",
    "the patient",
    "my patient",
    "date of birth",
    "social security",
    "protected health",
)
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]*)\d{3}[-.\s]*\d{4}")


@dataclass(frozen=True)
class JobSignalRecord:
    intent_code: JobIntentCode
    role_category: JobRoleCategory
    date_posted: str | None
    recency_status: JobRecencyStatus
    source_url: str
    confidence: float
    observed_at: datetime
    recency_days: int | None = None
    evidence_id: str | None = None
    extracted_value: str | None = None


def recency_days_for(posted_on: date | None, *, now: datetime | None = None) -> int | None:
    if posted_on is None:
        return None
    as_of = now or datetime.now(tz=UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    return max(0, (as_of.astimezone(UTC).date() - posted_on).days)


def recency_status_for(posted_on: date | None, *, now: datetime | None = None) -> JobRecencyStatus:
    age = recency_days_for(posted_on, now=now)
    if age is None:
        return JobRecencyStatus.UNKNOWN
    if age >= JOB_SIGNAL_EXPIRY_DAYS:
        return JobRecencyStatus.EXPIRED
    if age <= FRESH_MAX_DAYS:
        return JobRecencyStatus.FRESH
    if age <= AGING_MAX_DAYS:
        return JobRecencyStatus.AGING
    return JobRecencyStatus.STALE


def job_signal_points(
    intent: JobIntentCode,
    *,
    recency_days: int | None,
    recency_status: JobRecencyStatus | None = None,
) -> int:
    if intent not in BILLING_JOB_INTENT_CODES:
        return 0
    status = recency_status
    if status is None:
        if recency_days is None:
            status = JobRecencyStatus.UNKNOWN
        elif recency_days >= JOB_SIGNAL_EXPIRY_DAYS:
            status = JobRecencyStatus.EXPIRED
        elif recency_days <= FRESH_MAX_DAYS:
            status = JobRecencyStatus.FRESH
        elif recency_days <= AGING_MAX_DAYS:
            status = JobRecencyStatus.AGING
        else:
            status = JobRecencyStatus.STALE
    match status:
        case JobRecencyStatus.UNKNOWN | JobRecencyStatus.EXPIRED:
            return 0
        case JobRecencyStatus.FRESH | JobRecencyStatus.AGING | JobRecencyStatus.STALE:
            if recency_days is None:
                return 0
            remaining = JOB_SIGNAL_EXPIRY_DAYS - recency_days
            if remaining <= 0:
                return 0
            return max(1, round(POINTS_JOB_SIGNAL * remaining / JOB_SIGNAL_EXPIRY_DAYS))
        case _:
            unreachable = status
            raise RuntimeError(f"unhandled job recency status: {unreachable!r}")


def sanitize_job_title(value: str | None, *, max_length: int = 120) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = WHITESPACE_RE.sub(" ", value).strip()
    if not stripped:
        return None
    redacted = _EMAIL_RE.sub("[REDACTED]", stripped)
    redacted = _PHONE_RE.sub("[REDACTED]", redacted)
    if contains_phi_indicator(redacted):
        return None
    if len(redacted) > max_length:
        return redacted[: max_length - 3].rstrip() + "..."
    return redacted


def sanitize_job_signal_metrics_from_facts(facts: Sequence[Mapping[str, object]]) -> dict[str, Any]:
    intent_counts: Counter[str] = Counter()
    recency_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    billing_count = 0
    for fact in facts:
        intent = str(fact.get("intent_code") or "unknown")
        recency = str(fact.get("recency_status") or JobRecencyStatus.UNKNOWN.value)
        role = str(fact.get("role_category") or JobRoleCategory.OTHER.value)
        intent_counts[intent] += 1
        recency_counts[recency] += 1
        role_counts[role] += 1
        try:
            parsed = JobIntentCode(intent)
        except ValueError:
            parsed = None
        if parsed in BILLING_JOB_INTENT_CODES:
            billing_count += 1
    return {
        "extracted": sum(intent_counts.values()),
        "billing_intent_count": billing_count,
        "by_intent_code": dict(sorted(intent_counts.items())),
        "by_recency_status": dict(sorted(recency_counts.items())),
        "by_role_category": dict(sorted(role_counts.items())),
    }


def extract_job_posting_signals(
    page: PublicPage,
    *,
    now: datetime | None = None,
) -> tuple[ExtractedFact, ...]:
    if (
        is_directory_host(page.url)
        or is_job_board_host(page.url)
        or is_blocked_public_path(page.url)
    ):
        return ()
    as_of = now or datetime.now(tz=UTC)
    facts: list[ExtractedFact] = []
    seen: set[str] = set()
    for payload in _json_ld_payloads(page.text):
        for node in _job_posting_nodes(payload):
            fact = _fact_from_job_posting(node, page=page, now=as_of)
            if fact is None:
                continue
            key = fact.value.lower()
            if key in seen:
                continue
            seen.add(key)
            facts.append(fact)
            if len(facts) >= JOB_POSTING_MAX_PER_PAGE:
                return tuple(facts)
    return tuple(facts)


def job_signal_metrics(facts: Sequence[ExtractedFact]) -> dict[str, object]:
    payloads = [
        {
            "intent_code": fact.metadata.get("intent_code"),
            "recency_status": fact.metadata.get("recency_status"),
            "role_category": fact.metadata.get("role_category"),
        }
        for fact in facts
        if fact.fact_type is WebsiteFactType.JOB_POSTING_SIGNAL
    ]
    return sanitize_job_signal_metrics_from_facts(payloads)


def _json_ld_payloads(html_text: str) -> tuple[object, ...]:
    payloads: list[object] = []
    for match in JSON_LD_SCRIPT_RE.finditer(html_text):
        raw = match.group(1).strip()
        if not raw or len(raw) > JSON_LD_MAX_BYTES:
            continue
        cleaned = raw.removeprefix("<!--").removesuffix("-->").strip()
        try:
            payloads.append(json.loads(cleaned))
        except json.JSONDecodeError:
            continue
    return tuple(payloads)


def _job_posting_nodes(payload: object) -> tuple[dict[str, Any], ...]:
    nodes: list[dict[str, Any]] = []
    for item in _walk_json_ld(payload):
        if _is_job_posting(item):
            nodes.append(item)
    return tuple(nodes)


def _walk_json_ld(payload: object) -> tuple[dict[str, Any], ...]:
    if isinstance(payload, list):
        nodes: list[dict[str, Any]] = []
        for item in payload:
            nodes.extend(_walk_json_ld(item))
        return tuple(nodes)
    if not isinstance(payload, dict):
        return ()
    nodes = [payload]
    graph = payload.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            nodes.extend(_walk_json_ld(item))
    return tuple(nodes)


def _is_job_posting(node: Mapping[str, Any]) -> bool:
    raw_type = node.get("@type")
    names: list[str] = []
    if isinstance(raw_type, str):
        names.append(raw_type)
    elif isinstance(raw_type, list):
        names.extend(item for item in raw_type if isinstance(item, str))
    return any(name.strip().lower().rstrip("/") in JOB_POSTING_TYPE_NAMES for name in names)


def _fact_from_job_posting(
    node: Mapping[str, Any],
    *,
    page: PublicPage,
    now: datetime,
) -> ExtractedFact | None:
    title = sanitize_job_title(_ld_text(node.get("title")), max_length=TITLE_MAX_LENGTH)
    category = _ld_text(node.get("occupationalCategory"))
    description = _ld_text(node.get("description"))
    haystack = " ".join(part for part in (title, category, description) if part)
    if not haystack or _unsafe_text(haystack):
        return None
    intent = classify_job_intent(haystack)
    role = classify_job_role(title or haystack, intent)
    posted_on = parse_job_posted_date(node.get("datePosted"))
    recency = recency_status_for(posted_on, now=now)
    record = JobSignalRecord(
        intent_code=intent,
        role_category=role,
        date_posted=posted_on.isoformat() if posted_on is not None else None,
        recency_status=recency,
        source_url=page.url,
        confidence=_confidence_for(intent, posted_on is not None, page.url),
        observed_at=now,
    )
    value = _extracted_value(record, title)
    snippet = clip_text(title or intent.value, EVIDENCE_SNIPPET_MAX_LENGTH)
    return ExtractedFact(
        fact_type=WebsiteFactType.JOB_POSTING_SIGNAL,
        value=value,
        confidence=record.confidence,
        snippet=snippet,
        source_url=page.url,
        metadata={
            "intent_code": record.intent_code.value,
            "role_category": record.role_category.value,
            "date_posted": record.date_posted,
            "recency_status": record.recency_status.value,
            "extractor": JOB_SIGNAL_EXTRACTOR_VERSION,
            "source_kind": "schema_org_job_posting",
            "fabricated": False,
            "applied": False,
            "contacted": False,
        },
    )


def classify_job_intent(text: str) -> JobIntentCode:
    lowered = f" {text.lower()} "
    if any(phrase in lowered for phrase in DENIALS_PHRASES):
        return JobIntentCode.DENIALS_HIRING
    if any(phrase in lowered for phrase in CODING_PHRASES):
        return JobIntentCode.CODING_HIRING
    if any(phrase in lowered for phrase in RCM_PHRASES):
        return JobIntentCode.RCM_HIRING
    if any(phrase in lowered for phrase in AR_PHRASES):
        return JobIntentCode.AR_HIRING
    if any(phrase in lowered for phrase in BILLING_PHRASES) or " billing" in lowered:
        return JobIntentCode.BILLING_HIRING
    return JobIntentCode.NON_BILLING_HIRING


def classify_job_role(text: str, intent: JobIntentCode) -> JobRoleCategory:
    lowered = text.lower()
    manager = any(token in lowered for token in MANAGER_TOKENS)
    match intent:
        case JobIntentCode.BILLING_HIRING:
            if manager:
                return JobRoleCategory.BILLING_MANAGER
            return JobRoleCategory.BILLING_SPECIALIST
        case JobIntentCode.CODING_HIRING:
            return JobRoleCategory.CODING_MANAGER if manager else JobRoleCategory.MEDICAL_CODER
        case JobIntentCode.DENIALS_HIRING:
            return JobRoleCategory.DENIALS_SPECIALIST
        case JobIntentCode.RCM_HIRING:
            return JobRoleCategory.RCM_MANAGER
        case JobIntentCode.AR_HIRING:
            return JobRoleCategory.AR_SPECIALIST
        case JobIntentCode.NON_BILLING_HIRING:
            return JobRoleCategory.OTHER
        case _:
            unreachable = intent
            raise RuntimeError(f"unhandled job intent: {unreachable!r}")


def parse_job_posted_date(value: object) -> date | None:
    text = _ld_text(value)
    if text is None:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            return date.fromisoformat(candidate[:10])
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.date()


def _confidence_for(intent: JobIntentCode, has_date: bool, url: str) -> float:
    if intent is JobIntentCode.NON_BILLING_HIRING:
        base = 0.55
    elif has_date:
        base = 0.9
    else:
        base = 0.7
    if is_job_page_url(url):
        base = min(0.95, base + 0.04)
    return round(base, 3)


def _extracted_value(record: JobSignalRecord, title: str | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (title or record.role_category.value).lower()).strip("_")
    posted = record.date_posted or "unknown"
    return f"{record.intent_code.value}:{record.role_category.value}:{posted}:{slug[:40]}"


def _ld_text(value: object) -> str | None:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, list):
        parts = [_ld_text(item) for item in value]
        joined = " ".join(part for part in parts if part)
        return joined or None
    if isinstance(value, dict):
        for key in ("name", "title", "text", "value"):
            text = _ld_text(value.get(key))
            if text:
                return text
    return None


def _clean_text(value: str) -> str | None:
    without_tags = TAG_RE.sub(" ", unescape(value))
    stripped = WHITESPACE_RE.sub(" ", without_tags).strip(" -,|:;")
    return stripped or None


def _unsafe_text(value: str) -> bool:
    lowered = value.lower()
    if any(phrase in lowered for phrase in PHI_PHRASES):
        return True
    return contains_phi_indicator(value) and any(
        token in lowered for token in ("diagnosis", "diabetes", "phi", "ssn", "hipaa", "mrn")
    )
