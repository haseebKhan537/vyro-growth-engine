from __future__ import annotations

from uuid import uuid4

from vyro_growth.domain import EmailCandidateOrigin, EmailPatternName
from vyro_growth.services.email_pattern_inference import (
    NamedPerson,
    apply_pattern,
    detect_pattern,
    infer_domain_pattern,
    infer_email_candidates,
    is_business_email_domain,
)


def _person(
    *,
    full_name: str,
    email: str | None = None,
    verified: bool = False,
    first_name: str | None = None,
    last_name: str | None = None,
) -> NamedPerson:
    return NamedPerson(
        contact_id=uuid4(),
        full_name=full_name,
        first_name=first_name,
        last_name=last_name,
        email=email,
        email_verified_safe=verified,
    )


def test_detects_unique_first_dot_last_pattern() -> None:
    pattern = detect_pattern("jordan.blake@austinfamily.example", first="jordan", last="blake")
    assert pattern is EmailPatternName.FIRST_DOT_LAST
    assert apply_pattern(pattern, first="sam", last="rivera", domain="austinfamily.example") == (
        "sam.rivera@austinfamily.example"
    )


def test_does_not_invent_when_no_verified_pattern() -> None:
    people = (
        _person(full_name="Jordan Blake", email="jordan.blake@austinfamily.example"),
        _person(full_name="Sam Rivera"),
    )
    assert infer_domain_pattern(people) is None
    assert infer_email_candidates(people) == ()


def test_does_not_invent_when_verified_patterns_conflict() -> None:
    people = (
        _person(
            full_name="Jordan Blake",
            email="jordan.blake@austinfamily.example",
            verified=True,
        ),
        _person(
            full_name="Alex Smith",
            email="asmith@austinfamily.example",
            verified=True,
        ),
        _person(full_name="Sam Rivera"),
    )
    assert infer_domain_pattern(people) is None
    assert infer_email_candidates(people) == ()


def test_ignores_personal_email_domains() -> None:
    assert is_business_email_domain("gmail.com") is False
    people = (
        _person(full_name="Jordan Blake", email="jordan.blake@gmail.com", verified=True),
        _person(full_name="Sam Rivera"),
    )
    assert infer_email_candidates(people) == ()


def test_infers_unverified_candidates_from_unique_verified_pattern() -> None:
    source = _person(
        full_name="Jordan Blake",
        email="jordan.blake@austinfamily.example",
        verified=True,
    )
    target = _person(full_name="Sam Rivera")
    people = (source, target)

    candidates = infer_email_candidates(people)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.contact_id == target.contact_id
    assert candidate.source_contact_id == source.contact_id
    assert candidate.candidate_email == "sam.rivera@austinfamily.example"
    assert candidate.pattern_name is EmailPatternName.FIRST_DOT_LAST
    assert candidate.origin is EmailCandidateOrigin.INFERRED
    assert candidate.unverified is True
    assert candidate.invented is False


def test_does_not_overwrite_existing_emails_or_duplicate_candidates() -> None:
    people = (
        _person(
            full_name="Jordan Blake",
            email="jordan.blake@austinfamily.example",
            verified=True,
        ),
        _person(full_name="Sam Rivera", email="office@austinfamily.example"),
        _person(full_name="Sam Rivera"),
    )
    candidates = infer_email_candidates(people)
    assert [item.candidate_email for item in candidates] == ["sam.rivera@austinfamily.example"]


def test_ambiguous_local_part_is_not_a_pattern() -> None:
    assert detect_pattern("jordan@austinfamily.example", first="jordan", last=None) is (
        EmailPatternName.FIRST
    )
    assert detect_pattern("jordan@austinfamily.example", first="jordan", last="blake") is (
        EmailPatternName.FIRST
    )
    assert detect_pattern("not-a-match@austinfamily.example", first="jordan", last="blake") is None
