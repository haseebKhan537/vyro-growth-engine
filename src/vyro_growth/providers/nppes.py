from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol


@dataclass(frozen=True)
class NppesSearchQuery:
    state: str | None = None
    city: str | None = None
    taxonomy_description: str | None = None
    organization_name: str | None = None
    limit: int = 200
    skip: int = 0

    def with_skip(self, skip: int) -> NppesSearchQuery:
        return replace(self, skip=skip)

    def to_params(self) -> dict[str, str | int]:
        params: dict[str, str | int] = {
            "version": "2.1",
            "enumeration_type": "NPI-2",
            "limit": self.limit,
            "skip": self.skip,
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
    raw_record: dict[str, object]


@dataclass(frozen=True)
class NppesSearchPage:
    results: tuple[NormalizedNppesOrganization, ...]
    result_count: int
    source_url: str


class NppesProvider(Protocol):
    def search_organizations(self, query: NppesSearchQuery) -> NppesSearchPage: ...
