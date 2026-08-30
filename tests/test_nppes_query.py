from __future__ import annotations

import pytest

from vyro_growth.providers.nppes import NARROW_FILTER_ERROR, NppesQueryError, NppesSearchQuery


@pytest.mark.parametrize(
    "query",
    [
        NppesSearchQuery(),
        NppesSearchQuery(state="TX"),
        NppesSearchQuery(state="tx"),
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
