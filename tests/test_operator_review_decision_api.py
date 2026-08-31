from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from tests.test_review_queue_service import _seed_optimizer_recommendation
from vyro_growth.api.operator_review_queue import (
    GENERIC_DECISION_ERROR,
    OPERATOR_REVIEW_QUEUE_PATH,
    OPERATOR_UI_DECISION_SOURCE,
)
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import ReviewArtifactType, ReviewDecisionStatus
from vyro_growth.main import app
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    Meeting,
    OperatorReviewDecision,
    OutreachMessage,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt

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


def _decision_url(artifact_type: str, artifact_id: object) -> str:
    return f"{OPERATOR_REVIEW_QUEUE_PATH}/{artifact_type}/{artifact_id}/decision"


def _counts(db: Session) -> dict[str, int]:
    return {
        "decisions": db.scalar(select(func.count()).select_from(OperatorReviewDecision)) or 0,
        "activities": db.scalar(select(func.count()).select_from(Activity)) or 0,
        "meetings": db.scalar(select(func.count()).select_from(Meeting)) or 0,
        "enrollments": db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0,
        "messages": db.scalar(select(func.count()).select_from(OutreachMessage)) or 0,
    }


def test_valid_decision_submission_records_and_redirects(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    _seed_pipeline(db_session)
    recommendation = _seed_optimizer_recommendation(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)

    posted = api_client.post(
        _decision_url(ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value, recommendation.id),
        data={
            "decision": ReviewDecisionStatus.APPROVED.value,
            "reviewer": "ops",
            "reviewer_notes": "Looks ready for a later phase",
        },
        follow_redirects=False,
    )
    after = _counts(db_session)
    stored = db_session.scalar(select(OperatorReviewDecision))
    detail = api_client.get(posted.headers["location"])

    assert posted.status_code == 303
    assert posted.headers["location"].endswith(
        f"{OPERATOR_REVIEW_QUEUE_PATH}/optimizer_recommendation/"
        f"{recommendation.id}?decision_recorded=1"
    )
    assert after["decisions"] == before["decisions"] + 1
    assert after["activities"] == before["activities"] + 1
    assert after["meetings"] == before["meetings"]
    assert after["enrollments"] == before["enrollments"]
    assert after["messages"] == before["messages"]
    assert stored is not None
    assert stored.decision == ReviewDecisionStatus.APPROVED.value
    assert stored.reviewer == "ops"
    assert stored.source == OPERATOR_UI_DECISION_SOURCE
    assert stored.executed is False
    assert stored.execution_attempted is False
    assert stored.outbound_attempted is False
    assert stored.live_call_attempted is False
    assert stored.recommendation_applied is False
    assert detail.status_code == 200
    body = detail.text
    assert 'id="decision-recorded"' in body
    assert "Decision recorded" in body
    assert "approved" in body
    assert "ops" in body
    assert "No execution was attempted" in body
    assert "There is no execute control" in body
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    for marker in EXECUTE_MARKERS:
        assert marker not in body.lower()


def test_invalid_decision_is_generic_and_does_not_write(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    _seed_pipeline(db_session)
    recommendation = _seed_optimizer_recommendation(db_session)
    before = _counts(db_session)

    response = api_client.post(
        _decision_url(ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value, recommendation.id),
        data={
            "decision": "execute_now",
            "reviewer": "ops",
            "reviewer_notes": f"Call {PROSPECT_EMAIL} about {PHI_SNIPPET} sk-testsecret12345",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    body = response.text
    assert GENERIC_DECISION_ERROR in body
    assert 'id="decision-form-error"' in body
    assert "execute_now" not in body
    for token in UNSAFE_TOKENS:
        assert token.lower() not in body.lower() if token != XSS_LABEL else token not in body
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.UNAVAILABLE


def test_missing_item_decision_is_not_found(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    missing = api_client.post(
        _decision_url(ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value, uuid4()),
        data={"decision": "approved", "reviewer": "ops"},
        follow_redirects=False,
    )
    invalid = api_client.post(
        _decision_url("not-a-type", "not-a-uuid"),
        data={"decision": "approved"},
        follow_redirects=False,
    )

    assert missing.status_code == 404
    assert "Review item not found" in missing.text
    assert invalid.status_code == 404
    assert "Review item not found" in invalid.text
    for body in (missing.text, invalid.text):
        assert "<form" not in body.lower()
        for marker in EXECUTE_MARKERS:
            assert marker not in body.lower()


def test_decision_form_requires_internal_access(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recommendation = _seed_optimizer_recommendation(db_session)
    url = _decision_url(ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value, recommendation.id)

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
    stored = db_session.scalar(select(OperatorReviewDecision))
    assert stored is not None
    assert stored.decision == ReviewDecisionStatus.REJECTED.value
    assert stored.executed is False


def test_reviewer_notes_are_sanitized_and_escaped(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    recommendation = _seed_optimizer_recommendation(db_session)

    posted = api_client.post(
        _decision_url(ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value, recommendation.id),
        data={
            "decision": ReviewDecisionStatus.NEEDS_CHANGES.value,
            "reviewer": XSS_LABEL,
            "reviewer_notes": (
                f"Call {PROSPECT_EMAIL} about {PHI_SNIPPET} {XSS_LABEL} sk-testsecret12345"
            ),
        },
        follow_redirects=False,
    )
    detail = api_client.get(posted.headers["location"])
    stored = db_session.scalar(select(OperatorReviewDecision))

    assert posted.status_code == 303
    assert stored is not None
    assert stored.decision == ReviewDecisionStatus.NEEDS_CHANGES.value
    assert stored.reviewer_notes == "[REDACTED_UNSAFE_TEXT]"
    assert PROSPECT_EMAIL not in (stored.reviewer_notes or "")
    body = detail.text
    assert XSS_LABEL not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "[REDACTED_UNSAFE_TEXT]" in body
    for token in (PHI_SNIPPET, PROSPECT_EMAIL, "diabetes", "sk-testsecret12345"):
        assert token.lower() not in body.lower()
    assert stored.executed is False


def test_double_submit_and_refresh_are_idempotent(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    recommendation = _seed_optimizer_recommendation(db_session)
    payload = {
        "decision": ReviewDecisionStatus.APPROVED.value,
        "reviewer": "ops",
        "reviewer_notes": "Hold as a decision record only",
    }
    url = _decision_url(ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value, recommendation.id)

    first = api_client.post(url, data=payload, follow_redirects=False)
    after_first = _counts(db_session)
    second = api_client.post(url, data=payload, follow_redirects=False)
    after_second = _counts(db_session)
    refresh = api_client.get(first.headers["location"])
    after_refresh = _counts(db_session)
    stored_rows = db_session.scalars(select(OperatorReviewDecision)).all()

    assert first.status_code == 303
    assert second.status_code == 303
    assert first.headers["location"] == second.headers["location"]
    assert after_first["decisions"] == 1
    assert after_second["decisions"] == 1
    assert after_second["activities"] == after_first["activities"]
    assert after_refresh == after_second
    assert len(stored_rows) == 1
    assert stored_rows[0].executed is False
    assert stored_rows[0].outbound_attempted is False
    assert refresh.status_code == 200
    assert "Decision recorded" in refresh.text
    assert "approved" in refresh.text


def test_decision_update_still_does_not_execute(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    recommendation = _seed_optimizer_recommendation(db_session)
    url = _decision_url(ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value, recommendation.id)
    set_operator_halt(db_session, halted=True, reason="keep-halted")

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
    stored = db_session.scalar(select(OperatorReviewDecision))
    assert after["decisions"] == before["decisions"]
    assert after["activities"] == before["activities"] + 1
    assert after["meetings"] == before["meetings"]
    assert stored is not None
    assert stored.decision == ReviewDecisionStatus.NEEDS_CHANGES.value
    assert stored.previous_decision == ReviewDecisionStatus.APPROVED.value
    assert stored.executed is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_decision_form_has_no_execution_side_effects(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    _seed_pipeline(db_session)
    recommendation = _seed_optimizer_recommendation(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)

    response = api_client.post(
        _decision_url(ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value, recommendation.id),
        data={"decision": "approved", "reviewer": "ops"},
        follow_redirects=False,
    )
    after = _counts(db_session)
    activities = db_session.scalars(
        select(Activity).where(Activity.action == "operator_review_decision_recorded")
    ).all()

    assert response.status_code == 303
    assert after["meetings"] == before["meetings"]
    assert after["enrollments"] == before["enrollments"]
    assert after["messages"] == before["messages"]
    assert after["decisions"] == before["decisions"] + 1
    assert activities
    for activity in activities:
        details = activity.details
        assert details["executed"] is False
        assert details["execution_attempted"] is False
        assert details["outbound_attempted"] is False
        assert details["live_call_attempted"] is False
        assert details["recommendation_applied"] is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED
