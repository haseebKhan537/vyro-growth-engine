from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from vyro_growth.config import Settings, get_settings
from vyro_growth.providers.website import (
    HeuristicWebsiteSearchProvider,
    PublicPageFetcher,
    WebsiteSearchProvider,
)
from vyro_growth.providers.website_client import build_public_page_fetcher
from vyro_growth.services.website_enrichment import (
    WebsiteEnrichmentError,
    WebsiteEnrichmentService,
)
from vyro_growth.workers.base import Job

ENRICH_ORGANIZATION_WEBSITES_JOB = "enrich_organization_websites"


@dataclass
class EnrichOrganizationWebsitesHandler:
    db: Session
    settings: Settings | None = None
    search_provider: WebsiteSearchProvider | None = None
    page_fetcher: PublicPageFetcher | None = None

    def handle(self, job: Job) -> None:
        organization_id = _optional_uuid(job.payload.get("organization_id"))
        candidate_url = _optional_str(job.payload.get("candidate_url"))
        limit = _optional_int(job.payload.get("limit"))
        skip_verified = _optional_bool(job.payload.get("skip_verified"), default=True)
        state = _optional_str(job.payload.get("state"))
        city = _optional_str(job.payload.get("city"))
        if organization_id is None and candidate_url is not None and limit is None:
            raise WebsiteEnrichmentError("candidate_url requires organization_id")

        service = self._service()
        if organization_id is not None:
            service.enrich_organization(
                self.db,
                organization_id,
                candidate_url=candidate_url,
                skip_verified=False if candidate_url else skip_verified,
            )
            return
        service.enrich_batch(
            self.db,
            limit=limit or 50,
            skip_verified=skip_verified,
            state=state,
            city=city,
        )

    def _service(self) -> WebsiteEnrichmentService:
        settings = self.settings or get_settings()
        search = self.search_provider or HeuristicWebsiteSearchProvider()
        fetcher = self.page_fetcher or build_public_page_fetcher(
            timeout_seconds=settings.website_fetch_timeout_seconds,
            max_bytes=settings.website_fetch_max_bytes,
            max_redirects=settings.website_fetch_max_redirects,
            rate_limit_seconds=settings.website_rate_limit_seconds,
            user_agent=settings.website_user_agent,
        )
        return WebsiteEnrichmentService(
            search,
            fetcher,
            max_pages_per_org=settings.website_max_pages_per_org,
        )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _optional_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
    return default


def _optional_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str) and value.strip():
        return UUID(value)
    return None
