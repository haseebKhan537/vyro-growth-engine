"""Isolated email-pattern inference helpers.

Phase 69 infers candidate emails only from already verified same-domain
business emails plus known public names. It never invents a pattern, never
contacts SMTP servers, and never promotes a candidate without verification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Never
from uuid import UUID

from vyro_growth.domain import EmailCandidateOrigin, EmailPatternName
from vyro_growth.providers.decision_makers import (
    EMAIL_MAX_LENGTH,
    EMAIL_RE,
    PERSONAL_EMAIL_DOMAINS,
    clean_optional_text,
    clip_text,
)

NAME_TOKEN_RE = re.compile(r"[^a-z]+")
LOCAL_PART_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$")


@dataclass(frozen=True)
class NamedPerson:
    contact_id: UUID
    full_name: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    email_verified_safe: bool = False


@dataclass(frozen=True)
class InferredEmailCandidate:
    contact_id: UUID
    source_contact_id: UUID
    full_name: str
    candidate_email: str
    domain: str
    pattern_name: EmailPatternName
    origin: EmailCandidateOrigin = EmailCandidateOrigin.INFERRED
    unverified: bool = True
    invented: bool = False


def split_person_name(full_name: str | None) -> tuple[str | None, str | None]:
    cleaned = clean_optional_text(full_name)
    if cleaned is None:
        return None, None
    parts = [part for part in NAME_TOKEN_RE.sub(" ", cleaned.lower()).split() if part]
    if not parts:
        return None, None
    first = parts[0]
    last = parts[-1] if len(parts) > 1 else None
    return first, last


def email_domain(email: str | None) -> str | None:
    cleaned = clean_optional_text(email)
    if cleaned is None or "@" not in cleaned:
        return None
    domain = cleaned.rsplit("@", maxsplit=1)[1].lower().strip()
    return domain or None


def is_business_email_domain(domain: str | None) -> bool:
    if domain is None or "." not in domain:
        return False
    return domain not in PERSONAL_EMAIL_DOMAINS


def apply_pattern(
    pattern: EmailPatternName,
    *,
    first: str,
    last: str | None,
    domain: str,
) -> str | None:
    local = _local_part(pattern, first=first, last=last)
    if local is None or not LOCAL_PART_RE.match(local):
        return None
    candidate = f"{local}@{domain}"
    if not EMAIL_RE.match(candidate):
        return None
    return clip_text(candidate, EMAIL_MAX_LENGTH)


def detect_pattern(email: str, *, first: str, last: str | None) -> EmailPatternName | None:
    cleaned = clean_optional_text(email)
    if cleaned is None or not EMAIL_RE.match(cleaned.lower()):
        return None
    local = cleaned.lower().rsplit("@", maxsplit=1)[0]
    matches = [
        pattern
        for pattern in EmailPatternName
        if _local_part(pattern, first=first, last=last) == local
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def infer_domain_pattern(people: tuple[NamedPerson, ...]) -> tuple[str, EmailPatternName] | None:
    """Return a unique verified same-domain pattern, or None if it cannot be determined."""
    verified: list[tuple[str, EmailPatternName, str]] = []
    for person in people:
        if not person.email_verified_safe:
            continue
        first, last = _names(person)
        if first is None:
            continue
        domain = email_domain(person.email)
        if not is_business_email_domain(domain) or person.email is None:
            continue
        pattern = detect_pattern(person.email, first=first, last=last)
        if pattern is None:
            continue
        assert domain is not None
        verified.append((domain, pattern, person.email.lower()))
    if not verified:
        return None
    domains = {item[0] for item in verified}
    patterns = {item[1] for item in verified}
    if len(domains) != 1 or len(patterns) != 1:
        return None
    domain, pattern, _email = verified[0]
    return domain, pattern


def infer_email_candidates(people: tuple[NamedPerson, ...]) -> tuple[InferredEmailCandidate, ...]:
    """Generate inferred/unverified candidates. Does not invent unmatched patterns."""
    detected = infer_domain_pattern(people)
    if detected is None:
        return ()
    domain, pattern = detected
    source = next(
        person
        for person in people
        if person.email_verified_safe
        and email_domain(person.email) == domain
        and person.email is not None
    )
    existing_emails = {
        person.email.lower()
        for person in people
        if clean_optional_text(person.email) is not None and person.email is not None
    }
    candidates: list[InferredEmailCandidate] = []
    for person in people:
        if person.email_verified_safe:
            continue
        if clean_optional_text(person.email) is not None:
            continue
        first, last = _names(person)
        if first is None:
            continue
        generated = apply_pattern(pattern, first=first, last=last, domain=domain)
        if generated is None or generated.lower() in existing_emails:
            continue
        existing_emails.add(generated.lower())
        candidates.append(
            InferredEmailCandidate(
                contact_id=person.contact_id,
                source_contact_id=source.contact_id,
                full_name=person.full_name,
                candidate_email=generated,
                domain=domain,
                pattern_name=pattern,
            )
        )
    return tuple(candidates)


def candidate_idempotency_key(*, contact_id: UUID, candidate_email: str) -> str:
    return clip_text(f"{contact_id}:{candidate_email.lower()}", 255)


def _names(person: NamedPerson) -> tuple[str | None, str | None]:
    first = clean_optional_text(person.first_name)
    last = clean_optional_text(person.last_name)
    if first is None or last is None:
        split_first, split_last = split_person_name(person.full_name)
        first = first or split_first
        last = last or split_last
    return first, last


def _local_part(pattern: EmailPatternName, *, first: str, last: str | None) -> str | None:
    first_token = first.lower()
    last_token = last.lower() if last else None
    match pattern:
        case EmailPatternName.FIRST_DOT_LAST:
            if last_token is None:
                return None
            return f"{first_token}.{last_token}"
        case EmailPatternName.FIRST_UNDERSCORE_LAST:
            if last_token is None:
                return None
            return f"{first_token}_{last_token}"
        case EmailPatternName.FIRST_LAST:
            if last_token is None:
                return None
            return f"{first_token}{last_token}"
        case EmailPatternName.F_DOT_LAST:
            if last_token is None:
                return None
            return f"{first_token[0]}.{last_token}"
        case EmailPatternName.F_LAST:
            if last_token is None:
                return None
            return f"{first_token[0]}{last_token}"
        case EmailPatternName.FIRST_L:
            if last_token is None:
                return None
            return f"{first_token}{last_token[0]}"
        case EmailPatternName.FIRST:
            return first_token
        case EmailPatternName.LAST:
            return last_token
        case EmailPatternName.LAST_DOT_FIRST:
            if last_token is None:
                return None
            return f"{last_token}.{first_token}"
        case _:
            unreachable: Never = pattern
            raise RuntimeError(f"unhandled email pattern: {unreachable}")
