from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Never
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.domain import LeadStage
from vyro_growth.models import Activity, Contact, Lead, LeadScore, Organization, SourceEvidence

logger = structlog.get_logger(__name__)

MODEL_VERSION = "deterministic-v1"
SCORE_MIN = 0
SCORE_MAX = 100
BATCH_MAX = 500
NPPES_CLAIM_TYPE = "nppes_organization_record"
LEAD_SCORING_ACTOR = "lead_scoring"
LEAD_SCORED_ACTION = "lead_scored"
NPPES_ACTIVE_STATUS = "A"

POINTS_NAME = 5
POINTS_NPI = 20
POINTS_STATE = 15
POINTS_CITY = 10
POINTS_SPECIALTY_PRESENT = 8
POINTS_SPECIALTY_TARGET = 15
POINTS_SPECIALTY_EXCLUDED = -10
POINTS_NPPES_ACTIVE = 10
POINTS_NPPES_EVIDENCE = 12
POINTS_WEBSITE = 5
POINTS_VERIFIED_EMAIL = 5
POINTS_DECISION_MAKER_TITLE = 5
POINTS_EXCLUDED_NAME = -15

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
    }
)


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
    LOCAL_WEBSITE = "local_website"
    VERIFIED_EMAIL = "verified_email"
    DECISION_MAKER_TITLE = "decision_maker_title"
    EXCLUDED_ORGANIZATION_NAME = "excluded_organization_name"


class FactorStatus(StrEnum):
    APPLIED = "applied"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


class SpecialtyFit(StrEnum):
    TARGET = "target"
    UNKNOWN = "unknown"
    EXCLUDED = "excluded"


class ScoreBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ScoringSnapshot:
    organization_name: str | None
    npi: str | None
    city: str | None
    state: str | None
    specialty: str | None
    website: str | None
    nppes_status: str | None
    has_nppes_evidence: bool
    nppes_source_url: str | None
    verified_email: bool
    has_contact_email: bool
    decision_maker_title: str | None


@dataclass(frozen=True)
class ScoreFactor:
    code: FactorCode
    points: int
    reason: str
    evidence_field: str
    observed_value: str | None
    status: FactorStatus

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "points": self.points,
            "reason": self.reason,
            "evidence_field": self.evidence_field,
            "observed_value": self.observed_value,
            "status": self.status.value,
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

    def to_rationale(self) -> dict[str, object]:
        return {
            "model_version": self.model_version,
            "total": self.total,
            "band": self.band.value,
            "factors": [factor.to_dict() for factor in self.factors],
            "missing_fields": list(self.missing_fields),
            "used_fields": list(self.used_fields),
            "fabricated_facts": self.fabricated_facts,
            "external_providers_called": list(self.external_providers_called),
            "policy": {
                "no_outbound": True,
                "local_data_only": True,
                "unknown_not_inferred": True,
            },
        }


@dataclass(frozen=True)
class PersistedScoreResult:
    lead_id: UUID
    organization_id: UUID
    lead_score_id: UUID
    lead_created: bool
    scoring: ScoringResult


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


def band_for_score(total: int) -> ScoreBand:
    if total >= 70:
        return ScoreBand.HIGH
    if total >= 40:
        return ScoreBand.MEDIUM
    return ScoreBand.LOW


def _specialty_fit_points(fit: SpecialtyFit) -> tuple[int, str]:
    match fit:
        case SpecialtyFit.TARGET:
            return (
                POINTS_SPECIALTY_TARGET,
                "specialty matches independent US medical practice target list",
            )
        case SpecialtyFit.EXCLUDED:
            return (
                POINTS_SPECIALTY_EXCLUDED,
                "specialty is outside the conservative medical billing ICP",
            )
        case SpecialtyFit.UNKNOWN:
            return (0, "specialty fit unknown; not assumed")
        case _:
            unreachable: Never = fit
            raise RuntimeError(f"unhandled specialty fit: {unreachable}")


def _usable_local_website(value: str | None) -> str | None:
    text = _text(value)
    if text is None or " " in text or "." not in text:
        return None
    return text


def score_snapshot(snapshot: ScoringSnapshot) -> ScoringResult:
    factors = (
        _name_factor(snapshot.organization_name),
        _npi_factor(snapshot.npi),
        _state_factor(snapshot.state),
        _city_factor(snapshot.city),
        _specialty_present_factor(snapshot.specialty),
        _specialty_fit_factor(snapshot.specialty),
        _nppes_active_factor(snapshot.nppes_status, snapshot.has_nppes_evidence),
        _nppes_evidence_factor(snapshot.has_nppes_evidence, snapshot.nppes_source_url),
        _website_factor(snapshot.website),
        _verified_email_factor(snapshot.verified_email, snapshot.has_contact_email),
        _decision_maker_factor(snapshot.decision_maker_title),
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
    return ScoringResult(
        total=total,
        model_version=MODEL_VERSION,
        band=band_for_score(total),
        factors=factors,
        missing_fields=missing_fields,
        used_fields=used_fields,
        fabricated_facts=False,
        external_providers_called=(),
    )


def _name_factor(name: str | None) -> ScoreFactor:
    text = _text(name)
    if text is None:
        return ScoreFactor(
            code=FactorCode.ORGANIZATION_NAME,
            points=0,
            reason="organization name missing; not inferred",
            evidence_field="organization.name",
            observed_value=None,
            status=FactorStatus.MISSING,
        )
    return ScoreFactor(
        code=FactorCode.ORGANIZATION_NAME,
        points=POINTS_NAME,
        reason="organization name is present in local records",
        evidence_field="organization.name",
        observed_value=text,
        status=FactorStatus.APPLIED,
    )


def _npi_factor(npi: str | None) -> ScoreFactor:
    text = _text(npi)
    if text is None:
        return ScoreFactor(
            code=FactorCode.NPI_IDENTITY,
            points=0,
            reason="npi missing; identity not inferred",
            evidence_field="organization.npi",
            observed_value=None,
            status=FactorStatus.MISSING,
        )
    if not npi_checksum_valid(text):
        return ScoreFactor(
            code=FactorCode.NPI_IDENTITY,
            points=0,
            reason="npi failed checksum; not treated as identity evidence",
            evidence_field="organization.npi",
            observed_value=text,
            status=FactorStatus.APPLIED,
        )
    return ScoreFactor(
        code=FactorCode.NPI_IDENTITY,
        points=POINTS_NPI,
        reason="npi is present and checksum-valid",
        evidence_field="organization.npi",
        observed_value=text,
        status=FactorStatus.APPLIED,
    )


def _state_factor(state: str | None) -> ScoreFactor:
    text = _text(state)
    if text is None:
        return ScoreFactor(
            code=FactorCode.US_STATE,
            points=0,
            reason="state missing; US location not inferred",
            evidence_field="organization.state",
            observed_value=None,
            status=FactorStatus.MISSING,
        )
    normalized = text.upper()
    if normalized not in US_STATE_CODES:
        return ScoreFactor(
            code=FactorCode.US_STATE,
            points=0,
            reason="state is not a recognized US jurisdiction; not assumed",
            evidence_field="organization.state",
            observed_value=normalized,
            status=FactorStatus.APPLIED,
        )
    return ScoreFactor(
        code=FactorCode.US_STATE,
        points=POINTS_STATE,
        reason="state is a recognized US jurisdiction",
        evidence_field="organization.state",
        observed_value=normalized,
        status=FactorStatus.APPLIED,
    )


def _city_factor(city: str | None) -> ScoreFactor:
    text = _text(city)
    if text is None:
        return ScoreFactor(
            code=FactorCode.CITY,
            points=0,
            reason="city missing; not inferred",
            evidence_field="organization.city",
            observed_value=None,
            status=FactorStatus.MISSING,
        )
    return ScoreFactor(
        code=FactorCode.CITY,
        points=POINTS_CITY,
        reason="city is present in local records",
        evidence_field="organization.city",
        observed_value=text,
        status=FactorStatus.APPLIED,
    )


def _specialty_present_factor(specialty: str | None) -> ScoreFactor:
    text = _text(specialty)
    if text is None:
        return ScoreFactor(
            code=FactorCode.SPECIALTY_PRESENT,
            points=0,
            reason="specialty missing; not inferred",
            evidence_field="organization.specialty",
            observed_value=None,
            status=FactorStatus.MISSING,
        )
    return ScoreFactor(
        code=FactorCode.SPECIALTY_PRESENT,
        points=POINTS_SPECIALTY_PRESENT,
        reason="specialty is present in local records",
        evidence_field="organization.specialty",
        observed_value=text,
        status=FactorStatus.APPLIED,
    )


def _specialty_fit_factor(specialty: str | None) -> ScoreFactor:
    text = _text(specialty)
    if text is None:
        return ScoreFactor(
            code=FactorCode.SPECIALTY_FIT,
            points=0,
            reason="specialty missing; fit not inferred",
            evidence_field="organization.specialty",
            observed_value=None,
            status=FactorStatus.MISSING,
        )
    fit = classify_specialty(text)
    points, reason = _specialty_fit_points(fit)
    return ScoreFactor(
        code=FactorCode.SPECIALTY_FIT,
        points=points,
        reason=reason,
        evidence_field="organization.specialty",
        observed_value=text,
        status=FactorStatus.APPLIED,
    )


def _nppes_active_factor(status: str | None, has_evidence: bool) -> ScoreFactor:
    if not has_evidence:
        return ScoreFactor(
            code=FactorCode.NPPES_ACTIVE_STATUS,
            points=0,
            reason="nppes status missing; active status not assumed",
            evidence_field="source_evidence.metadata_json.business_record.status",
            observed_value=None,
            status=FactorStatus.MISSING,
        )
    text = _text(status)
    if text is None:
        return ScoreFactor(
            code=FactorCode.NPPES_ACTIVE_STATUS,
            points=0,
            reason="nppes evidence present but status missing; active status not assumed",
            evidence_field="source_evidence.metadata_json.business_record.status",
            observed_value=None,
            status=FactorStatus.MISSING,
        )
    normalized = text.upper()
    if normalized != NPPES_ACTIVE_STATUS:
        return ScoreFactor(
            code=FactorCode.NPPES_ACTIVE_STATUS,
            points=0,
            reason="nppes status is not active; not assumed eligible",
            evidence_field="source_evidence.metadata_json.business_record.status",
            observed_value=normalized,
            status=FactorStatus.APPLIED,
        )
    return ScoreFactor(
        code=FactorCode.NPPES_ACTIVE_STATUS,
        points=POINTS_NPPES_ACTIVE,
        reason="nppes business record status is active",
        evidence_field="source_evidence.metadata_json.business_record.status",
        observed_value=normalized,
        status=FactorStatus.APPLIED,
    )


def _nppes_evidence_factor(has_evidence: bool, source_url: str | None) -> ScoreFactor:
    if not has_evidence:
        return ScoreFactor(
            code=FactorCode.NPPES_SOURCE_EVIDENCE,
            points=0,
            reason="nppes source evidence missing; provenance not inferred",
            evidence_field="source_evidence.source_url",
            observed_value=None,
            status=FactorStatus.MISSING,
        )
    return ScoreFactor(
        code=FactorCode.NPPES_SOURCE_EVIDENCE,
        points=POINTS_NPPES_EVIDENCE,
        reason="nppes organization evidence is stored locally",
        evidence_field="source_evidence.source_url",
        observed_value=_text(source_url),
        status=FactorStatus.APPLIED,
    )


def _website_factor(website: str | None) -> ScoreFactor:
    usable = _usable_local_website(website)
    raw = _text(website)
    if raw is None:
        return ScoreFactor(
            code=FactorCode.LOCAL_WEBSITE,
            points=0,
            reason="website missing locally; not guessed from organization name",
            evidence_field="organization.website",
            observed_value=None,
            status=FactorStatus.MISSING,
        )
    if usable is None:
        return ScoreFactor(
            code=FactorCode.LOCAL_WEBSITE,
            points=0,
            reason="website present but not a usable local URL; not fetched or inferred",
            evidence_field="organization.website",
            observed_value=raw,
            status=FactorStatus.APPLIED,
        )
    return ScoreFactor(
        code=FactorCode.LOCAL_WEBSITE,
        points=POINTS_WEBSITE,
        reason="website is present in local records and was not fetched",
        evidence_field="organization.website",
        observed_value=usable,
        status=FactorStatus.APPLIED,
    )


def _verified_email_factor(verified_email: bool, has_contact_email: bool) -> ScoreFactor:
    if verified_email:
        return ScoreFactor(
            code=FactorCode.VERIFIED_EMAIL,
            points=POINTS_VERIFIED_EMAIL,
            reason="a locally stored contact email is marked verified",
            evidence_field="contact.email_verified",
            observed_value="true",
            status=FactorStatus.APPLIED,
        )
    if has_contact_email:
        return ScoreFactor(
            code=FactorCode.VERIFIED_EMAIL,
            points=0,
            reason="contact email present but not verified; not counted",
            evidence_field="contact.email_verified",
            observed_value="false",
            status=FactorStatus.APPLIED,
        )
    return ScoreFactor(
        code=FactorCode.VERIFIED_EMAIL,
        points=0,
        reason="verified contact email missing; not inferred",
        evidence_field="contact.email_verified",
        observed_value=None,
        status=FactorStatus.MISSING,
    )


def _decision_maker_factor(title: str | None) -> ScoreFactor:
    text = _text(title)
    if text is None:
        return ScoreFactor(
            code=FactorCode.DECISION_MAKER_TITLE,
            points=0,
            reason="decision-maker title missing; not inferred",
            evidence_field="contact.title",
            observed_value=None,
            status=FactorStatus.MISSING,
        )
    return ScoreFactor(
        code=FactorCode.DECISION_MAKER_TITLE,
        points=POINTS_DECISION_MAKER_TITLE,
        reason="stored contact title matches a local decision-maker phrase",
        evidence_field="contact.title",
        observed_value=text,
        status=FactorStatus.APPLIED,
    )


def _excluded_name_factor(name: str | None) -> ScoreFactor:
    text = _text(name)
    if text is None:
        return ScoreFactor(
            code=FactorCode.EXCLUDED_ORGANIZATION_NAME,
            points=0,
            reason="organization name missing; exclusion not inferred",
            evidence_field="organization.name",
            observed_value=None,
            status=FactorStatus.NOT_APPLICABLE,
        )
    matched = _contains_phrase(text, EXCLUDED_NAME_PHRASES)
    if matched is None:
        return ScoreFactor(
            code=FactorCode.EXCLUDED_ORGANIZATION_NAME,
            points=0,
            reason="organization name is not on the conservative exclusion list",
            evidence_field="organization.name",
            observed_value=text,
            status=FactorStatus.NOT_APPLICABLE,
        )
    return ScoreFactor(
        code=FactorCode.EXCLUDED_ORGANIZATION_NAME,
        points=POINTS_EXCLUDED_NAME,
        reason=f"organization name contains excluded phrase '{matched}'",
        evidence_field="organization.name",
        observed_value=text,
        status=FactorStatus.APPLIED,
    )


def snapshot_from_records(
    organization: Organization,
    evidence_rows: Sequence[SourceEvidence],
    contacts: Sequence[Contact],
) -> ScoringSnapshot:
    has_nppes, status, source_url = _nppes_evidence_fields(evidence_rows)
    verified_email = any(contact.email_verified for contact in contacts)
    has_contact_email = any(_text(contact.email) is not None for contact in contacts)
    return ScoringSnapshot(
        organization_name=_text(organization.name),
        npi=_text(organization.npi),
        city=_text(organization.city),
        state=_text(organization.state),
        specialty=_text(organization.specialty),
        website=_text(organization.website),
        nppes_status=status,
        has_nppes_evidence=has_nppes,
        nppes_source_url=source_url,
        verified_email=verified_email,
        has_contact_email=has_contact_email,
        decision_maker_title=_decision_maker_title(contacts),
    )


def _nppes_evidence_fields(
    evidence_rows: Sequence[SourceEvidence],
) -> tuple[bool, str | None, str | None]:
    nppes_rows = [row for row in evidence_rows if row.claim_type == NPPES_CLAIM_TYPE]
    if not nppes_rows:
        return False, None, None
    latest = max(nppes_rows, key=lambda row: (row.created_at is not None, row.created_at))
    metadata = latest.metadata_json if isinstance(latest.metadata_json, dict) else {}
    business = metadata.get("business_record")
    business_record = business if isinstance(business, dict) else {}
    status = _text(business_record.get("status"))
    return True, status.upper() if status is not None else None, _text(latest.source_url)


def _decision_maker_title(contacts: Sequence[Contact]) -> str | None:
    for contact in contacts:
        title = _text(contact.title)
        if title is None:
            continue
        if _contains_phrase(title, DECISION_MAKER_TITLE_PHRASES) is not None:
            return title
    return None


class LeadScoringService:
    """Deterministic local-only scorer. Does not call providers or send outbound actions."""

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
        has_nppes, _status, _url = _nppes_evidence_fields(evidence_rows)
        lead = Lead(
            organization_id=organization.id,
            stage=LeadStage.DISCOVERED.value,
            source="nppes" if has_nppes else "local",
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
        lead_score = LeadScore(
            lead_id=lead.id,
            score=scoring.total,
            model_version=scoring.model_version,
            rationale=scoring.to_rationale(),
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
                    "factor_codes": [factor.code.value for factor in scoring.factors],
                    "fabricated_facts": False,
                    "external_providers_called": [],
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
        )
