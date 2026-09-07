from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_phone_verification_service import PROSPECT_EMAIL, PROSPECT_PHONE, _org
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import ContactDiscoveryCallStatus
from vyro_growth.main import app
from vyro_growth.models import Activity, ContactDiscoveryCall
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.phone_verification import PhoneVerificationService

LIST_PATH = "/internal/phone-verification/tasks"


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


def test_list_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.get(LIST_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["outbound_attempted"] is False
    assert body["live_call_attempted"] is False
    assert body["voice_provider_used"] is False
    assert body["queued_count"] == 0
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_list_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(LIST_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_outcome_endpoint_stores_dnc_without_exposing_phone(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    queued = PhoneVerificationService().queue_for_organization(db_session, organization.id)

    response = api_client.post(
        f"{LIST_PATH}/{queued.task_id}/outcome",
        json={
            "outcome": ContactDiscoveryCallStatus.DO_NOT_CONTACT.value,
            "phone": PROSPECT_PHONE,
            "email": PROSPECT_EMAIL,
            "operator": "Jordan Blake",
            "notes": (
                "Asked Jordan Blake at AUSTIN FAMILY MEDICINE PLLC "
                f"not to use {PROSPECT_PHONE} or {PROSPECT_EMAIL}"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    dumped = str(body)
    assert PROSPECT_PHONE not in dumped
    assert PROSPECT_EMAIL not in dumped
    assert body["status"] == ContactDiscoveryCallStatus.DO_NOT_CONTACT.value
    assert body["suppression_created"] is True
    assert body["live_call_attempted"] is False
    assert body["voice_provider_used"] is False
    assert body["has_phone"] is True
    assert body["has_email"] is True
    assert body["has_operator_notes"] is True
    assert body["has_operator_label"] is True
    assert "operator_notes" not in body
    assert "operator_label" not in body
    assert "Jordan Blake" not in dumped
    assert "AUSTIN FAMILY MEDICINE" not in dumped
    task = db_session.get(ContactDiscoveryCall, queued.task_id)
    assert task is not None
    assert task.live_call_attempted is False
    assert task.operator_notes is not None
    assert task.operator_label is not None
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    listed = api_client.get(f"{LIST_PATH}?include_completed=true")
    assert listed.status_code == 200
    listed_body = listed.json()
    listed_text = listed.text
    assert PROSPECT_PHONE not in listed_text
    assert PROSPECT_EMAIL not in listed_text
    assert "Jordan Blake" not in listed_text
    assert "AUSTIN FAMILY MEDICINE" not in listed_text
    assert "operator_notes" not in listed_body["items"][0]
    assert "operator_label" not in listed_body["items"][0]
    assert listed_body["items"][0]["has_operator_notes"] is True
    assert listed_body["items"][0]["has_phone"] is True
    assert listed_body["items"][0]["has_email"] is True
