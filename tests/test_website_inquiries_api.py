from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings, validate_runtime_settings
from vyro_growth.database import get_db
from vyro_growth.domain import LeadStage, MessageDirection
from vyro_growth.main import app
from vyro_growth.models import (
    Activity,
    Contact,
    Conversation,
    Lead,
    Organization,
    OutreachMessage,
    WebsiteInquiry,
)
from vyro_growth.services.command_center import OperatorCommandCenterService

INTAKE_PATH = "/public/website-inquiries"


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


def _payload(*, submission_id: str | None = None) -> dict[str, object]:
    return {
        "submission_id": submission_id or str(uuid4()),
        "form_name": "Free audit request",
        "source_page": "/audit.html",
        "practice_name": "Potomac Cardiology Group",
        "contact_name": "Jordan Blake",
        "work_email": "Jordan.Blake@potomaccardiology.example",
        "business_phone": "+1 571 555 0100",
        "specialty": "Cardiology",
        "state": "va",
        "provider_count": "2-5",
        "primary_concern": "Denied or rejected claims",
        "preferred_contact": "Email",
        "business_context": "We want to discuss denial workflow ownership and aging A/R.",
        "contact_consent": True,
        "consent_text_version": "2026-09-10",
    }


def test_intake_fails_closed_when_disabled(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(website_intake_enabled=False))

    response = api_client.post(INTAKE_PATH, json=_payload())

    assert response.status_code == 503
    assert response.json()["detail"] == "Website inquiry intake is unavailable"


def test_intake_requires_dedicated_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(website_intake_enabled=True, website_intake_api_key="intake-secret"),
    )

    missing = api_client.post(INTAKE_PATH, json=_payload())
    invalid = api_client.post(
        INTAKE_PATH,
        json=_payload(),
        headers={"X-Website-Intake-Key": "wrong"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert "intake-secret" not in missing.text + invalid.text


def test_intake_authenticates_before_parsing_or_reading_large_body(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(website_intake_enabled=True, website_intake_api_key="intake-secret"),
    )

    malformed = api_client.post(INTAKE_PATH, content=b"not-json")
    oversized = api_client.post(INTAKE_PATH, content=b"x" * 25_000)

    assert malformed.status_code == 401
    assert oversized.status_code == 401


def test_intake_limits_authenticated_body_size(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(website_intake_enabled=True, website_intake_api_key="intake-secret"),
    )

    response = api_client.post(
        INTAKE_PATH,
        content=b"x" * 25_000,
        headers={"X-Website-Intake-Key": "intake-secret"},
    )

    assert response.status_code == 413


def test_intake_records_interested_lead_and_is_idempotent(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(
            website_intake_enabled=True,
            website_intake_api_key="intake-secret",
            outbound_enabled=False,
        ),
    )
    submission_id = str(uuid4())
    payload = _payload(submission_id=submission_id)
    headers = {"X-Website-Intake-Key": "intake-secret"}

    created = api_client.post(INTAKE_PATH, json=payload, headers=headers)
    repeated = api_client.post(INTAKE_PATH, json=payload, headers=headers)

    assert created.status_code == 202
    assert repeated.status_code == 202
    assert created.json()["accepted"] is True
    assert created.json()["duplicate"] is False
    assert repeated.json()["duplicate"] is True
    assert repeated.json()["reference_id"] == created.json()["reference_id"]

    assert db_session.scalar(select(func.count()).select_from(WebsiteInquiry)) == 1
    assert db_session.scalar(select(func.count()).select_from(Organization)) == 1
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 1
    assert db_session.scalar(select(func.count()).select_from(Lead)) == 1
    assert db_session.scalar(select(func.count()).select_from(Conversation)) == 1
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == 1

    organization = db_session.scalar(select(Organization))
    contact = db_session.scalar(select(Contact))
    lead = db_session.scalar(select(Lead))
    message = db_session.scalar(select(OutreachMessage))
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "website_inquiry_received")
    )
    assert organization is not None and organization.state == "VA"
    assert contact is not None and contact.email == "jordan.blake@potomaccardiology.example"
    assert contact.email_verified is False
    assert lead is not None and lead.stage == LeadStage.INTERESTED.value
    assert lead.source == "website_inquiry"
    assert message is not None and message.direction == MessageDirection.INBOUND.value
    assert activity is not None
    assert activity.details["outbound_attempted"] is False
    assert activity.details["live_call_attempted"] is False
    assert "jordan.blake" not in str(activity.details).casefold()
    summary = OperatorCommandCenterService().summarize(db_session, Settings())
    assert summary.pipeline.website_inquiries == 1


def test_intake_rejects_phi_hint_and_unknown_fields(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(website_intake_enabled=True, website_intake_api_key="intake-secret"),
    )
    payload = _payload()
    payload["business_context"] = "Patient name: Example Person"
    payload["unexpected"] = "value"

    response = api_client.post(
        INTAKE_PATH,
        json=payload,
        headers={"X-Website-Intake-Key": "intake-secret"},
    )

    assert response.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(WebsiteInquiry)) == 0


@pytest.mark.parametrize("field", ["practice_name", "contact_name", "business_context"])
def test_intake_rejects_phi_hints_across_submitted_text(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(website_intake_enabled=True, website_intake_api_key="intake-secret"),
    )
    payload = _payload()
    payload[field] = "Patient name: Example Person"

    response = api_client.post(
        INTAKE_PATH,
        json=payload,
        headers={"X-Website-Intake-Key": "intake-secret"},
    )

    assert response.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(WebsiteInquiry)) == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_page", "/"),
        ("specialty", None),
        ("state", None),
        ("state", "Virginia"),
    ],
)
def test_audit_intake_rejects_inconsistent_source_or_required_fields(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(website_intake_enabled=True, website_intake_api_key="intake-secret"),
    )
    payload = _payload()
    payload[field] = value

    response = api_client.post(
        INTAKE_PATH,
        json=payload,
        headers={"X-Website-Intake-Key": "intake-secret"},
    )

    assert response.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(WebsiteInquiry)) == 0


def test_runtime_config_requires_intake_key_only_when_enabled() -> None:
    disabled = Settings(
        environment="production",
        internal_api_key="internal-secret",
        website_intake_enabled=False,
    )
    enabled_without_key = Settings(
        environment="production",
        internal_api_key="internal-secret",
        website_intake_enabled=True,
        website_intake_api_key="",
    )

    assert not any("WEBSITE_INTAKE" in item for item in validate_runtime_settings(disabled))
    assert any("WEBSITE_INTAKE" in item for item in validate_runtime_settings(enabled_without_key))
