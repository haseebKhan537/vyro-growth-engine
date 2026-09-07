from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Never, Protocol
from uuid import UUID

from vyro_growth.domain import (
    ContactRoleCategory,
    ContactVerificationStatus,
    WebsiteFactType,
    WebsiteMatchStatus,
)

DECISION_MAKER_SOURCE = "decision_maker"
STUB_PROVIDER_NAME = "stub"
LIVE_PROVIDER_NAME = "decision_maker_guarded"
NO_CONTACT_FOUND = "no_contact_found"
FUTURE_WATERFALL_STAGES: tuple[str, ...] = (
    "people_search",
    "domain_verification",
    "website_fallback",
)
FUTURE_HOOKS: tuple[str, ...] = (
    "person_level_website_extraction",
    "email_verification_provider",
    "email_pattern_inference",
    "job_posting_intent",
    "human_phone_verification_queue",
)

FULL_NAME_MAX_LENGTH = 255
TITLE_MAX_LENGTH = 255
EMAIL_MAX_LENGTH = 320
PHONE_MAX_LENGTH = 50
PROVIDER_MAX_LENGTH = 64
DEDUPE_KEY_MAX_LENGTH = 512
EVIDENCE_SNIPPET_MAX_LENGTH = 400
SOURCE_URL_MAX_LENGTH = 1000

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")
WHITESPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
WORD_OWNER_RE = re.compile(r"\b(?:owner|operator|founding\s+partner|managing\s+partner)\b", re.I)
WORD_COO_RE = re.compile(r"\b(?:coo|chief\s+operating\s+officer)\b", re.I)
WORD_CEO_RE = re.compile(r"\b(?:ceo|chief\s+executive\s+officer)\b", re.I)
CLINICAL_CREDENTIAL_RE = re.compile(
    r"\b(?:m\.?d\.?|d\.?o\.?|d\.?d\.?s\.?|d\.?m\.?d\.?|r\.?n\.?|n\.?p\.?|"
    r"p\.?a\.?-?c?|pharm\.?d\.?)\b",
    re.I,
)

PERSONAL_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "aol.com",
        "icloud.com",
        "me.com",
        "live.com",
        "msn.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "ymail.com",
    }
)

CLINICAL_TITLE_PHRASES = (
    "physician",
    "doctor",
    "dentist",
    "chiropractor",
    "nurse practitioner",
    "registered nurse",
    "medical doctor",
    "clinician",
    "therapist",
    "surgeon",
    "pediatrician",
    "cardiologist",
    "dermatologist",
    "family nurse",
)

ROLE_TITLE_PHRASES: tuple[tuple[ContactRoleCategory, tuple[str, ...]], ...] = (
    (
        ContactRoleCategory.OWNER_PHYSICIAN_OWNER,
        (
            "physician owner",
            "physician-owner",
            "practice owner",
            "owner/operator",
            "owner-operator",
            "owner operator",
            "principal owner",
            "managing partner",
        ),
    ),
    (
        ContactRoleCategory.PRACTICE_ADMINISTRATOR,
        ("practice administrator", "practice admin"),
    ),
    (ContactRoleCategory.PRACTICE_MANAGER, ("practice manager",)),
    (ContactRoleCategory.OFFICE_MANAGER, ("office manager",)),
    (ContactRoleCategory.EXECUTIVE_DIRECTOR, ("executive director",)),
    (ContactRoleCategory.COO, ("chief operating officer",)),
    (ContactRoleCategory.CEO_INDEPENDENT, ("chief executive officer",)),
    (
        ContactRoleCategory.REVENUE_CYCLE_MANAGER,
        ("revenue cycle manager", "revenue cycle director", "rcm manager"),
    ),
    (
        ContactRoleCategory.BILLING_MANAGER,
        ("billing manager", "billing director", "billing supervisor"),
    ),
    (
        ContactRoleCategory.OPERATIONS_MANAGER,
        ("operations manager", "ops manager"),
    ),
)

SMALL_PROVIDER_COUNT_MAX = 10


class ContactSkipReason(StrEnum):
    MISSING_NAME = "missing_name"
    MALFORMED = "malformed"
    IRRELEVANT_CLINICAL = "irrelevant_clinical"
    UNKNOWN_ROLE = "unknown_role"
    CEO_NOT_INDEPENDENT_GROUP = "ceo_not_independent_group"


class DecisionMakerProviderError(RuntimeError):
    """Raised when a decision-maker provider cannot complete a lookup."""

    retryable: bool = False


class RetryableDecisionMakerError(DecisionMakerProviderError):
    retryable = True


class NonRetryableDecisionMakerError(DecisionMakerProviderError):
    retryable = False


class MalformedDecisionMakerOutput(NonRetryableDecisionMakerError):
    """Raised when provider output cannot be parsed into professional candidates."""


class LiveDecisionMakerDisabledError(NonRetryableDecisionMakerError):
    """Raised when the live decision-maker boundary is not explicitly enabled."""


class LiveDecisionMakerNotImplementedError(NonRetryableDecisionMakerError):
    """Raised when Phase 66 refuses to open a live people-search HTTP session."""


@dataclass(frozen=True)
class WebsiteFactContext:
    fact_type: str
    value: str | None = None
    confidence: float | None = None
    source_url: str | None = None
    snippet: str | None = None


@dataclass(frozen=True)
class OrganizationContactContext:
    organization_id: UUID
    name: str
    npi: str | None = None
    city: str | None = None
    state: str | None = None
    specialty: str | None = None
    website: str | None = None
    website_match_status: str | None = None
    website_facts: tuple[WebsiteFactContext, ...] = ()


@dataclass(frozen=True)
class DecisionMakerEnrichmentRequest:
    organization: OrganizationContactContext
    max_candidates: int = 10


@dataclass(frozen=True)
class ContactProvenance:
    source_url: str | None = None
    evidence_snippet: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionMakerCandidate:
    full_name: str
    source_provider: str
    source_timestamp: datetime
    title: str | None = None
    role_category: ContactRoleCategory | None = None
    business_email: str | None = None
    business_phone: str | None = None
    confidence: float | None = None
    verification_status: ContactVerificationStatus = ContactVerificationStatus.UNKNOWN
    provenance: ContactProvenance = field(default_factory=ContactProvenance)
    provider_record_id: str | None = None
    owner_operator_evidence: str | None = None


@dataclass(frozen=True)
class DecisionMakerEnrichmentResult:
    candidates: tuple[DecisionMakerCandidate, ...]
    provider_name: str
    fetched_at: datetime
    raw_count: int


@dataclass(frozen=True)
class ClassifiedDecisionMaker:
    candidate: DecisionMakerCandidate
    role_category: ContactRoleCategory
    role_rank: int
    business_email: str | None
    business_phone: str | None
    dedupe_key: str


@dataclass(frozen=True)
class CandidateDisposition:
    classified: ClassifiedDecisionMaker | None
    skip_reason: ContactSkipReason | None
    skip_detail: str | None = None


class DecisionMakerEnrichmentProvider(Protocol):
    def enrich_decision_makers(
        self, request: DecisionMakerEnrichmentRequest
    ) -> DecisionMakerEnrichmentResult: ...


def clean_optional_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = WHITESPACE_RE.sub(" ", value).strip()
    return stripped or None


def clip_text(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


def normalize_person_key(value: str) -> str:
    lowered = NON_ALNUM_RE.sub(" ", value.lower())
    return " ".join(lowered.split())


def role_rank(category: ContactRoleCategory) -> int:
    match category:
        case ContactRoleCategory.OWNER_PHYSICIAN_OWNER:
            return 1
        case ContactRoleCategory.PRACTICE_ADMINISTRATOR:
            return 2
        case ContactRoleCategory.PRACTICE_MANAGER:
            return 3
        case ContactRoleCategory.OFFICE_MANAGER:
            return 4
        case ContactRoleCategory.EXECUTIVE_DIRECTOR:
            return 5
        case ContactRoleCategory.COO:
            return 6
        case ContactRoleCategory.CEO_INDEPENDENT:
            return 7
        case ContactRoleCategory.REVENUE_CYCLE_MANAGER:
            return 8
        case ContactRoleCategory.BILLING_MANAGER:
            return 9
        case ContactRoleCategory.OPERATIONS_MANAGER:
            return 10
        case _:
            unreachable: Never = category
            raise RuntimeError(f"unhandled contact role category: {unreachable}")


def _role_from_value(value: object) -> ContactRoleCategory | None:
    if isinstance(value, ContactRoleCategory):
        return value
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower().replace(" ", "_").replace("-", "_")
    for category in ContactRoleCategory:
        if category.value == cleaned:
            return category
    return None


def _verification_from_value(value: object) -> ContactVerificationStatus | None:
    if isinstance(value, ContactVerificationStatus):
        return value
    if value is None:
        return ContactVerificationStatus.UNKNOWN
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower().replace(" ", "_").replace("-", "_")
    for status in ContactVerificationStatus:
        if status.value == cleaned:
            return status
    aliases = {
        "verified": ContactVerificationStatus.PROVIDER_VERIFIED,
        "valid": ContactVerificationStatus.PROVIDER_VERIFIED,
    }
    return aliases.get(cleaned)


def classify_title(title: str | None) -> ContactRoleCategory | None:
    text = clean_optional_text(title)
    if text is None:
        return None
    lowered = text.lower()
    for category, phrases in ROLE_TITLE_PHRASES:
        if any(phrase in lowered for phrase in phrases):
            return category
    if WORD_CEO_RE.search(text):
        return ContactRoleCategory.CEO_INDEPENDENT
    if WORD_COO_RE.search(text):
        return ContactRoleCategory.COO
    if WORD_OWNER_RE.search(text):
        return ContactRoleCategory.OWNER_PHYSICIAN_OWNER
    return None


def is_clinical_title(title: str | None) -> bool:
    text = clean_optional_text(title)
    if text is None:
        return False
    lowered = text.lower()
    if any(phrase in lowered for phrase in CLINICAL_TITLE_PHRASES):
        return True
    return CLINICAL_CREDENTIAL_RE.search(text) is not None


def has_owner_operator_signal(title: str | None, evidence: str | None) -> bool:
    if clean_optional_text(evidence) is not None:
        return True
    text = clean_optional_text(title)
    if text is None:
        return False
    return WORD_OWNER_RE.search(text) is not None


def independent_small_group(facts: Sequence[WebsiteFactContext]) -> bool | None:
    has_independent = False
    has_larger_group = False
    provider_count: int | None = None
    for fact in facts:
        if fact.fact_type == WebsiteFactType.OWNERSHIP_SIGNAL.value:
            value = (fact.value or "").strip().lower()
            if value == "independent":
                has_independent = True
            elif value.startswith("larger_group"):
                has_larger_group = True
        if fact.fact_type == WebsiteFactType.PROVIDER_COUNT.value:
            raw = (fact.value or "").strip()
            if raw.isdigit():
                provider_count = int(raw)
    if has_larger_group:
        return False
    if provider_count is not None and provider_count > SMALL_PROVIDER_COUNT_MAX:
        return False
    if has_independent:
        return True
    return None


def website_host_from_context(organization: OrganizationContactContext) -> str | None:
    website = clean_optional_text(organization.website)
    if website is None:
        return None
    without_scheme = re.sub(r"^https?://", "", website, flags=re.I)
    host = without_scheme.split("/", maxsplit=1)[0].lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _email_domain(email: str) -> str | None:
    if "@" not in email:
        return None
    return email.rsplit("@", maxsplit=1)[1].lower() or None


def business_email_or_unknown(
    email: str | None,
    *,
    website_host: str | None,
) -> str | None:
    cleaned = clean_optional_text(email)
    if cleaned is None:
        return None
    normalized = cleaned.lower()
    if not EMAIL_RE.match(normalized):
        return None
    domain = _email_domain(normalized)
    if domain is None:
        return None
    if website_host and (domain == website_host or website_host.endswith(f".{domain}")):
        return clip_text(normalized, EMAIL_MAX_LENGTH)
    if domain in PERSONAL_EMAIL_DOMAINS:
        return None
    return clip_text(normalized, EMAIL_MAX_LENGTH)


def business_phone_or_unknown(phone: str | None) -> str | None:
    cleaned = clean_optional_text(phone)
    if cleaned is None:
        return None
    digits = "".join(character for character in cleaned if character.isdigit())
    if len(digits) < 10:
        return None
    return clip_text(cleaned, PHONE_MAX_LENGTH)


def contact_dedupe_key(
    *,
    email: str | None,
    source_provider: str,
    provider_record_id: str | None,
    full_name: str,
    title: str | None,
) -> str:
    if email:
        return clip_text(f"email:{email.lower()}", DEDUPE_KEY_MAX_LENGTH)
    record_id = clean_optional_text(provider_record_id)
    if record_id:
        provider = clean_optional_text(source_provider) or "unknown"
        return clip_text(f"provider:{provider}:{record_id}", DEDUPE_KEY_MAX_LENGTH)
    name_key = normalize_person_key(full_name)
    title_key = normalize_person_key(title or "")
    return clip_text(f"name:{name_key}|title:{title_key}", DEDUPE_KEY_MAX_LENGTH)


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _parse_confidence(value: object) -> float | None | str:
    if value is None:
        return None
    if isinstance(value, bool):
        return "malformed"
    if isinstance(value, int | float):
        number = float(value)
        if 0.0 <= number <= 1.0:
            return number
        return "malformed"
    return "malformed"


def _optional_mapping_text(raw: dict[str, object], key: str) -> str | None:
    value = raw.get(key)
    if isinstance(value, str):
        return clean_optional_text(value)
    return None


def _provenance_from_raw(raw: object) -> ContactProvenance:
    if not isinstance(raw, dict):
        return ContactProvenance()
    source_url = _optional_mapping_text(raw, "source_url")
    snippet = _optional_mapping_text(raw, "evidence_snippet")
    metadata_raw = raw.get("metadata")
    metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
    return ContactProvenance(
        source_url=clip_text(source_url, SOURCE_URL_MAX_LENGTH) if source_url else None,
        evidence_snippet=clip_text(snippet, EVIDENCE_SNIPPET_MAX_LENGTH) if snippet else None,
        metadata=metadata,
    )


def parse_decision_maker_candidate(raw: object) -> DecisionMakerCandidate | None:
    """Return a candidate only when required professional fields are present and well-typed."""
    if isinstance(raw, DecisionMakerCandidate):
        return raw
    if not isinstance(raw, dict):
        return None
    full_name = _optional_mapping_text(raw, "full_name")
    source_provider = _optional_mapping_text(raw, "source_provider")
    timestamp = _parse_timestamp(raw.get("source_timestamp"))
    if full_name is None or source_provider is None or timestamp is None:
        return None
    confidence = _parse_confidence(raw.get("confidence"))
    if isinstance(confidence, str):
        return None
    verification = _verification_from_value(raw.get("verification_status"))
    if verification is None:
        return None
    title_raw = raw.get("title")
    if title_raw is not None and not isinstance(title_raw, str):
        return None
    email_raw = raw.get("business_email")
    if email_raw is not None and not isinstance(email_raw, str):
        return None
    phone_raw = raw.get("business_phone")
    if phone_raw is not None and not isinstance(phone_raw, str):
        return None
    owner_raw = raw.get("owner_operator_evidence")
    if owner_raw is not None and not isinstance(owner_raw, str):
        return None
    record_raw = raw.get("provider_record_id")
    if record_raw is not None and not isinstance(record_raw, str):
        return None
    role_raw = raw.get("role_category")
    role = _role_from_value(role_raw) if role_raw is not None else None
    if role_raw is not None and role is None:
        return None
    title_text = clean_optional_text(title_raw if isinstance(title_raw, str) else None)
    title = clip_text(title_text, TITLE_MAX_LENGTH) if title_text else None
    return DecisionMakerCandidate(
        full_name=clip_text(full_name, FULL_NAME_MAX_LENGTH),
        title=title,
        role_category=role,
        business_email=clean_optional_text(email_raw),
        business_phone=clean_optional_text(phone_raw),
        source_provider=clip_text(source_provider, PROVIDER_MAX_LENGTH),
        source_timestamp=timestamp,
        confidence=confidence,
        verification_status=verification,
        provenance=_provenance_from_raw(raw.get("provenance")),
        provider_record_id=clean_optional_text(record_raw),
        owner_operator_evidence=clean_optional_text(owner_raw),
    )


def _skip_reason_label(reason: ContactSkipReason) -> str:
    match reason:
        case ContactSkipReason.MISSING_NAME:
            return "missing_name"
        case ContactSkipReason.MALFORMED:
            return "malformed"
        case ContactSkipReason.IRRELEVANT_CLINICAL:
            return "irrelevant_clinical"
        case ContactSkipReason.UNKNOWN_ROLE:
            return "unknown_role"
        case ContactSkipReason.CEO_NOT_INDEPENDENT_GROUP:
            return "ceo_not_independent_group"
        case _:
            unreachable: Never = reason
            raise RuntimeError(f"unhandled skip reason: {unreachable}")


def classify_candidate(
    candidate: DecisionMakerCandidate,
    *,
    organization: OrganizationContactContext,
) -> CandidateDisposition:
    name = clean_optional_text(candidate.full_name)
    if name is None:
        return CandidateDisposition(None, ContactSkipReason.MISSING_NAME)
    if candidate.source_timestamp.tzinfo is None:
        return CandidateDisposition(None, ContactSkipReason.MALFORMED, "naive_timestamp")
    if candidate.confidence is not None and not 0.0 <= candidate.confidence <= 1.0:
        return CandidateDisposition(None, ContactSkipReason.MALFORMED, "confidence_out_of_range")
    if clean_optional_text(candidate.source_provider) is None:
        return CandidateDisposition(None, ContactSkipReason.MALFORMED, "missing_source_provider")
    if candidate.business_email is not None and business_email_or_unknown(
        candidate.business_email, website_host=None
    ) is None and clean_optional_text(candidate.business_email) is not None:
        # Invalid syntax is malformed; personal webmail is dropped later as unknown email.
        cleaned_email = clean_optional_text(candidate.business_email)
        if cleaned_email is not None and not EMAIL_RE.match(cleaned_email.lower()):
            return CandidateDisposition(None, ContactSkipReason.MALFORMED, "invalid_email")

    title = clean_optional_text(candidate.title)
    title_role = classify_title(title)
    provider_role = candidate.role_category
    clinical = is_clinical_title(title)
    owner_signal = has_owner_operator_signal(title, candidate.owner_operator_evidence)

    owner_role = ContactRoleCategory.OWNER_PHYSICIAN_OWNER
    if clinical and not owner_signal and provider_role is not owner_role:
        return CandidateDisposition(None, ContactSkipReason.IRRELEVANT_CLINICAL)

    role = title_role or provider_role
    if clinical and owner_signal:
        role = ContactRoleCategory.OWNER_PHYSICIAN_OWNER
    if role is None:
        return CandidateDisposition(None, ContactSkipReason.UNKNOWN_ROLE)

    if role is ContactRoleCategory.CEO_INDEPENDENT:
        independence = independent_small_group(organization.website_facts)
        if independence is not True:
            return CandidateDisposition(None, ContactSkipReason.CEO_NOT_INDEPENDENT_GROUP)

    website_host = website_host_from_context(organization)
    email = business_email_or_unknown(candidate.business_email, website_host=website_host)
    phone = business_phone_or_unknown(candidate.business_phone)
    classified = ClassifiedDecisionMaker(
        candidate=candidate,
        role_category=role,
        role_rank=role_rank(role),
        business_email=email,
        business_phone=phone,
        dedupe_key=contact_dedupe_key(
            email=email,
            source_provider=candidate.source_provider,
            provider_record_id=candidate.provider_record_id,
            full_name=name,
            title=title,
        ),
    )
    return CandidateDisposition(classified, None)


def rank_classified(
    classified: Sequence[ClassifiedDecisionMaker],
) -> tuple[ClassifiedDecisionMaker, ...]:
    return tuple(
        sorted(
            classified,
            key=lambda item: (
                item.role_rank,
                -(item.candidate.confidence or 0.0),
                item.candidate.full_name,
            ),
        )
    )


class StubDecisionMakerEnrichmentProvider:
    """CI/local default. Does not call paid providers or invent contacts."""

    live = False

    def __init__(self) -> None:
        self.requests: list[DecisionMakerEnrichmentRequest] = []

    def enrich_decision_makers(
        self, request: DecisionMakerEnrichmentRequest
    ) -> DecisionMakerEnrichmentResult:
        self.requests.append(request)
        return DecisionMakerEnrichmentResult(
            candidates=(),
            provider_name=STUB_PROVIDER_NAME,
            fetched_at=datetime.now(tz=UTC),
            raw_count=0,
        )


class StaticDecisionMakerEnrichmentProvider:
    """Test adapter that returns configured records. Does not invent or call a network."""

    live = False

    def __init__(self, candidates: Sequence[object] = ()) -> None:
        self._candidates = tuple(candidates)
        self.requests: list[DecisionMakerEnrichmentRequest] = []

    def enrich_decision_makers(
        self, request: DecisionMakerEnrichmentRequest
    ) -> DecisionMakerEnrichmentResult:
        self.requests.append(request)
        parsed: list[DecisionMakerCandidate] = []
        raw_count = 0
        for item in self._candidates:
            raw_count += 1
            candidate = parse_decision_maker_candidate(item)
            if candidate is not None:
                parsed.append(candidate)
        return DecisionMakerEnrichmentResult(
            candidates=tuple(parsed),
            provider_name="static",
            fetched_at=datetime.now(tz=UTC),
            raw_count=raw_count,
        )


class WaterfallDecisionMakerProvider:
    """Dry-run design hook. Sequences inner providers and never invents contacts.

    Phase 66 does not add social-network scraping, list-purchase, voice, or live paid calls.
    Later stages (domain verification, website person extraction) can be added
    as additional inner providers without changing classify/rank logic.
    """

    live = False
    planned_stages = FUTURE_WATERFALL_STAGES
    planned_hooks = FUTURE_HOOKS

    def __init__(self, providers: Sequence[DecisionMakerEnrichmentProvider] = ()) -> None:
        self._providers = tuple(providers)
        self.requests: list[DecisionMakerEnrichmentRequest] = []
        self.stage_errors: list[str] = []

    def enrich_decision_makers(
        self, request: DecisionMakerEnrichmentRequest
    ) -> DecisionMakerEnrichmentResult:
        self.requests.append(request)
        self.stage_errors = []
        if not self._providers:
            return DecisionMakerEnrichmentResult(
                candidates=(),
                provider_name="waterfall",
                fetched_at=datetime.now(tz=UTC),
                raw_count=0,
            )
        last_result: DecisionMakerEnrichmentResult | None = None
        last_error: Exception | None = None
        for provider in self._providers:
            try:
                result = provider.enrich_decision_makers(request)
            except DecisionMakerProviderError as exc:
                last_error = exc
                category = "retryable" if exc.retryable else "non_retryable"
                self.stage_errors.append(category)
                continue
            last_result = result
            if result.candidates:
                return result
        if last_result is not None:
            return last_result
        if last_error is not None:
            raise last_error
        return DecisionMakerEnrichmentResult(
            candidates=(),
            provider_name="waterfall",
            fetched_at=datetime.now(tz=UTC),
            raw_count=0,
        )


def build_decision_maker_provider(
    settings: object | None = None,
) -> DecisionMakerEnrichmentProvider:
    """Always the stub. Live paid adapters are not wired and must not be called in CI."""
    _ = settings
    return StubDecisionMakerEnrichmentProvider()


def website_match_status_value(value: str | None) -> str | None:
    if value is None:
        return None
    for status in WebsiteMatchStatus:
        if status.value == value:
            return status.value
    return value


def skip_reason_value(reason: ContactSkipReason) -> str:
    return _skip_reason_label(reason)
