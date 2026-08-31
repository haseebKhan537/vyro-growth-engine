from __future__ import annotations

import re
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_action_readiness_service import _seed_plans_and_packets
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL
from tests.test_launch_readiness_service import SECRET_VALUE, _assert_no_leakage
from vyro_growth.api.compliance_evidence_binder import (
    AuditTimelineEntryEvidenceResponse,
    BinderChecklistItemResponse,
    ComplianceEvidenceBinderResponse,
    GuardrailDocEvidenceResponse,
    SecretPresenceItemResponse,
)
from vyro_growth.api.operator_compliance_evidence_binder import (
    render_compliance_evidence_binder,
    render_compliance_evidence_binder_error,
)
from vyro_growth.api.operator_ui import OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH
from vyro_growth.config import Settings
from vyro_growth.database import get_db
from vyro_growth.domain import FindingSeverity, NextActionCode, SettingsChangeRequestType
from vyro_growth.main import app
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    LiveSettingsChangeRequest,
    Meeting,
    OutreachMessage,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.settings_change_requests import SettingsChangeRequestService

XSS_LABEL = "<script>alert(1)</script>"
ACTION_MARKERS = ("javascript:", "onclick=", "onerror=")
FORM_MARKERS = ("<form", "<button", "<input", "<select", "<textarea")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
SECTION_IDS = (
    "outbound-and-halt",
    "live-provider-defaults",
    "no-execution-side-effects",
    "phi-secrets-redaction",
    "consent-phone-boundary",
    "ci-gates",
    "documented-guardrails",
    "operator-audit-timeline-summary",
    "reused-summaries",
    "remaining-manual-owner-checklist",
)
SECTION_HEADINGS = (
    "Outbound disabled and operator halt evidence",
    "No-live-provider default config evidence",
    "No-execution side-effect evidence",
    "PHI, secrets, and redaction evidence",
    "Consent-based phone-only boundary evidence",
    "CI dry-run smoke and deploy-config gates",
    "Documented compliance guardrails",
    "Operator audit timeline summary",
    "Reused read-only summaries",
    "Remaining manual owner checklist",
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


def _empty_binder(**overrides: object) -> ComplianceEvidenceBinderResponse:
    payload: dict[str, object] = {
        "generated_at": datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        "overall_status": "blocked",
        "operator_halt_status": "halted",
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "outbound_and_halt": {
            "operator_halt_status": "halted",
            "operator_halt_before": "halted",
            "operator_halt_after": "halted",
            "command_name": "compliance-evidence-binder",
            "route_name": "/internal/compliance-evidence-binder",
        },
        "live_provider_defaults": {},
        "no_execution_side_effects": {},
        "phi_secrets_redaction": {},
        "consent_phone_boundary": {"undeployed_callback_job": "place_consent_callback"},
        "ci_gates": {
            "smoke_gate": {
                "job_name": "smoke-dry-run",
                "command_name": "vyro-growth smoke-dry-run --local-only --json",
            },
            "deploy_config_gate": {
                "job_name": "deploy-config",
                "command_name": "docker compose config --quiet",
            },
            "smoke_run_command": "vyro-growth smoke-dry-run --local-only --json",
            "smoke_check_command": "vyro-growth check-smoke-output",
        },
        "operator_audit_timeline": {"route_name": "/internal/operator-audit-timeline"},
        "reused_summaries": {
            "launch_readiness_overall_status": "blocked",
            "settings_preflight_overall_status": "blocked",
            "owner_handoff_command": "owner-handoff-packet",
            "owner_handoff_route": "/internal/owner-handoff-packet",
        },
    }
    payload.update(overrides)
    return ComplianceEvidenceBinderResponse.model_validate(payload)


def _secret(**overrides: object) -> SecretPresenceItemResponse:
    payload: dict[str, object] = {
        "name": "EXAMPLE_API_KEY",
        "present": False,
        "status": "missing",
        "required": True,
    }
    payload.update(overrides)
    return SecretPresenceItemResponse.model_validate(payload)


def _guardrail(**overrides: object) -> GuardrailDocEvidenceResponse:
    payload: dict[str, object] = {
        "path": "docs/SECURITY.md",
        "present": True,
        "documented_codes": ["no_patient_phi", "outbound_disabled_default"],
    }
    payload.update(overrides)
    return GuardrailDocEvidenceResponse.model_validate(payload)


def _audit_entry(**overrides: object) -> AuditTimelineEntryEvidenceResponse:
    payload: dict[str, object] = {
        "event_type": "operator_review_decision",
        "source_surface": "operator_review_queue",
        "occurred_at": datetime(2026, 8, 31, 11, 0, tzinfo=UTC),
        "status": "approved",
        "decision_status": "approved",
    }
    payload.update(overrides)
    return AuditTimelineEntryEvidenceResponse.model_validate(payload)


def _checklist(**overrides: object) -> BinderChecklistItemResponse:
    payload: dict[str, object] = {
        "code": NextActionCode.BINDER_IS_NOT_GO_LIVE.value,
        "severity": FindingSeverity.INFO.value,
        "source_section": "compliance_evidence_binder",
        "status": "open",
    }
    payload.update(overrides)
    return BinderChecklistItemResponse.model_validate(payload)


def _strip_timestamps(html: str) -> str:
    return TIMESTAMP_RE.sub("<timestamp>", html)


def test_renderer_empty_state_is_read_only_and_has_no_execute_controls() -> None:
    html = render_compliance_evidence_binder(_empty_binder())

    assert 'id="operator-compliance-evidence-binder"' in html
    assert (
        OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH
        == "/internal/operator-compliance-evidence-binder"
    )
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in html
    for heading in SECTION_HEADINGS:
        assert heading in html
    assert "No secret inventory rows" in html
    assert "No audit timeline entries in this binder" in html
    assert "No remaining checklist items" in html
    assert "go_live_permitted=false" in html
    assert "execution_allowed=false" in html
    assert "binder_is_not_go_live=true" in html
    assert "not permission or machinery for going live" in html
    assert "There are no apply, execute, lift-halt" in html
    assert 'data-execution-allowed="false"' in html
    assert 'data-go-live-permitted="false"' in html
    assert 'data-manual-review-only="true"' in html
    assert 'data-no-execution="true"' in html
    assert 'data-binder-is-not-go-live="true"' in html
    assert "/internal/operator-owner-handoff-packet" in html
    assert "/internal/operator-audit-timeline" in html
    assert "/internal/compliance-evidence-binder" in html
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()


def test_renderer_populated_sections_and_xss_escape() -> None:
    html = render_compliance_evidence_binder(
        _empty_binder(
            blocker_codes=["execution_disabled_in_this_phase", XSS_LABEL],
            missing_credential_names=["EXAMPLE_API_KEY", XSS_LABEL],
            closed_provider_flag_names=["EXAMPLE_LIVE_ENABLED"],
            related_commands=["compliance-evidence-binder"],
            related_routes=[OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH],
            live_provider_defaults={
                "live_providers_enabled": False,
                "live_provider_flags": {XSS_LABEL: False, "VOICE_LIVE_ENABLED": False},
                "closed_provider_flag_names": ["VOICE_LIVE_ENABLED"],
                "required_flag_names": ["VOICE_LIVE_ENABLED"],
                "env_example_defaults_present": True,
            },
            phi_secrets_redaction={
                "missing_credential_names": ["EXAMPLE_API_KEY"],
                "secret_inventory": [_secret(name=XSS_LABEL), _secret()],
            },
            documented_guardrails=[_guardrail(path=XSS_LABEL), _guardrail()],
            operator_audit_timeline={
                "matching_count": 1,
                "shown_count": 1,
                "route_name": "/internal/operator-audit-timeline",
                "available_event_types": [XSS_LABEL, "operator_review_decision"],
                "entries": [_audit_entry(event_type=XSS_LABEL)],
            },
            reused_summaries={
                "launch_readiness_overall_status": "blocked",
                "launch_readiness_blocker_codes": [XSS_LABEL, "outbound_disabled"],
                "launch_readiness_next_action_codes": [
                    NextActionCode.KEEP_OUTBOUND_DISABLED.value
                ],
                "settings_preflight_overall_status": "blocked",
                "owner_handoff_command": "owner-handoff-packet",
                "owner_handoff_route": "/internal/owner-handoff-packet",
            },
            remaining_manual_owner_checklist=[
                _checklist(code=XSS_LABEL, severity=FindingSeverity.WARNING.value),
                _checklist(code="execution_disabled_in_this_phase"),
            ],
        )
    )
    error = render_compliance_evidence_binder_error()

    assert XSS_LABEL not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    for heading in SECTION_HEADINGS:
        assert heading in html
    assert "EXAMPLE_API_KEY" in html
    assert "EXAMPLE_LIVE_ENABLED" in html
    assert "execution_disabled_in_this_phase" in html
    assert "docs/SECURITY.md" in html
    assert "smoke-dry-run" in html
    assert "deploy-config" in html
    assert "place_consent_callback" in html
    assert "go live permitted" in html.lower()
    assert "execution allowed" in html.lower()
    assert 'id="operator-compliance-evidence-binder-error"' in error
    assert "sk-testsecret" not in error
    for marker in ACTION_MARKERS + FORM_MARKERS:
        assert marker not in html.lower()
        assert marker not in error.lower()


def test_renderer_is_deterministic_aside_from_timestamps() -> None:
    first = render_compliance_evidence_binder(_empty_binder())
    second = render_compliance_evidence_binder(
        _empty_binder(generated_at=datetime(2026, 9, 1, 8, 30, tzinfo=UTC))
    )

    assert _strip_timestamps(first) == _strip_timestamps(second)


def test_operator_compliance_evidence_binder_open_in_development(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    response = api_client.get(OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Compliance evidence binder" in body
    assert "Compliance binder" in body
    for heading in SECTION_HEADINGS:
        assert heading in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "binder_is_not_go_live=true" in body
    assert "not permission or machinery for going live" in body
    assert PHI_SNIPPET not in body
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    for marker in FORM_MARKERS:
        assert marker not in body.lower()


def test_operator_compliance_evidence_binder_requires_internal_access(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="production", internal_api_key=""))
    denied = api_client.get(OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH)
    assert denied.status_code == 403

    _patch_settings(
        monkeypatch,
        Settings(environment="production", internal_api_key="internal-secret"),
    )
    missing = api_client.get(OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH)
    invalid = api_client.get(
        OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
        headers={"X-Internal-Api-Key": "wrong-secret"},
    )
    post = api_client.post(
        OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    put = api_client.put(
        OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    delete = api_client.delete(
        OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    patch = api_client.patch(
        OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert post.status_code == 405
    assert put.status_code == 405
    assert delete.status_code == 405
    assert patch.status_code == 405


def test_operator_compliance_evidence_binder_populated_sections_and_no_side_effects(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="production",
        internal_api_key="internal-secret",
        voice_api_key=SECRET_VALUE,
    )
    _patch_settings(monkeypatch, settings)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    _seed_plans_and_packets(db_session)
    created = SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="ui-binder",
        reviewer_notes=PHI_SNIPPET,
    )
    SettingsChangeRequestService().record_decision(
        db_session,
        settings,
        request_id=created.request_id,
        decision="approved",
        reviewer="owner",
    )
    SettingsChangeRequestService().create(
        db_session,
        settings,
        request_type=SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED.value,
        requested_setting_names=["OUTBOUND_ENABLED"],
        idempotency_key="ui-binder-pending",
    )
    before_activities = int(db_session.scalar(select(func.count()).select_from(Activity)) or 0)
    before_meetings = int(db_session.scalar(select(func.count()).select_from(Meeting)) or 0)
    before_enrollments = int(
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0
    )
    before_messages = int(db_session.scalar(select(func.count()).select_from(OutreachMessage)) or 0)
    before_requests = int(
        db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest)) or 0
    )
    before_halt = read_operator_halt(db_session)

    first = api_client.get(
        OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )
    second = api_client.get(
        OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
        headers={"X-Internal-Api-Key": "internal-secret"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    body = first.text
    for section_id in SECTION_IDS:
        assert f'id="{section_id}"' in body
    for heading in SECTION_HEADINGS:
        assert heading in body
    assert "OUTBOUND_ENABLED" in body
    assert "execution_disabled_in_this_phase" in body
    assert NextActionCode.BINDER_IS_NOT_GO_LIVE.value in body
    assert "go_live_permitted=false" in body
    assert "execution_allowed=false" in body
    assert "binder_is_not_go_live=true" in body
    assert "not permission or machinery for going live" in body
    assert "smoke-dry-run" in body
    assert "deploy-config" in body
    assert "place_consent_callback" in body
    _assert_no_leakage(body, SECRET_VALUE)
    assert PHI_SNIPPET not in body
    assert PROSPECT_EMAIL not in body
    assert "reviewer_notes" not in body
    for marker in FORM_MARKERS:
        assert marker not in body.lower()
    assert _strip_timestamps(first.text) == _strip_timestamps(second.text)
    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert (
        db_session.scalar(select(func.count()).select_from(LiveSettingsChangeRequest))
        == before_requests
    )
    assert read_operator_halt(db_session) is before_halt
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert settings.outbound_enabled is False
    assert settings.voice_live_enabled is False


def test_operator_compliance_evidence_binder_failure_state_redacts_errors(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, Settings(environment="development", internal_api_key=""))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("patient diagnosis sk-testsecret12345")

    monkeypatch.setattr(
        "vyro_growth.api.operator_compliance_evidence_binder.build_compliance_evidence_binder_response",
        _boom,
    )
    response = api_client.get(OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH)

    assert response.status_code == 500
    assert "patient diagnosis" not in response.text.lower()
    assert "sk-testsecret12345" not in response.text
    assert "Unable to load the compliance evidence binder" in response.text
    for marker in FORM_MARKERS:
        assert marker not in response.text.lower()
