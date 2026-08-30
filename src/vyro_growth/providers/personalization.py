from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Never, Protocol
from uuid import UUID

from vyro_growth.config import Settings, get_settings
from vyro_growth.domain import (
    PersonalizationReadiness,
    PersonalizationReferenceKind,
)
from vyro_growth.providers.decision_makers import clean_optional_text, clip_text

PERSONALIZATION_SOURCE = "personalization"
STUB_PROVIDER_NAME = "stub"
PROMPT_VERSION = "personalization-v1"
SCHEMA_VERSION = "personalization-draft-v1"
DEFAULT_OFFER = "Complimentary Revenue Leakage Analysis"
SUMMARY_MAX_LENGTH = 400
BODY_MAX_LENGTH = 600
OPENING_MAX_LENGTH = 280
OFFER_MAX_LENGTH = 255
NOTE_MAX_LENGTH = 240
MAX_MISSING_NOTES = 16
MAX_EVIDENCE_REFS = 24
FINGERPRINT_LENGTH = 64

INVENTED_CLAIM_PHRASES = frozenset(
    {
        "denial rate",
        "denial rates",
        "accounts receivable",
        "a/r days",
        "payer mix",
        "billing software",
        "testimonial",
        "increased collections",
        "we recovered",
        "vyro typically",
        "industry-leading",
        "guaranteed roi",
        "patient portal login",
        "phi",
    }
)

PROMPT_SYSTEM = (
    "You generate B2B personalization drafts for Vyro Medical Billing. "
    "Use only the supplied evidence pack. Do not invent practice facts, pain points, "
    "provider counts, revenue, denial rates, A/R, payer mix, billing software, contacts, "
    "emails, phone numbers, testimonials, or Vyro performance claims. Unknown facts must "
    "remain unknown and listed in missing_data_notes. Do not include patient or PHI content. "
    f'Default suggested_offer to "{DEFAULT_OFFER}" when the pack identifies a US medical '
    "practice; do not claim the practice has leakage. Every material statement must be backed "
    "by evidence_references to supplied source_evidence ids, scoring factor codes, or "
    "organization fields. Return JSON only matching the schema."
)

PERSONALIZATION_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "practice_summary",
        "why_vyro_relevant",
        "opening_line",
        "outreach_angle",
        "suggested_offer",
        "missing_data_notes",
        "evidence_references",
        "confidence",
        "readiness_status",
    ],
    "properties": {
        "practice_summary": {"type": "string"},
        "why_vyro_relevant": {"type": "string"},
        "opening_line": {"type": "string"},
        "outreach_angle": {"type": "string"},
        "suggested_offer": {"type": "string"},
        "missing_data_notes": {"type": "array", "items": {"type": "string"}},
        "evidence_references": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "ref", "field"],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [kind.value for kind in PersonalizationReferenceKind],
                    },
                    "ref": {"type": "string"},
                    "field": {"type": "string"},
                },
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "readiness_status": {
            "type": "string",
            "enum": [status.value for status in PersonalizationReadiness],
        },
    },
}


class PersonalizationProviderError(RuntimeError):
    """Base error for personalization providers."""

    retryable: bool = False


class RetryablePersonalizationError(PersonalizationProviderError):
    retryable = True


class NonRetryablePersonalizationError(PersonalizationProviderError):
    retryable = False


class MalformedPersonalizationOutput(NonRetryablePersonalizationError):
    """Raised when provider JSON cannot be parsed or is not evidence-grounded."""


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    claim_type: str
    source_url: str
    extracted_value: str | None = None
    snippet: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class ScoringFactorRef:
    code: str
    reason: str
    observed_value: str | None = None
    points: int = 0
    status: str | None = None
    evidence_id: str | None = None
    source_url: str | None = None
    claim_type: str | None = None


@dataclass(frozen=True)
class StoredScoreContext:
    lead_score_id: str | None = None
    total: int | None = None
    band: str | None = None
    model_version: str | None = None
    missing_fields: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    disqualification_codes: tuple[str, ...] = ()
    research_reasons: tuple[str, ...] = ()
    factors: tuple[ScoringFactorRef, ...] = ()


@dataclass(frozen=True)
class ContactContext:
    full_name: str
    title: str | None = None
    role_category: str | None = None


@dataclass(frozen=True)
class OrganizationContext:
    organization_id: UUID
    name: str | None = None
    npi: str | None = None
    city: str | None = None
    state: str | None = None
    specialty: str | None = None
    website: str | None = None
    website_match_status: str | None = None


@dataclass(frozen=True)
class PersonalizationEvidencePack:
    organization: OrganizationContext
    evidence: tuple[EvidenceItem, ...] = ()
    score: StoredScoreContext = field(default_factory=StoredScoreContext)
    contacts: tuple[ContactContext, ...] = ()


@dataclass(frozen=True)
class PersonalizationRequest:
    lead_id: UUID
    pack: PersonalizationEvidencePack
    prompt_version: str = PROMPT_VERSION
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class EvidenceReference:
    kind: PersonalizationReferenceKind
    ref: str
    field: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "ref": self.ref, "field": self.field}


@dataclass(frozen=True)
class ProviderAudit:
    prompt_version: str
    schema_version: str
    prompt_hash: str
    provider_name: str
    model: str | None
    max_input_tokens: int
    max_output_tokens: int
    estimated_cost_usd_limit: float | None
    input_tokens: int | None
    output_tokens: int | None
    retry_attempts: int
    live_call_attempted: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "prompt_hash": self.prompt_hash,
            "provider_name": self.provider_name,
            "model": self.model,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "estimated_cost_usd_limit": self.estimated_cost_usd_limit,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "retry_attempts": self.retry_attempts,
            "live_call_attempted": self.live_call_attempted,
        }


@dataclass(frozen=True)
class PersonalizationContent:
    practice_summary: str
    why_vyro_relevant: str
    opening_line: str
    outreach_angle: str
    suggested_offer: str
    missing_data_notes: tuple[str, ...]
    evidence_references: tuple[EvidenceReference, ...]
    confidence: float
    readiness_status: PersonalizationReadiness

    def to_dict(self) -> dict[str, object]:
        return {
            "practice_summary": self.practice_summary,
            "why_vyro_relevant": self.why_vyro_relevant,
            "opening_line": self.opening_line,
            "outreach_angle": self.outreach_angle,
            "suggested_offer": self.suggested_offer,
            "missing_data_notes": list(self.missing_data_notes),
            "evidence_references": [item.to_dict() for item in self.evidence_references],
            "confidence": self.confidence,
            "readiness_status": self.readiness_status.value,
        }


@dataclass(frozen=True)
class PersonalizationProviderResult:
    content: PersonalizationContent
    audit: ProviderAudit


class PersonalizationProvider(Protocol):
    def generate(self, request: PersonalizationRequest) -> PersonalizationProviderResult: ...


def prompt_hash(prompt: str = PROMPT_SYSTEM) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def evidence_fingerprint(pack: PersonalizationEvidencePack) -> str:
    payload = {
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "organization": {
            "id": str(pack.organization.organization_id),
            "name": pack.organization.name,
            "npi": pack.organization.npi,
            "city": pack.organization.city,
            "state": pack.organization.state,
            "specialty": pack.organization.specialty,
            "website": pack.organization.website,
            "website_match_status": pack.organization.website_match_status,
        },
        "evidence": [
            {
                "id": item.evidence_id,
                "claim_type": item.claim_type,
                "value": item.extracted_value,
                "source_url": item.source_url,
            }
            for item in pack.evidence
        ],
        "score": {
            "lead_score_id": pack.score.lead_score_id,
            "total": pack.score.total,
            "band": pack.score.band,
            "model_version": pack.score.model_version,
            "missing_fields": list(pack.score.missing_fields),
            "reason_codes": list(pack.score.reason_codes),
            "disqualification_codes": list(pack.score.disqualification_codes),
            "factors": [
                {
                    "code": factor.code,
                    "observed_value": factor.observed_value,
                    "points": factor.points,
                    "status": factor.status,
                    "evidence_id": factor.evidence_id,
                }
                for factor in pack.score.factors
            ],
        },
        "contacts": [
            {
                "full_name": contact.full_name,
                "title": contact.title,
                "role_category": contact.role_category,
            }
            for contact in pack.contacts
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def pack_to_prompt_payload(pack: PersonalizationEvidencePack) -> dict[str, object]:
    return {
        "organization": {
            "name": pack.organization.name,
            "npi": pack.organization.npi,
            "city": pack.organization.city,
            "state": pack.organization.state,
            "specialty": pack.organization.specialty,
            "website": pack.organization.website,
            "website_match_status": pack.organization.website_match_status,
        },
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "claim_type": item.claim_type,
                "extracted_value": item.extracted_value,
                "source_url": item.source_url,
                "snippet": item.snippet,
            }
            for item in pack.evidence
        ],
        "score": {
            "total": pack.score.total,
            "band": pack.score.band,
            "model_version": pack.score.model_version,
            "missing_fields": list(pack.score.missing_fields),
            "reason_codes": list(pack.score.reason_codes),
            "disqualification_codes": list(pack.score.disqualification_codes),
            "research_reasons": list(pack.score.research_reasons),
            "factors": [
                {
                    "code": factor.code,
                    "reason": factor.reason,
                    "observed_value": factor.observed_value,
                    "points": factor.points,
                    "status": factor.status,
                    "evidence_id": factor.evidence_id,
                    "source_url": factor.source_url,
                    "claim_type": factor.claim_type,
                }
                for factor in pack.score.factors
            ],
        },
        "contacts": [
            {
                "full_name": contact.full_name,
                "title": contact.title,
                "role_category": contact.role_category,
            }
            for contact in pack.contacts
        ],
        "policy": {
            "no_invented_facts": True,
            "unknown_stays_unknown": True,
            "no_phi": True,
            "no_outbound": True,
            "default_offer": DEFAULT_OFFER,
        },
    }


def _readiness_from_value(value: object) -> PersonalizationReadiness | None:
    if isinstance(value, PersonalizationReadiness):
        return value
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower().replace(" ", "_").replace("-", "_")
    for status in PersonalizationReadiness:
        if status.value == cleaned:
            return status
    return None


def _kind_from_value(value: object) -> PersonalizationReferenceKind | None:
    if isinstance(value, PersonalizationReferenceKind):
        return value
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower().replace(" ", "_").replace("-", "_")
    for kind in PersonalizationReferenceKind:
        if kind.value == cleaned:
            return kind
    return None


def parse_personalization_content(raw: object) -> PersonalizationContent | None:
    if isinstance(raw, PersonalizationContent):
        return raw
    if not isinstance(raw, dict):
        return None
    summary = clean_optional_text(_optional_str(raw.get("practice_summary")))
    why = clean_optional_text(_optional_str(raw.get("why_vyro_relevant")))
    opening = clean_optional_text(_optional_str(raw.get("opening_line")))
    angle = clean_optional_text(_optional_str(raw.get("outreach_angle")))
    offer = clean_optional_text(_optional_str(raw.get("suggested_offer")))
    if None in (summary, why, opening, angle, offer):
        return None
    confidence = _parse_confidence(raw.get("confidence"))
    if confidence is None:
        return None
    readiness = _readiness_from_value(raw.get("readiness_status"))
    if readiness is None:
        return None
    notes_raw = raw.get("missing_data_notes")
    if notes_raw is None:
        notes_raw = []
    if not isinstance(notes_raw, list):
        return None
    notes: list[str] = []
    for item in notes_raw[:MAX_MISSING_NOTES]:
        text = clean_optional_text(_optional_str(item))
        if text:
            notes.append(clip_text(text, NOTE_MAX_LENGTH))
    refs_raw = raw.get("evidence_references")
    if refs_raw is None:
        refs_raw = []
    if not isinstance(refs_raw, list):
        return None
    refs: list[EvidenceReference] = []
    for item in refs_raw[:MAX_EVIDENCE_REFS]:
        parsed_ref = _parse_reference(item)
        if parsed_ref is None:
            return None
        refs.append(parsed_ref)
    assert summary is not None and why is not None and opening is not None
    assert angle is not None and offer is not None
    return PersonalizationContent(
        practice_summary=clip_text(summary, SUMMARY_MAX_LENGTH),
        why_vyro_relevant=clip_text(why, BODY_MAX_LENGTH),
        opening_line=clip_text(opening, OPENING_MAX_LENGTH),
        outreach_angle=clip_text(angle, BODY_MAX_LENGTH),
        suggested_offer=clip_text(offer, OFFER_MAX_LENGTH),
        missing_data_notes=tuple(notes),
        evidence_references=tuple(refs),
        confidence=confidence,
        readiness_status=readiness,
    )


def ground_personalization_content(
    content: PersonalizationContent,
    pack: PersonalizationEvidencePack,
) -> PersonalizationContent:
    _assert_references_resolve(content.evidence_references, pack)
    _assert_no_invented_claims(content, pack)
    readiness = _readiness_for_pack(pack, content.readiness_status)
    notes = _merge_missing_notes(content.missing_data_notes, _missing_notes_for_pack(pack))
    offer = content.suggested_offer
    if clean_optional_text(offer) is None:
        offer = DEFAULT_OFFER
    return PersonalizationContent(
        practice_summary=content.practice_summary,
        why_vyro_relevant=content.why_vyro_relevant,
        opening_line=content.opening_line,
        outreach_angle=content.outreach_angle,
        suggested_offer=offer,
        missing_data_notes=notes,
        evidence_references=content.evidence_references,
        confidence=content.confidence,
        readiness_status=readiness,
    )


def generate_stub_content(pack: PersonalizationEvidencePack) -> PersonalizationContent:
    org = pack.organization
    refs: list[EvidenceReference] = []
    parts: list[str] = []
    if org.name:
        parts.append(org.name)
        refs.append(
            EvidenceReference(
                PersonalizationReferenceKind.ORGANIZATION_FIELD,
                "organization.name",
                "practice_summary",
            )
        )
    location = _location_text(org.city, org.state)
    if location:
        parts.append(f"in {location}")
        if org.city:
            refs.append(
                EvidenceReference(
                    PersonalizationReferenceKind.ORGANIZATION_FIELD,
                    "organization.city",
                    "practice_summary",
                )
            )
        if org.state:
            refs.append(
                EvidenceReference(
                    PersonalizationReferenceKind.ORGANIZATION_FIELD,
                    "organization.state",
                    "practice_summary",
                )
            )
    if org.specialty:
        parts.append(f"({org.specialty})")
        refs.append(
            EvidenceReference(
                PersonalizationReferenceKind.ORGANIZATION_FIELD,
                "organization.specialty",
                "practice_summary",
            )
        )
    if parts:
        summary = " ".join(parts) + " is a US medical practice in stored records."
    else:
        summary = "Practice identity is incomplete in stored records."

    why, why_refs = _why_vyro(pack)
    refs.extend(why_refs)
    opening, opening_refs = _opening_line(pack)
    refs.extend(opening_refs)
    angle, angle_refs = _outreach_angle(pack)
    refs.extend(angle_refs)
    score_ref = _score_reference(pack)
    if score_ref is not None:
        refs.append(score_ref)
    evidence_refs = _evidence_item_refs(pack)
    refs.extend(evidence_refs)

    readiness = _readiness_for_pack(pack, None)
    notes = _missing_notes_for_pack(pack)
    confidence = _stub_confidence(pack)
    offer = DEFAULT_OFFER
    if org.name or org.specialty or location:
        refs.append(
            EvidenceReference(
                PersonalizationReferenceKind.ORGANIZATION_FIELD,
                "policy.default_offer",
                "suggested_offer",
            )
        )
    return PersonalizationContent(
        practice_summary=clip_text(summary, SUMMARY_MAX_LENGTH),
        why_vyro_relevant=clip_text(why, BODY_MAX_LENGTH),
        opening_line=clip_text(opening, OPENING_MAX_LENGTH),
        outreach_angle=clip_text(angle, BODY_MAX_LENGTH),
        suggested_offer=offer,
        missing_data_notes=notes,
        evidence_references=_dedupe_refs(refs),
        confidence=confidence,
        readiness_status=readiness,
    )


def stub_audit(*, retry_attempts: int = 0) -> ProviderAudit:
    return ProviderAudit(
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        prompt_hash=prompt_hash(),
        provider_name=STUB_PROVIDER_NAME,
        model="deterministic-stub",
        max_input_tokens=0,
        max_output_tokens=0,
        estimated_cost_usd_limit=None,
        input_tokens=0,
        output_tokens=0,
        retry_attempts=retry_attempts,
        live_call_attempted=False,
    )


class StubPersonalizationProvider:
    """CI/local default. Builds drafts from stored evidence only. Never calls a live model."""

    def __init__(self) -> None:
        self.requests: list[PersonalizationRequest] = []

    def generate(self, request: PersonalizationRequest) -> PersonalizationProviderResult:
        self.requests.append(request)
        content = generate_stub_content(request.pack)
        return PersonalizationProviderResult(content=content, audit=stub_audit())


class StaticPersonalizationProvider:
    """Test adapter that returns configured output or raises. Does not call a network."""

    def __init__(
        self,
        payload: object | None = None,
        *,
        error: PersonalizationProviderError | None = None,
    ) -> None:
        self._payload = payload
        self._error = error
        self.requests: list[PersonalizationRequest] = []

    def generate(self, request: PersonalizationRequest) -> PersonalizationProviderResult:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        if self._payload is None:
            content = generate_stub_content(request.pack)
            return PersonalizationProviderResult(content=content, audit=stub_audit())
        parsed = parse_personalization_content(self._payload)
        if parsed is None:
            raise MalformedPersonalizationOutput(
                "provider output was not valid personalization JSON"
            )
        return PersonalizationProviderResult(
            content=parsed,
            audit=ProviderAudit(
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
                prompt_hash=prompt_hash(),
                provider_name="static",
                model="static",
                max_input_tokens=0,
                max_output_tokens=0,
                estimated_cost_usd_limit=None,
                input_tokens=0,
                output_tokens=0,
                retry_attempts=0,
                live_call_attempted=False,
            ),
        )


def build_personalization_provider(
    settings: Settings | None = None,
) -> PersonalizationProvider:
    """Return the stub unless live personalization is explicitly enabled with a key."""
    active = settings or get_settings()
    if active.openai_personalization_enabled and clean_optional_text(active.openai_api_key):
        # Imported here to avoid a circular import with personalization_openai.
        from vyro_growth.providers.personalization_openai import OpenAIPersonalizationProvider

        return OpenAIPersonalizationProvider.from_settings(active)
    return StubPersonalizationProvider()


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _parse_confidence(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
        if 0.0 <= number <= 1.0:
            return number
        return None
    return None


def _parse_reference(raw: object) -> EvidenceReference | None:
    if isinstance(raw, EvidenceReference):
        return raw
    if not isinstance(raw, dict):
        return None
    kind = _kind_from_value(raw.get("kind"))
    ref = clean_optional_text(_optional_str(raw.get("ref")))
    field_name = clean_optional_text(_optional_str(raw.get("field")))
    if kind is None or ref is None or field_name is None:
        return None
    return EvidenceReference(kind=kind, ref=clip_text(ref, 120), field=clip_text(field_name, 64))


def _assert_references_resolve(
    references: Sequence[EvidenceReference],
    pack: PersonalizationEvidencePack,
) -> None:
    evidence_ids = {item.evidence_id for item in pack.evidence}
    factor_codes = {factor.code for factor in pack.score.factors}
    org_fields = {
        "organization.name",
        "organization.npi",
        "organization.city",
        "organization.state",
        "organization.specialty",
        "organization.website",
        "organization.website_match_status",
        "policy.default_offer",
        "score.total",
        "score.band",
    }
    for reference in references:
        match reference.kind:
            case PersonalizationReferenceKind.SOURCE_EVIDENCE:
                if reference.ref not in evidence_ids:
                    raise MalformedPersonalizationOutput(
                        f"evidence reference does not match stored evidence: {reference.ref}"
                    )
            case PersonalizationReferenceKind.SCORING_FACTOR:
                if reference.ref not in factor_codes:
                    raise MalformedPersonalizationOutput(
                        f"scoring factor reference is not in the stored score: {reference.ref}"
                    )
            case PersonalizationReferenceKind.ORGANIZATION_FIELD:
                if reference.ref not in org_fields:
                    raise MalformedPersonalizationOutput(
                        f"organization field reference is not allowed: {reference.ref}"
                    )
            case _:
                unreachable: Never = reference.kind
                raise RuntimeError(f"unhandled personalization reference kind: {unreachable}")


def _allowed_claim_text(pack: PersonalizationEvidencePack) -> str:
    chunks = [
        pack.organization.name or "",
        pack.organization.npi or "",
        pack.organization.city or "",
        pack.organization.state or "",
        pack.organization.specialty or "",
        pack.organization.website or "",
        DEFAULT_OFFER.lower(),
    ]
    for item in pack.evidence:
        chunks.append(item.extracted_value or "")
        chunks.append(item.snippet or "")
        chunks.append(item.claim_type)
    for factor in pack.score.factors:
        chunks.append(factor.observed_value or "")
        chunks.append(factor.reason)
        chunks.append(factor.code)
    for contact in pack.contacts:
        chunks.append(contact.full_name)
        chunks.append(contact.title or "")
    return " ".join(chunks).lower()


def _assert_no_invented_claims(
    content: PersonalizationContent,
    pack: PersonalizationEvidencePack,
) -> None:
    combined = " ".join(
        [
            content.practice_summary,
            content.why_vyro_relevant,
            content.opening_line,
            content.outreach_angle,
            content.suggested_offer,
            *content.missing_data_notes,
        ]
    ).lower()
    allowed = _allowed_claim_text(pack)
    for phrase in sorted(INVENTED_CLAIM_PHRASES):
        if phrase in combined and phrase not in allowed and phrase not in DEFAULT_OFFER.lower():
            raise MalformedPersonalizationOutput(
                f"personalization output includes an ungrounded claim: {phrase}"
            )


def _location_text(city: str | None, state: str | None) -> str | None:
    if city and state:
        return f"{city}, {state}"
    return city or state


def _why_vyro(pack: PersonalizationEvidencePack) -> tuple[str, list[EvidenceReference]]:
    refs: list[EvidenceReference] = []
    billing = _evidence_by_type(pack, "billing_signal")
    if billing is not None:
        refs.append(
            EvidenceReference(
                PersonalizationReferenceKind.SOURCE_EVIDENCE,
                billing.evidence_id,
                "why_vyro_relevant",
            )
        )
        return (
            "Stored public business evidence includes billing or revenue-cycle language, "
            "which is relevant to Vyro Medical Billing.",
            refs,
        )
    if pack.organization.specialty:
        refs.append(
            EvidenceReference(
                PersonalizationReferenceKind.ORGANIZATION_FIELD,
                "organization.specialty",
                "why_vyro_relevant",
            )
        )
        return (
            f"Stored specialty '{pack.organization.specialty}' identifies a US medical practice "
            "that may be relevant to medical billing support. No operational pain is assumed.",
            refs,
        )
    if pack.organization.name:
        refs.append(
            EvidenceReference(
                PersonalizationReferenceKind.ORGANIZATION_FIELD,
                "organization.name",
                "why_vyro_relevant",
            )
        )
        return (
            "Vyro relevance cannot be assessed beyond the stored practice identity; "
            "specialty and billing facts are missing.",
            refs,
        )
    return (
        "Vyro relevance is unknown because stored identity and billing evidence are missing.",
        refs,
    )


def _opening_line(pack: PersonalizationEvidencePack) -> tuple[str, list[EvidenceReference]]:
    refs: list[EvidenceReference] = []
    contact = pack.contacts[0] if pack.contacts else None
    greeting = "Hello"
    if contact is not None:
        first = contact.full_name.split()[0]
        greeting = f"Hello {first}"
        refs.append(
            EvidenceReference(
                PersonalizationReferenceKind.ORGANIZATION_FIELD,
                "organization.name",
                "opening_line",
            )
        )
    org = pack.organization
    if org.name and _location_text(org.city, org.state) and org.specialty:
        refs.extend(
            [
                EvidenceReference(
                    PersonalizationReferenceKind.ORGANIZATION_FIELD,
                    "organization.name",
                    "opening_line",
                ),
                EvidenceReference(
                    PersonalizationReferenceKind.ORGANIZATION_FIELD,
                    "organization.specialty",
                    "opening_line",
                ),
            ]
        )
        if org.city:
            refs.append(
                EvidenceReference(
                    PersonalizationReferenceKind.ORGANIZATION_FIELD,
                    "organization.city",
                    "opening_line",
                )
            )
        location = _location_text(org.city, org.state)
        return (
            f"{greeting}. I was reviewing {org.name}, the {org.specialty} practice in {location}.",
            refs,
        )
    if org.name:
        refs.append(
            EvidenceReference(
                PersonalizationReferenceKind.ORGANIZATION_FIELD,
                "organization.name",
                "opening_line",
            )
        )
        return (
            f"{greeting}. I was reviewing stored public records for {org.name}.",
            refs,
        )
    return (
        f"{greeting}. Stored practice identity is incomplete, so this note stays generic.",
        refs,
    )


def _outreach_angle(pack: PersonalizationEvidencePack) -> tuple[str, list[EvidenceReference]]:
    refs: list[EvidenceReference] = []
    billing = _evidence_by_type(pack, "billing_signal")
    if billing is not None:
        refs.append(
            EvidenceReference(
                PersonalizationReferenceKind.SOURCE_EVIDENCE,
                billing.evidence_id,
                "outreach_angle",
            )
        )
        return (
            "Lead with the stored billing/revenue-cycle signal and offer a review of public "
            "billing operations. Do not claim a specific leakage amount.",
            refs,
        )
    ownership = _evidence_by_type(pack, "ownership_signal")
    if ownership is not None and (ownership.extracted_value or "").lower() == "independent":
        refs.append(
            EvidenceReference(
                PersonalizationReferenceKind.SOURCE_EVIDENCE,
                ownership.evidence_id,
                "outreach_angle",
            )
        )
        return (
            "Lead with independent-practice operations and medical billing support. "
            "Ownership is stored as independent; no other operating model is assumed.",
            refs,
        )
    if pack.organization.specialty:
        refs.append(
            EvidenceReference(
                PersonalizationReferenceKind.ORGANIZATION_FIELD,
                "organization.specialty",
                "outreach_angle",
            )
        )
        return (
            f"Lead with {pack.organization.specialty} practice operations and outsourced billing "
            "as a question, not a diagnosed problem.",
            refs,
        )
    return (
        "Keep outreach generic to medical billing operations. Missing specialty and billing "
        "evidence means no practice-specific pain should be claimed.",
        refs,
    )


def _score_reference(pack: PersonalizationEvidencePack) -> EvidenceReference | None:
    if pack.score.total is None and pack.score.band is None:
        return None
    return EvidenceReference(
        PersonalizationReferenceKind.ORGANIZATION_FIELD,
        "score.band" if pack.score.band else "score.total",
        "practice_summary",
    )


def _evidence_item_refs(pack: PersonalizationEvidencePack) -> list[EvidenceReference]:
    refs: list[EvidenceReference] = []
    for item in pack.evidence[:8]:
        refs.append(
            EvidenceReference(
                PersonalizationReferenceKind.SOURCE_EVIDENCE,
                item.evidence_id,
                "practice_summary",
            )
        )
    for factor in pack.score.factors:
        if factor.status == "applied" and factor.points != 0:
            refs.append(
                EvidenceReference(
                    PersonalizationReferenceKind.SCORING_FACTOR,
                    factor.code,
                    "why_vyro_relevant",
                )
            )
            if len(refs) >= MAX_EVIDENCE_REFS:
                break
    return refs


def _evidence_by_type(pack: PersonalizationEvidencePack, claim_type: str) -> EvidenceItem | None:
    for item in pack.evidence:
        if item.claim_type == claim_type:
            return item
    return None


def _readiness_for_pack(
    pack: PersonalizationEvidencePack,
    requested: PersonalizationReadiness | None,
) -> PersonalizationReadiness:
    if pack.score.disqualification_codes:
        return PersonalizationReadiness.BLOCKED
    if pack.score.band == "disqualified":
        return PersonalizationReadiness.BLOCKED
    has_identity = pack.organization.name is not None
    has_context = (
        pack.organization.specialty is not None
        or pack.organization.city is not None
        or pack.organization.state is not None
    )
    has_score = pack.score.total is not None
    if not has_identity or not has_context or not has_score:
        return PersonalizationReadiness.NEEDS_MORE_EVIDENCE
    if requested is PersonalizationReadiness.BLOCKED:
        return PersonalizationReadiness.BLOCKED
    if requested is PersonalizationReadiness.NEEDS_MORE_EVIDENCE:
        return PersonalizationReadiness.NEEDS_MORE_EVIDENCE
    return PersonalizationReadiness.READY


def _missing_notes_for_pack(pack: PersonalizationEvidencePack) -> tuple[str, ...]:
    notes: list[str] = []
    org = pack.organization
    if org.name is None:
        notes.append("organization.name is missing")
    if org.specialty is None:
        notes.append("organization.specialty is missing")
    if org.city is None:
        notes.append("organization.city is missing")
    if org.state is None:
        notes.append("organization.state is missing")
    if org.website is None:
        notes.append("organization.website is missing")
    if org.npi is None:
        notes.append("organization.npi is missing")
    if pack.score.total is None:
        notes.append("lead_score is missing")
    if not pack.contacts:
        notes.append("decision-maker contact is missing")
    if _evidence_by_type(pack, "billing_signal") is None:
        notes.append("billing_signal evidence is missing")
    if _evidence_by_type(pack, "provider_count") is None:
        notes.append("provider_count is unknown")
    for field_name in pack.score.missing_fields:
        note = f"score missing field: {field_name}"
        if note not in notes:
            notes.append(note)
    return tuple(notes[:MAX_MISSING_NOTES])


def _merge_missing_notes(
    provider_notes: Sequence[str],
    pack_notes: Sequence[str],
) -> tuple[str, ...]:
    merged: list[str] = []
    for note in (*provider_notes, *pack_notes):
        cleaned = clean_optional_text(note)
        if cleaned and cleaned not in merged:
            merged.append(clip_text(cleaned, NOTE_MAX_LENGTH))
        if len(merged) >= MAX_MISSING_NOTES:
            break
    return tuple(merged)


def _stub_confidence(pack: PersonalizationEvidencePack) -> float:
    score = 0.15
    if pack.organization.name:
        score += 0.15
    if pack.organization.specialty:
        score += 0.15
    if pack.organization.city or pack.organization.state:
        score += 0.1
    if pack.score.total is not None:
        score += 0.15
    if pack.organization.website:
        score += 0.1
    if pack.contacts:
        score += 0.1
    if _evidence_by_type(pack, "billing_signal") is not None:
        score += 0.05
    return round(min(0.9, score), 2)


def _dedupe_refs(refs: Sequence[EvidenceReference]) -> tuple[EvidenceReference, ...]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[EvidenceReference] = []
    for item in refs:
        key = (item.kind.value, item.ref, item.field)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= MAX_EVIDENCE_REFS:
            break
    return tuple(unique)
