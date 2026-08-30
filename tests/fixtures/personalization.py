from __future__ import annotations

from uuid import uuid4

from vyro_growth.domain import PersonalizationReadiness, PersonalizationReferenceKind
from vyro_growth.providers.personalization import (
    ContactContext,
    EvidenceItem,
    OrganizationContext,
    PersonalizationEvidencePack,
    ScoringFactorRef,
    StoredScoreContext,
    generate_stub_content,
)


def sample_pack(
    *,
    missing: bool = False,
    billing: bool = True,
    disqualified: bool = False,
) -> PersonalizationEvidencePack:
    if missing:
        return PersonalizationEvidencePack(
            organization=OrganizationContext(organization_id=uuid4(), name="Sparse Clinic")
        )
    evidence = [
        EvidenceItem(
            evidence_id="ev-nppes",
            claim_type="nppes_organization_record",
            source_url="https://npiregistry.cms.hhs.gov/api/",
            extracted_value="AUSTIN FAMILY MEDICINE PLLC",
        ),
        EvidenceItem(
            evidence_id="ev-own",
            claim_type="ownership_signal",
            source_url="https://austinfamily.example/about",
            extracted_value="independent",
            snippet="independently owned practice",
        ),
    ]
    if billing:
        evidence.append(
            EvidenceItem(
                evidence_id="ev-bill",
                claim_type="billing_signal",
                source_url="https://austinfamily.example/billing",
                extracted_value="in-house billing",
                snippet="our billing department",
            )
        )
    score = StoredScoreContext(
        lead_score_id="score-1",
        total=12 if disqualified else 88,
        band="disqualified" if disqualified else "hot",
        model_version="deterministic-icp-v2",
        missing_fields=(),
        reason_codes=("pos_target_specialty",),
        disqualification_codes=("disq_excluded_specialty",) if disqualified else (),
        factors=(
            ScoringFactorRef(
                code="specialty_fit",
                reason="specialty matches independent US medical practice target list",
                observed_value="Family Medicine",
                points=13,
                status="applied",
            ),
        ),
    )
    return PersonalizationEvidencePack(
        organization=OrganizationContext(
            organization_id=uuid4(),
            name="AUSTIN FAMILY MEDICINE PLLC",
            npi="1487448189",
            city="AUSTIN",
            state="TX",
            specialty="Family Medicine",
            website="https://austinfamily.example",
            website_match_status="verified",
        ),
        evidence=tuple(evidence),
        score=score,
        contacts=(
            ContactContext(
                full_name="Jordan Blake",
                title="Practice Manager",
                role_category="practice_manager",
            ),
        ),
    )


def stub_payload(pack: PersonalizationEvidencePack) -> dict[str, object]:
    content = generate_stub_content(pack)
    return content.to_dict()


def invented_payload() -> dict[str, object]:
    return {
        "practice_summary": "This clinic has a 40% denial rate and 90 A/R days.",
        "why_vyro_relevant": "Vyro typically increases collections by 20%.",
        "opening_line": "I know your payer mix is hurting cash flow.",
        "outreach_angle": "Pitch billing software replacement with guaranteed ROI.",
        "suggested_offer": "Complimentary Revenue Leakage Analysis",
        "missing_data_notes": [],
        "evidence_references": [
            {
                "kind": PersonalizationReferenceKind.ORGANIZATION_FIELD.value,
                "ref": "organization.name",
                "field": "practice_summary",
            }
        ],
        "confidence": 0.9,
        "readiness_status": PersonalizationReadiness.READY.value,
    }


def malformed_payload() -> dict[str, object]:
    return {"practice_summary": "not enough fields"}
