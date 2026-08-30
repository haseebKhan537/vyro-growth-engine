from __future__ import annotations

from typing import Any

from vyro_growth.providers.nppes import (
    NPPES_ORGANIZATION_ENUMERATION,
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


def _normalize_npi(value: object) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return str(value)
    if isinstance(value, str) and value.strip().isdigit():
        return value.strip()
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
    city = _optional_text(address.get("city"))
    state = _optional_text(address.get("state"))
    specialty = _primary_taxonomy(_as_list(record.get("taxonomies")))

    return NormalizedNppesOrganization(
        npi=npi,
        name=organization_name,
        city=city.upper() if city is not None else None,
        state=state.upper() if state is not None else None,
        specialty=specialty,
        source_url=source_url,
        query_metadata={
            "query": query.to_params(),
            "enumeration_type": record.get("enumeration_type"),
            "npi": npi,
        },
    )
