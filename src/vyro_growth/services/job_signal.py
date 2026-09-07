"""Read-only job-posting intent helpers for stored website facts.

Phase 68 scores public schema.org JobPosting evidence already extracted from a
verified practice website. It does not fetch job boards, apply, contact hiring
managers, or send outreach.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from vyro_growth.domain import JobIntentCode, JobRoleCategory, WebsiteFactType
from vyro_growth.models import SourceEvidence
from vyro_growth.providers.job_signal import (
    BILLING_JOB_INTENT_CODES,
    JOB_SIGNAL_EXPIRY_DAYS,
    JOB_SIGNAL_EXTRACTOR_VERSION,
    POINTS_JOB_SIGNAL,
    JobSignalRecord,
    job_signal_points,
    recency_days_for,
    recency_status_for,
    sanitize_job_signal_metrics_from_facts,
    sanitize_job_title,
)

__all__ = [
    "BILLING_JOB_INTENT_CODES",
    "JOB_SIGNAL_EXTRACTOR_VERSION",
    "JOB_SIGNAL_EXPIRY_DAYS",
    "POINTS_JOB_SIGNAL",
    "JobSignalRecord",
    "job_signal_from_evidence",
    "job_signal_points",
    "recency_days_for",
    "recency_status_for",
    "sanitize_job_signal_metrics",
    "sanitize_job_signal_metrics_from_facts",
    "sanitize_job_title",
    "select_best_job_signal",
]


def parse_job_intent(value: object) -> JobIntentCode | None:
    text = _text(value)
    if text is None:
        return None
    token = text.split(":", 1)[0]
    try:
        return JobIntentCode(token)
    except ValueError:
        return None


def parse_job_role(value: object) -> JobRoleCategory:
    text = _text(value)
    if text is None:
        return JobRoleCategory.OTHER
    try:
        return JobRoleCategory(text)
    except ValueError:
        return JobRoleCategory.OTHER


def parse_posted_date(value: object) -> date | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def job_signal_from_evidence(
    row: SourceEvidence,
    *,
    now: datetime | None = None,
) -> JobSignalRecord | None:
    if row.claim_type != WebsiteFactType.JOB_POSTING_SIGNAL.value:
        return None
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    intent = parse_job_intent(metadata.get("intent_code") or row.extracted_value)
    if intent is None:
        return None
    posted_on = parse_posted_date(metadata.get("date_posted"))
    as_of = now or datetime.now(tz=UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    status = recency_status_for(posted_on, now=as_of)
    return JobSignalRecord(
        intent_code=intent,
        role_category=parse_job_role(metadata.get("role_category")),
        date_posted=posted_on.isoformat() if posted_on is not None else None,
        recency_status=status,
        recency_days=recency_days_for(posted_on, now=as_of),
        source_url=row.source_url,
        confidence=float(row.confidence) if row.confidence is not None else 0.0,
        observed_at=as_of,
        evidence_id=str(row.id),
        extracted_value=_text(row.extracted_value),
    )


def select_best_job_signal(
    rows: Sequence[SourceEvidence],
    *,
    now: datetime | None = None,
) -> JobSignalRecord | None:
    ranked: list[tuple[int, int, float, JobSignalRecord]] = []
    as_of = now or datetime.now(tz=UTC)
    for row in rows:
        record = job_signal_from_evidence(row, now=as_of)
        if record is None:
            continue
        points = job_signal_points(
            record.intent_code,
            recency_days=record.recency_days,
            recency_status=record.recency_status,
        )
        recency_rank = 0 if record.recency_days is None else -record.recency_days
        ranked.append((points, recency_rank, record.confidence, record))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return ranked[0][3]


def sanitize_job_signal_metrics(records: Sequence[JobSignalRecord]) -> dict[str, Any]:
    intent_counts: Counter[str] = Counter(record.intent_code.value for record in records)
    recency_counts: Counter[str] = Counter(record.recency_status.value for record in records)
    role_counts: Counter[str] = Counter(record.role_category.value for record in records)
    return {
        "extracted": len(records),
        "billing_intent_count": sum(
            1 for record in records if record.intent_code in BILLING_JOB_INTENT_CODES
        ),
        "by_intent_code": dict(sorted(intent_counts.items())),
        "by_recency_status": dict(sorted(recency_counts.items())),
        "by_role_category": dict(sorted(role_counts.items())),
    }


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
