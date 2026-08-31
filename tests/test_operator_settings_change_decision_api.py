from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from vyro_growth.api.operator_review_queue import GENERIC_DECISION_ERROR
from vyro_growth.api.operator_settings_change_requests import (
    OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH,
    OPERATOR_UI_SETTINGS_DECISION_SOURCE,
)
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import SettingsChangeDecisionStatus, SettingsChangeRequestType
from vyro_growth.main import app
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    LiveSettingsChangeRequest,
    LiveSettingsChangeRequestDecision,
    Meeting,
    OutreachMessage,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

XSS_LABEL = "<script>alert(1)</script>"
EXECUTE_MARKERS = ("javascript:", "onclick=", "onerror=")
UNSAFE_TOKENS = (
    PHI_SNIPPET,
    PROSPECT_EMAIL,
    "diabetes",
    "sk-testsecret12345",
    XSS_LABEL,
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


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr("vyro_growth.main.get_settings", lambda: settings)


def _seed_request(db: Session) -> LiveSettingsChangeRequest:
    set_operator_halt(db, halted=True, reason="keep-halted")
    view = SettingsChangeRequestService().create(
        db,
        Settings(),
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        desired_boolean=False,
        desired_status="disabled",
        idempotency_key="ui-decision-keep-outbound",
    )
    row = db.get(LiveSettingsChangeRequest, view.request_id)
    assert row is not None
    return row


def _decision_url(request_id: object) -> str:
    return f"{OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH}/{request_id}/decision"


def _counts(db: Session) -> dict[str, int]:
    return {
        "decisions": db.scalar(select(func.count()).select_from(LiveSettingsChangeRequestDecision))
        or 0,
        "activities": db.scalar(select(func.count()).select_from(Activity)) or 0,
        "requests": db.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) or 0,
        "meetings": db.scalar(select(func.count()).select_from(Meeting)) or 0,
        "enrollments": db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0,
        "messages": db.scalar(select(func.count()).select_from(OutreachMessage)) or 0,
    }


def test_valid_settings_change_decision_submission_records_and_redirects(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    row = _seed_request(db_session)
    before = _counts(db_session)

    posted = api_client.post(
        _decision_url(row.id),
        data={
            "decision": SettingsChangeDecisionStatus.APPROVED.value,
            "reviewer": "ops",
            "reviewer_notes": "Hold as a later settings review",
        },
        follow_redirects=False,
    )
    after = _counts(db_session)
    stored = db_session.scalar(select(LiveSettingsChangeRequestDecision))
    db_session.refresh(row)
    detail = api_client.get(posted.headers["location"])

    assert posted.status_code == 303
    assert posted.headers["location"].endswith(
        f"{OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH}/{row.id}?decision_recorded=1"
    )
    assert after["decisions"] == before["decisions"] + 1
    assert after["activities"] == before["activities"] + 1
    assert after["requests"] == before["requests"]
    assert after["meetings"] == before["meetings"]
    assert after["enrollments"] == before["enrollments"]
    assert after["messages"] == before["messages"]
    assert stored is not None
    assert stored.decision == SettingsChangeDecisionStatus.APPROVED.value
    assert stored.reviewer == "ops"
    assert stored.source == OPERATOR_UI_SETTINGS_DECISION_SOURCE
    assert stored.executed is False
    assert stored.settings_applied is False
    assert stored.halt_changed is False
    assert stored.owner_approved is False
    assert stored.live_action is False
    assert stored.outbound_attempted is False
    assert row.executed is False
    assert row.settings_applied is False
    assert row.owner_approved is False
    assert row.halt_changed is False
    assert detail.status_code == 200
    body = detail.text
    assert 'id="decision-recorded"' in body
    assert "Decision recorded" in body
    assert "approved" in body
    assert "ops" in body
    assert "No settings were applied" in body
    assert "There is no apply, execute, enable outbound, or lift-halt control" in body
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    for marker in EXECUTE_MARKERS:
        assert marker not in body.lower()


def test_invalid_settings_change_decision_is_generic_and_does_not_write(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    row = _seed_request(db_session)
    before = _counts(db_session)

    response = api_client.post(
        _decision_url(row.id),
        data={
            "decision": "apply_now",
            "reviewer": "ops",
            "reviewer_notes": f"Call {PROSPECT_EMAIL} about {PHI_SNIPPET} sk-testsecret12345",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    body = response.text
    assert GENERIC_DECISION_ERROR in body
    assert 'id="decision-form-error"' in body
    assert "apply_now" not in body
    for token in UNSAFE_TOKENS:
        assert token not in body
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    db_session.refresh(row)
    assert row.settings_applied is False
    assert row.owner_approved is False


def test_missing_settings_change_decision_is_not_found(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    missing = api_client.post(
        _decision_url(uuid4()),
        data={"decision": "approved", "reviewer": "ops"},
        follow_redirects=False,
    )
    invalid = api_client.post(
        _decision_url("not-a-uuid"),
        data={"decision": "approved"},
        follow_redirects=False,
    )

    assert missing.status_code == 404
    assert "Settings change request not found" in missing.text
    assert invalid.status_code == 404
    assert "Settings change request not found" in invalid.text
    for body in (missing.text, invalid.text):
        assert "<form" not in body.lower()
        for marker in EXECUTE_MARKERS:
            assert marker not in body.lower()


def test_settings_change_decision_form_requires_internal_access(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _seed_request(db_session)
    url = _decision_url(row.id)

    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    unconfigured = api_client.post(url, data={"decision": "approved"}, follow_redirects=False)
    assert unconfigured.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.post(url, data={"decision": "approved"}, follow_redirects=False)
    assert missing.status_code == 401

    invalid = api_client.post(
        url,
        data={"decision": "approved"},
        headers={"X-Internal-Api-Key": "wrong-secret"},
        follow_redirects=False,
    )
    assert invalid.status_code == 401

    allowed = api_client.post(
        url,
        data={"decision": "rejected", "reviewer": "ops"},
        headers={"X-Internal-Api-Key": "internal-secret"},
        follow_redirects=False,
    )
    assert allowed.status_code == 303
    stored = db_session.scalar(select(LiveSettingsChangeRequestDecision))
    db_session.refresh(row)
    assert stored is not None
    assert stored.decision == SettingsChangeDecisionStatus.REJECTED.value
    assert stored.executed is False
    assert stored.settings_applied is False
    assert stored.owner_approved is False
    assert row.owner_approved is False
    assert row.settings_applied is False


def test_settings_change_decision_notes_are_sanitized_and_escaped(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    row = _seed_request(db_session)

    posted = api_client.post(
        _decision_url(row.id),
        data={
            "decision": SettingsChangeDecisionStatus.NEEDS_CHANGES.value,
            "reviewer": XSS_LABEL,
            "reviewer_notes": (
                f"Call {PROSPECT_EMAIL} about {PHI_SNIPPET} {XSS_LABEL} sk-testsecret12345"
            ),
        },
        follow_redirects=False,
    )
    detail = api_client.get(posted.headers["location"])
    stored = db_session.scalar(select(LiveSettingsChangeRequestDecision))

    assert posted.status_code == 303
    assert stored is not None
    assert stored.decision == SettingsChangeDecisionStatus.NEEDS_CHANGES.value
    assert stored.reviewer_notes == "[REDACTED_UNSAFE_TEXT]"
    assert PROSPECT_EMAIL not in (stored.reviewer_notes or "")
    body = detail.text
    assert XSS_LABEL not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "[REDACTED_UNSAFE_TEXT]" in body
    for token in (PHI_SNIPPET, PROSPECT_EMAIL, "diabetes", "sk-testsecret12345"):
        assert token.lower() not in body.lower()
    assert stored.executed is False
    assert stored.settings_applied is False
    assert stored.owner_approved is False
    db_session.refresh(row)
    assert row.settings_applied is False


def test_settings_change_double_submit_and_refresh_are_idempotent(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    row = _seed_request(db_session)
    payload = {
        "decision": SettingsChangeDecisionStatus.APPROVED.value,
        "reviewer": "ops",
        "reviewer_notes": "Hold as a decision record only",
    }
    url = _decision_url(row.id)

    first = api_client.post(url, data=payload, follow_redirects=False)
    after_first = _counts(db_session)
    second = api_client.post(url, data=payload, follow_redirects=False)
    after_second = _counts(db_session)
    refresh = api_client.get(first.headers["location"])
    after_refresh = _counts(db_session)
    stored_rows = db_session.scalars(select(LiveSettingsChangeRequestDecision)).all()

    assert first.status_code == 303
    assert second.status_code == 303
    assert first.headers["location"] == second.headers["location"]
    assert after_first["decisions"] == 1
    assert after_second["decisions"] == 1
    assert after_second["activities"] == after_first["activities"]
    assert after_refresh == after_second
    assert len(stored_rows) == 1
    assert stored_rows[0].executed is False
    assert stored_rows[0].settings_applied is False
    assert stored_rows[0].owner_approved is False
    assert refresh.status_code == 200
    assert "Decision recorded" in refresh.text
    assert "approved" in refresh.text


def test_settings_change_decision_update_still_does_not_apply(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    row = _seed_request(db_session)
    url = _decision_url(row.id)

    api_client.post(
        url,
        data={"decision": "approved", "reviewer": "ops"},
        follow_redirects=False,
    )
    before = _counts(db_session)
    changed = api_client.post(
        url,
        data={"decision": "needs_changes", "reviewer": "ops", "reviewer_notes": "Hold"},
        follow_redirects=False,
    )

    assert changed.status_code == 303
    after = _counts(db_session)
    stored = db_session.scalar(select(LiveSettingsChangeRequestDecision))
    db_session.refresh(row)
    assert after["decisions"] == before["decisions"]
    assert after["activities"] == before["activities"] + 1
    assert after["meetings"] == before["meetings"]
    assert stored is not None
    assert stored.decision == SettingsChangeDecisionStatus.NEEDS_CHANGES.value
    assert stored.previous_decision == SettingsChangeDecisionStatus.APPROVED.value
    assert stored.executed is False
    assert stored.settings_applied is False
    assert stored.owner_approved is False
    assert row.owner_approved is False
    assert row.executed is False
    assert row.settings_applied is False
    assert row.halt_changed is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_settings_change_decision_form_has_no_live_action_side_effects(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    row = _seed_request(db_session)
    before = _counts(db_session)

    response = api_client.post(
        _decision_url(row.id),
        data={"decision": "approved", "reviewer": "ops"},
        follow_redirects=False,
    )
    after = _counts(db_session)
    activities = db_session.scalars(
        select(Activity).where(Activity.action == "live_settings_change_decision_recorded")
    ).all()
    db_session.refresh(row)

    assert response.status_code == 303
    assert after["meetings"] == before["meetings"]
    assert after["enrollments"] == before["enrollments"]
    assert after["messages"] == before["messages"]
    assert after["requests"] == before["requests"]
    assert after["decisions"] == before["decisions"] + 1
    assert activities
    for activity in activities:
        details = activity.details
        assert details["executed"] is False
        assert details["settings_applied"] is False
        assert details["owner_approved"] is False
        assert details["halt_changed"] is False
        assert details["live_action"] is False
        assert details["no_execution"] is True
    assert row.owner_approved is False
    assert row.executed is False
    assert row.settings_applied is False
    assert row.halt_changed is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED
