from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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
                ),
            ),
            result_count=1,
            page_size=1,
            source_url="https://example.test",
        )


@pytest.fixture
def api_client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _patch_discovery_settings(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    monkeypatch.setattr("vyro_growth.main.get_settings", lambda: settings)


def _patch_fake_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "vyro_growth.api.discovery.build_nppes_provider",
        lambda **_kwargs: ApiFakeProvider(),
    )


def test_discovery_api_triggers_run_in_development(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_discovery_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    _patch_fake_provider(monkeypatch)

    response = api_client.post(
        "/internal/discovery/nppes",
        json={"state": "TX", "city": "Austin", "max_records": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["records_fetched"] == 1
    assert body["status"] == "completed"


def test_discovery_api_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_discovery_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.post(
        "/internal/discovery/nppes",
        json={"state": "TX", "city": "Austin", "max_records": 1},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal discovery trigger requires INTERNAL_API_KEY"


def test_discovery_api_rejects_missing_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_discovery_settings(
        monkeypatch,
        Settings(environment="development", internal_api_key="internal-secret"),
    )

    response = api_client.post(
        "/internal/discovery/nppes",
        json={"state": "TX", "city": "Austin", "max_records": 1},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing internal API key"


def test_discovery_api_rejects_invalid_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_discovery_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    response = api_client.post(
        "/internal/discovery/nppes",
        headers={"X-Internal-Api-Key": "wrong-secret"},
        json={"state": "TX", "city": "Austin", "max_records": 1},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing internal API key"


def test_discovery_api_accepts_valid_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_discovery_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    _patch_fake_provider(monkeypatch)

    response = api_client.post(
        "/internal/discovery/nppes",
        headers={"X-Internal-Api-Key": "internal-secret"},
        json={"state": "TX", "city": "Austin", "max_records": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["records_fetched"] == 1
    assert body["status"] == "completed"


def test_discovery_api_requires_a_targeting_filter(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_discovery_settings(
        monkeypatch,
        Settings(environment="development", internal_api_key="internal-secret"),
    )

    response = api_client.post(
        "/internal/discovery/nppes",
        headers={"X-Internal-Api-Key": "internal-secret"},
        json={"max_records": 1},
    )

    assert response.status_code == 422


def test_discovery_api_rejects_state_only(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_discovery_settings(
        monkeypatch,
        Settings(environment="development", internal_api_key="internal-secret"),
    )

    response = api_client.post(
        "/internal/discovery/nppes",
        headers={"X-Internal-Api-Key": "internal-secret"},
        json={"state": "TX", "max_records": 1},
    )

    assert response.status_code == 422


def test_discovery_api_rejects_whitespace_only_city(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_discovery_settings(
        monkeypatch,
        Settings(environment="development", internal_api_key="internal-secret"),
    )

    response = api_client.post(
        "/internal/discovery/nppes",
        headers={"X-Internal-Api-Key": "internal-secret"},
        json={"state": "TX", "city": "   ", "max_records": 1},
    )

    assert response.status_code == 422
