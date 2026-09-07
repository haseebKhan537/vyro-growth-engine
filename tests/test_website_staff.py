from __future__ import annotations

from tests.fixtures.website_pages import (
    EMPTY_ABOUT_HTML,
    PHI_REVIEW_STAFF_HTML,
    ROSTER_HTML,
    STAFF_CARD_HTML,
    STAFF_TEAM_HTML,
    page,
)
from vyro_growth.domain import WebsiteFactType
from vyro_growth.providers.website import (
    generate_staff_page_candidates,
    is_blocked_public_path,
    is_staff_page_url,
    prioritize_page_urls,
    staff_page_rank,
)
from vyro_growth.providers.website_staff import (
    extract_staff_members,
    format_staff_member_value,
    parse_staff_member_value,
)


def test_staff_pages_are_prioritized_ahead_of_generic_paths() -> None:
    ordered = prioritize_page_urls(
        (
            "https://austinfamilymedicine.com/contact",
            "https://austinfamilymedicine.com/about",
            "https://austinfamilymedicine.com/our-team",
            "https://austinfamilymedicine.com/leadership",
            "https://austinfamilymedicine.com/blog",
        )
    )
    assert ordered[0].endswith("/our-team")
    assert ordered[1].endswith("/leadership")
    assert ordered[2].endswith("/about")
    assert is_staff_page_url("https://clinic.example/meet-the-team")
    assert is_staff_page_url("https://clinic.example/staff")
    assert not is_staff_page_url("https://clinic.example/blog")
    assert staff_page_rank("https://clinic.example/our-team") < staff_page_rank(
        "https://clinic.example/about"
    )


def test_staff_heuristic_candidates_stay_on_public_business_paths() -> None:
    urls = [item.url for item in generate_staff_page_candidates("https://clinic.example")]
    assert "https://clinic.example/about" in urls
    assert "https://clinic.example/our-team" in urls
    assert "https://clinic.example/staff" in urls
    assert "https://clinic.example/meet-the-team" in urls
    assert "https://clinic.example/leadership" in urls
    assert all(not is_blocked_public_path(url) for url in urls)
    assert "https://www.linkedin.com/company/clinic" not in urls


def test_extracts_stated_name_and_title_pairs_only() -> None:
    facts = extract_staff_members(
        page("https://austinfamilymedicine.com/our-team", STAFF_TEAM_HTML)
    )
    values = {fact.value for fact in facts}
    assert format_staff_member_value("Jordan Blake", "Practice Manager") in values
    assert format_staff_member_value("Riley Chen", "Office Manager") in values
    assert all(fact.fact_type is WebsiteFactType.STAFF_MEMBER for fact in facts)
    assert all(fact.source_url.endswith("/our-team") for fact in facts)
    assert all(0 < fact.confidence <= 1 for fact in facts)
    assert all(fact.snippet for fact in facts)
    assert all(fact.metadata.get("fabricated") is False for fact in facts)
    parsed = parse_staff_member_value(next(iter(values)))
    assert parsed is not None


def test_card_markup_extracts_name_and_title() -> None:
    facts = extract_staff_members(
        page("https://austinfamilymedicine.com/leadership", STAFF_CARD_HTML)
    )
    by_name = {fact.metadata["full_name"]: fact.metadata["title"] for fact in facts}
    assert by_name["Jordan Blake"] == "Practice Manager"
    assert by_name["Avery Stone"] == "Billing Manager"


def test_does_not_invent_names_titles_emails_or_credentials() -> None:
    facts = extract_staff_members(page("https://austinfamilymedicine.com/about", EMPTY_ABOUT_HTML))
    assert facts == ()
    roster = extract_staff_members(page("https://austinfamilymedicine.com", ROSTER_HTML))
    values = " ".join(fact.value for fact in roster)
    snippets = " ".join(fact.snippet for fact in roster)
    assert "Jane Example" not in values
    assert "MD" not in values
    assert "Jane Example" not in snippets
    assert not any("@" in fact.value for fact in roster)
    assert parse_staff_member_value("Not A Real Person") is None


def test_phi_and_review_blocks_are_not_stored() -> None:
    facts = extract_staff_members(
        page("https://austinfamilymedicine.com/about", PHI_REVIEW_STAFF_HTML)
    )
    combined = " ".join(f"{fact.value} {fact.snippet}" for fact in facts).lower()
    assert facts == ()
    assert "diabetes" not in combined
    assert "patient" not in combined
    assert is_blocked_public_path("https://clinic.example/patient-intake")
    assert is_blocked_public_path("https://clinic.example/new-patient-form")
    assert not is_staff_page_url("https://www.linkedin.com/in/jordan-blake")
    assert not is_staff_page_url("https://clinic.example/reviews")
