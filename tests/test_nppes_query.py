from __future__ import annotations

import pytest

from vyro_growth.providers.nppes import NARROW_FILTER_ERROR, NppesQueryError, NppesSearchQuery


@pytest.mark.parametrize(
    "query",
    [
        NppesSearchQuery(),
        NppesSearchQuery(state="TX"),
        NppesSearchQuery(state="tx"),
        NppesSearchQuery(state="TX", city="   "),
        NppesSearchQuery(state="TX", taxonomy_description="\t"),
        NppesSearchQuery(state="TX", organization_name="  \n"),
        NppesSearchQuery(city="   ", taxonomy_description="  ", organization_name=""),
    ],
)
def test_state_alone_is_not_a_valid_query(query: NppesSearchQuery) -> None:
    assert query.has_narrow_filter() is False
    with pytest.raises(NppesQueryError, match="narrow filter"):
        query.require_valid()


@pytest.mark.parametrize(
    "query",
    [
        NppesSearchQuery(city="Austin"),
        NppesSearchQuery(state="TX", city="Austin"),
        NppesSearchQuery(taxonomy_description="Chiropractor"),
        NppesSearchQuery(organization_name="100 CHIRO"),
        NppesSearchQuery(state="TX", organization_name="100 CHIRO"),
    ],
)
def test_narrow_filters_are_valid(query: NppesSearchQuery) -> None:
    assert query.has_narrow_filter() is True
    query.require_valid()


def test_narrow_filter_error_message_is_stable() -> None:
    assert "state alone is not sufficient" in NARROW_FILTER_ERROR


def test_query_strips_filters_and_omits_blanks_from_params() -> None:
    query = NppesSearchQuery(
        state="  tx  ",
        city="  Austin  ",
        taxonomy_description="  Chiropractor  ",
        organization_name="  100 CHIRO  ",
    )

    assert query.state == "tx"
    assert query.city == "Austin"
    assert query.taxonomy_description == "Chiropractor"
    assert query.organization_name == "100 CHIRO"
    assert query.to_params()["state"] == "TX"
    assert query.to_params()["city"] == "Austin"

    blank = NppesSearchQuery(state="TX", city="   ", taxonomy_description="\t")
    params = blank.to_params()
    assert "city" not in params
    assert "taxonomy_description" not in params
    assert "organization_name" not in params
