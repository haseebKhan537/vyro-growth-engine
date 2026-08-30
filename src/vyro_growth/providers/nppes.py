from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

NPPES_API_VERSION = "2.1"
NPPES_ORGANIZATION_ENUMERATION = "NPI-2"
NPPES_MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class NppesSearchQuery:
    state: str | None = None
    city: str | None = None
    taxonomy_description: str | None = None
    organization_name: str | None = None
    limit: int = NPPES_MAX_PAGE_SIZE
    skip: int = 0

    def has_targeting_filter(self) -> bool:
        return any(
            (
                self.state,
                self.city,
                self.taxonomy_description,
                self.organization_name,
            )
        )

    def with_skip(self, skip: int) -> NppesSearchQuery:
        return replace(self, skip=skip)

    def with_limit(self, limit: int) -> NppesSearchQuery:
        return replace(self, limit=min(max(limit, 1), NPPES_MAX_PAGE_SIZE))

    def to_params(self) -> dict[str, str | int]:
        params: dict[str, str | int] = {
            "version": NPPES_API_VERSION,
            "enumeration_type": NPPES_ORGANIZATION_ENUMERATION,
            "limit": min(max(self.limit, 1), NPPES_MAX_PAGE_SIZE),
            "skip": max(self.skip, 0),
        }
        if self.state:
            params["state"] = self.state.upper()
        if self.city:
            params["city"] = self.city
        if self.taxonomy_description:
            params["taxonomy_description"] = self.taxonomy_description
        if self.organization_name:
            params["organization_name"] = self.organization_name
        return params


@dataclass(frozen=True)
class NormalizedNppesOrganization:
    npi: str
    name: str
    city: str | None
    state: str | None
    specialty: str | None
    source_url: str
    query_metadata: dict[str, object]


@dataclass(frozen=True)
class NppesSearchPage:
    results: tuple[NormalizedNppesOrganization, ...]
    result_count: int
    page_size: int
    source_url: str


class NppesProvider(Protocol):
    def search_organizations(self, query: NppesSearchQuery) -> NppesSearchPage: ...
