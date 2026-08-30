from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.domain import EnrichmentRunStatus, WebsiteFactType, WebsiteMatchStatus
from vyro_growth.models import Activity, EnrichmentRun, Organization, SourceEvidence
from vyro_growth.providers.website import (
    WEBSITE_ENRICHMENT_SOURCE,
    WEBSITE_MAX_LENGTH,
    ExtractedFact,
    OrganizationMatchInput,
    PublicPage,
    PublicPageFetcher,
    WebsiteCandidate,
    WebsiteFetchError,
    WebsiteMatchDecision,
    WebsiteSearchProvider,
    WebsiteSearchQuery,
    WebsiteUrlError,
    clip_text,
    hostname_of,
    is_blocked_public_path,
    is_directory_host,
    normalize_url,
)
from vyro_growth.providers.website_analyze import (
    decide_website_match,
    extract_business_facts,
    match_status_label,
)

logger = structlog.get_logger(__name__)

WEBSITE_ENRICHMENT_ACTOR = "website_enrichment"
BATCH_MAX = 200
DEFAULT_MAX_PAGES = 5


class WebsiteEnrichmentError(ValueError):
    """Raised when a website enrichment job cannot load the requested organization."""


@dataclass(frozen=True)
class WebsiteEnrichmentResult:
    enrichment_run_id: UUID
    organization_id: UUID
    match_status: WebsiteMatchStatus
    official_website: str | None
    facts_extracted: int
    pages_fetched: int
    candidates_considered: int
    status: EnrichmentRunStatus


class WebsiteEnrichmentService:
    def __init__(
        self,
        search_provider: WebsiteSearchProvider,
        page_fetcher: PublicPageFetcher,
        *,
        max_pages_per_org: int = DEFAULT_MAX_PAGES,
    ) -> None:
        self._search_provider = search_provider
        self._page_fetcher = page_fetcher
        self._max_pages_per_org = max(1, max_pages_per_org)

    def enrich_organization(
        self,
        db: Session,
        organization_id: UUID,
        *,
        candidate_url: str | None = None,
        skip_verified: bool = False,
    ) -> WebsiteEnrichmentResult:
        organization = db.get(Organization, organization_id)
        if organization is None:
            raise WebsiteEnrichmentError(f"Organization not found: {organization_id}")
        if skip_verified and organization.website_match_status == WebsiteMatchStatus.VERIFIED.value:
            return self._already_verified_result(db, organization)

        run = EnrichmentRun(
            organization_id=organization.id,
            source=WEBSITE_ENRICHMENT_SOURCE,
            status=EnrichmentRunStatus.RUNNING.value,
            input_params={
                "candidate_url": candidate_url,
                "skip_verified": skip_verified,
            },
            started_at=datetime.now(tz=UTC),
        )
        db.add(run)
        db.flush()

        try:
            result = self._enrich(db, organization, run, candidate_url=candidate_url)
        except WebsiteEnrichmentError:
            raise
        except Exception as exc:
            run.status = EnrichmentRunStatus.FAILED.value
            run.finished_at = datetime.now(tz=UTC)
            run.error_message = str(exc)
            self._record_activity(
                db,
                action="website_enrichment_failed",
                details={
                    "enrichment_run_id": str(run.id),
                    "organization_id": str(organization.id),
                    "error": str(exc),
                },
            )
            db.commit()
            logger.exception(
                "website_enrichment_failed",
                enrichment_run_id=str(run.id),
                organization_id=str(organization.id),
            )
            raise

        db.commit()
        logger.info(
            "website_enrichment_completed",
            enrichment_run_id=str(result.enrichment_run_id),
            organization_id=str(result.organization_id),
            match_status=result.match_status.value,
            facts_extracted=result.facts_extracted,
        )
        return result

    def enrich_batch(
        self,
        db: Session,
        *,
        limit: int = 50,
        skip_verified: bool = True,
        state: str | None = None,
        city: str | None = None,
    ) -> tuple[WebsiteEnrichmentResult, ...]:
        query = select(Organization).order_by(Organization.created_at.asc())
        if skip_verified:
            query = query.where(
                (Organization.website_match_status.is_(None))
                | (Organization.website_match_status != WebsiteMatchStatus.VERIFIED.value)
            )
        if state:
            query = query.where(Organization.state == state.strip().upper())
        if city:
            query = query.where(Organization.city == city.strip().upper())
        organizations = db.scalars(query.limit(min(max(limit, 1), BATCH_MAX))).all()
        return tuple(
            self.enrich_organization(db, organization.id, skip_verified=skip_verified)
            for organization in organizations
        )

    def _already_verified_result(
        self,
        db: Session,
        organization: Organization,
    ) -> WebsiteEnrichmentResult:
        run = EnrichmentRun(
            organization_id=organization.id,
            source=WEBSITE_ENRICHMENT_SOURCE,
            status=EnrichmentRunStatus.COMPLETED.value,
            match_status=WebsiteMatchStatus.VERIFIED.value,
            official_website=organization.website,
            facts_extracted=0,
            pages_fetched=0,
            candidates_considered=0,
            input_params={"skipped": True, "reason": "already_verified"},
            started_at=datetime.now(tz=UTC),
            finished_at=datetime.now(tz=UTC),
        )
        db.add(run)
        db.flush()
        self._record_activity(
            db,
            action="website_enrichment_skipped",
            details={
                "enrichment_run_id": str(run.id),
                "organization_id": str(organization.id),
                "reason": "already_verified",
            },
        )
        db.commit()
        return WebsiteEnrichmentResult(
            enrichment_run_id=run.id,
            organization_id=organization.id,
            match_status=WebsiteMatchStatus.VERIFIED,
            official_website=organization.website,
            facts_extracted=0,
            pages_fetched=0,
            candidates_considered=0,
            status=EnrichmentRunStatus.COMPLETED,
        )

    def _enrich(
        self,
        db: Session,
        organization: Organization,
        run: EnrichmentRun,
        *,
        candidate_url: str | None,
    ) -> WebsiteEnrichmentResult:
        candidates = self._collect_candidates(organization, candidate_url)
        run.candidates_considered = len(candidates)
        pages, fetch_errors = self._fetch_pages(candidates)
        run.pages_fetched = len(pages)

        match_input = OrganizationMatchInput(
            name=organization.name,
            city=organization.city,
            state=organization.state,
            npi=organization.npi,
            specialty=organization.specialty,
        )
        decision = decide_website_match(match_input, tuple(pages))
        facts = ()
        if decision.status is WebsiteMatchStatus.VERIFIED and decision.official_website:
            winner = next(
                (page for page in pages if page.url == decision.official_website),
                None,
            )
            if winner is not None:
                facts = extract_business_facts(winner)
            self._apply_verified_website(organization, decision.official_website)
        organization.website_match_status = match_status_label(decision.status)

        self._persist_match_evidence(db, organization, run, decision, fetch_errors)
        for fact in facts:
            self._persist_fact(db, organization, run, fact)

        run.match_status = decision.status.value
        run.official_website = (
            clip_text(decision.official_website, WEBSITE_MAX_LENGTH)
            if decision.official_website
            else None
        )
        run.facts_extracted = len(facts)
        run.status = EnrichmentRunStatus.COMPLETED.value
        run.finished_at = datetime.now(tz=UTC)

        self._record_activity(
            db,
            action="website_enrichment_completed",
            details={
                "enrichment_run_id": str(run.id),
                "organization_id": str(organization.id),
                "match_status": decision.status.value,
                "official_website": run.official_website,
                "facts_extracted": len(facts),
                "pages_fetched": len(pages),
                "candidates_considered": len(candidates),
                "fetch_errors": fetch_errors,
                "fabricated_facts": False,
            },
        )
        return WebsiteEnrichmentResult(
            enrichment_run_id=run.id,
            organization_id=organization.id,
            match_status=decision.status,
            official_website=run.official_website,
            facts_extracted=len(facts),
            pages_fetched=len(pages),
            candidates_considered=len(candidates),
            status=EnrichmentRunStatus.COMPLETED,
        )

    def _collect_candidates(
        self,
        organization: Organization,
        candidate_url: str | None,
    ) -> list[WebsiteCandidate]:
        ordered: list[WebsiteCandidate] = []
        if candidate_url:
            ordered.append(WebsiteCandidate(url=candidate_url.strip(), source="operator"))
        if organization.website:
            ordered.append(WebsiteCandidate(url=organization.website, source="existing"))
        query = WebsiteSearchQuery(
            organization_name=organization.name,
            city=organization.city,
            state=organization.state,
            npi=organization.npi,
            specialty=organization.specialty,
        )
        ordered.extend(self._search_provider.find_candidates(query))

        unique: list[WebsiteCandidate] = []
        seen: set[str] = set()
        for candidate in ordered:
            if not candidate.url.strip():
                continue
            normalized = normalize_url(candidate.url)
            if hostname_of(normalized) is None:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            unique.append(
                WebsiteCandidate(
                    url=normalized,
                    source=candidate.source,
                    title=candidate.title,
                    snippet=candidate.snippet,
                )
            )
        return unique

    def _fetch_pages(
        self,
        candidates: list[WebsiteCandidate],
    ) -> tuple[list[PublicPage], list[dict[str, str]]]:
        pages: list[PublicPage] = []
        errors: list[dict[str, str]] = []
        for candidate in candidates:
            if len(pages) >= self._max_pages_per_org:
                break
            if is_directory_host(candidate.url):
                errors.append({"url": candidate.url, "error": "directory_host"})
                continue
            if is_blocked_public_path(candidate.url):
                errors.append({"url": candidate.url, "error": "blocked_public_path"})
                continue
            try:
                pages.append(self._page_fetcher.fetch(candidate.url))
            except (WebsiteFetchError, WebsiteUrlError) as exc:
                errors.append({"url": candidate.url, "error": str(exc)})
        return pages, errors

    def _apply_verified_website(self, organization: Organization, url: str) -> None:
        organization.website = clip_text(url, WEBSITE_MAX_LENGTH)

    def _persist_match_evidence(
        self,
        db: Session,
        organization: Organization,
        run: EnrichmentRun,
        decision: WebsiteMatchDecision,
        fetch_errors: list[dict[str, str]],
    ) -> None:
        db.add(
            SourceEvidence(
                organization_id=organization.id,
                enrichment_run_id=run.id,
                source_url=decision.winning_url or "unmatched",
                claim_type=WebsiteFactType.WEBSITE_MATCH.value,
                extracted_value=decision.status.value,
                confidence=decision.confidence,
                evidence_snippet=decision.snippet,
                metadata_json={
                    "reasons": list(decision.reasons),
                    "official_website": decision.official_website,
                    "scored_pages": [
                        {
                            "url": item.url,
                            "confidence": item.confidence,
                            "reasons": list(item.reasons),
                            "directory": item.is_directory,
                        }
                        for item in decision.scored_pages
                    ],
                    "fetch_errors": fetch_errors,
                    "fabricated": False,
                },
            )
        )
        if decision.status is WebsiteMatchStatus.VERIFIED and decision.official_website:
            db.add(
                SourceEvidence(
                    organization_id=organization.id,
                    enrichment_run_id=run.id,
                    source_url=decision.official_website,
                    claim_type=WebsiteFactType.OFFICIAL_WEBSITE.value,
                    extracted_value=decision.official_website,
                    confidence=decision.confidence,
                    evidence_snippet=decision.snippet,
                    metadata_json={"reasons": list(decision.reasons), "fabricated": False},
                )
            )

    def _persist_fact(
        self,
        db: Session,
        organization: Organization,
        run: EnrichmentRun,
        fact: ExtractedFact,
    ) -> None:
        db.add(
            SourceEvidence(
                organization_id=organization.id,
                enrichment_run_id=run.id,
                source_url=fact.source_url,
                claim_type=fact.fact_type.value,
                extracted_value=fact.value,
                confidence=fact.confidence,
                evidence_snippet=fact.snippet,
                metadata_json={"fabricated": False, "extractor": "deterministic-v1"},
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
                actor=WEBSITE_ENRICHMENT_ACTOR,
                action=action,
                details=details,
            )
        )

