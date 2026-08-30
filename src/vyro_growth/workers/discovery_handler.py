from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from vyro_growth.config import Settings, get_settings
from vyro_growth.providers.nppes import NppesSearchQuery
from vyro_growth.providers.nppes_client import build_nppes_provider
from vyro_growth.services.discovery import NppesDiscoveryService
from vyro_growth.workers.base import Job


@dataclass
class DiscoverNppesPracticesHandler:
    db: Session
    settings: Settings | None = None

    def handle(self, job: Job) -> None:
        settings = self.settings or get_settings()
        provider = build_nppes_provider(
            base_url=settings.nppes_api_base_url,
            timeout_seconds=settings.nppes_timeout_seconds,
            max_retries=settings.nppes_max_retries,
            retry_backoff_seconds=settings.nppes_retry_backoff_seconds,
        )
        service = NppesDiscoveryService(
            provider,
            max_records_per_run=settings.discovery_max_records_per_run,
        )
        query = _query_from_payload(job.payload)
        discovery_run_id = _optional_uuid(job.payload.get("discovery_run_id"))
        max_records = _optional_int(job.payload.get("max_records"))
        service.run(
            self.db,
            query=query,
            discovery_run_id=discovery_run_id,
            max_records=max_records,
        )


def _query_from_payload(payload: dict[str, object]) -> NppesSearchQuery:
    return NppesSearchQuery(
        state=_optional_str(payload.get("state")),
        city=_optional_str(payload.get("city")),
        taxonomy_description=_optional_str(payload.get("taxonomy_description")),
        organization_name=_optional_str(payload.get("organization_name")),
    )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _optional_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    return None
