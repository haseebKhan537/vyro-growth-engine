from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.domain import DiscoveryRunStatus
from vyro_growth.models import DiscoveryRun, Organization, SourceEvidence
from vyro_growth.providers.nppes import NormalizedNppesOrganization, NppesProvider, NppesSearchQuery


@dataclass(frozen=True)
class DiscoveryRunResult:
    discovery_run_id: UUID
    records_fetched: int
    records_upserted: int
    records_skipped: int
    status: DiscoveryRunStatus


class NppesDiscoveryService:
    def __init__(self, provider: NppesProvider, *, max_records_per_run: int) -> None:
        self._provider = provider
        self._max_records_per_run = max_records_per_run

    def run(
        self,
        db: Session,
        *,
        query: NppesSearchQuery,
        discovery_run_id: UUID | None = None,
        max_records: int | None = None,
    ) -> DiscoveryRunResult:
        run_limit = min(max_records or self._max_records_per_run, self._max_records_per_run)
        discovery_run = self._get_or_create_run(db, query, discovery_run_id)
        discovery_run.status = DiscoveryRunStatus.RUNNING.value
        discovery_run.started_at = datetime.now(tz=UTC)
        discovery_run.error_message = None
        db.commit()

        fetched = 0
        upserted = 0
        skipped = 0
        seen_npis: set[str] = set()
        skip = 0

        try:
            while fetched < run_limit:
                page = self._provider.search_organizations(query.with_skip(skip))
                if not page.results:
                    break

                for record in page.results:
                    if record.npi in seen_npis:
                        skipped += 1
                        continue
                    seen_npis.add(record.npi)

                    if fetched >= run_limit:
                        break

                    created = self._upsert_organization(db, record)
                    self._persist_evidence(db, discovery_run.id, record, created)
                    fetched += 1
                    upserted += 1

                if len(page.results) < query.limit:
                    break
                skip += len(page.results)

            discovery_run.status = DiscoveryRunStatus.COMPLETED.value
            discovery_run.finished_at = datetime.now(tz=UTC)
        except Exception as exc:
            discovery_run.status = DiscoveryRunStatus.FAILED.value
            discovery_run.finished_at = datetime.now(tz=UTC)
            discovery_run.error_message = str(exc)
            db.commit()
            raise

        discovery_run.records_fetched = fetched
        discovery_run.records_upserted = upserted
        discovery_run.records_skipped = skipped
        db.commit()

        return DiscoveryRunResult(
            discovery_run_id=discovery_run.id,
            records_fetched=fetched,
            records_upserted=upserted,
            records_skipped=skipped,
            status=DiscoveryRunStatus(discovery_run.status),
        )

    def _get_or_create_run(
        self,
        db: Session,
        query: NppesSearchQuery,
        discovery_run_id: UUID | None,
    ) -> DiscoveryRun:
        if discovery_run_id is not None:
            run = db.get(DiscoveryRun, discovery_run_id)
            if run is None:
                raise ValueError(f"Discovery run not found: {discovery_run_id}")
            return run

        run = DiscoveryRun(
            source="nppes",
            status=DiscoveryRunStatus.PENDING.value,
            query_params=query.to_params(),
        )
        db.add(run)
        db.flush()
        return run

    def _upsert_organization(
        self,
        db: Session,
        record: NormalizedNppesOrganization,
    ) -> bool:
        organization = db.scalar(select(Organization).where(Organization.npi == record.npi))
        created = organization is None
        if organization is None:
            organization = Organization(npi=record.npi, name=record.name)
            db.add(organization)

        organization.name = record.name
        organization.city = record.city
        organization.state = record.state
        organization.specialty = record.specialty
        db.flush()
        return created

    def _persist_evidence(
        self,
        db: Session,
        discovery_run_id: UUID,
        record: NormalizedNppesOrganization,
        created: bool,
    ) -> None:
        organization = db.scalar(select(Organization).where(Organization.npi == record.npi))
        if organization is None:
            raise RuntimeError(f"Organization missing after upsert for NPI {record.npi}")

        evidence = SourceEvidence(
            organization_id=organization.id,
            discovery_run_id=discovery_run_id,
            source_url=record.source_url,
            claim_type="nppes_organization_record",
            extracted_value=record.name,
            metadata_json={
                "npi": record.npi,
                "query_metadata": record.query_metadata,
                "created_on_upsert": created,
            },
        )
        db.add(evidence)
