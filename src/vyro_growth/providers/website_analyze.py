from __future__ import annotations

import html
import re
from typing import Never
from urllib.parse import urljoin

from vyro_growth.domain import WebsiteFactType, WebsiteMatchStatus
from vyro_growth.providers.website import (
    EVIDENCE_SNIPPET_MAX_LENGTH,
    US_STATE_NAMES,
    ExtractedFact,
    OrganizationMatchInput,
    PageMatchScore,
    PublicPage,
    WebsiteMatchDecision,
    clip_text,
    hostname_of,
    is_directory_host,
    normalize_name_tokens,
    normalized_name,
    registrable_host,
)

SCRIPT_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
HREF_RE = re.compile(r"""<a\b[^>]*href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")
PHONE_RE = re.compile(r"(?:\+1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
EMAIL_RE = re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.IGNORECASE)
PROVIDER_COUNT_RE = re.compile(
    r"\b(?:our\s+)?(?:team\s+of\s+)?(\d{1,3})\s+"
    r"(?:board-certified\s+)?(?:physicians?|providers?|doctors?|clinicians?)\b",
    re.IGNORECASE,
)
LOCATION_COUNT_RE = re.compile(
    r"\b(\d{1,3})\s+(?:office|clinic|practice)?\s*locations?\b",
    re.IGNORECASE,
)
SINGLE_LOCATION_RE = re.compile(
    r"\b(?:single|one|1)\s+(?:office|location|clinic)\b",
    re.IGNORECASE,
)
INDEPENDENT_RE = re.compile(
    r"\b(?:independently\s+owned|independent\s+practice|physician-owned|"
    r"doctor-owned|privately\s+owned)\b",
    re.IGNORECASE,
)
GROUP_RE = re.compile(
    r"\b(?:part of|affiliate(?:d)? of|a member of|owned by)\s+"
    r"([A-Z][A-Za-z0-9&.,' -]{2,80})\b"
)
CITY_STATE_RE = re.compile(
    r"\b([A-Z][A-Za-z.'-]{1,24}(?:\s+[A-Z][A-Za-z.'-]{1,24}){0,2}),\s*([A-Z]{2})\b"
)
CREDENTIAL_LI_RE = re.compile(
    r"<li\b[^>]*>[\s\S]{0,200}?\b(?:M\.?D\.?|D\.?O\.?|N\.?P\.?|P\.?A\.?C?\.?)\b[\s\S]{0,80}?</li>",
    re.IGNORECASE,
)
TEAM_HEADING_RE = re.compile(
    r"(our (?:team|providers|doctors|physicians)|meet (?:the|our) (?:team|providers|doctors))",
    re.IGNORECASE,
)
CONTACT_HREF_HINTS = ("contact", "contact-us", "get-in-touch", "locations")
IGNORED_EMAIL_PREFIXES = ("noreply", "no-reply", "donotreply", "mailer-daemon")
SPECIALTY_PHRASES = (
    "family medicine",
    "internal medicine",
    "general practice",
    "pediatrics",
    "chiropractor",
    "chiropractic",
    "dermatology",
    "obstetrics",
    "gynecology",
    "orthopaedic",
    "orthopedic",
    "cardiology",
    "gastroenterology",
    "neurology",
    "ophthalmology",
    "physical therapy",
    "occupational therapy",
    "podiatry",
    "psychiatry",
    "endocrinology",
    "rheumatology",
    "urology",
    "otolaryngology",
    "pulmonary",
    "nephrology",
    "pain medicine",
    "sports medicine",
    "allergy",
    "immunology",
    "sleep medicine",
    "primary care",
)
BILLING_PHRASES = (
    "in-house billing",
    "in house billing",
    "we do our own billing",
    "our own billing",
    "outsourced billing",
    "third-party billing",
    "third party billing",
    "revenue cycle",
    "we handle billing",
    "billing department",
)
PRACTICE_SIZE_PHRASES = (
    "small practice",
    "boutique practice",
    "single-location",
    "multi-location",
    "multi-specialty group",
    "large medical group",
)

VERIFIED_MIN_CONFIDENCE = 0.75
AMBIGUOUS_GAP = 0.15


def visible_text(html_text: str) -> str:
    without_scripts = SCRIPT_RE.sub(" ", html_text)
    without_tags = TAG_RE.sub(" ", without_scripts)
    unescaped = html.unescape(without_tags)
    return WHITESPACE_RE.sub(" ", unescaped).strip()


def snippet_around(text: str, needle: str, *, radius: int = 80) -> str:
    lowered = text.lower()
    index = lowered.find(needle.lower())
    if index < 0:
        return clip_text(text, EVIDENCE_SNIPPET_MAX_LENGTH)
    start = max(0, index - radius)
    end = min(len(text), index + len(needle) + radius)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return clip_text(snippet, EVIDENCE_SNIPPET_MAX_LENGTH)


def _city_location_match(
    city: str | None,
    state: str | None,
    text: str,
    name_tokens: tuple[str, ...],
) -> bool:
    if not city:
        return False
    if state:
        for alias in (state, *_state_aliases(state)):
            pattern = rf"\b{re.escape(city)}\s*,\s*{re.escape(alias)}\b"
            if re.search(pattern, text, flags=re.IGNORECASE):
                return True
        return False
    if city.lower() in name_tokens:
        return False
    return bool(re.search(rf"\b{re.escape(city)}\b", text, flags=re.IGNORECASE))


def _contains_token_set(haystack: str, tokens: tuple[str, ...]) -> bool:
    if not tokens:
        return False
    lowered = f" {haystack.lower()} "
    return all(f" {token} " in lowered or token in haystack.lower() for token in tokens)


def _domain_matches_name(url: str, tokens: tuple[str, ...]) -> bool:
    host = hostname_of(url)
    if host is None or len(tokens) < 2:
        return False
    slug = registrable_host(host).split(".")[0].replace("-", "")
    joined = "".join(tokens)
    return joined == slug or all(token in slug for token in tokens)


def _state_aliases(state: str | None) -> tuple[str, ...]:
    if state is None:
        return ()
    code = state.strip().upper()
    aliases = [code.lower()]
    name = US_STATE_NAMES.get(code)
    if name is not None:
        aliases.append(name)
    return tuple(aliases)


def score_page(organization: OrganizationMatchInput, page: PublicPage) -> PageMatchScore:
    text = visible_text(page.text)
    tokens = normalize_name_tokens(organization.name)
    exact_name = bool(normalized_name(organization.name)) and normalized_name(
        organization.name
    ) in text.lower()
    if not exact_name:
        exact_name = organization.name.lower() in text.lower()
    name_tokens = _contains_token_set(text, tokens)
    domain_name_match = _domain_matches_name(page.url, tokens)
    city_match = _city_location_match(
        organization.city,
        organization.state,
        text,
        tokens,
    )
    state_match = False
    for alias in _state_aliases(organization.state):
        if re.search(rf"\b{re.escape(alias)}\b", text, flags=re.IGNORECASE):
            state_match = True
            break
    specialty_match = bool(
        organization.specialty and organization.specialty.lower() in text.lower()
    )
    npi_match = bool(organization.npi and organization.npi in text)
    directory = is_directory_host(page.url)
    reasons: list[str] = []
    if exact_name:
        reasons.append("organization name appears on page")
    elif name_tokens:
        reasons.append("organization name tokens appear on page")
    if domain_name_match:
        reasons.append("domain slug matches organization name")
    if city_match:
        reasons.append("city appears on page")
    if state_match:
        reasons.append("state appears on page")
    if specialty_match:
        reasons.append("specialty appears on page")
    if npi_match:
        reasons.append("NPI appears on page")
    if directory:
        reasons.append("directory or aggregator host")

    confidence = 0.0
    if directory:
        confidence = 0.1
    else:
        if exact_name:
            confidence += 0.45
        elif name_tokens:
            confidence += 0.25
        if domain_name_match:
            confidence += 0.15
        if city_match:
            confidence += 0.2
        if state_match:
            confidence += 0.1
        if npi_match:
            confidence += 0.2
        elif specialty_match:
            confidence += 0.05
        confidence = min(confidence, 1.0)

    needle = organization.name if exact_name else (organization.city or tokens[0] if tokens else "")
    snippet = (
        snippet_around(text, needle) if needle else clip_text(text, EVIDENCE_SNIPPET_MAX_LENGTH)
    )
    return PageMatchScore(
        url=page.url,
        name_exact=exact_name,
        name_tokens=name_tokens,
        domain_name_match=domain_name_match,
        city_match=city_match,
        state_match=state_match,
        specialty_match=specialty_match,
        npi_match=npi_match,
        is_directory=directory,
        is_blocked_page=False,
        confidence=round(confidence, 3),
        reasons=tuple(reasons),
        snippet=snippet or None,
    )


def _is_verified(score: PageMatchScore, organization: OrganizationMatchInput) -> bool:
    if score.is_directory or score.confidence < VERIFIED_MIN_CONFIDENCE:
        return False
    strong_name = score.name_exact or (score.name_tokens and score.domain_name_match)
    if not strong_name:
        return False
    if organization.city and not score.city_match:
        return False
    if organization.city is None and organization.state and not (
        score.state_match or score.npi_match
    ):
        return False
    if organization.city is None and organization.state is None:
        return score.npi_match or (score.name_exact and score.domain_name_match)
    return True


def decide_website_match(
    organization: OrganizationMatchInput,
    pages: tuple[PublicPage, ...],
) -> WebsiteMatchDecision:
    scored = tuple(score_page(organization, page) for page in pages)
    if not scored:
        return WebsiteMatchDecision(
            status=WebsiteMatchStatus.NO_MATCH,
            confidence=0.0,
            official_website=None,
            reasons=("no public pages were available to compare",),
            winning_url=None,
            snippet=None,
            scored_pages=(),
        )

    verified = [item for item in scored if _is_verified(item, organization)]
    name_hits = [
        item
        for item in scored
        if not item.is_directory and (item.name_exact or item.name_tokens)
    ]

    if len(verified) == 1:
        winner = verified[0]
        return WebsiteMatchDecision(
            status=WebsiteMatchStatus.VERIFIED,
            confidence=winner.confidence,
            official_website=winner.url,
            reasons=winner.reasons + ("conservative NPPES match succeeded",),
            winning_url=winner.url,
            snippet=winner.snippet,
            scored_pages=scored,
        )

    if len(verified) > 1:
        ordered = sorted(verified, key=lambda item: item.confidence, reverse=True)
        top, second = ordered[0], ordered[1]
        if top.confidence - second.confidence >= AMBIGUOUS_GAP:
            return WebsiteMatchDecision(
                status=WebsiteMatchStatus.VERIFIED,
                confidence=top.confidence,
                official_website=top.url,
                reasons=top.reasons + ("highest-confidence verified candidate selected",),
                winning_url=top.url,
                snippet=top.snippet,
                scored_pages=scored,
            )
        return WebsiteMatchDecision(
            status=WebsiteMatchStatus.AMBIGUOUS,
            confidence=top.confidence,
            official_website=None,
            reasons=(
                "multiple public pages matched the NPPES organization equally well",
            ),
            winning_url=None,
            snippet=top.snippet,
            scored_pages=scored,
        )

    if name_hits:
        best = max(name_hits, key=lambda item: item.confidence)
        return WebsiteMatchDecision(
            status=WebsiteMatchStatus.AMBIGUOUS,
            confidence=best.confidence,
            official_website=None,
            reasons=best.reasons
            + ("name matched but location or identity evidence was insufficient",),
            winning_url=best.url,
            snippet=best.snippet,
            scored_pages=scored,
        )

    best = max(scored, key=lambda item: item.confidence)
    return WebsiteMatchDecision(
        status=WebsiteMatchStatus.NO_MATCH,
        confidence=best.confidence,
        official_website=None,
        reasons=("no candidate page contained a conservative organization name match",),
        winning_url=None,
        snippet=best.snippet,
        scored_pages=scored,
    )


def _absolute_url(page_url: str, href: str) -> str | None:
    raw = href.strip()
    if not raw or raw.startswith("#") or raw.lower().startswith("javascript:"):
        return None
    if raw.lower().startswith("mailto:") or raw.lower().startswith("tel:"):
        return raw
    return urljoin(page_url, raw)


def extract_hrefs(page: PublicPage) -> tuple[str, ...]:
    found: list[str] = []
    for match in HREF_RE.finditer(page.text):
        absolute = _absolute_url(page.url, match.group(1))
        if absolute is not None:
            found.append(absolute)
    return tuple(found)


def _fact(
    fact_type: WebsiteFactType,
    value: str,
    confidence: float,
    snippet: str,
    source_url: str,
) -> ExtractedFact:
    return ExtractedFact(
        fact_type=fact_type,
        value=value,
        confidence=round(confidence, 3),
        snippet=clip_text(snippet, EVIDENCE_SNIPPET_MAX_LENGTH),
        source_url=source_url,
    )


def _digits_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def extract_business_facts(page: PublicPage) -> tuple[ExtractedFact, ...]:
    text = visible_text(page.text)
    hrefs = extract_hrefs(page)
    facts: list[ExtractedFact] = []

    contact_url = next(
        (
            href
            for href in hrefs
            if href.startswith("http")
            and any(hint in href.lower() for hint in CONTACT_HREF_HINTS)
        ),
        None,
    )
    if contact_url is not None:
        facts.append(
            _fact(
                WebsiteFactType.CONTACT_PAGE_URL,
                contact_url,
                0.9,
                snippet_around(page.text, "contact"),
                page.url,
            )
        )

    tel_href = next((href for href in hrefs if href.lower().startswith("tel:")), None)
    if tel_href is not None:
        phone = _digits_phone(tel_href)
        if len(phone) == 10:
            facts.append(
                _fact(
                    WebsiteFactType.BUSINESS_PHONE,
                    phone,
                    0.92,
                    snippet_around(page.text, phone[-4:]),
                    page.url,
                )
            )
    elif (phone_match := PHONE_RE.search(text)) is not None:
        phone = _digits_phone(phone_match.group(0))
        if len(phone) == 10:
            facts.append(
                _fact(
                    WebsiteFactType.BUSINESS_PHONE,
                    phone,
                    0.72,
                    snippet_around(text, phone_match.group(0)),
                    page.url,
                )
            )

    mailto = next((href for href in hrefs if href.lower().startswith("mailto:")), None)
    email: str | None = None
    if mailto is not None:
        email = mailto.split(":", 1)[1].split("?", 1)[0].strip().lower()
    else:
        email_match = EMAIL_RE.search(text)
        if email_match is not None:
            email = email_match.group(0).lower()
    if email and email.split("@", 1)[0] not in IGNORED_EMAIL_PREFIXES:
        facts.append(
            _fact(
                WebsiteFactType.BUSINESS_EMAIL,
                email,
                0.9 if mailto else 0.7,
                snippet_around(text, email),
                page.url,
            )
        )

    specialties = [phrase for phrase in SPECIALTY_PHRASES if phrase in text.lower()]
    if specialties:
        value = ", ".join(dict.fromkeys(specialties))
        facts.append(
            _fact(
                WebsiteFactType.SPECIALTY_SERVICES,
                value,
                0.8,
                snippet_around(text, specialties[0]),
                page.url,
            )
        )

    city_state = CITY_STATE_RE.search(text)
    if city_state is not None:
        location = f"{city_state.group(1).strip()}, {city_state.group(2).upper()}"
        facts.append(
            _fact(
                WebsiteFactType.LOCATION,
                location,
                0.82,
                snippet_around(text, city_state.group(0)),
                page.url,
            )
        )

    if SINGLE_LOCATION_RE.search(text):
        match = SINGLE_LOCATION_RE.search(text)
        assert match is not None
        facts.append(
            _fact(
                WebsiteFactType.PRACTICE_SIZE_SIGNAL,
                "single_location",
                0.78,
                snippet_around(text, match.group(0)),
                page.url,
            )
        )
    elif (location_count := LOCATION_COUNT_RE.search(text)) is not None:
        facts.append(
            _fact(
                WebsiteFactType.PRACTICE_SIZE_SIGNAL,
                f"{location_count.group(1)}_locations",
                0.8,
                snippet_around(text, location_count.group(0)),
                page.url,
            )
        )
    else:
        for phrase in PRACTICE_SIZE_PHRASES:
            if phrase in text.lower():
                slug = phrase.replace(" ", "_").replace("-", "_")
                facts.append(
                    _fact(
                        WebsiteFactType.PRACTICE_SIZE_SIGNAL,
                        slug,
                        0.76,
                        snippet_around(text, phrase),
                        page.url,
                    )
                )
                break

    if (provider_count := PROVIDER_COUNT_RE.search(text)) is not None:
        facts.append(
            _fact(
                WebsiteFactType.PROVIDER_COUNT,
                provider_count.group(1),
                0.86,
                snippet_around(text, provider_count.group(0)),
                page.url,
            )
        )
    elif TEAM_HEADING_RE.search(text):
        roster_count = len(CREDENTIAL_LI_RE.findall(page.text))
        if roster_count > 0:
            facts.append(
                _fact(
                    WebsiteFactType.PROVIDER_COUNT,
                    str(roster_count),
                    0.7,
                    "counted credentialed provider listings in a team/providers section",
                    page.url,
                )
            )

    if (independent := INDEPENDENT_RE.search(text)) is not None:
        facts.append(
            _fact(
                WebsiteFactType.OWNERSHIP_SIGNAL,
                "independent",
                0.84,
                snippet_around(text, independent.group(0)),
                page.url,
            )
        )
    elif (group := GROUP_RE.search(page.text)) is not None:
        parent = group.group(1).strip().rstrip(".,")
        facts.append(
            _fact(
                WebsiteFactType.OWNERSHIP_SIGNAL,
                f"larger_group:{parent}",
                0.8,
                snippet_around(visible_text(page.text), parent),
                page.url,
            )
        )

    for phrase in BILLING_PHRASES:
        if phrase in text.lower():
            facts.append(
                _fact(
                    WebsiteFactType.BILLING_SIGNAL,
                    phrase.replace(" ", "_"),
                    0.85,
                    snippet_around(text, phrase),
                    page.url,
                )
            )
            break

    return tuple(_dedupe_facts(facts))


def _dedupe_facts(facts: list[ExtractedFact]) -> list[ExtractedFact]:
    seen: set[tuple[str, str]] = set()
    unique: list[ExtractedFact] = []
    for fact in facts:
        key = (fact.fact_type.value, fact.value.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(fact)
    return unique


def match_status_label(status: WebsiteMatchStatus) -> str:
    match status:
        case WebsiteMatchStatus.VERIFIED:
            return "verified"
        case WebsiteMatchStatus.AMBIGUOUS:
            return "ambiguous"
        case WebsiteMatchStatus.NO_MATCH:
            return "no_match"
        case _:
            unreachable: Never = status
            raise RuntimeError(f"unhandled website match status: {unreachable}")
