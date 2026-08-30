from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Never
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.domain import (
    ContactFactType,
    ContactRoleCategory,
    LeadStage,
    WebsiteFactType,
    WebsiteMatchStatus,
)
from vyro_growth.models import (
    Activity,
    Contact,
    Lead,
    LeadScore,
    Organization,
    SourceEvidence,
)

logger = structlog.get_logger(__name__)

MODEL_VERSION = "deterministic-icp-v2"
SCORE_MIN = 0
SCORE_MAX = 100
BATCH_MAX = 500
NPPES_CLAIM_TYPE = "nppes_organization_record"
LEAD_SCORING_ACTOR = "lead_scoring"
LEAD_SCORED_ACTION = "lead_scored"
NPPES_ACTIVE_STATUS = "A"
SMALL_PROVIDER_COUNT_MAX = 8
MODERATE_PROVIDER_COUNT_MAX = 15
LARGE_PROVIDER_COUNT_MIN = 26
SMALL_LOCATION_COUNT_MAX = 3

POINTS_NAME = 4
POINTS_NPI = 12
POINTS_STATE = 8
POINTS_CITY = 5
POINTS_SPECIALTY_PRESENT = 5
POINTS_SPECIALTY_TARGET = 13
POINTS_NPPES_ACTIVE = 6
POINTS_NPPES_EVIDENCE = 5
POINTS_WEBSITE_VERIFIED = 8
POINTS_WEBSITE_LOCAL = 3
POINTS_INDEPENDENT = 8
POINTS_LARGER_GROUP = -10
POINTS_PRACTICE_SIZE_SMALL = 6
POINTS_PRACTICE_SIZE_MODERATE = 3
POINTS_PRACTICE_SIZE_LARGE = -6
POINTS_PROVIDER_COUNT_SMALL = 4
POINTS_PROVIDER_COUNT_MODERATE = 2
POINTS_PROVIDER_COUNT_LARGE = -6
POINTS_BILLING = 6
POINTS_BUSINESS_PHONE = 3
POINTS_BUSINESS_EMAIL = 3
POINTS_DECISION_MAKER = 6
POINTS_VERIFIED_EMAIL = 4
POINTS_EXCLUDED_NAME = -15

HOT_MIN = 85
HIGH_MIN = 70
MEDIUM_MIN = 45

US_STATE_CODES = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "PR",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    }
)

TARGET_SPECIALTY_PHRASES = frozenset(
    {
        "family medicine",
        "internal medicine",
        "general practice",
        "pediatrics",
        "chiropractor",
        "dermatology",
        "obstetrics",
        "gynecology",
        "orthopaedic",
        "orthopedic",
        "cardiology",
        "cardiovascular disease",
        "gastroenterology",
        "neurology",
        "ophthalmology",
        "physical therapist",
        "occupational therapist",
        "podiatrist",
        "psychiatry",
        "psychologist",
        "endocrinology",
        "rheumatology",
        "urology",
        "otolaryngology",
        "pulmonary disease",
        "nephrology",
        "pain medicine",
        "sports medicine",
        "allergy",
        "immunology",
        "sleep medicine",
    }
)

EXCLUDED_SPECIALTY_PHRASES = frozenset(
    {
        "hospital",
        "pharmacy",
        "durable medical equipment",
        "clinical medical laboratory",
        "skilled nursing",
        "ambulance",
        "home health",
        "health maintenance organization",
        "managed care",
        "hospice",
        "nursing facility",
        "intermediate care",
        "portable x-ray",
        "insurance",
    }
)

EXCLUDED_NAME_PHRASES = frozenset(
    {
        "hospital",
        "health system",
        "medical center",
        "pharmacy",
        "health plan",
        "health maintenance",
    }
)

DECISION_MAKER_TITLE_PHRASES = frozenset(
    {
        "practice manager",
        "office manager",
        "practice administrator",
        "office administrator",
        "administrator",
        "owner",
        "billing manager",
        "managing partner",
        "executive director",
        "revenue cycle",
        "operations manager",
        "chief operating",
        "chief executive",
    }
)

SMALL_PRACTICE_SIZE_VALUES = frozenset(
    {
        "single_location",
        "small_practice",
        "boutique_practice",
        "1_locations",
        "one_location",
    }
)
MODERATE_PRACTICE_SIZE_VALUES = frozenset(
    {
        "2_locations",
        "3_locations",
    }
)
LARGE_PRACTICE_SIZE_VALUES = frozenset(
    {
        "multi_location",
        "large_medical_group",
        "4_locations",
        "5_locations",
        "6_locations",
        "7_locations",
        "8_locations",
        "9_locations",
        "10_locations",
    }
)
IN_HOUSE_BILLING_VALUES = frozenset(
    {
        "in-house_billing",
        "in_house_billing",
        "we_do_our_own_billing",
        "our_own_billing",
        "we_handle_billing",
        "billing_department",
        "revenue_cycle",
        "outsourced_billing",
        "third-party_billing",
        "third_party_billing",
    }
)
RANKED_DECISION_MAKER_ROLES = frozenset(category.value for category in ContactRoleCategory)


class LeadScoringError(ValueError):
    """Raised when a scoring job cannot load the requested lead or organization."""


class FactorCode(StrEnum):
    ORGANIZATION_NAME = "organization_name"
    NPI_IDENTITY = "npi_identity"
    US_STATE = "us_state"
    CITY = "city"
    SPECIALTY_PRESENT = "specialty_present"
    SPECIALTY_FIT = "specialty_fit"
    NPPES_ACTIVE_STATUS = "nppes_active_status"
    NPPES_SOURCE_EVIDENCE = "nppes_source_evidence"
    WEBSITE_MATCH = "website_match"
    LOCAL_WEBSITE = "local_website"
    OWNERSHIP_SIGNAL = "ownership_signal"
    PRACTICE_SIZE_SIGNAL = "practice_size_signal"
    PROVIDER_COUNT = "provider_count"
    BILLING_SIGNAL = "billing_signal"
    BUSINESS_PHONE = "business_phone"
    BUSINESS_EMAIL = "business_email"
    DECISION_MAKER_TITLE = "decision_maker_title"
    VERIFIED_EMAIL = "verified_email"
    EXCLUDED_ORGANIZATION_NAME = "excluded_organization_name"


class FactorStatus(StrEnum):
    APPLIED = "applied"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"


class FactorPolarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class ReasonCode(StrEnum):
    POS_ORGANIZATION_NAME = "pos_organization_name"
    POS_NPI_VALID = "pos_npi_valid"
    POS_US_STATE = "pos_us_state"
    POS_CITY = "pos_city"
    POS_SPECIALTY_PRESENT = "pos_specialty_present"
    POS_TARGET_SPECIALTY = "pos_target_specialty"
    POS_NPPES_ACTIVE = "pos_nppes_active"
    POS_NPPES_EVIDENCE = "pos_nppes_evidence"
    POS_WEBSITE_VERIFIED = "pos_website_verified"
    POS_LOCAL_WEBSITE = "pos_local_website"
    POS_INDEPENDENT_OWNERSHIP = "pos_independent_ownership"
    POS_SMALL_PRACTICE = "pos_small_practice"
    POS_MODERATE_PRACTICE = "pos_moderate_practice"
    POS_PROVIDER_COUNT_ICP = "pos_provider_count_icp"
    POS_BILLING_SIGNAL = "pos_billing_signal"
    POS_BUSINESS_PHONE = "pos_business_phone"
    POS_BUSINESS_EMAIL = "pos_business_email"
    POS_DECISION_MAKER = "pos_decision_maker"
    POS_VERIFIED_CONTACT_EMAIL = "pos_verified_contact_email"
    NEG_INVALID_NPI = "neg_invalid_npi"
    NEG_EXCLUDED_SPECIALTY = "neg_excluded_specialty"
    NEG_EXCLUDED_NAME = "neg_excluded_name"
    NEG_LARGER_GROUP = "neg_larger_group"
    NEG_LARGE_PRACTICE = "neg_large_practice"
    NEG_LARGE_PROVIDER_COUNT = "neg_large_provider_count"
    NEG_WEBSITE_AMBIGUOUS = "neg_website_ambiguous"
    NEG_WEBSITE_NO_MATCH = "neg_website_no_match"
    NEG_WEBSITE_CONFLICT = "neg_website_conflict"
    INFO_MISSING = "info_missing"
    INFO_NOT_APPLICABLE = "info_not_applicable"
    INFO_UNKNOWN_SPECIALTY = "info_unknown_specialty"
    INFO_UNVERIFIED_EMAIL = "info_unverified_email"
    INFO_UNCLASSIFIED_SIGNAL = "info_unclassified_signal"
    INFO_CONFLICTING_OWNERSHIP = "info_conflicting_ownership"
    INFO_CONFLICTING_PRACTICE_SIZE = "info_conflicting_practice_size"
    INFO_CONFLICTING_PROVIDER_COUNT = "info_conflicting_provider_count"
    INFO_CONFLICTING_BILLING = "info_conflicting_billing"
    INFO_CONFLICTING_SIZE_AND_COUNT = "info_conflicting_size_and_count"
    INFO_WEBSITE_FACTS_SKIPPED = "info_website_facts_skipped"
    DISQ_EXCLUDED_ORGANIZATION = "disq_excluded_organization"
    DISQ_EXCLUDED_SPECIALTY = "disq_excluded_specialty"
    RESEARCH_SPECIALTY_MISSING = "research_specialty_missing"


class SpecialtyFit(StrEnum):
    TARGET = "target"
    UNKNOWN = "unknown"
    EXCLUDED = "excluded"


class ScoreBand(StrEnum):
    HOT = "hot"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    RESEARCH = "research"
    DISQUALIFIED = "disqualified"


class PracticeSizeClass(StrEnum):
    SMALL = "small"
    MODERATE = "moderate"
    LARGE = "large"
    UNKNOWN = "unknown"


class OwnershipClass(StrEnum):
    INDEPENDENT = "independent"
    LARGER_GROUP = "larger_group"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EvidencePointer:
    evidence_id: str | None = None
    source_url: str | None = None
    claim_type: str | None = None
    extracted_value: str | None = None
    conflicting_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoringSnapshot:
    organization_name: str | None = None
    npi: str | None = None
    city: str | None = None
    state: str | None = None
    specialty: str | None = None
    website: str | None = None
    nppes_status: str | None = None
    has_nppes_evidence: bool = False
    nppes_source_url: str | None = None
    nppes_evidence: EvidencePointer | None = None
    verified_email: bool = False
    has_contact_email: bool = False
    has_contact_phone: bool = False
    decision_maker_title: str | None = None
    decision_maker_role: str | None = None
    decision_maker_evidence: EvidencePointer | None = None
    verified_email_evidence: EvidencePointer | None = None
    website_match_status: str | None = None
    website_match_conflict: bool = False
    website_match_evidence: EvidencePointer | None = None
    official_website: str | None = None
    website_facts_eligible: bool = False
    ownership_value: str | None = None
    ownership_conflict: bool = False
    ownership_evidence: EvidencePointer | None = None
    practice_size_value: str | None = None
    practice_size_conflict: bool = False
    practice_size_evidence: EvidencePointer | None = None
    provider_count_value: str | None = None
    provider_count_conflict: bool = False
    provider_count_evidence: EvidencePointer | None = None
    billing_value: str | None = None
    billing_conflict: bool = False
    billing_evidence: EvidencePointer | None = None
    business_phone: str | None = None
    business_phone_evidence: EvidencePointer | None = None
    business_email: str | None = None
    business_email_evidence: EvidencePointer | None = None


@dataclass(frozen=True)
class ScoreFactor:
    code: FactorCode
    points: int
    reason: str
    evidence_field: str
    observed_value: str | None
    status: FactorStatus
    reason_code: ReasonCode
    polarity: FactorPolarity
    evidence_id: str | None = None
    source_url: str | None = None
    claim_type: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "points": self.points,
            "reason": self.reason,
            "reason_code": self.reason_code.value,
            "polarity": self.polarity.value,
            "evidence_field": self.evidence_field,
            "observed_value": self.observed_value,
            "status": self.status.value,
            "evidence_id": self.evidence_id,
            "source_url": self.source_url,
            "claim_type": self.claim_type,
        }


@dataclass(frozen=True)
class ScoringResult:
    total: int
    model_version: str
    band: ScoreBand
    factors: tuple[ScoreFactor, ...]
    missing_fields: tuple[str, ...]
    used_fields: tuple[str, ...]
    fabricated_facts: bool
    external_providers_called: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()
    disqualification_codes: tuple[str, ...] = ()
    research_reasons: tuple[str, ...] = ()

    def to_rationale(self) -> dict[str, object]:
        return {
            "model_version": self.model_version,
            "total": self.total,
            "band": self.band.value,
            "factors": [factor.to_dict() for factor in self.factors],
            "missing_fields": list(self.missing_fields),
            "used_fields": list(self.used_fields),
            "reason_codes": list(self.reason_codes),
            "disqualification_codes": list(self.disqualification_codes),
            "research_reasons": list(self.research_reasons),
            "fabricated_facts": self.fabricated_facts,
            "external_providers_called": list(self.external_providers_called),
            "policy": {
                "no_outbound": True,
                "local_data_only": True,
                "unknown_not_inferred": True,
                "website_facts_require_verified_match": True,
                "billing_signals_require_explicit_evidence": True,
            },
        }


@dataclass(frozen=True)
class PersistedScoreResult:
    lead_id: UUID
    organization_id: UUID
    lead_score_id: UUID
    lead_created: bool
    scoring: ScoringResult
    reused_existing_score: bool = False


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def npi_checksum_valid(npi: str) -> bool:
    if len(npi) != 10 or not npi.isdigit():
        return False
    payload = "80840" + npi
    total = 0
    for index, char in enumerate(reversed(payload)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _contains_phrase(value: str, phrases: frozenset[str]) -> str | None:
    lowered = value.lower()
    for phrase in sorted(phrases):
        if phrase in lowered:
            return phrase
    return None


def classify_specialty(specialty: str | None) -> SpecialtyFit:
    text = _text(specialty)
    if text is None:
        return SpecialtyFit.UNKNOWN
    if _contains_phrase(text, EXCLUDED_SPECIALTY_PHRASES) is not None:
        return SpecialtyFit.EXCLUDED
    if _contains_phrase(text, TARGET_SPECIALTY_PHRASES) is not None:
        return SpecialtyFit.TARGET
    return SpecialtyFit.UNKNOWN


def classify_ownership(value: str | None) -> OwnershipClass:
    text = _text(value)
    if text is None:
        return OwnershipClass.UNKNOWN
    lowered = text.lower()
    if lowered == "independent" or lowered.startswith("independent"):
        return OwnershipClass.INDEPENDENT
    if lowered.startswith("larger_group"):
        return OwnershipClass.LARGER_GROUP
    return OwnershipClass.UNKNOWN


def classify_practice_size(value: str | None) -> PracticeSizeClass:
    text = _text(value)
    if text is None:
        return PracticeSizeClass.UNKNOWN
    lowered = text.lower()
    if lowered in SMALL_PRACTICE_SIZE_VALUES:
        return PracticeSizeClass.SMALL
    if lowered in MODERATE_PRACTICE_SIZE_VALUES:
        return PracticeSizeClass.MODERATE
    if lowered in LARGE_PRACTICE_SIZE_VALUES:
        return PracticeSizeClass.LARGE
    if lowered.endswith("_locations"):
        count = _parse_int(lowered.removesuffix("_locations"))
        if count is None:
            return PracticeSizeClass.UNKNOWN
        if count <= 1:
            return PracticeSizeClass.SMALL
        if count <= SMALL_LOCATION_COUNT_MAX:
            return PracticeSizeClass.MODERATE
        return PracticeSizeClass.LARGE
    return PracticeSizeClass.UNKNOWN


def parse_provider_count(value: str | None) -> int | None:
    text = _text(value)
    if text is None:
        return None
    return _parse_int(text)


def _parse_int(value: str) -> int | None:
    if not value.isdigit():
        return None
    return int(value)


def _provider_count_class(count: int) -> PracticeSizeClass:
    if count <= SMALL_PROVIDER_COUNT_MAX:
        return PracticeSizeClass.SMALL
    if count <= MODERATE_PROVIDER_COUNT_MAX:
        return PracticeSizeClass.MODERATE
    if count >= LARGE_PROVIDER_COUNT_MIN:
        return PracticeSizeClass.LARGE
    return PracticeSizeClass.UNKNOWN


def resolve_band(
    total: int,
    *,
    specialty_fit: SpecialtyFit,
    specialty_missing: bool,
    disqualified: bool,
) -> tuple[ScoreBand, tuple[ReasonCode, ...]]:
    if disqualified:
        return ScoreBand.DISQUALIFIED, ()
    if specialty_missing:
        return ScoreBand.RESEARCH, (ReasonCode.RESEARCH_SPECIALTY_MISSING,)
    if total >= HOT_MIN and specialty_fit is SpecialtyFit.TARGET:
        return ScoreBand.HOT, ()
    if total >= HIGH_MIN:
        return ScoreBand.HIGH, ()
    if total >= MEDIUM_MIN:
        return ScoreBand.MEDIUM, ()
    return ScoreBand.LOW, ()


def _specialty_fit_points(fit: SpecialtyFit) -> tuple[int, str, ReasonCode, FactorPolarity]:
    match fit:
        case SpecialtyFit.TARGET:
            return (
                POINTS_SPECIALTY_TARGET,
                "specialty matches independent US medical practice target list",
                ReasonCode.POS_TARGET_SPECIALTY,
                FactorPolarity.POSITIVE,
            )
        case SpecialtyFit.EXCLUDED:
            return (
                0,
                "specialty is outside the conservative medical billing ICP",
                ReasonCode.NEG_EXCLUDED_SPECIALTY,
                FactorPolarity.NEGATIVE,
            )
        case SpecialtyFit.UNKNOWN:
            return (
                0,
                "specialty fit unknown; not assumed",
                ReasonCode.INFO_UNKNOWN_SPECIALTY,
                FactorPolarity.NEUTRAL,
            )
        case _:
            unreachable: Never = fit
            raise RuntimeError(f"unhandled specialty fit: {unreachable}")


def _usable_local_website(value: str | None) -> str | None:
    text = _text(value)
    if text is None or " " in text or "." not in text:
        return None
    return text


def _pointer_fields(pointer: EvidencePointer | None) -> tuple[str | None, str | None, str | None]:
    if pointer is None:
        return None, None, None
    return pointer.evidence_id, pointer.source_url, pointer.claim_type


def _factor(
    *,
    code: FactorCode,
    points: int,
    reason: str,
    evidence_field: str,
    observed_value: str | None,
    status: FactorStatus,
    reason_code: ReasonCode,
    polarity: FactorPolarity,
    pointer: EvidencePointer | None = None,
) -> ScoreFactor:
    evidence_id, source_url, claim_type = _pointer_fields(pointer)
    return ScoreFactor(
        code=code,
        points=points,
        reason=reason,
        evidence_field=evidence_field,
        observed_value=observed_value,
        status=status,
        reason_code=reason_code,
        polarity=polarity,
        evidence_id=evidence_id,
        source_url=source_url,
        claim_type=claim_type,
    )


def score_snapshot(snapshot: ScoringSnapshot) -> ScoringResult:
    size_count_conflict = _size_and_count_conflict(snapshot)
    factors = (
        _name_factor(snapshot.organization_name),
        _npi_factor(snapshot.npi),
        _state_factor(snapshot.state),
        _city_factor(snapshot.city),
        _specialty_present_factor(snapshot.specialty),
        _specialty_fit_factor(snapshot.specialty),
        _nppes_active_factor(
            snapshot.nppes_status,
            snapshot.has_nppes_evidence,
            snapshot.nppes_evidence,
        ),
        _nppes_evidence_factor(
            snapshot.has_nppes_evidence,
            snapshot.nppes_source_url,
            snapshot.nppes_evidence,
        ),
        _website_match_factor(snapshot),
        _local_website_factor(snapshot),
        _ownership_factor(snapshot),
        _practice_size_factor(snapshot, size_count_conflict),
        _provider_count_factor(snapshot, size_count_conflict),
        _billing_factor(snapshot),
        _business_phone_factor(snapshot),
        _business_email_factor(snapshot),
        _decision_maker_factor(snapshot),
        _verified_email_factor(snapshot),
        _excluded_name_factor(snapshot.organization_name),
    )
    total = max(SCORE_MIN, min(SCORE_MAX, sum(factor.points for factor in factors)))
    missing_fields = tuple(
        dict.fromkeys(
            factor.evidence_field for factor in factors if factor.status is FactorStatus.MISSING
        )
    )
    used_fields = tuple(
        dict.fromkeys(
            factor.evidence_field for factor in factors if factor.status is FactorStatus.APPLIED
        )
    )
    specialty_fit = classify_specialty(snapshot.specialty)
    specialty_missing = _text(snapshot.specialty) is None
    excluded_name = (
        _text(snapshot.organization_name) is not None
        and _contains_phrase(snapshot.organization_name or "", EXCLUDED_NAME_PHRASES) is not None
    )
    disqualified = specialty_fit is SpecialtyFit.EXCLUDED or excluded_name
    disqualification_codes = _disqualification_codes(specialty_fit, excluded_name)
    band, research_codes = resolve_band(
        total,
        specialty_fit=specialty_fit,
        specialty_missing=specialty_missing,
        disqualified=disqualified,
    )
    reason_codes = tuple(dict.fromkeys(factor.reason_code.value for factor in factors))
    return ScoringResult(
        total=total,
        model_version=MODEL_VERSION,
        band=band,
        factors=factors,
        missing_fields=missing_fields,
        used_fields=used_fields,
        fabricated_facts=False,
        external_providers_called=(),
        reason_codes=reason_codes,
        disqualification_codes=tuple(code.value for code in disqualification_codes),
        research_reasons=tuple(code.value for code in research_codes),
    )


def _disqualification_codes(
    specialty_fit: SpecialtyFit,
    excluded_name: bool,
) -> tuple[ReasonCode, ...]:
    codes: list[ReasonCode] = []
    if specialty_fit is SpecialtyFit.EXCLUDED:
        codes.append(ReasonCode.DISQ_EXCLUDED_SPECIALTY)
    if excluded_name:
        codes.append(ReasonCode.DISQ_EXCLUDED_ORGANIZATION)
    return tuple(codes)


def _size_and_count_conflict(snapshot: ScoringSnapshot) -> bool:
    if not snapshot.website_facts_eligible:
        return False
    if snapshot.practice_size_conflict or snapshot.provider_count_conflict:
        return False
    size_class = classify_practice_size(snapshot.practice_size_value)
    count = parse_provider_count(snapshot.provider_count_value)
    if count is None:
        return False
    count_class = _provider_count_class(count)
    if size_class is PracticeSizeClass.SMALL and count_class is PracticeSizeClass.LARGE:
        return True
    if size_class is PracticeSizeClass.LARGE and count_class is PracticeSizeClass.SMALL:
        return True
    return False


def _name_factor(name: str | None) -> ScoreFactor:
    text = _text(name)
    if text is None:
        return _factor(
            code=FactorCode.ORGANIZATION_NAME,
            points=0,
            reason="organization name missing; not inferred",
            evidence_field="organization.name",
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    return _factor(
        code=FactorCode.ORGANIZATION_NAME,
        points=POINTS_NAME,
        reason="organization name is present in local records",
        evidence_field="organization.name",
        observed_value=text,
        status=FactorStatus.APPLIED,
        reason_code=ReasonCode.POS_ORGANIZATION_NAME,
        polarity=FactorPolarity.POSITIVE,
    )


def _npi_factor(npi: str | None) -> ScoreFactor:
    text = _text(npi)
    if text is None:
        return _factor(
            code=FactorCode.NPI_IDENTITY,
            points=0,
            reason="npi missing; identity not inferred",
            evidence_field="organization.npi",
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    if not npi_checksum_valid(text):
        return _factor(
            code=FactorCode.NPI_IDENTITY,
            points=0,
            reason="npi failed checksum; not treated as identity evidence",
            evidence_field="organization.npi",
            observed_value=text,
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.NEG_INVALID_NPI,
            polarity=FactorPolarity.NEGATIVE,
        )
    return _factor(
        code=FactorCode.NPI_IDENTITY,
        points=POINTS_NPI,
        reason="npi is present and checksum-valid",
        evidence_field="organization.npi",
        observed_value=text,
        status=FactorStatus.APPLIED,
        reason_code=ReasonCode.POS_NPI_VALID,
        polarity=FactorPolarity.POSITIVE,
    )


def _state_factor(state: str | None) -> ScoreFactor:
    text = _text(state)
    if text is None:
        return _factor(
            code=FactorCode.US_STATE,
            points=0,
            reason="state missing; US location not inferred",
            evidence_field="organization.state",
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    normalized = text.upper()
    if normalized not in US_STATE_CODES:
        return _factor(
            code=FactorCode.US_STATE,
            points=0,
            reason="state is not a recognized US jurisdiction; not assumed",
            evidence_field="organization.state",
            observed_value=normalized,
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.INFO_UNCLASSIFIED_SIGNAL,
            polarity=FactorPolarity.NEUTRAL,
        )
    return _factor(
        code=FactorCode.US_STATE,
        points=POINTS_STATE,
        reason="state is a recognized US jurisdiction",
        evidence_field="organization.state",
        observed_value=normalized,
        status=FactorStatus.APPLIED,
        reason_code=ReasonCode.POS_US_STATE,
        polarity=FactorPolarity.POSITIVE,
    )


def _city_factor(city: str | None) -> ScoreFactor:
    text = _text(city)
    if text is None:
        return _factor(
            code=FactorCode.CITY,
            points=0,
            reason="city missing; not inferred",
            evidence_field="organization.city",
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    return _factor(
        code=FactorCode.CITY,
        points=POINTS_CITY,
        reason="city is present in local records",
        evidence_field="organization.city",
        observed_value=text,
        status=FactorStatus.APPLIED,
        reason_code=ReasonCode.POS_CITY,
        polarity=FactorPolarity.POSITIVE,
    )


def _specialty_present_factor(specialty: str | None) -> ScoreFactor:
    text = _text(specialty)
    if text is None:
        return _factor(
            code=FactorCode.SPECIALTY_PRESENT,
            points=0,
            reason="specialty missing; not inferred",
            evidence_field="organization.specialty",
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    return _factor(
        code=FactorCode.SPECIALTY_PRESENT,
        points=POINTS_SPECIALTY_PRESENT,
        reason="specialty is present in local records",
        evidence_field="organization.specialty",
        observed_value=text,
        status=FactorStatus.APPLIED,
        reason_code=ReasonCode.POS_SPECIALTY_PRESENT,
        polarity=FactorPolarity.POSITIVE,
    )


def _specialty_fit_factor(specialty: str | None) -> ScoreFactor:
    text = _text(specialty)
    if text is None:
        return _factor(
            code=FactorCode.SPECIALTY_FIT,
            points=0,
            reason="specialty missing; fit not inferred",
            evidence_field="organization.specialty",
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    fit = classify_specialty(text)
    points, reason, reason_code, polarity = _specialty_fit_points(fit)
    return _factor(
        code=FactorCode.SPECIALTY_FIT,
        points=points,
        reason=reason,
        evidence_field="organization.specialty",
        observed_value=text,
        status=FactorStatus.APPLIED,
        reason_code=reason_code,
        polarity=polarity,
    )


def _nppes_active_factor(
    status: str | None,
    has_evidence: bool,
    pointer: EvidencePointer | None,
) -> ScoreFactor:
    if not has_evidence:
        return _factor(
            code=FactorCode.NPPES_ACTIVE_STATUS,
            points=0,
            reason="nppes status missing; active status not assumed",
            evidence_field="source_evidence.metadata_json.business_record.status",
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    text = _text(status)
    if text is None:
        return _factor(
            code=FactorCode.NPPES_ACTIVE_STATUS,
            points=0,
            reason="nppes evidence present but status missing; active status not assumed",
            evidence_field="source_evidence.metadata_json.business_record.status",
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
            pointer=pointer,
        )
    normalized = text.upper()
    if normalized != NPPES_ACTIVE_STATUS:
        return _factor(
            code=FactorCode.NPPES_ACTIVE_STATUS,
            points=0,
            reason="nppes status is not active; not assumed eligible",
            evidence_field="source_evidence.metadata_json.business_record.status",
            observed_value=normalized,
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.INFO_UNCLASSIFIED_SIGNAL,
            polarity=FactorPolarity.NEUTRAL,
            pointer=pointer,
        )
    return _factor(
        code=FactorCode.NPPES_ACTIVE_STATUS,
        points=POINTS_NPPES_ACTIVE,
        reason="nppes business record status is active",
        evidence_field="source_evidence.metadata_json.business_record.status",
        observed_value=normalized,
        status=FactorStatus.APPLIED,
        reason_code=ReasonCode.POS_NPPES_ACTIVE,
        polarity=FactorPolarity.POSITIVE,
        pointer=pointer,
    )


def _nppes_evidence_factor(
    has_evidence: bool,
    source_url: str | None,
    pointer: EvidencePointer | None,
) -> ScoreFactor:
    if not has_evidence:
        return _factor(
            code=FactorCode.NPPES_SOURCE_EVIDENCE,
            points=0,
            reason="nppes source evidence missing; provenance not inferred",
            evidence_field="source_evidence.source_url",
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    return _factor(
        code=FactorCode.NPPES_SOURCE_EVIDENCE,
        points=POINTS_NPPES_EVIDENCE,
        reason="nppes organization evidence is stored locally",
        evidence_field="source_evidence.source_url",
        observed_value=_text(source_url),
        status=FactorStatus.APPLIED,
        reason_code=ReasonCode.POS_NPPES_EVIDENCE,
        polarity=FactorPolarity.POSITIVE,
        pointer=pointer,
    )


def _website_match_factor(snapshot: ScoringSnapshot) -> ScoreFactor:
    pointer = snapshot.website_match_evidence
    if snapshot.website_match_conflict:
        return _factor(
            code=FactorCode.WEBSITE_MATCH,
            points=0,
            reason="website match evidence conflicts; verified website not assumed",
            evidence_field="organization.website_match_status",
            observed_value=_text(snapshot.website_match_status),
            status=FactorStatus.CONFLICTING,
            reason_code=ReasonCode.NEG_WEBSITE_CONFLICT,
            polarity=FactorPolarity.NEGATIVE,
            pointer=pointer,
        )
    status = _text(snapshot.website_match_status)
    if status is None:
        return _factor(
            code=FactorCode.WEBSITE_MATCH,
            points=0,
            reason="website match status missing; official website not inferred",
            evidence_field="organization.website_match_status",
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    normalized = status.lower()
    if normalized == WebsiteMatchStatus.VERIFIED.value:
        return _factor(
            code=FactorCode.WEBSITE_MATCH,
            points=POINTS_WEBSITE_VERIFIED,
            reason="official website match is verified against stored organization evidence",
            evidence_field="organization.website_match_status",
            observed_value=normalized,
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.POS_WEBSITE_VERIFIED,
            polarity=FactorPolarity.POSITIVE,
            pointer=pointer,
        )
    if normalized == WebsiteMatchStatus.AMBIGUOUS.value:
        return _factor(
            code=FactorCode.WEBSITE_MATCH,
            points=0,
            reason="website match is ambiguous; website facts are not used",
            evidence_field="organization.website_match_status",
            observed_value=normalized,
            status=FactorStatus.AMBIGUOUS,
            reason_code=ReasonCode.NEG_WEBSITE_AMBIGUOUS,
            polarity=FactorPolarity.NEGATIVE,
            pointer=pointer,
        )
    if normalized == WebsiteMatchStatus.NO_MATCH.value:
        return _factor(
            code=FactorCode.WEBSITE_MATCH,
            points=0,
            reason="no official website match; website facts are not used",
            evidence_field="organization.website_match_status",
            observed_value=normalized,
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.NEG_WEBSITE_NO_MATCH,
            polarity=FactorPolarity.NEGATIVE,
            pointer=pointer,
        )
    return _factor(
        code=FactorCode.WEBSITE_MATCH,
        points=0,
        reason="website match status is unrecognized; not assumed",
        evidence_field="organization.website_match_status",
        observed_value=normalized,
        status=FactorStatus.APPLIED,
        reason_code=ReasonCode.INFO_UNCLASSIFIED_SIGNAL,
        polarity=FactorPolarity.NEUTRAL,
        pointer=pointer,
    )


def _local_website_factor(snapshot: ScoringSnapshot) -> ScoreFactor:
    if snapshot.website_facts_eligible:
        return _factor(
            code=FactorCode.LOCAL_WEBSITE,
            points=0,
            reason="verified website match already accounted for; local website not double-counted",
            evidence_field="organization.website",
            observed_value=_usable_local_website(snapshot.website) or _text(snapshot.website),
            status=FactorStatus.NOT_APPLICABLE,
            reason_code=ReasonCode.INFO_NOT_APPLICABLE,
            polarity=FactorPolarity.NEUTRAL,
            pointer=snapshot.website_match_evidence,
        )
    usable = _usable_local_website(snapshot.website)
    raw = _text(snapshot.website)
    if raw is None:
        return _factor(
            code=FactorCode.LOCAL_WEBSITE,
            points=0,
            reason="website missing locally; not guessed from organization name",
            evidence_field="organization.website",
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    if usable is None:
        return _factor(
            code=FactorCode.LOCAL_WEBSITE,
            points=0,
            reason="website present but not a usable local URL; not fetched or inferred",
            evidence_field="organization.website",
            observed_value=raw,
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.INFO_UNCLASSIFIED_SIGNAL,
            polarity=FactorPolarity.NEUTRAL,
        )
    return _factor(
        code=FactorCode.LOCAL_WEBSITE,
        points=POINTS_WEBSITE_LOCAL,
        reason="website is present in local records and was not fetched",
        evidence_field="organization.website",
        observed_value=usable,
        status=FactorStatus.APPLIED,
        reason_code=ReasonCode.POS_LOCAL_WEBSITE,
        polarity=FactorPolarity.POSITIVE,
    )


def _skipped_website_fact(
    *,
    code: FactorCode,
    evidence_field: str,
    snapshot: ScoringSnapshot,
) -> ScoreFactor:
    match_status = _text(snapshot.website_match_status)
    if snapshot.website_match_conflict:
        reason = "website match conflicts; stored website facts are not scored"
        status = FactorStatus.CONFLICTING
        reason_code = ReasonCode.NEG_WEBSITE_CONFLICT
    elif match_status == WebsiteMatchStatus.AMBIGUOUS.value:
        reason = "website match is ambiguous; stored website facts are not scored"
        status = FactorStatus.AMBIGUOUS
        reason_code = ReasonCode.INFO_WEBSITE_FACTS_SKIPPED
    elif match_status == WebsiteMatchStatus.NO_MATCH.value:
        reason = "website match is no_match; stored website facts are not scored"
        status = FactorStatus.NOT_APPLICABLE
        reason_code = ReasonCode.INFO_WEBSITE_FACTS_SKIPPED
    else:
        reason = "website match is not verified; stored website facts are not scored"
        status = FactorStatus.NOT_APPLICABLE
        reason_code = ReasonCode.INFO_WEBSITE_FACTS_SKIPPED
    return _factor(
        code=code,
        points=0,
        reason=reason,
        evidence_field=evidence_field,
        observed_value=None,
        status=status,
        reason_code=reason_code,
        polarity=FactorPolarity.NEUTRAL,
        pointer=snapshot.website_match_evidence,
    )


def _ownership_factor(snapshot: ScoringSnapshot) -> ScoreFactor:
    field_name = "source_evidence.ownership_signal"
    if not snapshot.website_facts_eligible:
        return _skipped_website_fact(
            code=FactorCode.OWNERSHIP_SIGNAL,
            evidence_field=field_name,
            snapshot=snapshot,
        )
    if snapshot.ownership_conflict:
        return _factor(
            code=FactorCode.OWNERSHIP_SIGNAL,
            points=0,
            reason="ownership signals conflict; independence not assumed",
            evidence_field=field_name,
            observed_value=",".join(snapshot.ownership_evidence.conflicting_values)
            if snapshot.ownership_evidence
            else snapshot.ownership_value,
            status=FactorStatus.CONFLICTING,
            reason_code=ReasonCode.INFO_CONFLICTING_OWNERSHIP,
            polarity=FactorPolarity.NEUTRAL,
            pointer=snapshot.ownership_evidence,
        )
    text = _text(snapshot.ownership_value)
    if text is None:
        return _factor(
            code=FactorCode.OWNERSHIP_SIGNAL,
            points=0,
            reason="ownership signal missing; independence not inferred",
            evidence_field=field_name,
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    classified = classify_ownership(text)
    match classified:
        case OwnershipClass.INDEPENDENT:
            return _factor(
                code=FactorCode.OWNERSHIP_SIGNAL,
                points=POINTS_INDEPENDENT,
                reason="stored evidence states an independent or physician-owned practice",
                evidence_field=field_name,
                observed_value=text,
                status=FactorStatus.APPLIED,
                reason_code=ReasonCode.POS_INDEPENDENT_OWNERSHIP,
                polarity=FactorPolarity.POSITIVE,
                pointer=snapshot.ownership_evidence,
            )
        case OwnershipClass.LARGER_GROUP:
            return _factor(
                code=FactorCode.OWNERSHIP_SIGNAL,
                points=POINTS_LARGER_GROUP,
                reason="stored evidence states a larger-group or affiliated practice",
                evidence_field=field_name,
                observed_value=text,
                status=FactorStatus.APPLIED,
                reason_code=ReasonCode.NEG_LARGER_GROUP,
                polarity=FactorPolarity.NEGATIVE,
                pointer=snapshot.ownership_evidence,
            )
        case OwnershipClass.UNKNOWN:
            return _factor(
                code=FactorCode.OWNERSHIP_SIGNAL,
                points=0,
                reason="ownership signal present but unclassified; not assumed",
                evidence_field=field_name,
                observed_value=text,
                status=FactorStatus.APPLIED,
                reason_code=ReasonCode.INFO_UNCLASSIFIED_SIGNAL,
                polarity=FactorPolarity.NEUTRAL,
                pointer=snapshot.ownership_evidence,
            )
        case _:
            unreachable: Never = classified
            raise RuntimeError(f"unhandled ownership class: {unreachable}")


def _practice_size_factor(snapshot: ScoringSnapshot, size_count_conflict: bool) -> ScoreFactor:
    field_name = "source_evidence.practice_size_signal"
    if not snapshot.website_facts_eligible:
        return _skipped_website_fact(
            code=FactorCode.PRACTICE_SIZE_SIGNAL,
            evidence_field=field_name,
            snapshot=snapshot,
        )
    if snapshot.practice_size_conflict:
        return _factor(
            code=FactorCode.PRACTICE_SIZE_SIGNAL,
            points=0,
            reason="practice-size signals conflict; size not assumed",
            evidence_field=field_name,
            observed_value=",".join(snapshot.practice_size_evidence.conflicting_values)
            if snapshot.practice_size_evidence
            else snapshot.practice_size_value,
            status=FactorStatus.CONFLICTING,
            reason_code=ReasonCode.INFO_CONFLICTING_PRACTICE_SIZE,
            polarity=FactorPolarity.NEUTRAL,
            pointer=snapshot.practice_size_evidence,
        )
    if size_count_conflict:
        return _factor(
            code=FactorCode.PRACTICE_SIZE_SIGNAL,
            points=0,
            reason="practice-size and provider-count evidence conflict; size not assumed",
            evidence_field=field_name,
            observed_value=snapshot.practice_size_value,
            status=FactorStatus.CONFLICTING,
            reason_code=ReasonCode.INFO_CONFLICTING_SIZE_AND_COUNT,
            polarity=FactorPolarity.NEUTRAL,
            pointer=snapshot.practice_size_evidence,
        )
    text = _text(snapshot.practice_size_value)
    if text is None:
        return _factor(
            code=FactorCode.PRACTICE_SIZE_SIGNAL,
            points=0,
            reason="practice-size signal missing; size not inferred",
            evidence_field=field_name,
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    classified = classify_practice_size(text)
    match classified:
        case PracticeSizeClass.SMALL:
            return _factor(
                code=FactorCode.PRACTICE_SIZE_SIGNAL,
                points=POINTS_PRACTICE_SIZE_SMALL,
                reason="stored evidence supports a small or single-location practice",
                evidence_field=field_name,
                observed_value=text,
                status=FactorStatus.APPLIED,
                reason_code=ReasonCode.POS_SMALL_PRACTICE,
                polarity=FactorPolarity.POSITIVE,
                pointer=snapshot.practice_size_evidence,
            )
        case PracticeSizeClass.MODERATE:
            return _factor(
                code=FactorCode.PRACTICE_SIZE_SIGNAL,
                points=POINTS_PRACTICE_SIZE_MODERATE,
                reason="stored evidence supports a modest multi-location practice",
                evidence_field=field_name,
                observed_value=text,
                status=FactorStatus.APPLIED,
                reason_code=ReasonCode.POS_MODERATE_PRACTICE,
                polarity=FactorPolarity.POSITIVE,
                pointer=snapshot.practice_size_evidence,
            )
        case PracticeSizeClass.LARGE:
            return _factor(
                code=FactorCode.PRACTICE_SIZE_SIGNAL,
                points=POINTS_PRACTICE_SIZE_LARGE,
                reason="stored evidence supports a larger multi-location or medical group",
                evidence_field=field_name,
                observed_value=text,
                status=FactorStatus.APPLIED,
                reason_code=ReasonCode.NEG_LARGE_PRACTICE,
                polarity=FactorPolarity.NEGATIVE,
                pointer=snapshot.practice_size_evidence,
            )
        case PracticeSizeClass.UNKNOWN:
            return _factor(
                code=FactorCode.PRACTICE_SIZE_SIGNAL,
                points=0,
                reason="practice-size signal present but unclassified; not assumed",
                evidence_field=field_name,
                observed_value=text,
                status=FactorStatus.APPLIED,
                reason_code=ReasonCode.INFO_UNCLASSIFIED_SIGNAL,
                polarity=FactorPolarity.NEUTRAL,
                pointer=snapshot.practice_size_evidence,
            )
        case _:
            unreachable: Never = classified
            raise RuntimeError(f"unhandled practice size class: {unreachable}")


def _provider_count_factor(snapshot: ScoringSnapshot, size_count_conflict: bool) -> ScoreFactor:
    field_name = "source_evidence.provider_count"
    if not snapshot.website_facts_eligible:
        return _skipped_website_fact(
            code=FactorCode.PROVIDER_COUNT,
            evidence_field=field_name,
            snapshot=snapshot,
        )
    if snapshot.provider_count_conflict:
        return _factor(
            code=FactorCode.PROVIDER_COUNT,
            points=0,
            reason="provider-count signals conflict; count not assumed",
            evidence_field=field_name,
            observed_value=",".join(snapshot.provider_count_evidence.conflicting_values)
            if snapshot.provider_count_evidence
            else snapshot.provider_count_value,
            status=FactorStatus.CONFLICTING,
            reason_code=ReasonCode.INFO_CONFLICTING_PROVIDER_COUNT,
            polarity=FactorPolarity.NEUTRAL,
            pointer=snapshot.provider_count_evidence,
        )
    if size_count_conflict:
        return _factor(
            code=FactorCode.PROVIDER_COUNT,
            points=0,
            reason="practice-size and provider-count evidence conflict; count not assumed",
            evidence_field=field_name,
            observed_value=snapshot.provider_count_value,
            status=FactorStatus.CONFLICTING,
            reason_code=ReasonCode.INFO_CONFLICTING_SIZE_AND_COUNT,
            polarity=FactorPolarity.NEUTRAL,
            pointer=snapshot.provider_count_evidence,
        )
    text = _text(snapshot.provider_count_value)
    if text is None:
        return _factor(
            code=FactorCode.PROVIDER_COUNT,
            points=0,
            reason="provider count missing; size not inferred",
            evidence_field=field_name,
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    count = parse_provider_count(text)
    if count is None:
        return _factor(
            code=FactorCode.PROVIDER_COUNT,
            points=0,
            reason="provider count is not an explicit integer; not assumed",
            evidence_field=field_name,
            observed_value=text,
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.INFO_UNCLASSIFIED_SIGNAL,
            polarity=FactorPolarity.NEUTRAL,
            pointer=snapshot.provider_count_evidence,
        )
    classified = _provider_count_class(count)
    match classified:
        case PracticeSizeClass.SMALL:
            return _factor(
                code=FactorCode.PROVIDER_COUNT,
                points=POINTS_PROVIDER_COUNT_SMALL,
                reason="stored provider count is in the small independent-practice range",
                evidence_field=field_name,
                observed_value=str(count),
                status=FactorStatus.APPLIED,
                reason_code=ReasonCode.POS_PROVIDER_COUNT_ICP,
                polarity=FactorPolarity.POSITIVE,
                pointer=snapshot.provider_count_evidence,
            )
        case PracticeSizeClass.MODERATE:
            return _factor(
                code=FactorCode.PROVIDER_COUNT,
                points=POINTS_PROVIDER_COUNT_MODERATE,
                reason="stored provider count is in a modest independent-practice range",
                evidence_field=field_name,
                observed_value=str(count),
                status=FactorStatus.APPLIED,
                reason_code=ReasonCode.POS_PROVIDER_COUNT_ICP,
                polarity=FactorPolarity.POSITIVE,
                pointer=snapshot.provider_count_evidence,
            )
        case PracticeSizeClass.LARGE:
            return _factor(
                code=FactorCode.PROVIDER_COUNT,
                points=POINTS_PROVIDER_COUNT_LARGE,
                reason="stored provider count is above the conservative independent-practice range",
                evidence_field=field_name,
                observed_value=str(count),
                status=FactorStatus.APPLIED,
                reason_code=ReasonCode.NEG_LARGE_PROVIDER_COUNT,
                polarity=FactorPolarity.NEGATIVE,
                pointer=snapshot.provider_count_evidence,
            )
        case PracticeSizeClass.UNKNOWN:
            return _factor(
                code=FactorCode.PROVIDER_COUNT,
                points=0,
                reason="stored provider count is unclassified for ICP size; not assumed",
                evidence_field=field_name,
                observed_value=str(count),
                status=FactorStatus.APPLIED,
                reason_code=ReasonCode.INFO_UNCLASSIFIED_SIGNAL,
                polarity=FactorPolarity.NEUTRAL,
                pointer=snapshot.provider_count_evidence,
            )
        case _:
            unreachable: Never = classified
            raise RuntimeError(f"unhandled provider count class: {unreachable}")


def _billing_factor(snapshot: ScoringSnapshot) -> ScoreFactor:
    field_name = "source_evidence.billing_signal"
    if not snapshot.website_facts_eligible:
        return _skipped_website_fact(
            code=FactorCode.BILLING_SIGNAL,
            evidence_field=field_name,
            snapshot=snapshot,
        )
    if snapshot.billing_conflict:
        return _factor(
            code=FactorCode.BILLING_SIGNAL,
            points=0,
            reason="billing signals conflict; revenue-cycle facts not assumed",
            evidence_field=field_name,
            observed_value=",".join(snapshot.billing_evidence.conflicting_values)
            if snapshot.billing_evidence
            else snapshot.billing_value,
            status=FactorStatus.CONFLICTING,
            reason_code=ReasonCode.INFO_CONFLICTING_BILLING,
            polarity=FactorPolarity.NEUTRAL,
            pointer=snapshot.billing_evidence,
        )
    text = _text(snapshot.billing_value)
    if text is None:
        return _factor(
            code=FactorCode.BILLING_SIGNAL,
            points=0,
            reason="billing/revenue-cycle signal missing; not inferred",
            evidence_field=field_name,
            observed_value=None,
            status=FactorStatus.MISSING,
            reason_code=ReasonCode.INFO_MISSING,
            polarity=FactorPolarity.NEUTRAL,
        )
    normalized = text.lower()
    if normalized not in IN_HOUSE_BILLING_VALUES:
        return _factor(
            code=FactorCode.BILLING_SIGNAL,
            points=0,
            reason="billing signal present but not an explicit allowlisted RCM phrase; not assumed",
            evidence_field=field_name,
            observed_value=text,
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.INFO_UNCLASSIFIED_SIGNAL,
            polarity=FactorPolarity.NEUTRAL,
            pointer=snapshot.billing_evidence,
        )
    return _factor(
        code=FactorCode.BILLING_SIGNAL,
        points=POINTS_BILLING,
        reason="stored evidence explicitly states a billing or revenue-cycle signal",
        evidence_field=field_name,
        observed_value=text,
        status=FactorStatus.APPLIED,
        reason_code=ReasonCode.POS_BILLING_SIGNAL,
        polarity=FactorPolarity.POSITIVE,
        pointer=snapshot.billing_evidence,
    )


def _business_phone_factor(snapshot: ScoringSnapshot) -> ScoreFactor:
    website_phone = _text(snapshot.business_phone) if snapshot.website_facts_eligible else None
    contact_phone = snapshot.has_contact_phone
    if website_phone is not None:
        return _factor(
            code=FactorCode.BUSINESS_PHONE,
            points=POINTS_BUSINESS_PHONE,
            reason="public business phone is already stored from verified website evidence",
            evidence_field="source_evidence.business_phone",
            observed_value=website_phone,
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.POS_BUSINESS_PHONE,
            polarity=FactorPolarity.POSITIVE,
            pointer=snapshot.business_phone_evidence,
        )
    if contact_phone:
        return _factor(
            code=FactorCode.BUSINESS_PHONE,
            points=POINTS_BUSINESS_PHONE,
            reason="business phone is already stored on a local contact record",
            evidence_field="contact.phone",
            observed_value="stored",
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.POS_BUSINESS_PHONE,
            polarity=FactorPolarity.POSITIVE,
            pointer=snapshot.decision_maker_evidence,
        )
    if not snapshot.website_facts_eligible and _text(snapshot.business_phone) is not None:
        return _skipped_website_fact(
            code=FactorCode.BUSINESS_PHONE,
            evidence_field="source_evidence.business_phone",
            snapshot=snapshot,
        )
    return _factor(
        code=FactorCode.BUSINESS_PHONE,
        points=0,
        reason="public business phone missing; not inferred",
        evidence_field="source_evidence.business_phone",
        observed_value=None,
        status=FactorStatus.MISSING,
        reason_code=ReasonCode.INFO_MISSING,
        polarity=FactorPolarity.NEUTRAL,
    )


def _business_email_factor(snapshot: ScoringSnapshot) -> ScoreFactor:
    website_email = _text(snapshot.business_email) if snapshot.website_facts_eligible else None
    if website_email is not None:
        return _factor(
            code=FactorCode.BUSINESS_EMAIL,
            points=POINTS_BUSINESS_EMAIL,
            reason="public business email is already stored from verified website evidence",
            evidence_field="source_evidence.business_email",
            observed_value=website_email,
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.POS_BUSINESS_EMAIL,
            polarity=FactorPolarity.POSITIVE,
            pointer=snapshot.business_email_evidence,
        )
    if snapshot.has_contact_email:
        return _factor(
            code=FactorCode.BUSINESS_EMAIL,
            points=0,
            reason=(
                "contact email is stored but website business email is absent; not counted twice"
            ),
            evidence_field="source_evidence.business_email",
            observed_value=None,
            status=FactorStatus.NOT_APPLICABLE,
            reason_code=ReasonCode.INFO_NOT_APPLICABLE,
            polarity=FactorPolarity.NEUTRAL,
        )
    if not snapshot.website_facts_eligible and _text(snapshot.business_email) is not None:
        return _skipped_website_fact(
            code=FactorCode.BUSINESS_EMAIL,
            evidence_field="source_evidence.business_email",
            snapshot=snapshot,
        )
    return _factor(
        code=FactorCode.BUSINESS_EMAIL,
        points=0,
        reason="public business email missing; not inferred",
        evidence_field="source_evidence.business_email",
        observed_value=None,
        status=FactorStatus.MISSING,
        reason_code=ReasonCode.INFO_MISSING,
        polarity=FactorPolarity.NEUTRAL,
    )


def _decision_maker_factor(snapshot: ScoringSnapshot) -> ScoreFactor:
    role = _text(snapshot.decision_maker_role)
    title = _text(snapshot.decision_maker_title)
    if role is not None and role in RANKED_DECISION_MAKER_ROLES:
        return _factor(
            code=FactorCode.DECISION_MAKER_TITLE,
            points=POINTS_DECISION_MAKER,
            reason="stored contact has a ranked decision-maker role category",
            evidence_field="contact.role_category",
            observed_value=role,
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.POS_DECISION_MAKER,
            polarity=FactorPolarity.POSITIVE,
            pointer=snapshot.decision_maker_evidence,
        )
    if title is not None:
        return _factor(
            code=FactorCode.DECISION_MAKER_TITLE,
            points=POINTS_DECISION_MAKER,
            reason="stored contact title matches a local decision-maker phrase",
            evidence_field="contact.title",
            observed_value=title,
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.POS_DECISION_MAKER,
            polarity=FactorPolarity.POSITIVE,
            pointer=snapshot.decision_maker_evidence,
        )
    return _factor(
        code=FactorCode.DECISION_MAKER_TITLE,
        points=0,
        reason="decision-maker title missing; not inferred",
        evidence_field="contact.title",
        observed_value=None,
        status=FactorStatus.MISSING,
        reason_code=ReasonCode.INFO_MISSING,
        polarity=FactorPolarity.NEUTRAL,
    )


def _verified_email_factor(snapshot: ScoringSnapshot) -> ScoreFactor:
    if snapshot.verified_email:
        return _factor(
            code=FactorCode.VERIFIED_EMAIL,
            points=POINTS_VERIFIED_EMAIL,
            reason="a locally stored contact email is marked verified",
            evidence_field="contact.email_verified",
            observed_value="true",
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.POS_VERIFIED_CONTACT_EMAIL,
            polarity=FactorPolarity.POSITIVE,
            pointer=snapshot.verified_email_evidence,
        )
    if snapshot.has_contact_email:
        return _factor(
            code=FactorCode.VERIFIED_EMAIL,
            points=0,
            reason="contact email present but not verified; not counted",
            evidence_field="contact.email_verified",
            observed_value="false",
            status=FactorStatus.APPLIED,
            reason_code=ReasonCode.INFO_UNVERIFIED_EMAIL,
            polarity=FactorPolarity.NEUTRAL,
            pointer=snapshot.verified_email_evidence or snapshot.decision_maker_evidence,
        )
    return _factor(
        code=FactorCode.VERIFIED_EMAIL,
        points=0,
        reason="verified contact email missing; not inferred",
        evidence_field="contact.email_verified",
        observed_value=None,
        status=FactorStatus.MISSING,
        reason_code=ReasonCode.INFO_MISSING,
        polarity=FactorPolarity.NEUTRAL,
    )


def _excluded_name_factor(name: str | None) -> ScoreFactor:
    text = _text(name)
    if text is None:
        return _factor(
            code=FactorCode.EXCLUDED_ORGANIZATION_NAME,
            points=0,
            reason="organization name missing; exclusion not inferred",
            evidence_field="organization.name",
            observed_value=None,
            status=FactorStatus.NOT_APPLICABLE,
            reason_code=ReasonCode.INFO_NOT_APPLICABLE,
            polarity=FactorPolarity.NEUTRAL,
        )
    matched = _contains_phrase(text, EXCLUDED_NAME_PHRASES)
    if matched is None:
        return _factor(
            code=FactorCode.EXCLUDED_ORGANIZATION_NAME,
            points=0,
            reason="organization name is not on the conservative exclusion list",
            evidence_field="organization.name",
            observed_value=text,
            status=FactorStatus.NOT_APPLICABLE,
            reason_code=ReasonCode.INFO_NOT_APPLICABLE,
            polarity=FactorPolarity.NEUTRAL,
        )
    return _factor(
        code=FactorCode.EXCLUDED_ORGANIZATION_NAME,
        points=POINTS_EXCLUDED_NAME,
        reason=f"organization name contains excluded phrase '{matched}'",
        evidence_field="organization.name",
        observed_value=text,
        status=FactorStatus.APPLIED,
        reason_code=ReasonCode.NEG_EXCLUDED_NAME,
        polarity=FactorPolarity.NEGATIVE,
    )


def snapshot_from_records(
    organization: Organization,
    evidence_rows: Sequence[SourceEvidence],
    contacts: Sequence[Contact],
) -> ScoringSnapshot:
    nppes_pointer, nppes_status = _nppes_evidence_fields(evidence_rows)
    grouped = _group_evidence(evidence_rows)
    match_latest, match_values = _latest_and_values(
        grouped.get(WebsiteFactType.WEBSITE_MATCH.value, ())
    )
    org_match = _text(organization.website_match_status)
    evidence_match = _text(match_latest.extracted_value) if match_latest is not None else None
    match_conflict = _website_match_conflict(org_match, match_values)
    match_status = org_match or (evidence_match.lower() if evidence_match else None)
    if match_status is not None:
        match_status = match_status.lower()
    website_facts_eligible = (
        not match_conflict and match_status == WebsiteMatchStatus.VERIFIED.value
    )

    ownership_latest, ownership_values = _latest_and_values(
        grouped.get(WebsiteFactType.OWNERSHIP_SIGNAL.value, ())
    )
    size_latest, size_values = _latest_and_values(
        grouped.get(WebsiteFactType.PRACTICE_SIZE_SIGNAL.value, ())
    )
    count_latest, count_values = _latest_and_values(
        grouped.get(WebsiteFactType.PROVIDER_COUNT.value, ())
    )
    billing_latest, billing_values = _latest_and_values(
        grouped.get(WebsiteFactType.BILLING_SIGNAL.value, ())
    )
    phone_latest, phone_values = _latest_and_values(
        grouped.get(WebsiteFactType.BUSINESS_PHONE.value, ())
    )
    email_latest, email_values = _latest_and_values(
        grouped.get(WebsiteFactType.BUSINESS_EMAIL.value, ())
    )
    official_latest, _official_values = _latest_and_values(
        grouped.get(WebsiteFactType.OFFICIAL_WEBSITE.value, ())
    )
    decision_contact, decision_pointer = _decision_maker_from_records(contacts, evidence_rows)
    verified_contact = next((contact for contact in contacts if contact.email_verified), None)
    verified_pointer = (
        _contact_evidence_pointer(verified_contact, evidence_rows)
        if verified_contact is not None
        else decision_pointer
    )
    return ScoringSnapshot(
        organization_name=_text(organization.name),
        npi=_text(organization.npi),
        city=_text(organization.city),
        state=_text(organization.state),
        specialty=_text(organization.specialty),
        website=_text(organization.website),
        nppes_status=nppes_status,
        has_nppes_evidence=nppes_pointer is not None,
        nppes_source_url=nppes_pointer.source_url if nppes_pointer is not None else None,
        nppes_evidence=nppes_pointer,
        verified_email=any(contact.email_verified for contact in contacts),
        has_contact_email=any(_text(contact.email) is not None for contact in contacts),
        has_contact_phone=any(_text(contact.phone) is not None for contact in contacts),
        decision_maker_title=(
            _text(decision_contact.title) if decision_contact is not None else None
        ),
        decision_maker_role=(
            _text(decision_contact.role_category) if decision_contact is not None else None
        ),
        decision_maker_evidence=decision_pointer,
        verified_email_evidence=verified_pointer,
        website_match_status=match_status,
        website_match_conflict=match_conflict,
        website_match_evidence=_pointer_from_row(match_latest, match_values),
        official_website=(
            _text(official_latest.extracted_value) if official_latest is not None else None
        ),
        website_facts_eligible=website_facts_eligible,
        ownership_value=_selected_value(ownership_latest, ownership_values),
        ownership_conflict=len(ownership_values) > 1,
        ownership_evidence=_pointer_from_row(ownership_latest, ownership_values),
        practice_size_value=_selected_value(size_latest, size_values),
        practice_size_conflict=len(size_values) > 1,
        practice_size_evidence=_pointer_from_row(size_latest, size_values),
        provider_count_value=_selected_value(count_latest, count_values),
        provider_count_conflict=len(count_values) > 1,
        provider_count_evidence=_pointer_from_row(count_latest, count_values),
        billing_value=_selected_value(billing_latest, billing_values),
        billing_conflict=len(billing_values) > 1,
        billing_evidence=_pointer_from_row(billing_latest, billing_values),
        business_phone=_selected_value(phone_latest, phone_values),
        business_phone_evidence=_pointer_from_row(phone_latest, phone_values),
        business_email=_selected_value(email_latest, email_values),
        business_email_evidence=_pointer_from_row(email_latest, email_values),
    )


def _website_match_conflict(org_match: str | None, evidence_values: tuple[str, ...]) -> bool:
    if len(evidence_values) > 1:
        return True
    if org_match is None or not evidence_values:
        return False
    return org_match.lower() not in {value.lower() for value in evidence_values}


def _selected_value(row: SourceEvidence | None, values: tuple[str, ...]) -> str | None:
    if len(values) > 1:
        return None
    if row is None:
        return None
    return _text(row.extracted_value)


def _group_evidence(rows: Sequence[SourceEvidence]) -> dict[str, list[SourceEvidence]]:
    grouped: dict[str, list[SourceEvidence]] = {}
    for row in rows:
        grouped.setdefault(row.claim_type, []).append(row)
    return grouped


def _latest_and_values(
    rows: Sequence[SourceEvidence],
) -> tuple[SourceEvidence | None, tuple[str, ...]]:
    if not rows:
        return None, ()
    latest = max(rows, key=_evidence_sort_key)
    unique: list[str] = []
    seen: set[str] = set()
    for row in rows:
        value = _text(row.extracted_value)
        if value is None:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return latest, tuple(unique)


def _evidence_sort_key(row: SourceEvidence) -> tuple[bool, object, str]:
    return (row.created_at is not None, row.created_at or 0, str(row.id))


def _pointer_from_row(
    row: SourceEvidence | None,
    conflicting_values: tuple[str, ...] = (),
) -> EvidencePointer | None:
    if row is None:
        return None
    return EvidencePointer(
        evidence_id=str(row.id),
        source_url=_text(row.source_url),
        claim_type=_text(row.claim_type),
        extracted_value=_text(row.extracted_value),
        conflicting_values=conflicting_values if len(conflicting_values) > 1 else (),
    )


def _nppes_evidence_fields(
    evidence_rows: Sequence[SourceEvidence],
) -> tuple[EvidencePointer | None, str | None]:
    nppes_rows = [row for row in evidence_rows if row.claim_type == NPPES_CLAIM_TYPE]
    if not nppes_rows:
        return None, None
    latest = max(nppes_rows, key=_evidence_sort_key)
    metadata = latest.metadata_json if isinstance(latest.metadata_json, dict) else {}
    business = metadata.get("business_record")
    business_record = business if isinstance(business, dict) else {}
    status = _text(business_record.get("status"))
    pointer = EvidencePointer(
        evidence_id=str(latest.id),
        source_url=_text(latest.source_url),
        claim_type=_text(latest.claim_type),
        extracted_value=_text(latest.extracted_value),
    )
    return pointer, status.upper() if status is not None else None


def _decision_maker_from_records(
    contacts: Sequence[Contact],
    evidence_rows: Sequence[SourceEvidence],
) -> tuple[Contact | None, EvidencePointer | None]:
    ranked = [
        contact
        for contact in contacts
        if _text(contact.role_category) in RANKED_DECISION_MAKER_ROLES
    ]
    if ranked:
        ranked.sort(key=lambda contact: (contact.role_rank is None, contact.role_rank or 99))
        chosen = ranked[0]
        return chosen, _contact_evidence_pointer(chosen, evidence_rows)
    for contact in contacts:
        title = _text(contact.title)
        if title is None:
            continue
        if _contains_phrase(title, DECISION_MAKER_TITLE_PHRASES) is not None:
            return contact, _contact_evidence_pointer(contact, evidence_rows)
    return None, None


def _contact_evidence_pointer(
    contact: Contact | None,
    evidence_rows: Sequence[SourceEvidence],
) -> EvidencePointer | None:
    if contact is None:
        return None
    contact_rows = [
        row
        for row in evidence_rows
        if row.contact_id == contact.id
        and row.claim_type == ContactFactType.DECISION_MAKER_CONTACT.value
    ]
    if not contact_rows:
        return None
    latest = max(contact_rows, key=_evidence_sort_key)
    return _pointer_from_row(latest)


class LeadScoringService:
    """Deterministic local-only ICP scorer. Does not call providers or send outbound actions."""

    def score_lead(
        self,
        db: Session,
        lead_id: UUID,
        *,
        commit: bool = True,
    ) -> PersistedScoreResult:
        lead = db.get(Lead, lead_id)
        if lead is None:
            raise LeadScoringError(f"Lead not found: {lead_id}")
        organization = db.get(Organization, lead.organization_id)
        if organization is None:
            raise LeadScoringError(f"Organization not found for lead: {lead_id}")
        return self._persist(
            db,
            lead=lead,
            organization=organization,
            lead_created=False,
            commit=commit,
        )

    def score_organization(
        self,
        db: Session,
        organization_id: UUID,
        *,
        commit: bool = True,
    ) -> PersistedScoreResult:
        organization = db.get(Organization, organization_id)
        if organization is None:
            raise LeadScoringError(f"Organization not found: {organization_id}")
        lead, created = self._existing_or_create_lead(db, organization)
        return self._persist(
            db,
            lead=lead,
            organization=organization,
            lead_created=created,
            commit=commit,
        )

    def score_batch(
        self,
        db: Session,
        *,
        limit: int = 100,
    ) -> tuple[PersistedScoreResult, ...]:
        if limit < 1:
            raise LeadScoringError("limit must be >= 1")
        run_limit = min(limit, BATCH_MAX)
        organizations = db.scalars(
            select(Organization).order_by(Organization.created_at, Organization.id).limit(run_limit)
        ).all()
        results = tuple(
            self.score_organization(db, organization.id, commit=False)
            for organization in organizations
        )
        db.commit()
        return results

    def _existing_or_create_lead(
        self,
        db: Session,
        organization: Organization,
    ) -> tuple[Lead, bool]:
        lead = db.scalar(
            select(Lead)
            .where(Lead.organization_id == organization.id)
            .order_by(Lead.created_at.desc(), Lead.id.desc())
        )
        if lead is not None:
            return lead, False

        evidence_rows = db.scalars(
            select(SourceEvidence).where(SourceEvidence.organization_id == organization.id)
        ).all()
        has_nppes, _status = _nppes_evidence_fields(evidence_rows)
        lead = Lead(
            organization_id=organization.id,
            stage=LeadStage.DISCOVERED.value,
            source="nppes" if has_nppes is not None else "local",
        )
        db.add(lead)
        db.flush()
        return lead, True

    def _persist(
        self,
        db: Session,
        *,
        lead: Lead,
        organization: Organization,
        lead_created: bool,
        commit: bool,
    ) -> PersistedScoreResult:
        evidence_rows = db.scalars(
            select(SourceEvidence).where(SourceEvidence.organization_id == organization.id)
        ).all()
        contacts = db.scalars(
            select(Contact).where(Contact.organization_id == organization.id)
        ).all()
        scoring = score_snapshot(snapshot_from_records(organization, evidence_rows, contacts))
        rationale = scoring.to_rationale()
        existing = self._latest_score(db, lead.id)
        if existing is not None and _same_score(existing, rationale):
            if commit:
                db.commit()
            logger.info(
                "lead_score_unchanged",
                lead_id=str(lead.id),
                organization_id=str(organization.id),
                score=scoring.total,
                band=scoring.band.value,
                model_version=scoring.model_version,
            )
            return PersistedScoreResult(
                lead_id=lead.id,
                organization_id=organization.id,
                lead_score_id=existing.id,
                lead_created=lead_created,
                scoring=scoring,
                reused_existing_score=True,
            )

        lead_score = LeadScore(
            lead_id=lead.id,
            score=scoring.total,
            model_version=scoring.model_version,
            rationale=rationale,
        )
        db.add(lead_score)
        db.add(
            Activity(
                lead_id=lead.id,
                actor=LEAD_SCORING_ACTOR,
                action=LEAD_SCORED_ACTION,
                details={
                    "lead_id": str(lead.id),
                    "organization_id": str(organization.id),
                    "score": scoring.total,
                    "band": scoring.band.value,
                    "model_version": scoring.model_version,
                    "lead_created": lead_created,
                    "reason_codes": list(scoring.reason_codes),
                    "disqualification_codes": list(scoring.disqualification_codes),
                    "research_reasons": list(scoring.research_reasons),
                    "factor_codes": [factor.code.value for factor in scoring.factors],
                    "fabricated_facts": False,
                    "external_providers_called": [],
                    "outbound_messages_created": 0,
                },
            )
        )
        db.flush()
        if commit:
            db.commit()
        logger.info(
            "lead_scored",
            lead_id=str(lead.id),
            organization_id=str(organization.id),
            score=scoring.total,
            band=scoring.band.value,
            model_version=scoring.model_version,
        )
        return PersistedScoreResult(
            lead_id=lead.id,
            organization_id=organization.id,
            lead_score_id=lead_score.id,
            lead_created=lead_created,
            scoring=scoring,
            reused_existing_score=False,
        )

    def _latest_score(self, db: Session, lead_id: UUID) -> LeadScore | None:
        return db.scalar(
            select(LeadScore)
            .where(LeadScore.lead_id == lead_id, LeadScore.model_version == MODEL_VERSION)
            .order_by(LeadScore.created_at.desc(), LeadScore.id.desc())
        )


def canonical_rationale_digest(rationale: object) -> str:
    """Stable JSON digest of a scoring rationale for idempotent reuse checks."""
    return json.dumps(rationale, sort_keys=True, separators=(",", ":"), default=str)


def _same_score(existing: LeadScore, rationale: dict[str, object]) -> bool:
    stored = existing.rationale if isinstance(existing.rationale, dict) else {}
    return canonical_rationale_digest(stored) == canonical_rationale_digest(rationale)
