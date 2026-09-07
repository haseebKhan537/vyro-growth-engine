"""Dry-run email verification and pattern-inference service.

Phase 69 stores verifier verdicts and inferred/unverified candidates. It does
not send email, enroll campaigns, call SMTP recipient servers, or call live
verifiers unless a test injects a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings, get_settings
from vyro_growth.domain import (
    ContactFactType,
    ContactVerificationStatus,
    EmailCandidateOrigin,
    EmailVerificationOutcome,
    EmailVerificationVerdict,
    EnrichmentRunStatus,
)
from vyro_growth.models import (
    Activity,
    Contact,
    EmailPatternCandidate,
    EnrichmentRun,
    Organization,
    SourceEvidence,
)
from vyro_growth.providers.decision_makers import (
    EMAIL_MAX_LENGTH,
    EVIDENCE_SNIPPET_MAX_LENGTH,
    SOURCE_URL_MAX_LENGTH,
    clean_optional_text,
    clip_text,
)
from vyro_growth.providers.email_verification import (
    EMAIL_VERIFICATION_SOURCE,
    NO_VERIFIED_EMAIL,
    STUB_PROVIDER_NAME,
    EmailVerificationProvider,
    EmailVerificationProviderError,
    EmailVerificationRequest,
    EmailVerificationResult,
    LiveEmailVerificationDisabledError,
    LiveEmailVerificationNotImplementedError,
    MalformedEmailVerificationOutput,
    RetryableEmailVerificationError,
    build_email_verification_provider,
    is_verified_safe_verdict,
    outcome_for_verdict,
    parse_email_verification_result,
    parse_email_verification_verdict,
    sanitize_verification_details,
    verification_status_for_verdict,
)
from vyro_growth.services.email_pattern_inference import (
    NamedPerson,
    candidate_idempotency_key,
    infer_email_candidates,
)
from vyro_growth.services.operator_halt import read_operator_halt

logger = structlog.get_logger(__name__)

EMAIL_VERIFICATION_ACTOR = "email_verification"
BATCH_MAX = 200


class EmailVerificationError(ValueError):
    """Raised when a dry-run email verification job cannot load the requested records."""


@dataclass(frozen=True)
class EmailVerificationItemResult:
    contact_id: UUID
    organization_id: UUID
    outcome: EmailVerificationOutcome
    verdict: EmailVerificationVerdict | None
    origin: EmailCandidateOrigin
    reused: bool
    promoted: bool
    dry_run: bool
    live_call_attempted: bool
    smtp_attempted: bool
    provider_name: str


@dataclass(frozen=True)
class EmailVerificationRunResult:
    enrichment_run_id: UUID
    organization_id: UUID
    contacts_considered: int
    verified_count: int
    no_verified_email_count: int
    inferred_count: int
    promoted_count: int
    reused_count: int
    status: EnrichmentRunStatus
    provider_name: str
    items: tuple[EmailVerificationItemResult, ...]


class EmailVerificationService:
    """Verify stored business emails and optionally infer same-domain candidates."""

    def __init__(
        self,
        provider: EmailVerificationProvider | None = None,
        *,
        settings: Settings | None = None,
        infer_patterns: bool = True,
    ) -> None:
        self._settings = settings or get_settings()
        self._provider = provider or build_email_verification_provider(self._settings)
        self._infer_patterns = infer_patterns

    def verify_organization(
        self,
        db: Session,
        organization_id: UUID,
        *,
        commit: bool = True,
    ) -> EmailVerificationRunResult:
        organization = db.get(Organization, organization_id)
        if organization is None:
            raise EmailVerificationError(f"Organization not found: {organization_id}")
        return self._verify(
            db,
            organizations=(organization,),
            input_params={"organization_id": str(organization_id)},
            commit=commit,
        )[0]

    def verify_batch(
        self,
        db: Session,
        *,
        limit: int = 50,
        state: str | None = None,
        city: str | None = None,
        commit: bool = True,
    ) -> tuple[EmailVerificationRunResult, ...]:
        query = select(Organization).order_by(Organization.created_at.asc())
        if state:
            query = query.where(Organization.state == state.strip().upper())
        if city:
            query = query.where(Organization.city == city.strip().upper())
        organizations = tuple(db.scalars(query.limit(min(max(limit, 1), BATCH_MAX))).all())
        if not organizations:
            return ()
        return self._verify(
            db,
            organizations=organizations,
            input_params={
                "limit": min(max(limit, 1), BATCH_MAX),
                "state": state,
                "city": city,
            },
            commit=commit,
        )

    def _verify(
        self,
        db: Session,
        *,
        organizations: tuple[Organization, ...],
        input_params: dict[str, object],
        commit: bool,
    ) -> tuple[EmailVerificationRunResult, ...]:
        halt_before = read_operator_halt(db)
        results: list[EmailVerificationRunResult] = []
        for organization in organizations:
            results.append(
                self._verify_one(
                    db,
                    organization=organization,
                    input_params=input_params,
                )
            )
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("email verification must not change operator halt status")
        if commit:
            db.commit()
        return tuple(results)

    def _verify_one(
        self,
        db: Session,
        *,
        organization: Organization,
        input_params: dict[str, object],
    ) -> EmailVerificationRunResult:
        run = EnrichmentRun(
            organization_id=organization.id,
            source=EMAIL_VERIFICATION_SOURCE,
            status=EnrichmentRunStatus.RUNNING.value,
            started_at=datetime.now(tz=UTC),
            input_params={
                **input_params,
                "dry_run": True,
                "outbound_attempted": False,
                "live_call_attempted": False,
                "smtp_attempted": False,
                "infer_patterns": self._infer_patterns,
                "provider": "stub" if not getattr(self._provider, "live", False) else "live",
            },
        )
        db.add(run)
        db.flush()
        items: list[EmailVerificationItemResult] = []
        skip_reasons: list[dict[str, object]] = []
        try:
            contacts = list(
                db.scalars(
                    select(Contact)
                    .where(Contact.organization_id == organization.id)
                    .order_by(Contact.created_at.asc())
                ).all()
            )
            for contact in contacts:
                email = clean_optional_text(contact.email)
                if email is None:
                    continue
                items.append(
                    self._verify_stored_contact(
                        db,
                        run=run,
                        organization=organization,
                        contact=contact,
                        email=email,
                    )
                )
            if self._infer_patterns:
                inferred_items, inferred_skips = self._infer_and_verify(
                    db,
                    run=run,
                    organization=organization,
                    contacts=contacts,
                )
                items.extend(inferred_items)
                skip_reasons.extend(inferred_skips)
        except EmailVerificationError:
            raise
        except Exception as exc:
            run.status = EnrichmentRunStatus.FAILED.value
            run.finished_at = datetime.now(tz=UTC)
            error_category = _error_category(str(exc))
            run.error_message = error_category
            self._record_activity(
                db,
                action="email_verification_failed",
                details={
                    "enrichment_run_id": str(run.id),
                    "organization_id": str(organization.id),
                    "error_category": error_category,
                    "outbound_attempted": False,
                    "live_call_attempted": False,
                    "smtp_attempted": False,
                },
            )
            db.flush()
            logger.error(
                "email_verification_failed",
                enrichment_run_id=str(run.id),
                error_category=error_category,
            )
            raise

        verified = sum(1 for item in items if item.outcome is EmailVerificationOutcome.VERIFIED)
        no_verified = sum(
            1 for item in items if item.outcome is EmailVerificationOutcome.NO_VERIFIED_EMAIL
        )
        inferred = sum(1 for item in items if item.origin is EmailCandidateOrigin.INFERRED)
        promoted = sum(1 for item in items if item.promoted)
        reused = sum(1 for item in items if item.reused)
        if not any(item.outcome is EmailVerificationOutcome.VERIFIED for item in items):
            skip_reasons.append({"reason": NO_VERIFIED_EMAIL})
        run.input_params = {
            **dict(run.input_params or {}),
            "skip_reasons": skip_reasons,
            "inferred_count": inferred,
            "promoted_count": promoted,
        }
        run.candidates_considered = len(items)
        run.contacts_upserted = promoted
        run.contacts_skipped = no_verified
        run.facts_extracted = verified
        run.status = EnrichmentRunStatus.COMPLETED.value
        run.finished_at = datetime.now(tz=UTC)
        self._record_activity(
            db,
            action="email_verification_completed",
            details={
                "enrichment_run_id": str(run.id),
                "organization_id": str(organization.id),
                "contacts_considered": len(items),
                "verified_count": verified,
                "no_verified_email_count": no_verified,
                "inferred_count": inferred,
                "promoted_count": promoted,
                "reused_count": reused,
                "dry_run": True,
                "outbound_attempted": False,
                "live_call_attempted": False,
                "smtp_attempted": False,
                "provider": (
                    STUB_PROVIDER_NAME if not getattr(self._provider, "live", False) else "live"
                ),
            },
        )
        db.flush()
        logger.info(
            "email_verification_completed",
            enrichment_run_id=str(run.id),
            verified=verified,
            no_verified_email=no_verified,
            inferred=inferred,
        )
        return EmailVerificationRunResult(
            enrichment_run_id=run.id,
            organization_id=organization.id,
            contacts_considered=len(items),
            verified_count=verified,
            no_verified_email_count=no_verified,
            inferred_count=inferred,
            promoted_count=promoted,
            reused_count=reused,
            status=EnrichmentRunStatus.COMPLETED,
            provider_name=STUB_PROVIDER_NAME
            if not getattr(self._provider, "live", False)
            else "live",
            items=tuple(items),
        )

    def _verify_stored_contact(
        self,
        db: Session,
        *,
        run: EnrichmentRun,
        organization: Organization,
        contact: Contact,
        email: str,
    ) -> EmailVerificationItemResult:
        origin = _origin_from_contact(contact)
        existing_verdict = parse_email_verification_verdict(contact.email_verification_verdict)
        if (
            existing_verdict is not None
            and contact.email_verification_checked_at is not None
            and clean_optional_text(contact.email) == email.lower()
        ):
            return EmailVerificationItemResult(
                contact_id=contact.id,
                organization_id=organization.id,
                outcome=outcome_for_verdict(existing_verdict),
                verdict=existing_verdict,
                origin=origin,
                reused=True,
                promoted=False,
                dry_run=True,
                live_call_attempted=False,
                smtp_attempted=False,
                provider_name=contact.email_verification_provider or STUB_PROVIDER_NAME,
            )
        result = self._call_provider(
            EmailVerificationRequest(
                email=email,
                organization_id=organization.id,
                contact_id=contact.id,
                origin=origin,
            )
        )
        self._apply_contact_verdict(contact, result=result, origin=origin, promoted=False)
        self._persist_evidence(
            db,
            organization=organization,
            run=run,
            contact=contact,
            result=result,
            claim_type=ContactFactType.EMAIL_VERIFICATION,
            pattern_name=None,
            promoted=False,
        )
        return EmailVerificationItemResult(
            contact_id=contact.id,
            organization_id=organization.id,
            outcome=result.outcome,
            verdict=result.verdict,
            origin=origin,
            reused=False,
            promoted=False,
            dry_run=result.dry_run,
            live_call_attempted=result.live_call_attempted,
            smtp_attempted=result.smtp_attempted,
            provider_name=result.provider_name,
        )

    def _infer_and_verify(
        self,
        db: Session,
        *,
        run: EnrichmentRun,
        organization: Organization,
        contacts: list[Contact],
    ) -> tuple[list[EmailVerificationItemResult], list[dict[str, object]]]:
        people = tuple(_named_person(contact) for contact in contacts)
        generated = infer_email_candidates(people)
        items: list[EmailVerificationItemResult] = []
        skips: list[dict[str, object]] = []
        if not generated:
            return items, skips
        contacts_by_id = {contact.id: contact for contact in contacts}
        for candidate in generated:
            contact = contacts_by_id.get(candidate.contact_id)
            if contact is None:
                continue
            row, created = self._upsert_inferred_candidate(
                db,
                organization=organization,
                contact=contact,
                candidate_email=candidate.candidate_email,
                pattern_name=candidate.pattern_name.value,
                source_contact_id=candidate.source_contact_id,
            )
            if row.promoted or row.verification_verdict is not None:
                existing_verdict = parse_email_verification_verdict(row.verification_verdict)
                items.append(
                    EmailVerificationItemResult(
                        contact_id=contact.id,
                        organization_id=organization.id,
                        outcome=(
                            outcome_for_verdict(existing_verdict)
                            if existing_verdict is not None
                            else EmailVerificationOutcome.NO_VERIFIED_EMAIL
                        ),
                        verdict=existing_verdict,
                        origin=EmailCandidateOrigin.INFERRED,
                        reused=True,
                        promoted=False,
                        dry_run=True,
                        live_call_attempted=False,
                        smtp_attempted=False,
                        provider_name=STUB_PROVIDER_NAME,
                    )
                )
                continue
            result = self._call_provider(
                EmailVerificationRequest(
                    email=candidate.candidate_email,
                    organization_id=organization.id,
                    contact_id=contact.id,
                    origin=EmailCandidateOrigin.INFERRED,
                )
            )
            row.verification_verdict = result.verdict.value
            row.verification_status = result.verification_status.value
            row.live_call_attempted = result.live_call_attempted
            row.smtp_attempted = result.smtp_attempted
            row.dry_run = True
            row.details_json = sanitize_verification_details(
                verdict=result.verdict,
                outcome=result.outcome,
                origin=EmailCandidateOrigin.INFERRED,
                pattern_name=candidate.pattern_name.value,
                reused=not created,
            )
            promoted = False
            if result.verdict is EmailVerificationVerdict.VALID and clean_optional_text(
                contact.email
            ) is None:
                self._apply_contact_verdict(
                    contact,
                    result=result,
                    origin=EmailCandidateOrigin.INFERRED,
                    promoted=True,
                )
                row.promoted = True
                promoted = True
            elif result.verdict is not EmailVerificationVerdict.VALID:
                skips.append({"reason": NO_VERIFIED_EMAIL, "origin": "inferred"})
            self._persist_evidence(
                db,
                organization=organization,
                run=run,
                contact=contact,
                result=result,
                claim_type=ContactFactType.EMAIL_PATTERN_INFERENCE,
                pattern_name=candidate.pattern_name.value,
                promoted=promoted,
            )
            items.append(
                EmailVerificationItemResult(
                    contact_id=contact.id,
                    organization_id=organization.id,
                    outcome=result.outcome,
                    verdict=result.verdict,
                    origin=EmailCandidateOrigin.INFERRED,
                    reused=not created,
                    promoted=promoted,
                    dry_run=result.dry_run,
                    live_call_attempted=result.live_call_attempted,
                    smtp_attempted=result.smtp_attempted,
                    provider_name=result.provider_name,
                )
            )
        return items, skips

    def _upsert_inferred_candidate(
        self,
        db: Session,
        *,
        organization: Organization,
        contact: Contact,
        candidate_email: str,
        pattern_name: str,
        source_contact_id: UUID,
    ) -> tuple[EmailPatternCandidate, bool]:
        key = candidate_idempotency_key(contact_id=contact.id, candidate_email=candidate_email)
        existing = db.scalar(
            select(EmailPatternCandidate).where(EmailPatternCandidate.idempotency_key == key)
        )
        if existing is not None:
            return existing, False
        row = EmailPatternCandidate(
            organization_id=organization.id,
            contact_id=contact.id,
            source_contact_id=source_contact_id,
            candidate_email=clip_text(candidate_email.lower(), EMAIL_MAX_LENGTH),
            pattern_name=pattern_name,
            origin=EmailCandidateOrigin.INFERRED.value,
            promoted=False,
            verification_status=ContactVerificationStatus.INFERRED.value,
            idempotency_key=key,
            dry_run=True,
            live_call_attempted=False,
            smtp_attempted=False,
            details_json=sanitize_verification_details(
                verdict=EmailVerificationVerdict.UNVERIFIED,
                outcome=EmailVerificationOutcome.NO_VERIFIED_EMAIL,
                origin=EmailCandidateOrigin.INFERRED,
                pattern_name=pattern_name,
            ),
        )
        db.add(row)
        db.flush()
        return row, True

    def _apply_contact_verdict(
        self,
        contact: Contact,
        *,
        result: EmailVerificationResult,
        origin: EmailCandidateOrigin,
        promoted: bool,
    ) -> None:
        if promoted:
            contact.email = clip_text(result.email.lower(), EMAIL_MAX_LENGTH)
            contact.email_origin = EmailCandidateOrigin.INFERRED.value
        elif contact.email_origin is None:
            contact.email_origin = origin.value
        contact.email_verification_verdict = result.verdict.value
        contact.email_verification_provider = result.provider_name
        contact.email_verification_checked_at = result.checked_at
        contact.verification_status = verification_status_for_verdict(
            result.verdict, origin=origin
        ).value
        contact.email_verified = result.verdict is EmailVerificationVerdict.VALID
        provenance = dict(contact.provenance_json or {})
        provenance["email_verification"] = sanitize_verification_details(
            verdict=result.verdict,
            outcome=result.outcome,
            origin=origin,
            promoted=promoted,
        )
        contact.provenance_json = provenance

    def _call_provider(self, request: EmailVerificationRequest) -> EmailVerificationResult:
        try:
            parsed = parse_email_verification_result(self._provider.verify_email(request))
        except LiveEmailVerificationDisabledError:
            return _unverified_result(request, provider_name="disabled")
        except LiveEmailVerificationNotImplementedError:
            return _unverified_result(request, provider_name="not_implemented")
        except MalformedEmailVerificationOutput:
            return _unverified_result(request, provider_name="malformed")
        except RetryableEmailVerificationError:
            return _unverified_result(request, provider_name="retryable")
        except EmailVerificationProviderError:
            return _unverified_result(request, provider_name="error")
        return parsed

    def _persist_evidence(
        self,
        db: Session,
        *,
        organization: Organization,
        run: EnrichmentRun,
        contact: Contact,
        result: EmailVerificationResult,
        claim_type: ContactFactType,
        pattern_name: str | None,
        promoted: bool,
    ) -> None:
        db.add(
            SourceEvidence(
                organization_id=organization.id,
                enrichment_run_id=run.id,
                contact_id=contact.id,
                source_url=clip_text(f"provider:{result.provider_name}", SOURCE_URL_MAX_LENGTH),
                claim_type=claim_type.value,
                extracted_value=result.verdict.value,
                confidence=1.0 if result.verdict is EmailVerificationVerdict.VALID else None,
                evidence_snippet=clip_text(result.outcome.value, EVIDENCE_SNIPPET_MAX_LENGTH),
                metadata_json=sanitize_verification_details(
                    verdict=result.verdict,
                    outcome=result.outcome,
                    origin=result.origin,
                    pattern_name=pattern_name,
                    promoted=promoted,
                    extra={"has_email": True, "fabricated": False},
                ),
            )
        )

    def _record_activity(self, db: Session, *, action: str, details: dict[str, object]) -> None:
        db.add(
            Activity(
                lead_id=None,
                actor=EMAIL_VERIFICATION_ACTOR,
                action=action,
                details=details,
            )
        )


def contact_is_verified_safe(contact: Contact) -> bool:
    """Enrollment/readiness gate: a stored email with a verifier-valid verdict."""
    if clean_optional_text(contact.email) is None:
        return False
    if not contact.email_verified:
        return False
    return is_verified_safe_verdict(contact.email_verification_verdict)


def _named_person(contact: Contact) -> NamedPerson:
    return NamedPerson(
        contact_id=contact.id,
        full_name=contact.full_name,
        email=clean_optional_text(contact.email),
        email_verified_safe=contact_is_verified_safe(contact),
    )


def _origin_from_contact(contact: Contact) -> EmailCandidateOrigin:
    if contact.email_origin == EmailCandidateOrigin.INFERRED.value:
        return EmailCandidateOrigin.INFERRED
    return EmailCandidateOrigin.STORED


def _unverified_result(
    request: EmailVerificationRequest,
    *,
    provider_name: str,
) -> EmailVerificationResult:
    return EmailVerificationResult(
        email=request.email.lower(),
        verdict=EmailVerificationVerdict.UNVERIFIED,
        outcome=EmailVerificationOutcome.NO_VERIFIED_EMAIL,
        dry_run=True,
        live_call_attempted=False,
        smtp_attempted=False,
        provider_name=provider_name,
        checked_at=datetime.now(tz=UTC),
        origin=request.origin,
        verification_status=verification_status_for_verdict(
            EmailVerificationVerdict.UNVERIFIED,
            origin=request.origin,
        ),
        raw={"dry_run": True},
    )


def _error_category(error_message: str) -> str:
    text = error_message.lower()
    if "disabled" in text:
        return "live_disabled"
    if "smtp" in text:
        return "smtp_forbidden"
    if "not implemented" in text or "does not perform live" in text:
        return "not_implemented"
    if "api key" in text or "base url" in text or "not configured" in text:
        return "missing_config"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "malformed" in text:
        return "malformed"
    return "unknown"
