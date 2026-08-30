from __future__ import annotations

from vyro_growth.domain import WebsiteFactType, WebsiteMatchStatus
from vyro_growth.providers.website import OrganizationMatchInput
from vyro_growth.providers.website_analyze import decide_website_match, extract_business_facts
from tests.fixtures.website_pages import (
    DIRECTORY_HTML,
    NAME_ONLY_HTML,
    NO_OPTIONAL_FACTS_HTML,
    REVIEW_HTML,
    ROSTER_HTML,
    SECOND_VERIFIED_HTML,
    UNRELATED_HTML,
    VERIFIED_HOME_HTML,
    WRONG_CITY_HTML,
    page,
)

ORG = OrganizationMatchInput(
    name="AUSTIN FAMILY MEDICINE PLLC",
    city="AUSTIN",
    state="TX",
    npi="1487448189",
    specialty="Family Medicine",
)


def test_verified_match_requires_name_and_city_state() -> None:
    decision = decide_website_match(
        ORG,
        (page("https://austinfamilymedicine.com", VERIFIED_HOME_HTML),),
    )
    assert decision.status is WebsiteMatchStatus.VERIFIED
    assert decision.official_website == "https://austinfamilymedicine.com"
    assert decision.confidence >= 0.75


def test_wrong_city_is_ambiguous_not_verified() -> None:
    decision = decide_website_match(
        ORG,
        (page("https://austinfamilymedicine.com", WRONG_CITY_HTML),),
    )
    assert decision.status is WebsiteMatchStatus.AMBIGUOUS
    assert decision.official_website is None


def test_unrelated_page_is_no_match() -> None:
    decision = decide_website_match(
        ORG,
        (page("https://sunrisecoffee.example", UNRELATED_HTML),),
    )
    assert decision.status is WebsiteMatchStatus.NO_MATCH
    assert decision.official_website is None


def test_directory_listing_is_not_an_official_website() -> None:
    decision = decide_website_match(
        ORG,
        (page("https://www.healthgrades.com/group/austin", DIRECTORY_HTML),),
    )
    assert decision.status is WebsiteMatchStatus.NO_MATCH
    assert decision.official_website is None


def test_name_only_page_is_ambiguous() -> None:
    decision = decide_website_match(
        ORG,
        (page("https://austinfamilymedicine.com", NAME_ONLY_HTML),),
    )
    assert decision.status is WebsiteMatchStatus.AMBIGUOUS


def test_two_similar_verified_candidates_are_ambiguous() -> None:
    decision = decide_website_match(
        ORG,
        (
            page("https://austinfamilymedicine.com", NO_OPTIONAL_FACTS_HTML),
            page("https://austin-family-medicine.org", SECOND_VERIFIED_HTML),
        ),
    )
    assert decision.status is WebsiteMatchStatus.AMBIGUOUS
    assert decision.official_website is None


def test_extracts_only_stated_public_business_facts() -> None:
    facts = extract_business_facts(page("https://austinfamilymedicine.com", VERIFIED_HOME_HTML))
    by_type = {fact.fact_type: fact for fact in facts}

    assert by_type[WebsiteFactType.BUSINESS_PHONE].value == "5125550100"
    assert by_type[WebsiteFactType.BUSINESS_EMAIL].value == "info@austinfamilymedicine.com"
    assert "family medicine" in by_type[WebsiteFactType.SPECIALTY_SERVICES].value
    assert by_type[WebsiteFactType.LOCATION].value == "Austin, TX"
    assert by_type[WebsiteFactType.PROVIDER_COUNT].value == "3"
    assert by_type[WebsiteFactType.OWNERSHIP_SIGNAL].value == "independent"
    assert by_type[WebsiteFactType.BILLING_SIGNAL].value == "in-house_billing"
    assert by_type[WebsiteFactType.CONTACT_PAGE_URL].value.endswith("/contact")
    assert all(fact.snippet for fact in facts)
    assert all(0 < fact.confidence <= 1 for fact in facts)


def test_does_not_invent_missing_facts() -> None:
    facts = extract_business_facts(page("https://austinfamilymedicine.com", NO_OPTIONAL_FACTS_HTML))
    types = {fact.fact_type for fact in facts}
    assert WebsiteFactType.LOCATION in types
    assert WebsiteFactType.BUSINESS_PHONE not in types
    assert WebsiteFactType.BUSINESS_EMAIL not in types
    assert WebsiteFactType.BILLING_SIGNAL not in types
    assert WebsiteFactType.PROVIDER_COUNT not in types


def test_provider_count_from_roster_does_not_store_names() -> None:
    facts = extract_business_facts(page("https://austinfamilymedicine.com", ROSTER_HTML))
    provider = next(fact for fact in facts if fact.fact_type is WebsiteFactType.PROVIDER_COUNT)
    assert provider.value == "3"
    assert "Jane" not in provider.value
    assert "Jane" not in provider.snippet


def test_review_text_is_not_extracted_as_business_facts() -> None:
    facts = extract_business_facts(page("https://austinfamilymedicine.com/about", REVIEW_HTML))
    types = {fact.fact_type for fact in facts}
    assert WebsiteFactType.BILLING_SIGNAL not in types
    assert WebsiteFactType.BUSINESS_EMAIL not in types
    assert not any("diabetes" in fact.value.lower() for fact in facts)
