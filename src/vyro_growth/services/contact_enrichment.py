from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.domain import (
    ContactFactType,
    ContactVerificationStatus,
    EnrichmentRunStatus,
    WebsiteFactType,
)
from vyro_growth.models import Activity, Contact, EnrichmentRun, Organization, SourceEvidence
from vyro_growth.providers.decision_makers import (
    DECISION_MAKER_SOURCE,
    EMAIL_MAX_LENGTH,
    EVIDENCE_SNIPPET_MAX_LENGTH,
    FULL_NAME_MAX_LENGTH,
    PHONE_MAX_LENGTH,
    PROVIDER_MAX_LENGTH,
    SOURCE_URL_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    CandidateDisposition,
    ClassifiedDecisionMaker,
    ContactSkipReason,
    DecisionMakerCandidate,
    DecisionMakerEnrichmentProvider,
    DecisionMakerEnrichmentRequest,
    OrganizationContactContext,
    WebsiteFactContext,
    classify_candidate,
    clean_optional_text,
    clip_text,
    contact_dedupe_key,
    rank_classified,
    skip_reason_value,
)

logger = structlog.get_logger(__name__)

CONTACT_ENRICHMENT_ACTOR = "decision_maker_enrichment"
BATCH_MAX = 200
DEFAULT_MAX_CANDIDATES = 10


class ContactEnrichmentError(ValueError):
    """Raised when a decision-maker enrichment job cannot load the organization."""


@dataclass(frozen=True)
class ContactEnrichmentResult:
    enrichment_run_id: UUID
    organization_id: UUID
    contacts_upserted: int
    contacts_skipped: int
    candidates_considered: int
    status: EnrichmentRunStatus
    provider_name: str


class ContactEnrichmentService:
    """Persist provider-supplied professional contacts. Does not send outreach."""

    def __init__(
        self,
        provider: DecisionMakerEnrichmentProvider,
        *,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ) -> None:
        self._provider = provider
        self._max_candidates = max(1, max_candidates)

    def enrich_organization(
        self,
        db: Session,
        organization_id: UUID,
    ) -> ContactEnrichmentResult:
        organization = db.get(Organization, organization_id)
        if organization is None:
            raise ContactEnrichmentError(f"Organization not found: {organization_id}")

        run = EnrichmentRun(
            organization_id=organization.id,
            source=DECISION_MAKER_SOURCE,
            status=EnrichmentRunStatus.RUNNING.value,
            input_params={"max_candidates": self._max_candidates},
            started_at=datetime.now(tz=UTC),
        )
        db.add(run)
        db.flush()

        try:
            result = self._enrich(db, organization, run)
        except ContactEnrichmentError:
            raise
        except Exception as exc:
            run.status = EnrichmentRunStatus.FAILED.value
            run.finished_at = datetime.now(tz=UTC)
            run.error_message = str(exc)
            self._record_activity(
                db,
                action="decision_maker_enrichment_failed",
                details={
                    "enrichment_run_id": str(run.id),
                    "organization_id": str(organization.id),
                    "error": str(exc),
                    "outbound_attempted": False,
                },
            )
            db.commit()
            logger.exception(
                "decision_maker_enrichment_failed",
                enrichment_run_id=str(run.id),
                organization_id=str(organization.id),
            )
            raise

        db.commit()
        logger.info(
            "decision_maker_enrichment_completed",
            enrichment_run_id=str(result.enrichment_run_id),
            organization_id=str(result.organization_id),
            contacts_upserted=result.contacts_upserted,
            contacts_skipped=result.contacts_skipped,
        )
        return result

    def enrich_batch(
        self,
        db: Session,
        *,
        limit: int = 50,
        state: str | None = None,
        city: str | None = None,
    ) -> tuple[ContactEnrichmentResult, ...]:
        query = select(Organization).order_by(Organization.created_at.asc())
        if state:
            query = query.where(Organization.state == state.strip().upper())
        if city:
            query = query.where(Organization.city == city.strip().upper())
        organizations = db.scalars(query.limit(min(max(limit, 1), BATCH_MAX))).all()
        return tuple(
            self.enrich_organization(db, organization.id) for organization in organizations
        )

    def _enrich(
        self,
        db: Session,
        organization: Organization,
        run: EnrichmentRun,
    ) -> ContactEnrichmentResult:
        context = self._organization_context(db, organization)
        request = DecisionMakerEnrichmentRequest(
            organization=context,
            max_candidates=self._max_candidates,
        )
        provider_result = self._provider.enrich_decision_makers(request)
        considered = max(provider_result.raw_count, len(provider_result.candidates))
        classified: list[ClassifiedDecisionMaker] = []
        skipped: list[dict[str, str]] = []
        parse_failures = max(0, considered - len(provider_result.candidates))
        if parse_failures:
            skipped.extend(
                {
                    "reason": skip_reason_value(ContactSkipReason.MALFORMED),
                    "name": "",
                    "detail": "unparseable_provider_result",
                }
                for _ in range(parse_failures)
            )
        for candidate in provider_result.candidates:
            disposition = classify_candidate(candidate, organization=context)
            self._record_disposition(disposition, classified, skipped, candidate)

        ranked = rank_classified(classified)[: self._max_candidates]
        upserted = 0
        seen_keys: set[str] = set()
        for item in ranked:
            if item.dedupe_key in seen_keys:
                skipped.append(
                    {
                        "reason": skip_reason_value(ContactSkipReason.MALFORMED),
                        "name": item.candidate.full_name,
                        "detail": "duplicate_in_result",
                    }
                )
                continue
            seen_keys.add(item.dedupe_key)
            contact = self._upsert_contact(db, organization, item)
            self._persist_evidence(db, organization, run, contact, item)
            upserted += 1

        run.candidates_considered = considered
        run.contacts_upserted = upserted
        run.contacts_skipped = len(skipped) + max(0, len(classified) - len(ranked))
        run.facts_extracted = upserted
        run.status = EnrichmentRunStatus.COMPLETED.value
        run.finished_at = datetime.now(tz=UTC)
        run.input_params = {
            "max_candidates": self._max_candidates,
            "provider": provider_result.provider_name,
            "skip_reasons": skipped,
            "fabricated_facts": False,
            "outbound_attempted": False,
        }

        self._record_activity(
            db,
            action="decision_maker_enrichment_completed",
            details={
                "enrichment_run_id": str(run.id),
                "organization_id": str(organization.id),
                "provider": provider_result.provider_name,
                "contacts_upserted": upserted,
                "contacts_skipped": run.contacts_skipped,
                "candidates_considered": considered,
                "skip_reasons": skipped,
                "fabricated_facts": False,
                "outbound_attempted": False,
            },
        )
        return ContactEnrichmentResult(
            enrichment_run_id=run.id,
            organization_id=organization.id,
            contacts_upserted=upserted,
            contacts_skipped=run.contacts_skipped,
            candidates_considered=considered,
            status=EnrichmentRunStatus.COMPLETED,
            provider_name=provider_result.provider_name,
        )

    def _record_disposition(
        self,
        disposition: CandidateDisposition,
        classified: list[ClassifiedDecisionMaker],
        skipped: list[dict[str, str]],
        candidate: DecisionMakerCandidate,
    ) -> None:
        if disposition.classified is not None:
            classified.append(disposition.classified)
            return
        reason = disposition.skip_reason or ContactSkipReason.MALFORMED
        skipped.append(
            {
                "reason": skip_reason_value(reason),
                "name": clean_optional_text(candidate.full_name) or "",
                "detail": disposition.skip_detail or "",
            }
        )

    def _organization_context(
        self,
        db: Session,
        organization: Organization,
    ) -> OrganizationContactContext:
        evidence_rows = db.scalars(
            select(SourceEvidence)
            .where(SourceEvidence.organization_id == organization.id)
            .order_by(SourceEvidence.created_at.asc())
        ).all()
        facts: list[WebsiteFactContext] = []
        for row in evidence_rows:
            if row.claim_type not in {
                WebsiteFactType.OWNERSHIP_SIGNAL.value,
                WebsiteFactType.PROVIDER_COUNT.value,
                WebsiteFactType.PRACTICE_SIZE_SIGNAL.value,
                WebsiteFactType.OFFICIAL_WEBSITE.value,
                WebsiteFactType.BUSINESS_EMAIL.value,
                WebsiteFactType.BUSINESS_PHONE.value,
            }:
                continue
            facts.append(
                WebsiteFactContext(
                    fact_type=row.claim_type,
                    value=row.extracted_value,
                    confidence=row.confidence,
                    source_url=row.source_url,
                    snippet=row.evidence_snippet,
                )
            )
        return OrganizationContactContext(
            organization_id=organization.id,
            name=organization.name,
            npi=organization.npi,
            city=organization.city,
            state=organization.state,
            specialty=organization.specialty,
            website=organization.website,
            website_match_status=organization.website_match_status,
            website_facts=tuple(facts),
        )

    def _upsert_contact(
        self,
        db: Session,
        organization: Organization,
        item: ClassifiedDecisionMaker,
    ) -> Contact:
        existing = self._find_existing(db, organization.id, item)
        verification = item.candidate.verification_status
        email_verified = (
            verification is ContactVerificationStatus.PROVIDER_VERIFIED
            and item.business_email is not None
        )
        provenance = _provenance_payload(item)
        name = clip_text(item.candidate.full_name.strip(), FULL_NAME_MAX_LENGTH)
        title = (
            clip_text(item.candidate.title, TITLE_MAX_LENGTH) if item.candidate.title else None
        )
        if existing is None:
            contact = Contact(
                organization_id=organization.id,
                full_name=name,
                title=title,
                email=item.business_email,
                phone=item.business_phone,
                email_verified=email_verified,
                role_category=item.role_category.value,
                role_rank=item.role_rank,
                source_provider=clip_text(item.candidate.source_provider, PROVIDER_MAX_LENGTH),
                source_timestamp=item.candidate.source_timestamp,
                confidence=item.candidate.confidence,
                verification_status=verification.value,
                provenance_json=provenance,
                dedupe_key=item.dedupe_key,
            )
            db.add(contact)
            db.flush()
            return contact

        existing.full_name = name
        if title:
            existing.title = title
        if item.business_email:
            existing.email = clip_text(item.business_email, EMAIL_MAX_LENGTH)
        if item.business_phone:
            existing.phone = clip_text(item.business_phone, PHONE_MAX_LENGTH)
        if existing.role_rank is None or item.role_rank <= existing.role_rank:
            existing.role_category = item.role_category.value
            existing.role_rank = item.role_rank
        existing.source_provider = clip_text(item.candidate.source_provider, PROVIDER_MAX_LENGTH)
        existing.source_timestamp = item.candidate.source_timestamp
        if item.candidate.confidence is not None:
            existing.confidence = item.candidate.confidence
        existing.verification_status = verification.value
        if email_verified:
            existing.email_verified = True
        existing.provenance_json = provenance
        existing.dedupe_key = item.dedupe_key
        db.flush()
        return existing

    def _find_existing(
        self,
        db: Session,
        organization_id: UUID,
        item: ClassifiedDecisionMaker,
    ) -> Contact | None:
        keys = [item.dedupe_key]
        name_key = contact_dedupe_key(
            email=None,
            source_provider=item.candidate.source_provider,
            provider_record_id=None,
            full_name=item.candidate.full_name,
            title=item.candidate.title,
        )
        if name_key not in keys:
            keys.append(name_key)
        if item.candidate.provider_record_id:
            provider_key = contact_dedupe_key(
                email=None,
                source_provider=item.candidate.source_provider,
                provider_record_id=item.candidate.provider_record_id,
                full_name=item.candidate.full_name,
                title=item.candidate.title,
            )
            if provider_key not in keys:
                keys.append(provider_key)
        existing = db.scalar(
            select(Contact).where(
                Contact.organization_id == organization_id,
                Contact.dedupe_key.in_(keys),
            )
        )
        if existing is not None:
            return existing
        if item.business_email:
            return db.scalar(
                select(Contact).where(
                    Contact.organization_id == organization_id,
                    Contact.email == item.business_email,
                )
            )
        return None

    def _persist_evidence(
        self,
        db: Session,
        organization: Organization,
        run: EnrichmentRun,
        contact: Contact,
        item: ClassifiedDecisionMaker,
    ) -> None:
        provider_label = item.candidate.source_provider
        source_url = item.candidate.provenance.source_url or f"provider:{provider_label}"
        snippet = item.candidate.provenance.evidence_snippet
        evidence_snippet = (
            clip_text(snippet, EVIDENCE_SNIPPET_MAX_LENGTH) if snippet else None
        )
        db.add(
            SourceEvidence(
                organization_id=organization.id,
                enrichment_run_id=run.id,
                contact_id=contact.id,
                source_url=clip_text(source_url, SOURCE_URL_MAX_LENGTH),
                claim_type=ContactFactType.DECISION_MAKER_CONTACT.value,
                extracted_value=contact.full_name,
                confidence=item.candidate.confidence,
                evidence_snippet=evidence_snippet,
                metadata_json={
                    "role_category": item.role_category.value,
                    "role_rank": item.role_rank,
                    "title": contact.title,
                    "has_business_email": contact.email is not None,
                    "has_business_phone": contact.phone is not None,
                    "source_provider": item.candidate.source_provider,
                    "verification_status": item.candidate.verification_status.value,
                    "fabricated": False,
                    "provider_record_id": item.candidate.provider_record_id,
                    "owner_operator_evidence": item.candidate.owner_operator_evidence,
                },
            )
        )

    def _record_activity(
        self,
        db: Session,
        *,
        action: str,
        details: dict[str, object],
    ) -> None:
        db.add(
            Activity(
                lead_id=None,
                actor=CONTACT_ENRICHMENT_ACTOR,
                action=action,
                details=details,
            )
        )


def _provenance_payload(item: ClassifiedDecisionMaker) -> dict[str, object]:
    provenance = item.candidate.provenance
    return {
        "source_url": provenance.source_url,
        "evidence_snippet": provenance.evidence_snippet,
        "metadata": provenance.metadata,
        "provider_record_id": item.candidate.provider_record_id,
        "owner_operator_evidence": item.candidate.owner_operator_evidence,
        "fabricated": False,
    }
