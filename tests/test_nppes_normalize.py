from __future__ import annotations

import pytest

from tests.fixtures.nppes_records import (
    MALFORMED_RECORDS,
    SAMPLE_ORG_RECORD,
    SAMPLE_ORG_RECORD_2,
    SAMPLE_ORG_RECORD_INTEGER_NPI,
)
from vyro_growth.providers.nppes import NppesSearchQuery
from vyro_growth.providers.nppes_normalize import normalize_nppes_record


def test_normalize_organization_record() -> None:
    query = NppesSearchQuery(state="TX", city="Austin")
    result = normalize_nppes_record(
        SAMPLE_ORG_RECORD,
        source_url="https://example.test",
        query=query,
    )

    assert result is not None
    assert result.npi == "1487448189"
    assert result.name == "100 CHIRO CORONA LLC"
    assert result.city == "AUSTIN"
    assert result.state == "TX"
    assert result.specialty == "Chiropractor"
    assert result.query_metadata["query"]["state"] == "TX"
    assert result.query_metadata["query"]["enumeration_type"] == "NPI-2"
    assert result.query_metadata["query"]["version"] == "2.1"


def test_normalize_accepts_integer_npi_and_location_address() -> None:
    result = normalize_nppes_record(
        SAMPLE_ORG_RECORD_INTEGER_NPI,
        source_url="https://example.test",
        query=NppesSearchQuery(state="TX"),
    )

    assert result is not None
    assert result.npi == "1487448189"
    assert result.city == "AUSTIN"
    assert result.state == "TX"


def test_normalize_second_record() -> None:
    result = normalize_nppes_record(
        SAMPLE_ORG_RECORD_2,
        source_url="https://example.test",
        query=NppesSearchQuery(state="TX"),
    )

    assert result is not None
    assert result.specialty == "Family Medicine"


@pytest.mark.parametrize("record", MALFORMED_RECORDS)
def test_normalize_skips_malformed_and_inactive_records(record: dict[str, object]) -> None:
    result = normalize_nppes_record(
        record,
        source_url="https://example.test",
        query=NppesSearchQuery(state="TX"),
    )

    assert result is None


def test_normalize_does_not_copy_authorized_official_fields() -> None:
    result = normalize_nppes_record(
        SAMPLE_ORG_RECORD,
        source_url="https://example.test",
        query=NppesSearchQuery(state="TX"),
    )

    assert result is not None
    serialized = str(result.query_metadata) + str(result.business_record)
    assert "CHRIS" not in serialized
    assert "5126388544" not in serialized
    assert "authorized_official" not in serialized
    assert set(result.business_record) == {
        "npi",
        "enumeration_type",
        "organization_name",
        "status",
        "city",
        "state",
        "specialty",
    }


def test_normalize_truncates_fields_to_db_lengths() -> None:
    record = {
        "number": "1487448189",
        "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "N" * 400,
            "status": "A",
        },
        "addresses": [
            {
                "address_purpose": "LOCATION",
                "city": "C" * 200,
                "state": "texas",
            }
        ],
        "taxonomies": [{"desc": "S" * 400, "primary": True}],
    }

    result = normalize_nppes_record(
        record,
        source_url="https://example.test",
        query=NppesSearchQuery(state="TX", city="Austin"),
    )

    assert result is not None
    assert len(result.name) == 255
    assert result.city is not None
    assert len(result.city) == 120
    assert result.state == "TE"
    assert result.specialty is not None
    assert len(result.specialty) == 255
