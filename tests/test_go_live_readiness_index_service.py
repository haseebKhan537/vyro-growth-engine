from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_action_readiness_service import _seed_plans_and_packets
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from vyro_growth.config import Settings
from vyro_growth.domain import NextActionCode, SettingsChangeRequestType
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    LiveSettingsChangeRequest,
    Meeting,
    OutreachMessage,
)
from vyro_growth.services.go_live_readiness_index import (
    HTML_ROUTE,
    GoLiveReadinessIndexService,
    index_payload,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

DB_SECRET_URL = "postgresql+psycopg://vyro:super-db-password@localhost:5432/vyro_growth"
VOLATILE_KEYS = {
    "generated_at",
    "current_sha",
    "current_branch",
    "working_tree_status",
    "available",
}


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _counts(db: Session) -> dict[str, int]:
    return {
        "activities": int(db.scalar(select(func.count()).select_from(Activity)) or 0),
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
        "requests": int(
            db.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) or 0
        ),
    }


def _strip_volatile(payload: object) -> object:
    if isinstance(payload, dict):
        return {
            key: "<volatile>" if key in VOLATILE_KEYS else _strip_volatile(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_strip_volatile(item) for item in payload]
    return payload


def test_empty_index_is_read_only_and_not_permission_to_go_live(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)
    settings = _settings()
    before_halt = read_operator_halt(db_session)

    index = GoLiveReadinessIndexService().build(db_session, settings)
    payload = index_payload(index)

    assert index.read_only is True
    assert index.no_execution is True
    assert index.execution_allowed is False
    assert index.go_live_permitted is False
    assert index.deployment_allowed is False
    assert index.build_allowed is False
    assert index.artifact_publish_allowed is False
    assert index.index_is_not_permission_to_go_live is True
    assert index.handoff_is_not_go_live is True
    assert index.binder_is_not_go_live is True
    assert index.runbook_is_not_deployment is True
    assert index.manifest_is_not_a_build_or_deploy is True
    assert index.owner_approved is False
    assert index.settings_applied is False
    assert index.halt_changed is False
    assert index.live_action is False
    assert index.outbound_enabled is False
    assert index.executed == 0
    keys = {card.key for card in index.surfaces}
    assert keys == {
        "operator-dashboard",
        "launch-readiness",
        "settings-execution-preflight",
        "owner-handoff-packet",
        "compliance-evidence-binder",
        "release-candidate-runbook",
        "release-artifact-manifest",
        "operator-audit-timeline",
    }
    assert HTML_ROUTE in index.related_routes
    codes = {item.code for item in index.remaining_manual_owner_checklist}
    assert NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value in codes
    assert NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value in codes
    assert payload["go_live_permitted"] is False
    assert payload["execution_allowed"] is False
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_index_reuses_summaries_and_does_not_leak_or_write(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings(openai_api_key=SECRET_VALUE, database_url=DB_SECRET_URL)
    _seed_plans_and_packets(db_session)
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="index-service",
        reviewer_notes=PHI_SNIPPET,
    )
    SettingsChangeRequestService().record_decision(
        db_session,
        settings,
        request_id=created.request_id,
        decision="approved",
        reviewer="owner",
    )
    before = _counts(db_session)
    before_halt = read_operator_halt(db_session)

    first = GoLiveReadinessIndexService().build(db_session, settings)
    second = GoLiveReadinessIndexService().build(db_session, settings)

    launch = next(card for card in first.surfaces if card.key == "launch-readiness")
    preflight = next(
        card for card in first.surfaces if card.key == "settings-execution-preflight"
    )
    handoff = next(card for card in first.surfaces if card.key == "owner-handoff-packet")
    assert launch.overall_status
    assert any(item.label == "Requests" for item in preflight.counts)
    assert any(item.label == "Packets" for item in handoff.counts)
    payload = index_payload(first)
    _assert_no_leakage(str(payload), SECRET_VALUE)
    assert PHI_SNIPPET not in str(payload)
    assert PROSPECT_EMAIL not in str(payload)
    assert SECRET_VALUE not in str(payload)
    assert DB_SECRET_URL not in str(payload)
    assert _strip_volatile(index_payload(first)) == _strip_volatile(index_payload(second))
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is before_halt
    assert settings.outbound_enabled is False
    assert first.local_git.git_provider_called is False
    assert first.local_git.github_actions_called is False


def test_index_is_deterministic_aside_from_timestamps_and_git(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    settings = _settings()
    first = GoLiveReadinessIndexService().build(db_session, settings)
    second = GoLiveReadinessIndexService().build(db_session, settings)
    assert first.generated_at != datetime(1999, 1, 1, tzinfo=UTC)
    assert _strip_volatile(index_payload(first)) == _strip_volatile(index_payload(second))
    assert first.packet_kind == "operator_go_live_readiness_index"
    assert first.purpose == "manual_owner_review_index_only"
