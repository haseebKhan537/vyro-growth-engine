from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from urllib.parse import urlparse, urlunparse

from vyro_growth.domain import WebsiteFactType, WebsiteMatchStatus

WEBSITE_MAX_LENGTH = 500
EVIDENCE_SNIPPET_MAX_LENGTH = 400
WEBSITE_ENRICHMENT_SOURCE = "official_website"

LEGAL_SUFFIXES = frozenset(
    {
        "llc",
        "l.l.c",
        "inc",
        "incorporated",
        "pllc",
        "p.l.l.c",
        "pa",
        "p.a",
        "pc",
        "p.c",
        "ltd",
        "corp",
        "corporation",
        "company",
        "co",
        "llp",
        "plc",
        "dba",
        "pllc.",
        "llc.",
        "inc.",
    }
)

DIRECTORY_HOSTS = frozenset(
    {
        "healthgrades.com",
        "vitals.com",
        "webmd.com",
        "yelp.com",
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "yellowpages.com",
        "bbb.org",
        "dnb.com",
        "zoominfo.com",
        "npidb.com",
        "npiprofile.com",
        "hipaaspace.com",
        "npino.com",
        "nppes.cms.hhs.gov",
        "wikipedia.org",
        "google.com",
        "maps.google.com",
        "sharecare.com",
        "wellness.com",
        "zocdoc.com",
        "doximity.com",
        "healthline.com",
        "bing.com",
    }
)

JOB_BOARD_HOSTS = frozenset(
    {
        "indeed.com",
        "ziprecruiter.com",
        "linkedin.com",
        "glassdoor.com",
        "monster.com",
        "careerbuilder.com",
        "simplyhired.com",
        "dice.com",
        "jooble.org",
        "snagajob.com",
        "talent.com",
        "greenhouse.io",
        "lever.co",
        "myworkdayjobs.com",
        "smartrecruiters.com",
        "icims.com",
        "jobvite.com",
        "applytojob.com",
    }
)

BLOCKED_PATH_FRAGMENTS = (
    "patient-portal",
    "patientportal",
    "mychart",
    "my-chart",
    "/portal",
    "/login",
    "/signin",
    "/sign-in",
    "/signup",
    "/sign-up",
    "/account",
    "/dashboard",
    "/wp-admin",
    "/admin",
    "health-record",
    "medical-record",
    "medicalrecord",
    "/ehr",
    "/phi",
    "appointment",
    "book-now",
    "booking",
    "schedule-online",
    "pay-bill",
    "patient-pay",
    "bill-pay",
    "/reviews",
    "/review",
    "testimonial",
    "intake-form",
    "intakeform",
    "patient-form",
    "patientform",
    "new-patient",
    "patient-intake",
    "patientintake",
)

STAFF_PAGE_PATH_HINTS: tuple[str, ...] = (
    "meet-the-team",
    "meet-our-team",
    "meettheteam",
    "our-team",
    "ourteam",
    "our-staff",
    "ourstaff",
    "staff",
    "leadership",
    "our-leadership",
    "executive-team",
    "leadership-team",
    "management-team",
    "management",
    "about-us",
    "aboutus",
    "about",
    "who-we-are",
    "whoweare",
    "our-people",
    "ourpeople",
)
STAFF_PAGE_SOURCE = "staff_page_heuristic"
NON_STAFF_PAGE_RANK = len(STAFF_PAGE_PATH_HINTS) + 1
JOB_PAGE_PATH_HINTS: tuple[str, ...] = (
    "careers",
    "jobs",
    "employment",
    "join-our-team",
    "joinourteam",
    "career-opportunities",
    "job-openings",
    "openings",
    "work-with-us",
    "we-are-hiring",
    "were-hiring",
    "hiring",
)
JOB_PAGE_SOURCE = "job_page_heuristic"
NON_JOB_PAGE_RANK = len(JOB_PAGE_PATH_HINTS) + 1

BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata.google",
    }
)

US_STATE_NAMES = {
    "AL": "alabama",
    "AK": "alaska",
    "AZ": "arizona",
    "AR": "arkansas",
    "CA": "california",
    "CO": "colorado",
    "CT": "connecticut",
    "DE": "delaware",
    "DC": "district of columbia",
    "FL": "florida",
    "GA": "georgia",
    "HI": "hawaii",
    "ID": "idaho",
    "IL": "illinois",
    "IN": "indiana",
    "IA": "iowa",
    "KS": "kansas",
    "KY": "kentucky",
    "LA": "louisiana",
    "ME": "maine",
    "MD": "maryland",
    "MA": "massachusetts",
    "MI": "michigan",
    "MN": "minnesota",
    "MS": "mississippi",
    "MO": "missouri",
    "MT": "montana",
    "NE": "nebraska",
    "NV": "nevada",
    "NH": "new hampshire",
    "NJ": "new jersey",
    "NM": "new mexico",
    "NY": "new york",
    "NC": "north carolina",
    "ND": "north dakota",
    "OH": "ohio",
    "OK": "oklahoma",
    "OR": "oregon",
    "PA": "pennsylvania",
    "PR": "puerto rico",
    "RI": "rhode island",
    "SC": "south carolina",
    "SD": "south dakota",
    "TN": "tennessee",
    "TX": "texas",
    "UT": "utah",
    "VT": "vermont",
    "VA": "virginia",
    "WA": "washington",
    "WV": "west virginia",
    "WI": "wisconsin",
    "WY": "wyoming",
}

HostResolver = Callable[[str], Sequence[str]]


class WebsiteFetchError(RuntimeError):
    """Raised when a public page cannot be fetched safely."""


class WebsiteUrlError(ValueError):
    """Raised when a URL is not a conservative public HTTP(S) target."""


@dataclass(frozen=True)
class WebsiteSearchQuery:
    organization_name: str
    city: str | None = None
    state: str | None = None
    npi: str | None = None
    specialty: str | None = None


@dataclass(frozen=True)
class WebsiteCandidate:
    url: str
    source: str
    title: str | None = None
    snippet: str | None = None


@dataclass(frozen=True)
class PublicPage:
    url: str
    status_code: int
    content_type: str
    text: str
    fetched_at: datetime


@dataclass(frozen=True)
class OrganizationMatchInput:
    name: str
    city: str | None = None
    state: str | None = None
    npi: str | None = None
    specialty: str | None = None


@dataclass(frozen=True)
class ExtractedFact:
    fact_type: WebsiteFactType
    value: str
    confidence: float
    snippet: str
    source_url: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PageMatchScore:
    url: str
    name_exact: bool
    name_tokens: bool
    domain_name_match: bool
    city_match: bool
    state_match: bool
    specialty_match: bool
    npi_match: bool
    is_directory: bool
    is_blocked_page: bool
    confidence: float
    reasons: tuple[str, ...]
    snippet: str | None


@dataclass(frozen=True)
class WebsiteMatchDecision:
    status: WebsiteMatchStatus
    confidence: float
    official_website: str | None
    reasons: tuple[str, ...]
    winning_url: str | None
    snippet: str | None
    scored_pages: tuple[PageMatchScore, ...]


class WebsiteSearchProvider(Protocol):
    def find_candidates(self, query: WebsiteSearchQuery) -> tuple[WebsiteCandidate, ...]: ...


class PublicPageFetcher(Protocol):
    def fetch(self, url: str) -> PublicPage: ...


def clean_optional_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def clip_text(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


def normalize_name_tokens(name: str) -> tuple[str, ...]:
    lowered = re.sub(r"[^a-z0-9\s]+", " ", name.lower())
    tokens = [token for token in lowered.split() if token and token not in LEGAL_SUFFIXES]
    return tuple(token for token in tokens if len(token) > 1)


def normalized_name(name: str) -> str:
    return " ".join(normalize_name_tokens(name))


def hostname_of(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return host or None


def registrable_host(host: str) -> str:
    labels = host.lower().split(".")
    if len(labels) >= 2:
        return ".".join(labels[-2:])
    return host.lower()


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path or ""
    if path == "/":
        path = ""
    elif path.endswith("/"):
        path = path.rstrip("/")
    netloc = host
    if parsed.port and parsed.port not in {80, 443}:
        netloc = f"{host}:{parsed.port}"
    return urlunparse((scheme, netloc, path, "", "", ""))


def is_directory_host(url: str) -> bool:
    host = hostname_of(url)
    if host is None:
        return False
    registrable = registrable_host(host)
    return (
        registrable in DIRECTORY_HOSTS
        or host in DIRECTORY_HOSTS
        or registrable in JOB_BOARD_HOSTS
        or host in JOB_BOARD_HOSTS
    )


def is_job_board_host(url: str) -> bool:
    host = hostname_of(url)
    if host is None:
        return False
    registrable = registrable_host(host)
    return registrable in JOB_BOARD_HOSTS or host in JOB_BOARD_HOSTS


def _path_and_query(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.path}{'?' + parsed.query if parsed.query else ''}".lower()


def is_blocked_public_path(url: str) -> bool:
    haystack = _path_and_query(url)
    return any(fragment in haystack for fragment in BLOCKED_PATH_FRAGMENTS)


def path_segments(url: str) -> tuple[str, ...]:
    parsed = urlparse(url)
    return tuple(segment for segment in parsed.path.lower().strip("/").split("/") if segment)


def staff_path_key(url: str) -> str:
    return "/".join(path_segments(url))


def staff_page_rank(url: str) -> int:
    if is_directory_host(url) or is_blocked_public_path(url):
        return NON_STAFF_PAGE_RANK + 1
    key = staff_path_key(url)
    segments = path_segments(url)
    for index, hint in enumerate(STAFF_PAGE_PATH_HINTS):
        if hint in segments or key.endswith(hint):
            return index
    return NON_STAFF_PAGE_RANK


def is_staff_page_url(url: str) -> bool:
    return staff_page_rank(url) < NON_STAFF_PAGE_RANK


def job_page_rank(url: str) -> int:
    if is_directory_host(url) or is_blocked_public_path(url) or is_job_board_host(url):
        return NON_JOB_PAGE_RANK + 1
    key = staff_path_key(url)
    segments = path_segments(url)
    for index, hint in enumerate(JOB_PAGE_PATH_HINTS):
        if hint in segments or key.endswith(hint):
            return index
    return NON_JOB_PAGE_RANK


def is_job_page_url(url: str) -> bool:
    return job_page_rank(url) < NON_JOB_PAGE_RANK


def same_registrable_host(left: str, right: str) -> bool:
    left_host = hostname_of(left)
    right_host = hostname_of(right)
    if left_host is None or right_host is None:
        return False
    return registrable_host(left_host) == registrable_host(right_host)


def origin_of(url: str) -> str | None:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if not host or parsed.scheme not in {"http", "https"}:
        return None
    netloc = host
    if parsed.port and parsed.port not in {80, 443}:
        netloc = f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme.lower(), netloc, "", "", "", ""))


def generate_staff_page_candidates(base_url: str) -> tuple[WebsiteCandidate, ...]:
    origin = origin_of(base_url)
    if origin is None:
        return ()
    candidates: list[WebsiteCandidate] = []
    seen: set[str] = set()
    for hint in STAFF_PAGE_PATH_HINTS:
        url = normalize_url(f"{origin}/{hint}")
        if url in seen or is_blocked_public_path(url) or is_directory_host(url):
            continue
        seen.add(url)
        candidates.append(
            WebsiteCandidate(url=url, source=STAFF_PAGE_SOURCE, title=None, snippet=None)
        )
    return tuple(candidates)


def generate_job_page_candidates(base_url: str) -> tuple[WebsiteCandidate, ...]:
    origin = origin_of(base_url)
    if origin is None:
        return ()
    candidates: list[WebsiteCandidate] = []
    seen: set[str] = set()
    for hint in JOB_PAGE_PATH_HINTS:
        url = normalize_url(f"{origin}/{hint}")
        if (
            url in seen
            or is_blocked_public_path(url)
            or is_directory_host(url)
            or is_job_board_host(url)
        ):
            continue
        seen.add(url)
        candidates.append(
            WebsiteCandidate(url=url, source=JOB_PAGE_SOURCE, title=None, snippet=None)
        )
    return tuple(candidates)


def prioritize_page_urls(urls: Sequence[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not url.strip():
            continue
        normalized = normalize_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    indexed = list(enumerate(unique))
    ordered = sorted(indexed, key=lambda item: (staff_page_rank(item[1]), item[0]))
    return tuple(url for _index, url in ordered)


def prioritize_job_page_urls(urls: Sequence[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not url.strip():
            continue
        normalized = normalize_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    indexed = list(enumerate(unique))
    ordered = sorted(indexed, key=lambda item: (job_page_rank(item[1]), item[0]))
    return tuple(url for _index, url in ordered)


def _is_blocked_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def default_host_resolver(host: str) -> tuple[str, ...]:
    try:
        answers = socket.getaddrinfo(host, None)
    except OSError:
        return ()
    addresses: list[str] = []
    for item in answers:
        address = item[4][0]
        if not isinstance(address, str) or address in addresses:
            continue
        addresses.append(address)
    return tuple(addresses)


def assert_public_http_url(url: str, *, resolver: HostResolver | None = None) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise WebsiteUrlError("only public http and https URLs are allowed")
    if parsed.username or parsed.password:
        raise WebsiteUrlError("URLs with credentials are not allowed")
    host = (parsed.hostname or "").lower()
    if not host:
        raise WebsiteUrlError("URL host is required")
    if host in BLOCKED_HOSTS or host.endswith(".localhost") or host.endswith(".internal"):
        raise WebsiteUrlError("host is not a public website")
    if _is_blocked_ip(host):
        raise WebsiteUrlError("literal private or reserved IP addresses are not allowed")
    if is_blocked_public_path(url):
        raise WebsiteUrlError("URL path is not a public business page")

    resolve = resolver or default_host_resolver
    resolved = tuple(resolve(host))
    if not resolved:
        raise WebsiteUrlError("host could not be resolved to a public address")
    for address in resolved:
        if _is_blocked_ip(address):
            raise WebsiteUrlError("host resolves to a private or reserved address")
    return normalize_url(url)


def generate_heuristic_candidates(query: WebsiteSearchQuery) -> tuple[WebsiteCandidate, ...]:
    tokens = normalize_name_tokens(query.organization_name)
    if len(tokens) < 2:
        return ()

    slugs = (
        "".join(tokens),
        "-".join(tokens),
    )
    candidates: list[WebsiteCandidate] = []
    seen: set[str] = set()
    for slug in slugs:
        if len(slug) < 8:
            continue
        for tld in (".com", ".org"):
            url = f"https://{slug}{tld}"
            normalized = normalize_url(url)
            if normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(
                WebsiteCandidate(url=normalized, source="name_heuristic", title=None, snippet=None)
            )
    return tuple(candidates)


class HeuristicWebsiteSearchProvider:
    """Deterministic candidate generator. Does not call a search API."""

    def find_candidates(self, query: WebsiteSearchQuery) -> tuple[WebsiteCandidate, ...]:
        return generate_heuristic_candidates(query)


class StaticWebsiteSearchProvider:
    """Test/operator adapter that returns a fixed candidate list."""

    def __init__(self, candidates: Sequence[WebsiteCandidate] = ()) -> None:
        self._candidates = tuple(candidates)

    def find_candidates(self, query: WebsiteSearchQuery) -> tuple[WebsiteCandidate, ...]:
        del query
        return self._candidates


class StaticPublicPageFetcher:
    """In-memory fetcher for tests. Never touches the network."""

    def __init__(self, pages: dict[str, PublicPage | Exception] | None = None) -> None:
        self._pages = {normalize_url(key): value for key, value in (pages or {}).items()}

    def fetch(self, url: str) -> PublicPage:
        key = normalize_url(url)
        page = self._pages.get(key)
        if page is None:
            raise WebsiteFetchError(f"no fixture page for {url}")
        if isinstance(page, Exception):
            raise page
        return page
