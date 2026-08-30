from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from vyro_growth.config import Settings, get_settings
from vyro_growth.providers.nppes import NARROW_FILTER_ERROR, NppesSearchQuery
from vyro_growth.providers.nppes_client import build_nppes_provider
from vyro_growth.services.discovery import DiscoveryRunResult, NppesDiscoveryService


class NppesDiscoveryRequest(BaseModel):
    state: str | None = None
    city: str | None = None
    taxonomy_description: str | None = None
    organization_name: str | None = None
    max_records: int | None = Field(default=None, ge=1)
    discovery_run_id: UUID | None = None

    @model_validator(mode="after")
    def require_narrow_filter(self) -> Self:
        query = NppesSearchQuery(
            state=self.state,
            city=self.city,
            taxonomy_description=self.taxonomy_description,
            organization_name=self.organization_name,
        )
        if not query.has_narrow_filter():
            raise ValueError(NARROW_FILTER_ERROR)
        return self


def run_nppes_discovery(
    db: Session,
    request: NppesDiscoveryRequest,
    *,
    settings: Settings | None = None,
) -> DiscoveryRunResult:
    active_settings = settings or get_settings()
    provider = build_nppes_provider(
        base_url=active_settings.nppes_api_base_url,
        timeout_seconds=active_settings.nppes_timeout_seconds,
        max_retries=active_settings.nppes_max_retries,
        retry_backoff_seconds=active_settings.nppes_retry_backoff_seconds,
    )
    service = NppesDiscoveryService(
        provider,
        max_records_per_run=active_settings.discovery_max_records_per_run,
    )
    query = NppesSearchQuery(
        state=request.state,
        city=request.city,
        taxonomy_description=request.taxonomy_description,
        organization_name=request.organization_name,
    )
    return service.run(
        db,
        query=query,
        discovery_run_id=request.discovery_run_id,
        max_records=request.max_records,
    )
