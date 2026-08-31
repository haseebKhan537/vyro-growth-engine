from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from tests.test_review_queue_service import _seed_optimizer_recommendation
from vyro_growth.api.operator_review_queue import (
    OPERATOR_REVIEW_QUEUE_PATH,
    parse_review_artifact_type,
    parse_review_status_filter,
    render_review_item_detail,
    render_review_item_missing,
    render_review_queue_error,
    render_review_queue_list,
)
from vyro_growth.api.operator_ui import OPERATOR_REVIEW_QUEUE_PATH as REVIEW_PATH
from vyro_growth.api.review_queue import (
    ReviewDecisionResponse,
    ReviewItemResponse,
    ReviewQueueResponse,
)
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import ReviewArtifactType, ReviewDecisionStatus
from vyro_growth.main import app
from vyro_growth.models import Activity, CampaignEnrollment, Meeting, OutreachMessage
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.review_queue import ReviewQueueService

XSS_LABEL = "<script>alert(1)</script>"
ACTION_MARKERS = ("<button", "<form", "javascript:", "onclick=", "<input")


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


def _empty_queue(**overrides: object) -> ReviewQueueResponse:
    payload = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "pending_count": 0,
        "decided_count": 0,
        "operator_halt_status": "halted",
        "items": [],
    }
    payload.update(overrides)
    return ReviewQueueResponse.model_validate(payload)


def _item(**overrides: object) -> ReviewItemResponse:
    payload = {
        "artifact_type": ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value,
        "artifact_id": uuid4(),
        "title": "Review optimizer recommendation",
        "summary": "Dry-run recommendation pending operator review",
        "status": "pending_operator_review",
        "created_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "risk_labels": ["decision_record_only", "not_executed"],
        "executable_later": True,
        "executed": False,
    }
    payload.update(overrides)
    return ReviewItemResponse.model_validate(payload)


def escape_marker() -> str:
    return "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_parse_review_filters_ignore_unknown_values() -> None:
    assert parse_review_status_filter(None, include_decided=False) == "pending"
    assert parse_review_status_filter(None, include_decided=True) == "all"
    assert parse_review_status_filter("approved", include_decided=False) == "approved"
    assert parse_review_status_filter("execute", include_decided=False) == "pending"
    assert parse_review_artifact_type(None) is None
    assert parse_review_artifact_type("personalization_draft") == "personalization_draft"
    assert parse_review_artifact_type("../secrets") is None
    assert REVIEW_PATH == OPERATOR_REVIEW_QUEUE_PATH


def test_renderer_empty_state_is_read_only_and_escaped() -> None:
    html = render_review_queue_list(
        _empty_queue(),
        artifact_type=None,
        status="pending",
        include_decided=False,
        items=[],
    )

    assert 'id="operator-review-queue"' in html
    assert "No pending review items" in html
    assert "No approve, reject, or execute controls" in html
    for marker in ACTION_MARKERS:
        assert marker not in html.lower()


def test_renderer_populated_status_filter_and_xss_escape() -> None:
    pending = _item(title=XSS_LABEL)
    decided = _item(
        artifact_type=ReviewArtifactType.CONTENT_BRIEF.value,
        status="approved",
        title="Approved content brief",
        decision=ReviewDecisionResponse(
            decision_id=uuid4(),
            decision="approved",
            reviewer="ops",
            source="cli",
            decided_at=datetime(2026, 8, 31, 13, 0, tzinfo=UTC),
        ),
    )
    html = render_review_queue_list(
        _empty_queue(pending_count=1, decided_count=1),
        artifact_type=None,
        status="pending",
        include_decided=False,
        items=[pending],
    )

    assert "Review optimizer recommendation" not in html or XSS_LABEL not in html
    assert XSS_LABEL not in html
    assert escape_marker() in html
    assert str(pending.artifact_id) in html
    assert str(decided.artifact_id) not in html
    assert "include_decided=true" in html
    for marker in ACTION_MARKERS:
        assert marker not in html.lower()


def test_detail_renderer_and_missing_pages_are_safe() -> None:
    item = _item(
        title=XSS_LABEL,
        summary="Safe summary",
        decision=ReviewDecisionResponse(
            decision_id=uuid4(),
            decision="needs_changes",
            reviewer=XSS_LABEL,
            source="internal_api",
            reviewer_notes=XSS_LABEL,
            decided_at=datetime(2026, 8, 31, 13, 0, tzinfo=UTC),
        ),
    )
    html = render_review_item_detail(item)
    missing = render_review_item_missing()
    error = render_review_queue_error()

    assert 'id="operator-review-item"' in html
    assert XSS_LABEL not in html
    assert escape_marker() in html
    assert "There are no approve, reject, or execute controls" in html
    assert 'id="operator-review-queue-missing"' in missing
    assert 'id="operator-review-queue-error"' in error
    assert "sk-testsecret12345" not in error
    for page in (html, missing, error):
        for marker in ACTION_MARKERS:
            assert marker not in page.lower()


def test_review_queue_ui_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    response = api_client.get(OPERATOR_REVIEW_QUEUE_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Review queue" in body
    assert "No pending review items" in body
    assert "read-only" in body.lower()
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in ACTION_MARKERS:
        assert marker not in body.lower()


def test_review_queue_ui_rejects_non_development_without_key(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))

    response = api_client.get(OPERATOR_REVIEW_QUEUE_PATH)

    assert response.status_code == 403
    assert response.json()["detail"] == "Internal operator route requires INTERNAL_API_KEY"


def test_review_queue_ui_rejects_missing_and_invalid_key_and_disallows_post(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )

    missing = api_client.get(OPERATOR_REVIEW_QUEUE_PATH)
    assert missing.status_code == 401

    post = api_client.post(
        OPERATOR_REVIEW_QUEUE_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    assert post.status_code == 405

    invalid = api_client.get(
        OPERATOR_REVIEW_QUEUE_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    assert invalid.status_code == 401


def test_review_queue_ui_accepts_valid_key_and_stays_read_only(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    _seed_pipeline(db_session)
    recommendation = _seed_optimizer_recommendation(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before_activities = db_session.scalar(select(func.count()).select_from(Activity))
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting))
    before_enrollments = db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage))

    response = api_client.get(
        OPERATOR_REVIEW_QUEUE_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert response.status_code == 200
    body = response.text
    assert "Review queue" in body
    assert str(recommendation.id) in body
    assert HaltStatus.HALTED.value in body
    assert PHI_SNIPPET not in body
    assert PROSPECT_EMAIL not in body
    assert "diabetes" not in body.lower()
    assert "sk-testsecret12345" not in body
    for marker in ACTION_MARKERS:
        assert marker not in body.lower()
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_review_queue_ui_filters_and_detail_are_read_only(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    _seed_pipeline(db_session)
    recommendation = _seed_optimizer_recommendation(db_session)
    ReviewQueueService().record_decision(
        db_session,
        artifact_type=ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value,
        artifact_id=recommendation.id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
    )
    before_activities = db_session.scalar(select(func.count()).select_from(Activity))

    pending = api_client.get(OPERATOR_REVIEW_QUEUE_PATH)
    decided = api_client.get(f"{OPERATOR_REVIEW_QUEUE_PATH}?include_decided=true&status=approved")
    typed = api_client.get(
        f"{OPERATOR_REVIEW_QUEUE_PATH}?artifact_type=optimizer_recommendation&include_decided=true"
    )
    detail = api_client.get(
        f"{OPERATOR_REVIEW_QUEUE_PATH}/optimizer_recommendation/{recommendation.id}"
    )
    missing = api_client.get(
        f"{OPERATOR_REVIEW_QUEUE_PATH}/optimizer_recommendation/{uuid4()}"
    )
    invalid = api_client.get(f"{OPERATOR_REVIEW_QUEUE_PATH}/not-a-type/not-a-uuid")

    assert pending.status_code == 200
    assert str(recommendation.id) not in pending.text
    assert decided.status_code == 200
    assert str(recommendation.id) in decided.text
    assert "approved" in decided.text
    assert typed.status_code == 200
    assert str(recommendation.id) in typed.text
    assert detail.status_code == 200
    assert "Review item" in detail.text
    assert "approved" in detail.text
    assert "There are no approve, reject, or execute controls" in detail.text
    assert missing.status_code == 404
    assert "Review item not found" in missing.text
    assert invalid.status_code == 404
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert read_operator_halt(db_session) is HaltStatus.UNAVAILABLE
    for body in (pending.text, decided.text, typed.text, detail.text, missing.text):
        assert PHI_SNIPPET not in body
        for marker in ACTION_MARKERS:
            assert marker not in body.lower()


def test_review_queue_ui_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def boom(*_args: object, **_kwargs: object) -> ReviewQueueResponse:
        raise RuntimeError("db exploded sk-testsecret12345 patient diabetes")

    monkeypatch.setattr(
        "vyro_growth.api.operator_review_queue.build_review_queue_response",
        boom,
    )

    response = api_client.get(OPERATOR_REVIEW_QUEUE_PATH)

    assert response.status_code == 500
    body = " ".join(response.text.split())
    assert "Unable to load the review queue" in body
    assert "sk-testsecret12345" not in body
    assert "diabetes" not in body.lower()
    assert "No pipeline rows were written" in body
    for marker in ACTION_MARKERS:
        assert marker not in response.text.lower()
