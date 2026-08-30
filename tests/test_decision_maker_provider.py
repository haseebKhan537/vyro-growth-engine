from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from tests.fixtures.decision_makers import FIXED_TIMESTAMP, candidate
from vyro_growth.domain import ContactRoleCategory, ContactVerificationStatus
from vyro_growth.providers.decision_makers import (
    ContactSkipReason,
    DecisionMakerEnrichmentRequest,
    OrganizationContactContext,
    StaticDecisionMakerEnrichmentProvider,
    StubDecisionMakerEnrichmentProvider,
    WebsiteFactContext,
    build_decision_maker_provider,
    classify_candidate,
    classify_title,
    independent_small_group,
    parse_decision_maker_candidate,
    rank_classified,
    role_rank,
)


def _org(**overrides: object) -> OrganizationContactContext:
    values: dict[str, object] = {
        "organization_id": uuid4(),
        "name": "AUSTIN FAMILY MEDICINE PLLC",
        "npi": "1487448189",
        "city": "AUSTIN",
        "state": "TX",
        "specialty": "Family Medicine",
        "website": "https://austinfamily.example",
        "website_match_status": "verified",
        "website_facts": (),
    }
    values.update(overrides)
    return OrganizationContactContext(**values)  # type: ignore[arg-type]


def test_title_classification_priority_phrases() -> None:
    assert classify_title("Physician Owner") is ContactRoleCategory.OWNER_PHYSICIAN_OWNER
    assert classify_title("Practice Administrator") is ContactRoleCategory.PRACTICE_ADMINISTRATOR
    assert classify_title("Practice Manager") is ContactRoleCategory.PRACTICE_MANAGER
    assert classify_title("Office Manager") is ContactRoleCategory.OFFICE_MANAGER
    assert classify_title("Executive Director") is ContactRoleCategory.EXECUTIVE_DIRECTOR
    assert classify_title("COO") is ContactRoleCategory.COO
    assert classify_title("Chief Executive Officer") is ContactRoleCategory.CEO_INDEPENDENT
    assert classify_title("Revenue Cycle Manager") is ContactRoleCategory.REVENUE_CYCLE_MANAGER
    assert classify_title("Billing Manager") is ContactRoleCategory.BILLING_MANAGER
    assert classify_title("Operations Manager") is ContactRoleCategory.OPERATIONS_MANAGER
    assert classify_title("Registered Nurse") is None
    assert classify_title(None) is None


def test_role_rank_order() -> None:
    ranks = [role_rank(category) for category in ContactRoleCategory]
    assert ranks == sorted(ranks)
    assert role_rank(ContactRoleCategory.OWNER_PHYSICIAN_OWNER) == 1
    assert role_rank(ContactRoleCategory.OPERATIONS_MANAGER) == 10


def test_happy_path_classifies_practice_manager() -> None:
    disposition = classify_candidate(candidate(), organization=_org())
    assert disposition.skip_reason is None
    assert disposition.classified is not None
    assert disposition.classified.role_category is ContactRoleCategory.PRACTICE_MANAGER
    assert disposition.classified.business_email == "jblake@austinfamily.example"


def test_missing_name_is_skipped() -> None:
    disposition = classify_candidate(candidate(full_name="  "), organization=_org())
    assert disposition.classified is None
    assert disposition.skip_reason is ContactSkipReason.MISSING_NAME


def test_unknown_values_stay_unknown() -> None:
    disposition = classify_candidate(
        candidate(
            business_email=None,
            business_phone=None,
            confidence=None,
            verification_status=ContactVerificationStatus.UNKNOWN,
        ),
        organization=_org(),
    )
    assert disposition.classified is not None
    assert disposition.classified.business_email is None
    assert disposition.classified.business_phone is None
    assert disposition.classified.candidate.confidence is None


def test_personal_email_is_not_stored_as_business_email() -> None:
    disposition = classify_candidate(
        candidate(business_email="jordan@gmail.com"),
        organization=_org(),
    )
    assert disposition.classified is not None
    assert disposition.classified.business_email is None


def test_irrelevant_clinical_contact_is_skipped() -> None:
    disposition = classify_candidate(
        candidate(full_name="Sam Rivera", title="Family Physician, MD"),
        organization=_org(),
    )
    assert disposition.classified is None
    assert disposition.skip_reason is ContactSkipReason.IRRELEVANT_CLINICAL


def test_clinical_owner_operator_is_accepted() -> None:
    disposition = classify_candidate(
        candidate(
            full_name="Sam Rivera",
            title="Family Physician, MD",
            owner_operator_evidence="listed as physician owner on the practice about page",
        ),
        organization=_org(),
    )
    assert disposition.classified is not None
    assert disposition.classified.role_category is ContactRoleCategory.OWNER_PHYSICIAN_OWNER


def test_ceo_requires_independent_small_group_evidence() -> None:
    ceo = candidate(full_name="Lee Chen", title="CEO")
    skipped = classify_candidate(ceo, organization=_org())
    assert skipped.skip_reason is ContactSkipReason.CEO_NOT_INDEPENDENT_GROUP

    independent = _org(
        website_facts=(
            WebsiteFactContext(fact_type="ownership_signal", value="independent"),
            WebsiteFactContext(fact_type="provider_count", value="4"),
        )
    )
    accepted = classify_candidate(ceo, organization=independent)
    assert accepted.classified is not None
    assert accepted.classified.role_category is ContactRoleCategory.CEO_INDEPENDENT

    large = _org(
        website_facts=(
            WebsiteFactContext(fact_type="ownership_signal", value="larger_group:Health System"),
        )
    )
    rejected = classify_candidate(ceo, organization=large)
    assert rejected.skip_reason is ContactSkipReason.CEO_NOT_INDEPENDENT_GROUP


def test_malformed_parse_results_are_dropped() -> None:
    assert parse_decision_maker_candidate({}) is None
    assert parse_decision_maker_candidate("not a mapping") is None
    assert parse_decision_maker_candidate({"full_name": "A", "source_provider": "x"}) is None
    assert (
        parse_decision_maker_candidate(
            {
                "full_name": "A",
                "source_provider": "x",
                "source_timestamp": FIXED_TIMESTAMP.isoformat(),
                "confidence": 1.5,
            }
        )
        is None
    )
    assert (
        parse_decision_maker_candidate(
            {
                "full_name": "A",
                "source_provider": "x",
                "source_timestamp": "2026-08-30T16:00:00",
            }
        )
        is None
    )
    parsed = parse_decision_maker_candidate(
        {
            "full_name": "Jordan Blake",
            "source_provider": "static",
            "source_timestamp": FIXED_TIMESTAMP.isoformat(),
            "title": "Office Manager",
            "confidence": 0.4,
        }
    )
    assert parsed is not None
    assert parsed.title == "Office Manager"
    assert parsed.confidence == 0.4


def test_malformed_confidence_on_typed_candidate_is_skipped() -> None:
    disposition = classify_candidate(candidate(confidence=2.0), organization=_org())
    assert disposition.skip_reason is ContactSkipReason.MALFORMED


def test_invalid_email_is_malformed() -> None:
    disposition = classify_candidate(
        candidate(business_email="not-an-email"),
        organization=_org(),
    )
    assert disposition.skip_reason is ContactSkipReason.MALFORMED


def test_rank_classified_orders_roles() -> None:
    org = _org(
        website_facts=(WebsiteFactContext(fact_type="ownership_signal", value="independent"),)
    )
    items = []
    for person in (
        candidate(full_name="Ops", title="Operations Manager"),
        candidate(full_name="Owner", title="Physician Owner"),
        candidate(full_name="Office", title="Office Manager"),
        candidate(full_name="Admin", title="Practice Administrator"),
    ):
        disposition = classify_candidate(person, organization=org)
        assert disposition.classified is not None
        items.append(disposition.classified)
    ranked = rank_classified(items)
    assert [item.candidate.full_name for item in ranked] == [
        "Owner",
        "Admin",
        "Office",
        "Ops",
    ]


def test_stub_provider_does_not_invent_contacts() -> None:
    provider = StubDecisionMakerEnrichmentProvider()
    request = DecisionMakerEnrichmentRequest(organization=_org())
    result = provider.enrich_decision_makers(request)
    assert result.candidates == ()
    assert result.raw_count == 0
    assert result.provider_name == "stub"
    assert provider.requests == [request]


def test_build_provider_is_stub() -> None:
    provider = build_decision_maker_provider()
    assert isinstance(provider, StubDecisionMakerEnrichmentProvider)


def test_static_provider_records_request_and_drops_malformed() -> None:
    provider = StaticDecisionMakerEnrichmentProvider(
        (
            candidate(),
            {"full_name": "Nope"},
        )
    )
    request = DecisionMakerEnrichmentRequest(organization=_org())
    result = provider.enrich_decision_makers(request)
    assert result.raw_count == 2
    assert len(result.candidates) == 1
    assert provider.requests == [request]


def test_independent_small_group_unknown_without_evidence() -> None:
    assert independent_small_group(()) is None
    assert (
        independent_small_group(
            (WebsiteFactContext(fact_type="ownership_signal", value="independent"),)
        )
        is True
    )


def test_decision_maker_modules_have_no_network_client() -> None:
    from pathlib import Path

    source = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "src/vyro_growth/providers/decision_makers.py",
            "src/vyro_growth/services/contact_enrichment.py",
            "src/vyro_growth/workers/contact_enrichment_handler.py",
        )
    )
    lowered = source.lower()
    assert "httpx" not in lowered
    assert "linkedin.com" not in lowered
    assert "requests.get" not in lowered
    assert datetime.now(tz=UTC).tzinfo is not None
