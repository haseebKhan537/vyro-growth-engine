from __future__ import annotations

import re
from collections.abc import Sequence

from vyro_growth.domain import WebsiteFactType
from vyro_growth.observability import contains_phi_indicator
from vyro_growth.providers.website import (
    EVIDENCE_SNIPPET_MAX_LENGTH,
    ExtractedFact,
    PublicPage,
    clip_text,
    is_blocked_public_path,
    is_directory_host,
    is_staff_page_url,
)
from vyro_growth.providers.website_analyze import snippet_around, visible_text

STAFF_EXTRACTOR_VERSION = "staff-page-v1"
WEBSITE_STAFF_PROVIDER_NAME = "website_staff"
STAFF_MEMBER_SEPARATOR = " | "
STAFF_MEMBER_MAX_PER_PAGE = 25
FULL_NAME_MAX_LENGTH = 255
TITLE_MAX_LENGTH = 255

STAFF_PHI_PHRASES = (
    "patient diagnosis",
    "patient name",
    "diagnosed with",
    "prescription",
    "medical record",
    "the patient",
    "my patient",
    "our patient",
    "date of birth",
    "social security",
    "protected health",
    "member id",
    "insurance member",
)
STAFF_REVIEW_PHRASES = (
    "google review",
    "patient review",
    "star review",
    "testimonial",
    "wrote a review",
)
NAME_STOPWORDS = frozenset(
    {
        "about",
        "administrator",
        "and",
        "austin",
        "billing",
        "clinic",
        "contact",
        "director",
        "doctors",
        "executive",
        "family",
        "home",
        "hours",
        "leadership",
        "location",
        "manager",
        "meet",
        "medicine",
        "office",
        "operations",
        "our",
        "people",
        "physicians",
        "practice",
        "privacy",
        "providers",
        "services",
        "staff",
        "team",
        "the",
        "welcome",
        "who",
    }
)
CREDENTIAL_ONLY_TITLES = frozenset(
    {
        "md",
        "m.d",
        "m.d.",
        "do",
        "d.o",
        "d.o.",
        "np",
        "n.p",
        "n.p.",
        "pa",
        "p.a",
        "p.a.",
        "pac",
        "pa-c",
        "rn",
        "r.n",
        "r.n.",
        "dds",
        "d.d.s",
        "d.d.s.",
        "dmd",
        "pharmd",
        "phd",
        "ph.d",
    }
)
TITLE_HINTS = (
    "administrator",
    "billing",
    "ceo",
    "chief executive",
    "chief operating",
    "coordinator",
    "coo",
    "director",
    "executive",
    "manager",
    "office",
    "operations",
    "operator",
    "owner",
    "president",
    "practice admin",
    "practice manager",
    "rcm",
    "revenue cycle",
    "supervisor",
)
REVIEW_HEADING_RE = re.compile(
    r"<h[1-6]\b[^>]*>\s*(?:patient\s+)?(?:reviews?|testimonials?)\s*</h[1-6]>",
    re.IGNORECASE,
)
BLOCK_RE = re.compile(
    r"<(?:li|article|section|figcaption)\b[^>]*>(.*?)</(?:li|article|section|figcaption)>",
    re.IGNORECASE | re.DOTALL,
)
HEADING_BLOCK_RE = re.compile(
    r"<h([1-6])\b[^>]*>(.*?)</h\1>\s*((?:<(?:p|div|span|h[1-6])\b[^>]*>.*?</(?:p|div|span|h[1-6])>\s*){1,3})",
    re.IGNORECASE | re.DOTALL,
)
CLASS_NAME_RE = re.compile(
    r"<(?:div|span|p|h[1-6]|strong)\b[^>]*class=\"[^\"]*\b(?:name|member-name|staff-name|"
    r"team-name|person-name)[^\"]*\"[^>]*>(.*?)</(?:div|span|p|h[1-6]|strong)>",
    re.IGNORECASE | re.DOTALL,
)
CLASS_TITLE_RE = re.compile(
    r"<(?:div|span|p|h[1-6]|strong)\b[^>]*class=\"[^\"]*\b(?:title|role|position|job-title|"
    r"member-title|staff-title)[^\"]*\"[^>]*>(.*?)</(?:div|span|p|h[1-6]|strong)>",
    re.IGNORECASE | re.DOTALL,
)
NAME_TITLE_LINE_RE = re.compile(
    r"^(?P<name>[A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){1,3})"
    r"\s*(?:,|:|\||–|—|-)\s*"
    r"(?P<title>[A-Za-z][A-Za-z0-9/&.,'\- ]{2,80})$"
)
WHITESPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")


def format_staff_member_value(full_name: str, title: str) -> str:
    return f"{full_name}{STAFF_MEMBER_SEPARATOR}{title}"


def parse_staff_member_value(value: str | None) -> tuple[str, str] | None:
    if not isinstance(value, str) or STAFF_MEMBER_SEPARATOR not in value:
        return None
    raw_name, raw_title = value.split(STAFF_MEMBER_SEPARATOR, 1)
    name = _clean_text(raw_name)
    title = _clean_text(raw_title)
    if name is None or title is None:
        return None
    if not _is_person_name(name) or not _is_job_title(title):
        return None
    return name, title


def extract_staff_members(page: PublicPage) -> tuple[ExtractedFact, ...]:
    if is_directory_host(page.url) or is_blocked_public_path(page.url):
        return ()
    html_text = REVIEW_HEADING_RE.split(page.text, maxsplit=1)[0]
    facts: list[ExtractedFact] = []
    for name, title, snippet in _candidate_pairs(html_text):
        if _unsafe_text(name, title, snippet):
            continue
        facts.append(
            _staff_fact(
                name=name,
                title=title,
                snippet=snippet,
                source_url=page.url,
                confidence=_confidence_for(page.url),
            )
        )
        if len(facts) >= STAFF_MEMBER_MAX_PER_PAGE:
            break
    return tuple(_dedupe_staff_facts(facts))


def _candidate_pairs(html_text: str) -> tuple[tuple[str, str, str], ...]:
    pairs: list[tuple[str, str, str]] = []
    pairs.extend(_pairs_from_class_cards(html_text))
    for match in BLOCK_RE.finditer(html_text):
        parsed = _pair_from_text(visible_text(match.group(1)))
        if parsed is not None:
            pairs.append(parsed)
    for match in HEADING_BLOCK_RE.finditer(html_text):
        heading = visible_text(match.group(2))
        following = visible_text(match.group(3))
        parsed = _pair_from_name_and_title(heading, following)
        if parsed is None:
            parsed = _pair_from_text(f"{heading}, {following}")
        if parsed is not None:
            pairs.append(parsed)
    return tuple(pairs)


def _pairs_from_class_cards(html_text: str) -> tuple[tuple[str, str, str], ...]:
    names = [visible_text(match.group(1)) for match in CLASS_NAME_RE.finditer(html_text)]
    titles = [visible_text(match.group(1)) for match in CLASS_TITLE_RE.finditer(html_text)]
    pairs: list[tuple[str, str, str]] = []
    for name, title in zip(names, titles, strict=False):
        parsed = _pair_from_name_and_title(name, title)
        if parsed is not None:
            pairs.append(parsed)
    return tuple(pairs)


def _pair_from_text(text: str) -> tuple[str, str, str] | None:
    cleaned = _clean_text(text)
    if cleaned is None:
        return None
    match = NAME_TITLE_LINE_RE.match(cleaned)
    if match is None:
        return None
    return _pair_from_name_and_title(match.group("name"), match.group("title"))


def _pair_from_name_and_title(name: str, title: str) -> tuple[str, str, str] | None:
    full_name = _clean_text(name)
    job_title = _clean_text(_strip_credential_suffix(title))
    if full_name is None or job_title is None:
        return None
    if not _is_person_name(full_name) or not _is_job_title(job_title):
        return None
    snippet = clip_text(f"{full_name}, {job_title}", EVIDENCE_SNIPPET_MAX_LENGTH)
    return full_name, job_title, snippet


def _staff_fact(
    *,
    name: str,
    title: str,
    snippet: str,
    source_url: str,
    confidence: float,
) -> ExtractedFact:
    evidence = snippet_around(snippet, name) if name.lower() in snippet.lower() else snippet
    return ExtractedFact(
        fact_type=WebsiteFactType.STAFF_MEMBER,
        value=format_staff_member_value(name, title),
        confidence=round(confidence, 3),
        snippet=clip_text(evidence, EVIDENCE_SNIPPET_MAX_LENGTH),
        source_url=source_url,
        metadata={
            "full_name": name,
            "title": title,
            "fabricated": False,
            "extractor": STAFF_EXTRACTOR_VERSION,
            "staff_page": is_staff_page_url(source_url),
        },
    )


def _confidence_for(url: str) -> float:
    if is_staff_page_url(url):
        return 0.84
    return 0.72


def _is_person_name(value: str) -> bool:
    if len(value) > FULL_NAME_MAX_LENGTH:
        return False
    tokens = value.split()
    if len(tokens) < 2 or len(tokens) > 4:
        return False
    if any(token.lower().strip(".") in NAME_STOPWORDS for token in tokens):
        return False
    if any(character.isdigit() for character in value):
        return False
    if "@" in value or "http" in value.lower():
        return False
    return all(_is_name_token(token) for token in tokens)


def _is_name_token(token: str) -> bool:
    if not token or not token[0].isupper():
        return False
    letters = token.replace(".", "").replace("-", "").replace("'", "")
    return letters.isalpha() and len(letters) > 1


def _is_job_title(value: str) -> bool:
    if len(value) > TITLE_MAX_LENGTH:
        return False
    lowered = value.lower().strip().strip(".")
    if lowered in CREDENTIAL_ONLY_TITLES:
        return False
    if any(character.isdigit() for character in value):
        return False
    if "@" in value or "http" in value.lower():
        return False
    if _unsafe_text(value):
        return False
    return any(hint in lowered for hint in TITLE_HINTS)


def _strip_credential_suffix(value: str) -> str:
    cleaned = value.strip().rstrip(".,;:")
    parts = [part.strip() for part in re.split(r"[,/|]", cleaned) if part.strip()]
    kept = [part for part in parts if part.lower().strip(".") not in CREDENTIAL_ONLY_TITLES]
    return ", ".join(kept) if kept else cleaned


def _unsafe_text(*values: str) -> bool:
    combined = " ".join(values).lower()
    if any(phrase in combined for phrase in STAFF_PHI_PHRASES):
        return True
    if any(phrase in combined for phrase in STAFF_REVIEW_PHRASES):
        return True
    return contains_phi_indicator(" ".join(values)) and any(
        token in combined for token in ("diagnosis", "diabetes", "phi", "ssn", "hipaa", "mrn")
    )


def _clean_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    without_tags = TAG_RE.sub(" ", value)
    stripped = WHITESPACE_RE.sub(" ", without_tags).strip(" -,|:;")
    return stripped or None


def _dedupe_staff_facts(facts: Sequence[ExtractedFact]) -> list[ExtractedFact]:
    seen: set[tuple[str, str]] = set()
    unique: list[ExtractedFact] = []
    for fact in facts:
        key = (fact.value.lower(), fact.source_url.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(fact)
    return unique
