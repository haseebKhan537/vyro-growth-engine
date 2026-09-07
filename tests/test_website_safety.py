from __future__ import annotations

import pytest

from vyro_growth.providers.website import (
    WebsiteSearchQuery,
    WebsiteUrlError,
    assert_public_http_url,
    generate_heuristic_candidates,
    is_blocked_public_path,
    is_directory_host,
    normalize_name_tokens,
    normalize_url,
)


def _public_resolver(_host: str) -> tuple[str, ...]:
    return ("8.8.8.8",)


def test_assert_public_http_url_accepts_https_public_host() -> None:
    url = assert_public_http_url(
        "https://www.AustinFamilyMedicine.com/about/",
        resolver=_public_resolver,
    )
    assert url == "https://austinfamilymedicine.com/about"


def test_assert_public_http_url_rejects_private_ip_literal() -> None:
    with pytest.raises(WebsiteUrlError, match="private"):
        assert_public_http_url("http://127.0.0.1/contact")


def test_assert_public_http_url_rejects_resolved_private_ip() -> None:
    with pytest.raises(WebsiteUrlError, match="private"):
        assert_public_http_url(
            "https://clinic.example",
            resolver=lambda _host: ("10.0.0.8",),
        )


def test_assert_public_http_url_rejects_credentials_and_portals() -> None:
    with pytest.raises(WebsiteUrlError, match="credentials"):
        assert_public_http_url("https://user:pass@clinic.example", resolver=_public_resolver)
    with pytest.raises(WebsiteUrlError, match="public business page"):
        assert_public_http_url(
            "https://clinic.example/patient-portal/login",
            resolver=_public_resolver,
        )


def test_blocked_paths_cover_phi_and_reviews() -> None:
    assert is_blocked_public_path("https://clinic.example/mychart")
    assert is_blocked_public_path("https://clinic.example/reviews")
    assert is_blocked_public_path("https://clinic.example/appointments")
    assert not is_blocked_public_path("https://clinic.example/contact")
    assert is_blocked_public_path("https://clinic.example/patient-intake")
    assert is_blocked_public_path("https://clinic.example/intake-form")
    assert not is_blocked_public_path("https://clinic.example/about")
    assert not is_blocked_public_path("https://clinic.example/our-team")


def test_directory_hosts_are_recognized() -> None:
    assert is_directory_host("https://www.healthgrades.com/group/austin")
    assert is_directory_host("https://www.indeed.com/viewjob?jk=abc")
    assert is_directory_host("https://www.ziprecruiter.com/jobs")
    assert not is_directory_host("https://austinfamilymedicine.com")


def test_heuristic_candidates_are_deterministic_and_skip_short_names() -> None:
    candidates = generate_heuristic_candidates(
        WebsiteSearchQuery(organization_name="Austin Family Medicine PLLC")
    )
    urls = [item.url for item in candidates]
    assert "https://austinfamilymedicine.com" in urls
    assert "https://austin-family-medicine.com" in urls
    assert generate_heuristic_candidates(WebsiteSearchQuery(organization_name="A LLC")) == ()


def test_name_tokens_drop_legal_suffixes() -> None:
    assert normalize_name_tokens("AUSTIN FAMILY MEDICINE PLLC") == (
        "austin",
        "family",
        "medicine",
    )
    assert normalize_url("HTTPS://WWW.Example.COM/Path/") == "https://example.com/Path"
