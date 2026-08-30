from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.domain import (
    EnrichmentRunStatus,
    LeadStage,
    PersonalizationFactType,
    PersonalizationReadiness,
)
from vyro_growth.models import (
    Activity,
    Contact,
    EnrichmentRun,
    Lead,
    LeadScore,
    Organization,
    PersonalizationDraft,
    SourceEvidence,
)
from vyro_growth.providers.decision_makers import clip_text
from vyro_growth.providers.personalization import (
    DEFAULT_OFFER,
    PERSONALIZATION_SOURCE,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    ContactContext,
    EvidenceItem,
    MalformedPersonalizationOutput,
    OrganizationContext,
    PersonalizationEvidencePack,
    PersonalizationProvider,
    PersonalizationProviderError,
    PersonalizationRequest,
    ScoringFactorRef,
    StoredScoreContext,
    evidence_fingerprint,
    ground_personalization_content,
)

logger = structlog.get_logger(__name__)

PERSONALIZATION_ACTOR = "personalization"
BATCH_MAX = 200
SOURCE_URL_MAX_LENGTH = 1000
SNIPPET_MAX_LENGTH = 400


class PersonalizationError(ValueError):
    """Raised when a personalization job cannot load the requested lead or organization."""


@dataclass(frozen=True)
class PersonalizationJobResult:
    enrichment_run_id: UUID
    lead_id: UUID
    organization_id: UUID
    draft_id: UUID | None
    readiness_status: PersonalizationReadiness | None
    provider_name: str
    status: EnrichmentRunStatus
    reused_existing_draft: bool
    live_call_attempted: bool
    outbound_attempted: bool


class PersonalizationService:
    """Persist evidence-grounded personalization drafts. Does not send outreach."""

    def __init__(self, provider: PersonalizationProvider) -> None:
        self._provider = provider

    def personalize_lead(
        self,
        db: Session,
        lead_id: UUID,
        *,
        commit: bool = True,
    ) -> PersonalizationJobResult:
        lead = db.get(Lead, lead_id)
        if lead is None:
            raise PersonalizationError(f"Lead not found: {lead_id}")
        organization = db.get(Organization, lead.organization_id)
        if organization is None:
            raise PersonalizationError(f"Organization not found for lead: {lead_id}")
        return self._run(
            db,
            lead=lead,
            organization=organization,
            lead_created=False,
            commit=commit,
        )

    def personalize_organization(
        self,
        db: Session,
        organization_id: UUID,
        *,
        commit: bool = True,
    ) -> PersonalizationJobResult:
        organization = db.get(Organization, organization_id)
        if organization is None:
            raise PersonalizationError(f"Organization not found: {organization_id}")
        lead, created = self._existing_or_create_lead(db, organization)
        return self._run(
            db,
            lead=lead,
            organization=organization,
            lead_created=created,
            commit=commit,
        )

    def personalize_batch(
        self,
        db: Session,
        *,
        limit: int = 50,
        state: str | None = None,
        city: str | None = None,
    ) -> tuple[PersonalizationJobResult, ...]:
        query = select(Organization).order_by(Organization.created_at.asc())
        if state:
            query = query.where(Organization.state == state.strip().upper())
        if city:
            query = query.where(Organization.city == city.strip().upper())
        organizations = db.scalars(query.limit(min(max(limit, 1), BATCH_MAX))).all()
        return tuple(
            self.personalize_organization(db, organization.id, commit=True)
            for organization in organizations
        )

    def _run(
        self,
        db: Session,
        *,
        lead: Lead,
        organization: Organization,
        lead_created: bool,
        commit: bool,
    ) -> PersonalizationJobResult:
        pack = self._evidence_pack(db, lead, organization)
        fingerprint = evidence_fingerprint(pack)
        existing = db.scalar(
            select(PersonalizationDraft).where(
                PersonalizationDraft.lead_id == lead.id,
                PersonalizationDraft.evidence_fingerprint == fingerprint,
            )
        )
        run = EnrichmentRun(
            organization_id=organization.id,
            source=PERSONALIZATION_SOURCE,
            status=EnrichmentRunStatus.RUNNING.value,
            started_at=datetime.now(tz=UTC),
            input_params={
                "lead_id": str(lead.id),
                "prompt_version": PROMPT_VERSION,
                "schema_version": SCHEMA_VERSION,
                "evidence_fingerprint": fingerprint,
                "lead_created": lead_created,
                "outbound_attempted": False,
            },
        )
        db.add(run)
        db.flush()

        if existing is not None:
            return self._reuse(
                db,
                run=run,
                draft=existing,
                lead=lead,
                organization=organization,
                commit=commit,
            )

        request = PersonalizationRequest(lead_id=lead.id, pack=pack)
        try:
            provider_result = self._provider.generate(request)
            grounded = ground_personalization_content(provider_result.content, pack)
        except PersonalizationProviderError as exc:
            return self._fail(
                db,
                run=run,
                lead=lead,
                organization=organization,
                error=exc,
                commit=commit,
            )
        except Exception as exc:
            self._mark_failed(run, str(exc), retryable=False)
            self._record_activity(
                db,
                lead_id=lead.id,
                action="personalization_failed",
                details={
                    "enrichment_run_id": str(run.id),
                    "organization_id": str(organization.id),
                    "lead_id": str(lead.id),
                    "error": str(exc),
                    "retryable": False,
                    "outbound_attempted": False,
                    "live_call_attempted": False,
                    "fabricated_facts": False,
                },
            )
            if commit:
                db.commit()
            logger.exception(
                "personalization_failed",
                enrichment_run_id=str(run.id),
                lead_id=str(lead.id),
            )
            raise

        audit = provider_result.audit
        draft = PersonalizationDraft(
            lead_id=lead.id,
            organization_id=organization.id,
            enrichment_run_id=run.id,
            readiness_status=grounded.readiness_status.value,
            prompt_version=audit.prompt_version,
            schema_version=audit.schema_version,
            provider_name=audit.provider_name,
            practice_summary=grounded.practice_summary,
            why_vyro_relevant=grounded.why_vyro_relevant,
            opening_line=grounded.opening_line,
            outreach_angle=grounded.outreach_angle,
            suggested_offer=grounded.suggested_offer or DEFAULT_OFFER,
            missing_data_notes=list(grounded.missing_data_notes),
            evidence_references=[item.to_dict() for item in grounded.evidence_references],
            confidence=grounded.confidence,
            content_json=grounded.to_dict(),
            audit_json=audit.to_dict(),
            evidence_fingerprint=fingerprint,
        )
        db.add(draft)
        db.flush()
        self._persist_evidence(db, organization=organization, run=run, draft=draft, pack=pack)

        run.status = EnrichmentRunStatus.COMPLETED.value
        run.facts_extracted = 1
        run.finished_at = datetime.now(tz=UTC)
        run.input_params = {
            **dict(run.input_params),
            "provider": audit.provider_name,
            "readiness_status": grounded.readiness_status.value,
            "prompt_version": audit.prompt_version,
            "schema_version": audit.schema_version,
            "live_call_attempted": audit.live_call_attempted,
            "retry_attempts": audit.retry_attempts,
            "fabricated_facts": False,
            "outbound_attempted": False,
            "draft_id": str(draft.id),
        }
        self._record_activity(
            db,
            lead_id=lead.id,
            action="personalization_completed",
            details={
                "enrichment_run_id": str(run.id),
                "organization_id": str(organization.id),
                "lead_id": str(lead.id),
                "draft_id": str(draft.id),
                "provider": audit.provider_name,
                "readiness_status": grounded.readiness_status.value,
                "prompt_version": audit.prompt_version,
                "confidence": grounded.confidence,
                "suggested_offer": grounded.suggested_offer,
                "missing_data_notes": list(grounded.missing_data_notes),
                "evidence_reference_count": len(grounded.evidence_references),
                "live_call_attempted": audit.live_call_attempted,
                "reused_existing_draft": False,
                "fabricated_facts": False,
                "outbound_attempted": False,
            },
        )
        if commit:
            db.commit()
        logger.info(
            "personalization_completed",
            enrichment_run_id=str(run.id),
            lead_id=str(lead.id),
            draft_id=str(draft.id),
            readiness_status=grounded.readiness_status.value,
            provider=audit.provider_name,
        )
        return PersonalizationJobResult(
            enrichment_run_id=run.id,
            lead_id=lead.id,
            organization_id=organization.id,
            draft_id=draft.id,
            readiness_status=grounded.readiness_status,
            provider_name=audit.provider_name,
            status=EnrichmentRunStatus.COMPLETED,
            reused_existing_draft=False,
            live_call_attempted=audit.live_call_attempted,
            outbound_attempted=False,
        )

    def _reuse(
        self,
        db: Session,
        *,
        run: EnrichmentRun,
        draft: PersonalizationDraft,
        lead: Lead,
        organization: Organization,
        commit: bool = True,
    ) -> PersonalizationJobResult:
        run.status = EnrichmentRunStatus.COMPLETED.value
        run.facts_extracted = 0
        run.finished_at = datetime.now(tz=UTC)
        run.input_params = {
            **dict(run.input_params),
            "provider": draft.provider_name,
            "readiness_status": draft.readiness_status,
            "reused_existing_draft": True,
            "draft_id": str(draft.id),
            "live_call_attempted": False,
            "fabricated_facts": False,
            "outbound_attempted": False,
        }
        self._record_activity(
            db,
            lead_id=lead.id,
            action="personalization_reused",
            details={
                "enrichment_run_id": str(run.id),
                "organization_id": str(organization.id),
                "lead_id": str(lead.id),
                "draft_id": str(draft.id),
                "provider": draft.provider_name,
                "readiness_status": draft.readiness_status,
                "reused_existing_draft": True,
                "live_call_attempted": False,
                "fabricated_facts": False,
                "outbound_attempted": False,
            },
        )
        if commit:
            db.commit()
        readiness = _readiness_value(draft.readiness_status)
        return PersonalizationJobResult(
            enrichment_run_id=run.id,
            lead_id=lead.id,
            organization_id=organization.id,
            draft_id=draft.id,
            readiness_status=readiness,
            provider_name=draft.provider_name,
            status=EnrichmentRunStatus.COMPLETED,
            reused_existing_draft=True,
            live_call_attempted=False,
            outbound_attempted=False,
        )

    def _fail(
        self,
        db: Session,
        *,
        run: EnrichmentRun,
        lead: Lead,
        organization: Organization,
        error: PersonalizationProviderError,
        commit: bool,
    ) -> PersonalizationJobResult:
        self._mark_failed(run, str(error), retryable=error.retryable)
        kind = "malformed_output" if isinstance(error, MalformedPersonalizationOutput) else (
            "retryable" if error.retryable else "non_retryable"
        )
        self._record_activity(
            db,
            lead_id=lead.id,
            action="personalization_failed",
            details={
                "enrichment_run_id": str(run.id),
                "organization_id": str(organization.id),
                "lead_id": str(lead.id),
                "error": str(error),
                "failure_kind": kind,
                "retryable": error.retryable,
                "outbound_attempted": False,
                "live_call_attempted": False,
                "fabricated_facts": False,
            },
        )
        if commit:
            db.commit()
        logger.info(
            "personalization_failed",
            enrichment_run_id=str(run.id),
            lead_id=str(lead.id),
            retryable=error.retryable,
            failure_kind=kind,
        )
        return PersonalizationJobResult(
            enrichment_run_id=run.id,
            lead_id=lead.id,
            organization_id=organization.id,
            draft_id=None,
            readiness_status=None,
            provider_name="unknown",
            status=EnrichmentRunStatus.FAILED,
            reused_existing_draft=False,
            live_call_attempted=False,
            outbound_attempted=False,
        )

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
        lead = Lead(
            organization_id=organization.id,
            stage=LeadStage.DISCOVERED.value,
            source="local",
        )
        db.add(lead)
        db.flush()
        return lead, True

    def _evidence_pack(
        self,
        db: Session,
        lead: Lead,
        organization: Organization,
    ) -> PersonalizationEvidencePack:
        evidence_rows = db.scalars(
            select(SourceEvidence)
            .where(SourceEvidence.organization_id == organization.id)
            .order_by(SourceEvidence.created_at.asc())
        ).all()
        contacts = db.scalars(
            select(Contact).where(Contact.organization_id == organization.id)
        ).all()
        score_row = db.scalar(
            select(LeadScore)
            .where(LeadScore.lead_id == lead.id)
            .order_by(LeadScore.created_at.desc(), LeadScore.id.desc())
        )
        evidence_items = tuple(
            EvidenceItem(
                evidence_id=str(row.id),
                claim_type=row.claim_type,
                source_url=row.source_url,
                extracted_value=row.extracted_value,
                snippet=row.evidence_snippet,
                confidence=row.confidence,
            )
            for row in evidence_rows
        )
        return PersonalizationEvidencePack(
            organization=OrganizationContext(
                organization_id=organization.id,
                name=_text(organization.name),
                npi=_text(organization.npi),
                city=_text(organization.city),
                state=_text(organization.state),
                specialty=_text(organization.specialty),
                website=_text(organization.website),
                website_match_status=_text(organization.website_match_status),
            ),
            evidence=evidence_items,
            score=_score_context(score_row),
            contacts=tuple(
                ContactContext(
                    full_name=contact.full_name,
                    title=_text(contact.title),
                    role_category=_text(contact.role_category),
                )
                for contact in contacts
                if _text(contact.full_name)
            ),
        )

    def _persist_evidence(
        self,
        db: Session,
        *,
        organization: Organization,
        run: EnrichmentRun,
        draft: PersonalizationDraft,
        pack: PersonalizationEvidencePack,
    ) -> None:
        db.add(
            SourceEvidence(
                organization_id=organization.id,
                enrichment_run_id=run.id,
                personalization_draft_id=draft.id,
                source_url=clip_text(f"prompt:{PROMPT_VERSION}", SOURCE_URL_MAX_LENGTH),
                claim_type=PersonalizationFactType.PERSONALIZATION_DRAFT.value,
                extracted_value=draft.practice_summary,
                confidence=draft.confidence,
                evidence_snippet=clip_text(draft.opening_line, SNIPPET_MAX_LENGTH),
                metadata_json={
                    "draft_id": str(draft.id),
                    "readiness_status": draft.readiness_status,
                    "prompt_version": draft.prompt_version,
                    "schema_version": draft.schema_version,
                    "provider_name": draft.provider_name,
                    "suggested_offer": draft.suggested_offer,
                    "evidence_ids": [item.evidence_id for item in pack.evidence],
                    "fabricated": False,
                    "outbound_attempted": False,
                },
            )
        )

    def _record_activity(
        self,
        db: Session,
        *,
        lead_id: UUID | None,
        action: str,
        details: dict[str, object],
    ) -> None:
        db.add(
            Activity(
                lead_id=lead_id,
                actor=PERSONALIZATION_ACTOR,
                action=action,
                details=details,
            )
        )

    def _mark_failed(self, run: EnrichmentRun, message: str, *, retryable: bool) -> None:
        run.status = EnrichmentRunStatus.FAILED.value
        run.finished_at = datetime.now(tz=UTC)
        run.error_message = message
        run.input_params = {
            **dict(run.input_params),
            "retryable": retryable,
            "outbound_attempted": False,
            "fabricated_facts": False,
        }


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _score_context(score_row: LeadScore | None) -> StoredScoreContext:
    if score_row is None:
        return StoredScoreContext()
    rationale = score_row.rationale if isinstance(score_row.rationale, dict) else {}
    factors_raw = rationale.get("factors")
    factors: list[ScoringFactorRef] = []
    if isinstance(factors_raw, list):
        for item in factors_raw:
            if not isinstance(item, dict):
                continue
            code = _text(item.get("code"))
            if code is None:
                continue
            points_raw = item.get("points")
            points = points_raw if isinstance(points_raw, int) else 0
            factors.append(
                ScoringFactorRef(
                    code=code,
                    reason=_text(item.get("reason")) or "",
                    observed_value=_text(item.get("observed_value")),
                    points=points,
                    status=_text(item.get("status")),
                    evidence_id=_text(item.get("evidence_id")),
                    source_url=_text(item.get("source_url")),
                    claim_type=_text(item.get("claim_type")),
                )
            )
    missing_raw = rationale.get("missing_fields")
    missing = tuple(
        str(item) for item in missing_raw if isinstance(item, str)
    ) if isinstance(missing_raw, list) else ()
    reason_raw = rationale.get("reason_codes")
    reasons = tuple(
        str(item) for item in reason_raw if isinstance(item, str)
    ) if isinstance(reason_raw, list) else ()
    disq_raw = rationale.get("disqualification_codes")
    disq = tuple(
        str(item) for item in disq_raw if isinstance(item, str)
    ) if isinstance(disq_raw, list) else ()
    research_raw = rationale.get("research_reasons")
    research = tuple(
        str(item) for item in research_raw if isinstance(item, str)
    ) if isinstance(research_raw, list) else ()
    band = _text(rationale.get("band"))
    model_version = _text(rationale.get("model_version")) or score_row.model_version
    return StoredScoreContext(
        lead_score_id=str(score_row.id),
        total=score_row.score,
        band=band,
        model_version=model_version,
        missing_fields=missing,
        reason_codes=reasons,
        disqualification_codes=disq,
        research_reasons=research,
        factors=tuple(factors),
    )


def _readiness_value(value: str) -> PersonalizationReadiness | None:
    for status in PersonalizationReadiness:
        if status.value == value:
            return status
    return None
