from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_email_verification_service import PROSPECT_EMAIL, _contact, _org
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import EmailVerificationVerdict
from vyro_growth.main import app
from vyro_growth.models import Activity
from vyro_growth.providers.email_verification import StaticEmailVerificationProvider
from vyro_growth.services.email_verification import EmailVerificationService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt


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


def test_metrics_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.get("/internal/email-verification/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["outbound_attempted"] is False
    assert body["live_call_attempted"] is False
    assert body["smtp_attempted"] is False
    assert body["owner_approved"] is False
    assert body["email_verification_live_enabled"] is False
    assert body["email_verification_is_not_outbound"] is True
    assert body["contacts_considered"] == 0
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_metrics_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get("/internal/email-verification/metrics")

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_metrics_export_never_includes_contact_fields(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    _contact(db_session, organization)
    EmailVerificationService(
        StaticEmailVerificationProvider({PROSPECT_EMAIL: EmailVerificationVerdict.VALID})
    ).verify_organization(db_session, organization.id)
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.get("/internal/email-verification/metrics")

    assert response.status_code == 200
    body = response.json()
    rendered = response.text
    assert body["contacts_with_verified_safe_email"] == 1
    assert body["halt_changed"] is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert PROSPECT_EMAIL not in rendered
    assert "512-555-0100" not in rendered
    assert "AUSTIN FAMILY MEDICINE" not in rendered
    assert "1487448189" not in rendered
    assert "email" not in body
    assert "phone" not in body
    assert "npi" not in body
