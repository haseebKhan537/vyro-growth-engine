from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from tests.test_monitoring_service import UNSAFE_ERROR
from vyro_growth.cli import main
from vyro_growth.config import Settings
from vyro_growth.domain import (
    SettingsChangeDecisionStatus,
    SettingsChangeRequestStatus,
    SettingsChangeRequestType,
)
from vyro_growth.models import (
    Activity,
    Campaign,
    CampaignEnrollment,
    LiveSettingsChangeRequest,
    LiveSettingsChangeRequestDecision,
    Meeting,
    OutreachMessage,
    OwnerApprovalPacket,
)
from vyro_growth.services.launch_readiness import LaunchReadinessService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.settings_change_requests import (
    SettingsChangeRequestError,
    SettingsChangeRequestService,
    format_settings_change_list,
    format_settings_change_request,
)

DB_SECRET_URL = "postgresql+psycopg://vyro:super-db-password@localhost:5432/vyro_growth"


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _counts(db: Session) -> dict[str, int]:
    return {
        "activities": int(db.scalar(select(func.count()).select_from(Activity)) or 0),
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
        "packets": int(db.scalar(select(func.count()).select_from(OwnerApprovalPacket)) or 0),
        "campaigns": int(db.scalar(select(func.count()).select_from(Campaign)) or 0),
        "requests": int(
            db.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) or 0
        ),
        "decisions": int(
            db.scalar(select(func.count()).select_from(LiveSettingsChangeRequestDecision)) or 0
        ),
    }


def _flags(settings: Settings) -> dict[str, bool]:
    return {
        "outbound_enabled": settings.outbound_enabled,
        "openai_personalization_enabled": settings.openai_personalization_enabled,
        "smartlead_live_enabled": settings.smartlead_live_enabled,
        "openai_reply_classification_enabled": settings.openai_reply_classification_enabled,
        "google_calendar_live_enabled": settings.google_calendar_live_enabled,
        "voice_live_enabled": settings.voice_live_enabled,
        "outbound_halted": settings.outbound_halted,
    }


def test_create_keep_outbound_disabled_is_record_only(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    before_flags = _flags(settings)
    before = _counts(db_session)

    view = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="keep-outbound-disabled-1",
    )

    assert view.request_type == SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value
    assert view.requested_setting_names == ("OUTBOUND_ENABLED",)
    assert view.desired_boolean is False
    assert view.desired_status == "disabled"
    assert view.status == SettingsChangeRequestStatus.PENDING.value
    assert view.owner_decision_status == SettingsChangeDecisionStatus.PENDING.value
    assert view.record_only is True
    assert view.no_execution is True
    assert view.executed is False
    assert view.settings_applied is False
    assert view.owner_approved is False
    assert view.halt_changed is False
    assert view.live_action is False
    assert view.reused is False
    assert _flags(settings) == before_flags
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    after = _counts(db_session)
    assert after["requests"] == before["requests"] + 1
    assert after["meetings"] == before["meetings"]
    assert after["enrollments"] == before["enrollments"]
    assert after["messages"] == before["messages"]
    assert after["packets"] == before["packets"]


def test_duplicate_idempotency_key_does_not_create_a_second_row(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    service = SettingsChangeRequestService()
    first = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="same-key-once",
    )
    second = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="same-key-once",
    )

    assert first.request_id == second.request_id
    assert second.reused is True
    assert db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) == 1
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_provider_live_flag_review_requires_one_flag(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    view = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_PROVIDER_LIVE_FLAG_REVIEW.value,
        requested_setting_names=["SMARTLEAD_LIVE_ENABLED"],
    )
    assert view.requested_setting_names == ("SMARTLEAD_LIVE_ENABLED",)
    assert view.desired_boolean is True
    assert view.settings_applied is False
    assert settings.smartlead_live_enabled is False

    try:
        SettingsChangeRequestService().create(
            db_session,
            settings,
            request_type=SettingsChangeRequestType.REQUEST_PROVIDER_LIVE_FLAG_REVIEW.value,
            requested_setting_names=["SMARTLEAD_LIVE_ENABLED", "VOICE_LIVE_ENABLED"],
        )
        raise AssertionError("expected invalid provider flag review")
    except SettingsChangeRequestError as exc:
        assert exc.code == "invalid_setting_name"


def test_credential_review_names_variables_only_and_rejects_secrets(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)

    view = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_CREDENTIAL_CONFIGURATION_REVIEW.value,
        requested_setting_names=["OPENAI_API_KEY", "INTERNAL_API_KEY"],
    )
    text = format_settings_change_request(view, as_json=True)

    assert view.requested_setting_names == ("OPENAI_API_KEY", "INTERNAL_API_KEY")
    assert view.desired_boolean is None
    assert view.desired_status == "configured"
    assert SECRET_VALUE not in text
    _assert_no_leakage(text, SECRET_VALUE, DB_SECRET_URL)

    try:
        SettingsChangeRequestService().create(
            db_session,
            settings,
            request_type=SettingsChangeRequestType.REQUEST_CREDENTIAL_CONFIGURATION_REVIEW.value,
            requested_setting_names=["OPENAI_API_KEY"],
            reviewer_notes=f"paste {SECRET_VALUE}",
        )
        raise AssertionError("expected secret rejection")
    except SettingsChangeRequestError as exc:
        assert exc.code == "secret_value_rejected"
    assert db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) == 1


def test_approval_record_does_not_apply_settings_or_lift_halt(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(outbound_enabled=False)
    service = SettingsChangeRequestService()
    created = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
    )
    before = _counts(db_session)

    decided = service.record_decision(
        db_session,
        settings,
        request_id=created.request_id,
        decision="approved",
        reviewer="owner",
    )

    assert decided.owner_decision_status == SettingsChangeDecisionStatus.APPROVED.value
    assert decided.status == SettingsChangeRequestStatus.DECISION_RECORDED.value
    assert decided.owner_approved is False
    assert decided.settings_applied is False
    assert decided.executed is False
    assert decided.halt_changed is False
    assert decided.live_action is False
    assert decided.decision is not None
    assert decided.decision.owner_approved is False
    assert decided.decision.settings_applied is False
    assert settings.outbound_enabled is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    after = _counts(db_session)
    assert after["decisions"] == before["decisions"] + 1
    assert after["meetings"] == before["meetings"]
    assert after["enrollments"] == before["enrollments"]
    assert after["messages"] == before["messages"]


def test_list_and_detail_are_sanitized_and_do_not_change_runtime(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE)
    service = SettingsChangeRequestService()
    created = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_SAFE_DEFAULT.value,
        requested_setting_names=[
            "OPENAI_PERSONALIZATION_ENABLED",
            "VOICE_LIVE_ENABLED",
        ],
    )
    listed = service.list_requests(db_session, settings)
    detail = service.get_request(db_session, settings, created.request_id)
    text = format_settings_change_list(listed, as_json=True) + format_settings_change_request(
        detail or created, as_json=False
    )

    assert listed.request_count == 1
    assert listed.pending_count == 1
    assert listed.settings_applied is False
    assert listed.live_action is False
    assert detail is not None
    assert detail.request_id == created.request_id
    _assert_no_leakage(text, SECRET_VALUE)
    assert PHI_SNIPPET not in text
    assert PROSPECT_EMAIL not in text
    assert UNSAFE_ERROR not in text
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.openai_personalization_enabled is False
    assert settings.voice_live_enabled is False


def test_operator_halt_review_and_keep_safe_default(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    service = SettingsChangeRequestService()
    halt_review = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OPERATOR_HALT_REVIEW.value,
        requested_setting_names=["OUTBOUND_HALTED"],
    )
    keep = service.create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_SAFE_DEFAULT.value,
        requested_setting_names=["OPERATOR_HALT"],
    )

    assert halt_review.requested_setting_names == ("OPERATOR_HALT",)
    assert halt_review.desired_boolean is True
    assert halt_review.desired_status == "halted"
    assert keep.desired_status == "halted"
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_propose_from_launch_readiness_is_idempotent_and_does_not_apply(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    checklist = LaunchReadinessService().assess(db_session, settings)
    assert checklist.proposed_settings_change_requests
    first = SettingsChangeRequestService().propose_from_seeds(
        db_session,
        settings,
        checklist.proposed_settings_change_requests,
    )
    second = SettingsChangeRequestService().propose_from_seeds(
        db_session,
        settings,
        checklist.proposed_settings_change_requests,
    )

    assert first.created_count >= 1
    assert second.created_count == 0
    assert second.reused_count == first.request_count
    assert first.settings_applied is False
    assert first.live_action is False
    assert settings.outbound_enabled is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    later = LaunchReadinessService().assess(db_session, settings)
    assert later.pending_settings_change_request_count == first.request_count
    dumped = json.dumps(later.proposed_settings_change_requests, default=str)
    _assert_no_leakage(dumped)


def test_rejects_secret_like_idempotency_key_and_unknown_settings(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    try:
        SettingsChangeRequestService().create(
            db_session,
            settings,
            request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
            requested_setting_names=["OUTBOUND_ENABLED"],
            idempotency_key="sk-live-secret-key-value",
        )
        raise AssertionError("expected secret key rejection")
    except SettingsChangeRequestError as exc:
        assert exc.code == "secret_value_rejected"
    try:
        SettingsChangeRequestService().create(
            db_session,
            settings,
            request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
            requested_setting_names=["SCORING_THRESHOLD"],
        )
        raise AssertionError("expected invalid setting")
    except SettingsChangeRequestError as exc:
        assert exc.code == "invalid_setting_name"
    assert db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) == 0


def test_cli_create_list_detail_decision_and_propose(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE)

    class SessionCM:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: SessionCM())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: settings)

    create_code = main(
        [
            "create-settings-change-request",
            "--request-type",
            "keep_outbound_disabled",
            "--setting-name",
            "OUTBOUND_ENABLED",
            "--idempotency-key",
            "cli-keep-outbound",
            "--json",
        ]
    )
    created_out = capsys.readouterr().out
    assert create_code == 0
    created = json.loads(created_out)
    request_id = created["request_id"]
    _assert_no_leakage(created_out, SECRET_VALUE)

    list_code = main(["settings-change-requests", "--json"])
    listed_out = capsys.readouterr().out
    assert list_code == 0
    listed = json.loads(listed_out)
    assert listed["request_count"] >= 1
    assert listed["settings_applied"] is False

    detail_code = main(["settings-change-request", "--id", request_id, "--json"])
    detail_out = capsys.readouterr().out
    assert detail_code == 0
    assert json.loads(detail_out)["request_id"] == request_id

    decide_code = main(
        [
            "record-settings-change-decision",
            "--id",
            request_id,
            "--decision",
            "rejected",
            "--json",
        ]
    )
    decide_out = capsys.readouterr().out
    assert decide_code == 0
    decided = json.loads(decide_out)
    assert decided["owner_decision_status"] == "rejected"
    assert decided["settings_applied"] is False
    assert decided["owner_approved"] is False
    assert settings.outbound_enabled is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED

    propose_code = main(["propose-settings-changes", "--json"])
    propose_out = capsys.readouterr().out
    assert propose_code == 0
    proposed = json.loads(propose_out)
    assert proposed["settings_applied"] is False
    assert proposed["live_action"] is False
    _assert_no_leakage(propose_out, SECRET_VALUE)
