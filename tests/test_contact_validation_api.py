from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.decision_makers import candidate
from tests.test_contact_enrichment_service import _org, _service
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import ContactVerificationStatus
from vyro_growth.main import app
from vyro_growth.models import Activity
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

PROSPECT_EMAIL = "owner@austinfamily.example"
PLAN_PATH = "/internal/contact-validation/plan"
REPORT_PATH = "/internal/contact-validation/report"


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


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr("vyro_growth.main.get_settings", lambda: settings)


def test_plan_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.get(PLAN_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["outbound_attempted"] is False
    assert body["live_call_attempted"] is False
    assert body["owner_approved"] is False
    assert body["supervised_validation_run_permitted"] is False
    assert body["packet_kind"] == "contact_validation_plan"
    assert body["segment"]["max_cohort_size"] == 200
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_report_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(REPORT_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_report_export_never_includes_contact_fields(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    _service(
        [
            candidate(
                business_email=PROSPECT_EMAIL,
                verification_status=ContactVerificationStatus.PROVIDER_VERIFIED,
            )
        ]
    ).enrich_organization(db_session, organization.id)
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.get(REPORT_PATH, params={"state": "TX", "max_cohort_size": 200})

    assert response.status_code == 200
    body = response.json()
    rendered = response.text
    assert body["decision_maker_candidates_found_count"] == 1
    assert body["halt_changed"] is False
    assert body["no_contact_found_is_failure"] is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert PROSPECT_EMAIL not in rendered
    assert "512-555-0100" not in rendered
    assert "AUSTIN FAMILY MEDICINE" not in rendered
    assert "1487448189" not in rendered
    assert "email" not in body
    assert "phone" not in body
    assert "npi" not in body


def test_invalid_cohort_size_is_rejected(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.get(PLAN_PATH, params={"max_cohort_size": 201})

    assert response.status_code == 422
