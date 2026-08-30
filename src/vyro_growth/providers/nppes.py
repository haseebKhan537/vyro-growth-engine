from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Protocol

NPPES_API_VERSION = "2.1"
NPPES_ORGANIZATION_ENUMERATION = "NPI-2"
NPPES_MAX_PAGE_SIZE = 200
NPPES_MAX_SKIP = 1000

NPI_MAX_LENGTH = 20
ORGANIZATION_NAME_MAX_LENGTH = 255
CITY_MAX_LENGTH = 120
STATE_MAX_LENGTH = 2
SPECIALTY_MAX_LENGTH = 255

NARROW_FILTER_ERROR = (
    "NPPES discovery requires a narrow filter "
    "(city, taxonomy_description, or organization_name); state alone is not sufficient"
)


class NppesQueryError(ValueError):
    """Raised when an NPPES query is missing required targeting filters."""


def clean_optional_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


@dataclass(frozen=True)
class NppesSearchQuery:
    state: str | None = None
    city: str | None = None
    taxonomy_description: str | None = None
    organization_name: str | None = None
    limit: int = NPPES_MAX_PAGE_SIZE
    skip: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", clean_optional_text(self.state))
        object.__setattr__(self, "city", clean_optional_text(self.city))
        object.__setattr__(
            self, "taxonomy_description", clean_optional_text(self.taxonomy_description)
        )
        object.__setattr__(self, "organization_name", clean_optional_text(self.organization_name))

    def has_narrow_filter(self) -> bool:
        return any((self.city, self.taxonomy_description, self.organization_name))

    def has_targeting_filter(self) -> bool:
        return self.has_narrow_filter()

    def require_valid(self) -> None:
        if not self.has_narrow_filter():
            raise NppesQueryError(NARROW_FILTER_ERROR)

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
    business_record: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class NppesSearchPage:
    results: tuple[NormalizedNppesOrganization, ...]
    result_count: int
    page_size: int
    source_url: str


class NppesProvider(Protocol):
    def search_organizations(self, query: NppesSearchQuery) -> NppesSearchPage: ...
