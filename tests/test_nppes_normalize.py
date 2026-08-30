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
    serialized = str(result.query_metadata)
    assert "CHRIS" not in serialized
    assert "5126388544" not in serialized
