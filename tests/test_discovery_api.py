from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.fixtures.nppes_records import SAMPLE_ORG_RECORD
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.main import app
from vyro_growth.providers.nppes import (
    NormalizedNppesOrganization,
    NppesSearchPage,
    NppesSearchQuery,
)


class ApiFakeProvider:
    def search_organizations(self, query: NppesSearchQuery) -> NppesSearchPage:
        return NppesSearchPage(
            results=(
                NormalizedNppesOrganization(
                    npi="1487448189",
                    name="100 CHIRO CORONA LLC",
                    city="AUSTIN",
                    state="TX",
                    specialty="Chiropractor",
                    source_url="https://example.test",
                    query_metadata={"query": query.to_params(), "npi": "1487448189"},
                    raw_record=SAMPLE_ORG_RECORD,
                ),
            ),
            result_count=1,
            source_url="https://example.test",
        )


@pytest.fixture
def api_client(db_session: Session) -> TestClient:
    def override_get_db() -> Session:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_discovery_api_triggers_run_in_development(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vyro_growth.main.get_settings",
        lambda: Settings(environment="development"),
    )
    monkeypatch.setattr(
        "vyro_growth.api.discovery.build_nppes_provider",
        lambda **_kwargs: ApiFakeProvider(),
    )

    response = api_client.post(
        "/internal/discovery/nppes",
        json={"state": "TX", "city": "Austin", "max_records": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["records_fetched"] == 1
    assert body["status"] == "completed"


def test_discovery_api_rejects_non_development(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vyro_growth.main.get_settings",
        lambda: Settings(environment="production"),
    )

    response = api_client.post(
        "/internal/discovery/nppes",
        json={"state": "TX", "max_records": 1},
    )

    assert response.status_code == 403
