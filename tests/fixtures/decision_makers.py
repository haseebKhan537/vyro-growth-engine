from __future__ import annotations

from datetime import UTC, datetime

from vyro_growth.domain import ContactRoleCategory, ContactVerificationStatus
from vyro_growth.providers.decision_makers import ContactProvenance, DecisionMakerCandidate

FIXED_TIMESTAMP = datetime(2026, 8, 30, 16, 0, tzinfo=UTC)


def candidate(
    *,
    full_name: str = "Jordan Blake",
    title: str | None = "Practice Manager",
    role_category: ContactRoleCategory | None = None,
    business_email: str | None = "jblake@austinfamily.example",
    business_phone: str | None = "512-555-0100",
    source_provider: str = "static",
    source_timestamp: datetime = FIXED_TIMESTAMP,
    confidence: float | None = 0.82,
    verification_status: ContactVerificationStatus = ContactVerificationStatus.UNVERIFIED,
    source_url: str | None = "https://provider.example/people/jblake",
    evidence_snippet: str | None = "Jordan Blake, Practice Manager",
    provider_record_id: str | None = "rec-jblake",
    owner_operator_evidence: str | None = None,
) -> DecisionMakerCandidate:
    return DecisionMakerCandidate(
        full_name=full_name,
        title=title,
        role_category=role_category,
        business_email=business_email,
        business_phone=business_phone,
        source_provider=source_provider,
        source_timestamp=source_timestamp,
        confidence=confidence,
        verification_status=verification_status,
        provenance=ContactProvenance(
            source_url=source_url,
            evidence_snippet=evidence_snippet,
            metadata={"fixture": True},
        ),
        provider_record_id=provider_record_id,
        owner_operator_evidence=owner_operator_evidence,
    )
