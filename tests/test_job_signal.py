from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from tests.fixtures.website_pages import (
    BILLING_JOB_JSONLD_HTML,
    MISSING_DATE_JOB_JSONLD_HTML,
    NON_BILLING_JOB_JSONLD_HTML,
    STALE_BILLING_JOB_JSONLD_HTML,
    page,
)
from vyro_growth.domain import JobIntentCode, JobRecencyStatus, JobRoleCategory, WebsiteFactType
from vyro_growth.providers.job_signal import (
    POINTS_JOB_SIGNAL,
    extract_job_posting_signals,
    job_signal_metrics,
    job_signal_points,
    recency_status_for,
)
from vyro_growth.providers.website import (
    generate_job_page_candidates,
    is_job_board_host,
    is_job_page_url,
)
from vyro_growth.services.job_signal import sanitize_job_signal_metrics, sanitize_job_title

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def test_extracts_billing_jobposting_jsonld() -> None:
    facts = extract_job_posting_signals(
        page("https://austinfamilymedicine.com/careers", BILLING_JOB_JSONLD_HTML),
        now=NOW,
    )
    assert len(facts) == 1
    fact = facts[0]
    assert fact.fact_type is WebsiteFactType.JOB_POSTING_SIGNAL
    assert fact.metadata["intent_code"] == JobIntentCode.BILLING_HIRING.value
    assert fact.metadata["role_category"] == JobRoleCategory.BILLING_SPECIALIST.value
    assert fact.metadata["date_posted"] == "2026-08-15"
    assert fact.metadata["recency_status"] == JobRecencyStatus.FRESH.value
    assert fact.metadata["fabricated"] is False
    assert fact.metadata["applied"] is False
    assert fact.metadata["contacted"] is False
    assert fact.source_url.endswith("/careers")
    assert 0 < fact.confidence <= 1
    assert "Medical Biller" in fact.snippet
    assert "apply@austinfamilymedicine.com" not in fact.snippet
    assert "(512) 555-0199" not in fact.snippet
    assert "apply@" not in fact.value


def test_non_billing_job_is_classified_and_not_a_billing_intent() -> None:
    facts = extract_job_posting_signals(
        page("https://austinfamilymedicine.com/jobs", NON_BILLING_JOB_JSONLD_HTML),
        now=NOW,
    )
    assert len(facts) == 1
    assert facts[0].metadata["intent_code"] == JobIntentCode.NON_BILLING_HIRING.value
    assert facts[0].metadata["role_category"] == JobRoleCategory.OTHER.value
    points = job_signal_points(
        JobIntentCode.NON_BILLING_HIRING,
        recency_days=5,
        recency_status=JobRecencyStatus.FRESH,
    )
    assert points == 0


def test_missing_date_is_unknown_recency_and_unscored() -> None:
    facts = extract_job_posting_signals(
        page("https://austinfamilymedicine.com/careers", MISSING_DATE_JOB_JSONLD_HTML),
        now=NOW,
    )
    assert len(facts) == 1
    assert facts[0].metadata["intent_code"] == JobIntentCode.RCM_HIRING.value
    assert facts[0].metadata["date_posted"] is None
    assert facts[0].metadata["recency_status"] == JobRecencyStatus.UNKNOWN.value
    assert (
        job_signal_points(
            JobIntentCode.RCM_HIRING,
            recency_days=None,
            recency_status=JobRecencyStatus.UNKNOWN,
        )
        == 0
    )


def test_recency_decay_expires_at_ninety_days() -> None:
    fresh = job_signal_points(
        JobIntentCode.BILLING_HIRING,
        recency_days=0,
        recency_status=JobRecencyStatus.FRESH,
    )
    mid = job_signal_points(
        JobIntentCode.CODING_HIRING,
        recency_days=45,
        recency_status=JobRecencyStatus.AGING,
    )
    stale = job_signal_points(
        JobIntentCode.DENIALS_HIRING,
        recency_days=80,
        recency_status=JobRecencyStatus.STALE,
    )
    expired = job_signal_points(
        JobIntentCode.BILLING_HIRING,
        recency_days=90,
        recency_status=JobRecencyStatus.EXPIRED,
    )
    assert fresh == POINTS_JOB_SIGNAL
    assert 0 < mid < fresh
    assert 0 < stale < mid
    assert expired == 0
    posted = date(2026, 5, 22)
    assert recency_status_for(posted, now=NOW) is JobRecencyStatus.EXPIRED
    facts = extract_job_posting_signals(
        page("https://austinfamilymedicine.com/careers", STALE_BILLING_JOB_JSONLD_HTML),
        now=NOW,
    )
    assert facts[0].metadata["intent_code"] == JobIntentCode.CODING_HIRING.value
    assert facts[0].metadata["recency_status"] == JobRecencyStatus.EXPIRED.value
    assert NOW.date() - timedelta(days=90) == date(2026, 5, 22)


def test_does_not_scrape_prohibited_job_boards() -> None:
    indeed = page("https://www.indeed.com/viewjob?jk=abc", BILLING_JOB_JSONLD_HTML)
    ziprecruiter = page("https://www.ziprecruiter.com/jobs/medical-biller", BILLING_JOB_JSONLD_HTML)
    linkedin = page("https://www.linkedin.com/jobs/view/123", BILLING_JOB_JSONLD_HTML)
    assert extract_job_posting_signals(indeed, now=NOW) == ()
    assert extract_job_posting_signals(ziprecruiter, now=NOW) == ()
    assert extract_job_posting_signals(linkedin, now=NOW) == ()
    assert is_job_board_host("https://www.indeed.com/cmp/clinic")
    assert is_job_board_host("https://www.ziprecruiter.com/jobs")
    assert is_job_board_host("https://www.linkedin.com/jobs")
    urls = [item.url for item in generate_job_page_candidates("https://clinic.example")]
    assert "https://clinic.example/careers" in urls
    assert "https://clinic.example/jobs" in urls
    assert all("indeed.com" not in url for url in urls)
    assert all("ziprecruiter.com" not in url for url in urls)
    assert all("linkedin.com" not in url for url in urls)
    assert is_job_page_url("https://clinic.example/careers")
    assert not is_job_page_url("https://www.indeed.com/jobs")


def test_metrics_and_titles_are_sanitized() -> None:
    facts = extract_job_posting_signals(
        page("https://austinfamilymedicine.com/careers", BILLING_JOB_JSONLD_HTML),
        now=NOW,
    )
    metrics = job_signal_metrics(facts)
    dumped = str(metrics)
    assert metrics["extracted"] == 1
    assert metrics["billing_intent_count"] == 1
    assert metrics["by_intent_code"] == {JobIntentCode.BILLING_HIRING.value: 1}
    assert "apply@austinfamilymedicine.com" not in dumped
    assert "512" not in dumped
    assert "Medical Biller" not in dumped
    assert sanitize_job_title("Biller apply@clinic.example (512) 555-0100") == (
        "Biller [REDACTED] [REDACTED]"
    )
    sanitized = sanitize_job_signal_metrics(())
    assert sanitized["extracted"] == 0
    assert "description" not in sanitized
    assert "snippet" not in sanitized
    assert "email" not in sanitized
