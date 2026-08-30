from __future__ import annotations

from typing import Any

from vyro_growth.providers.nppes import NormalizedNppesOrganization, NppesSearchQuery


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _location_address(addresses: list[object]) -> dict[str, Any]:
    for item in addresses:
        address = _as_dict(item)
        if address.get("address_purpose") == "LOCATION":
            return address
    if addresses:
        return _as_dict(addresses[0])
    return {}


def _primary_taxonomy(taxonomies: list[object]) -> str | None:
    primary: str | None = None
    for item in taxonomies:
        taxonomy = _as_dict(item)
        description = taxonomy.get("desc")
        if not isinstance(description, str) or not description.strip():
            continue
        if taxonomy.get("primary") is True:
            return description.strip()
        if primary is None:
            primary = description.strip()
    return primary


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return []


def normalize_nppes_record(
    record: dict[str, object],
    *,
    source_url: str,
    query: NppesSearchQuery,
) -> NormalizedNppesOrganization | None:
    if record.get("enumeration_type") != "NPI-2":
        return None

    npi = record.get("number")
    basic = _as_dict(record.get("basic"))
    organization_name = basic.get("organization_name")
    if not isinstance(npi, str) or not npi.strip():
        return None
    if not isinstance(organization_name, str) or not organization_name.strip():
        return None

    address = _location_address(_as_list(record.get("addresses")))
    city = address.get("city")
    state = address.get("state")
    specialty = _primary_taxonomy(_as_list(record.get("taxonomies")))

    return NormalizedNppesOrganization(
        npi=npi.strip(),
        name=organization_name.strip(),
        city=city.strip() if isinstance(city, str) and city.strip() else None,
        state=state.strip().upper() if isinstance(state, str) and state.strip() else None,
        specialty=specialty,
        source_url=source_url,
        query_metadata={
            "query": query.to_params(),
            "enumeration_type": record.get("enumeration_type"),
            "npi": npi.strip(),
        },
        raw_record=record,
    )
