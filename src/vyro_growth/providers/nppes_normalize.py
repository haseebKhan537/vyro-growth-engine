from __future__ import annotations

from typing import Any

from vyro_growth.providers.nppes import (
    CITY_MAX_LENGTH,
    NPI_MAX_LENGTH,
    NPPES_ORGANIZATION_ENUMERATION,
    ORGANIZATION_NAME_MAX_LENGTH,
    SPECIALTY_MAX_LENGTH,
    STATE_MAX_LENGTH,
    NormalizedNppesOrganization,
    NppesSearchQuery,
)

ACTIVE_STATUS = "A"


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return []


def _clip(value: str, max_length: int) -> str:
    return value[:max_length]


def _clip_optional(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    clipped = _clip(value, max_length)
    return clipped or None


def _normalize_npi(value: object) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return _clip(str(value), NPI_MAX_LENGTH)
    if isinstance(value, str) and value.strip().isdigit():
        return _clip(value.strip(), NPI_MAX_LENGTH)
    return None


def _optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _location_address(addresses: list[object]) -> dict[str, Any]:
    for item in addresses:
        address = _as_dict(item)
        if address.get("address_purpose") == "LOCATION":
            return address
    if addresses:
        return _as_dict(addresses[0])
    return {}


def _primary_taxonomy(taxonomies: list[object]) -> str | None:
    fallback: str | None = None
    for item in taxonomies:
        taxonomy = _as_dict(item)
        description = _optional_text(taxonomy.get("desc"))
        if description is None:
            continue
        if taxonomy.get("primary") is True:
            return description
        if fallback is None:
            fallback = description
    return fallback


def to_business_record(
    *,
    npi: str,
    name: str,
    status: str | None,
    city: str | None,
    state: str | None,
    specialty: str | None,
) -> dict[str, object]:
    return {
        "npi": npi,
        "enumeration_type": NPPES_ORGANIZATION_ENUMERATION,
        "organization_name": name,
        "status": status,
        "city": city,
        "state": state,
        "specialty": specialty,
    }


def normalize_nppes_record(
    record: dict[str, object],
    *,
    source_url: str,
    query: NppesSearchQuery,
) -> NormalizedNppesOrganization | None:
    if record.get("enumeration_type") != NPPES_ORGANIZATION_ENUMERATION:
        return None

    npi = _normalize_npi(record.get("number"))
    basic = _as_dict(record.get("basic"))
    organization_name = _optional_text(basic.get("organization_name"))
    status = _optional_text(basic.get("status"))
    if npi is None or organization_name is None:
        return None
    if status is not None and status.upper() != ACTIVE_STATUS:
        return None

    address = _location_address(_as_list(record.get("addresses")))
    city = _clip_optional(
        _optional_text(address.get("city")),
        CITY_MAX_LENGTH,
    )
    if city is not None:
        city = city.upper()
    state = _clip_optional(
        _optional_text(address.get("state")),
        STATE_MAX_LENGTH,
    )
    if state is not None:
        state = state.upper()
    specialty = _clip_optional(
        _primary_taxonomy(_as_list(record.get("taxonomies"))),
        SPECIALTY_MAX_LENGTH,
    )
    name = _clip(organization_name, ORGANIZATION_NAME_MAX_LENGTH)

    return NormalizedNppesOrganization(
        npi=npi,
        name=name,
        city=city,
        state=state,
        specialty=specialty,
        source_url=source_url,
        query_metadata={
            "query": query.to_params(),
            "enumeration_type": NPPES_ORGANIZATION_ENUMERATION,
            "npi": npi,
        },
        business_record=to_business_record(
            npi=npi,
            name=name,
            status=status.upper() if status is not None else None,
            city=city,
            state=state,
            specialty=specialty,
        ),
    )
