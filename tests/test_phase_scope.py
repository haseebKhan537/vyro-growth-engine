from __future__ import annotations

from pathlib import Path

from vyro_growth.config import Settings
from vyro_growth.providers.calendar_booking import (
    StubBookingCalendarProvider,
    build_booking_calendar_provider,
)
from vyro_growth.providers.personalization import (
    StubPersonalizationProvider,
    build_personalization_provider,
)
from vyro_growth.providers.reply_classification import (
    StubReplyClassifier,
    build_reply_classifier,
)
from vyro_growth.providers.smartlead import StubSmartleadProvider, build_smartlead_provider
from vyro_growth.providers.voice_qualification import (
    StubVoiceQualificationProvider,
    build_voice_qualification_provider,
)


def test_outbound_remains_disabled_by_default() -> None:
    settings = Settings()
    assert settings.outbound_enabled is False
    assert settings.internal_api_key == ""
    assert settings.openai_personalization_enabled is False
    assert settings.smartlead_live_enabled is False
    assert settings.smartlead_api_key == ""
    assert settings.openai_reply_classification_enabled is False
    assert settings.google_calendar_live_enabled is False
    assert settings.google_calendar_api_key == ""
    assert settings.voice_live_enabled is False
    assert settings.voice_api_key == ""


def test_env_example_keeps_outbound_disabled() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example
    assert "OUTBOUND_HALTED=false" in env_example
    assert "INTERNAL_API_KEY=" in env_example
    assert "WEBSITE_USER_AGENT=VyroGrowthEngine/0.1" in env_example
    assert "OPENAI_PERSONALIZATION_ENABLED=false" in env_example
    assert "SMARTLEAD_LIVE_ENABLED=false" in env_example
    assert "OPENAI_REPLY_CLASSIFICATION_ENABLED=false" in env_example
    assert "GOOGLE_CALENDAR_LIVE_ENABLED=false" in env_example
    assert "VOICE_LIVE_ENABLED=false" in env_example
    assert "sk-" not in env_example
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in dockerfile
    assert 'OUTBOUND_ENABLED: "false"' in compose
    assert "GOOGLE_CALENDAR_LIVE_ENABLED=false" in dockerfile
    assert "VOICE_LIVE_ENABLED=false" in dockerfile


def test_current_phases_do_not_add_later_phase_integrations() -> None:
    src_root = Path("src/vyro_growth")
    openai_boundary = {
        "config.py",
        "observability.py",
        "personalization.py",
        "personalization_openai.py",
        "personalization_handler.py",
        "reply_classification.py",
        "reply_classification_openai.py",
        "reply_classification_handler.py",
        "dashboard.py",
        "growth_optimizer.py",
        "optimizer.py",
        "monitoring.py",
        "domain.py",
        "launch_readiness.py",
        "settings_change_requests.py",
        "settings_execution_preflight.py",
        "provider_setup_checklist.py",
    }
    calendar_boundary = {
        "config.py",
        "observability.py",
        "calendar_booking.py",
        "google_calendar.py",
        "guarded.py",
        "booking_plan.py",
        "booking_plan_handler.py",
        "models.py",
        "cli.py",
        "domain.py",
        "__init__.py",
        "dashboard.py",
        "growth_optimizer.py",
        "optimizer.py",
        "monitoring.py",
        "launch_readiness.py",
        "settings_change_requests.py",
        "settings_execution_preflight.py",
        "provider_setup_checklist.py",
    }
    smartlead_boundary = {
        "config.py",
        "observability.py",
        "smartlead.py",
        "smartlead_live.py",
        "guarded.py",
        "outreach_enrollment.py",
        "outreach_enrollment_handler.py",
        "models.py",
        "cli.py",
        "domain.py",
        "__init__.py",
        "dashboard.py",
        "growth_optimizer.py",
        "optimizer.py",
        "monitoring.py",
        "launch_readiness.py",
        "settings_change_requests.py",
        "settings_execution_preflight.py",
        "provider_setup_checklist.py",
    }
    forbidden = (
        "apollo",
        "firecrawl",
        "google.calendar",
        "twilio",
        "vapi",
        "retell",
    )
    for path in src_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in source, f"{token} found in {path}"
        if "openai" in source:
            assert path.name in openai_boundary, f"openai token leaked into {path}"
        if "smartlead" in source:
            assert path.name in smartlead_boundary, f"smartlead token leaked into {path}"
        if "google_calendar" in source or "google calendar" in source:
            assert path.name in calendar_boundary, f"google calendar token leaked into {path}"


def test_default_personalization_provider_is_stub() -> None:
    settings = Settings(openai_personalization_enabled=False)
    provider = build_personalization_provider(settings)
    assert isinstance(provider, StubPersonalizationProvider)


def test_default_smartlead_provider_is_stub() -> None:
    settings = Settings(smartlead_live_enabled=True, smartlead_api_key="placeholder")
    provider = build_smartlead_provider(settings)
    assert isinstance(provider, StubSmartleadProvider)


def test_smartlead_stub_and_planner_do_not_use_httpx() -> None:
    paths = [
        Path("src/vyro_growth/providers/smartlead.py"),
        Path("src/vyro_growth/services/outreach_enrollment.py"),
        Path("src/vyro_growth/workers/outreach_enrollment_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example
    assert "SMARTLEAD_LIVE_ENABLED=false" in env_example


def test_default_booking_calendar_provider_is_stub() -> None:
    settings = Settings(google_calendar_live_enabled=True, google_calendar_api_key="placeholder")
    provider = build_booking_calendar_provider(settings)
    assert isinstance(provider, StubBookingCalendarProvider)


def test_booking_stub_and_planner_do_not_use_httpx() -> None:
    paths = [
        Path("src/vyro_growth/providers/calendar_booking.py"),
        Path("src/vyro_growth/services/booking_plan.py"),
        Path("src/vyro_growth/workers/booking_plan_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example
    assert "GOOGLE_CALENDAR_LIVE_ENABLED=false" in env_example


def test_default_reply_classifier_is_stub() -> None:
    settings = Settings(openai_reply_classification_enabled=False)
    provider = build_reply_classifier(settings)
    assert isinstance(provider, StubReplyClassifier)


def test_default_voice_qualification_provider_is_stub() -> None:
    settings = Settings(voice_live_enabled=True, voice_api_key="placeholder")
    provider = build_voice_qualification_provider(settings)
    assert isinstance(provider, StubVoiceQualificationProvider)


def test_voice_stub_and_planner_do_not_use_httpx() -> None:
    paths = [
        Path("src/vyro_growth/providers/voice_qualification.py"),
        Path("src/vyro_growth/services/voice_qualification.py"),
        Path("src/vyro_growth/workers/voice_qualification_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example
    assert "VOICE_LIVE_ENABLED=false" in env_example


def test_review_queue_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/review_queue.py"),
        Path("src/vyro_growth/api/review_queue.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_channel_planning_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/channel_planning.py"),
        Path("src/vyro_growth/api/channel_plans.py"),
        Path("src/vyro_growth/workers/channel_planning_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    assert "apollo" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_content_briefs_do_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/content_brief.py"),
        Path("src/vyro_growth/api/content_briefs.py"),
        Path("src/vyro_growth/workers/content_brief_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "openai" not in source
    assert "searchconsole" not in source
    assert "googleads.googleapis" not in source
    assert "apollo" not in source
    assert "smartlead" not in source
    assert "google.calendar" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_execution_planning_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/execution_planning.py"),
        Path("src/vyro_growth/api/execution_plans.py"),
        Path("src/vyro_growth/workers/execution_planning_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "openai" not in source
    assert "smartlead" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_approval_packets_do_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/approval_packets.py"),
        Path("src/vyro_growth/api/approval_packets.py"),
        Path("src/vyro_growth/workers/approval_packet_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "openai" not in source
    assert "smartlead" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_smoke_dry_run_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/smoke_dry_run.py"),
        Path("src/vyro_growth/smoke_ci_gate.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "openai" not in source
    assert "smartlead" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_launch_readiness_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/launch_readiness.py"),
        Path("src/vyro_growth/api/launch_readiness.py"),
        Path("tests/test_launch_readiness_service.py"),
        Path("tests/test_launch_readiness_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_settings_change_requests_do_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/settings_change_requests.py"),
        Path("src/vyro_growth/api/settings_change_requests.py"),
        Path("src/vyro_growth/api/operator_settings_change_requests.py"),
        Path("tests/test_settings_change_request_service.py"),
        Path("tests/test_settings_change_request_api.py"),
        Path("tests/test_settings_change_request_migration.py"),
        Path("tests/test_operator_settings_change_requests_api.py"),
        Path("tests/test_operator_settings_change_decision_api.py"),
        Path("tests/test_operator_settings_execution_preflight_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_settings_execution_preflight_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/settings_execution_preflight.py"),
        Path("src/vyro_growth/api/settings_execution_preflight.py"),
        Path("src/vyro_growth/api/operator_settings_execution_preflight.py"),
        Path("tests/test_settings_execution_preflight_service.py"),
        Path("tests/test_settings_execution_preflight_api.py"),
        Path("tests/test_operator_settings_execution_preflight_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_owner_handoff_packet_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/owner_handoff.py"),
        Path("src/vyro_growth/api/owner_handoff.py"),
        Path("src/vyro_growth/api/operator_owner_handoff.py"),
        Path("tests/test_owner_handoff_service.py"),
        Path("tests/test_owner_handoff_api.py"),
        Path("tests/test_operator_owner_handoff_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_compliance_evidence_binder_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/compliance_evidence_binder.py"),
        Path("src/vyro_growth/api/compliance_evidence_binder.py"),
        Path("src/vyro_growth/api/operator_compliance_evidence_binder.py"),
        Path("tests/test_compliance_evidence_binder_service.py"),
        Path("tests/test_compliance_evidence_binder_api.py"),
        Path("tests/test_operator_compliance_evidence_binder_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_release_candidate_runbook_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/release_candidate_runbook.py"),
        Path("src/vyro_growth/api/release_candidate_runbook.py"),
        Path("src/vyro_growth/api/operator_release_candidate_runbook.py"),
        Path("tests/test_release_candidate_runbook_service.py"),
        Path("tests/test_release_candidate_runbook_api.py"),
        Path("tests/test_operator_release_candidate_runbook_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_release_artifact_manifest_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/release_artifact_manifest.py"),
        Path("src/vyro_growth/api/release_artifact_manifest.py"),
        Path("src/vyro_growth/api/operator_release_artifact_manifest.py"),
        Path("tests/test_release_artifact_manifest_service.py"),
        Path("tests/test_release_artifact_manifest_api.py"),
        Path("tests/test_operator_release_artifact_manifest_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "api.github.com" not in source
    assert "docker build" not in source
    assert "docker push" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_staged_rollout_plan_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/staged_rollout_plan.py"),
        Path("src/vyro_growth/api/staged_rollout_plan.py"),
        Path("src/vyro_growth/api/operator_staged_rollout_plan.py"),
        Path("tests/test_staged_rollout_plan_service.py"),
        Path("tests/test_staged_rollout_plan_api.py"),
        Path("tests/test_operator_staged_rollout_plan_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "api.github.com" not in source
    assert "docker build" not in source
    assert "docker push" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_provider_setup_checklist_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/provider_setup_checklist.py"),
        Path("src/vyro_growth/api/provider_setup_checklist.py"),
        Path("src/vyro_growth/api/operator_provider_setup_checklist.py"),
        Path("tests/test_provider_setup_checklist_service.py"),
        Path("tests/test_provider_setup_checklist_api.py"),
        Path("tests/test_operator_provider_setup_checklist_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "api.github.com" not in source
    assert "docker build" not in source
    assert "docker push" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_go_live_rehearsal_checklist_does_not_execute_or_call_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/go_live_rehearsal_checklist.py"),
        Path("src/vyro_growth/api/go_live_rehearsal_checklist.py"),
        Path("tests/test_go_live_rehearsal_checklist_service.py"),
        Path("tests/test_go_live_rehearsal_checklist_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "subprocess" not in source
    assert "popen" not in source
    assert "os.system" not in source
    assert "api.github.com" not in source
    assert "docker build" not in source
    assert "docker push" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_owner_launch_dossier_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/owner_launch_dossier.py"),
        Path("src/vyro_growth/api/owner_launch_dossier.py"),
        Path("src/vyro_growth/api/operator_owner_launch_dossier.py"),
        Path("tests/test_owner_launch_dossier_service.py"),
        Path("tests/test_owner_launch_dossier_api.py"),
        Path("tests/test_operator_owner_launch_dossier_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "api.github.com" not in source
    assert "docker build" not in source
    assert "docker push" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_launch_blockers_plan_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/launch_blockers_plan.py"),
        Path("src/vyro_growth/api/launch_blockers_plan.py"),
        Path("src/vyro_growth/api/operator_launch_blockers_plan.py"),
        Path("tests/test_launch_blockers_plan_service.py"),
        Path("tests/test_launch_blockers_plan_api.py"),
        Path("tests/test_operator_launch_blockers_plan_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "api.github.com" not in source
    assert "docker build" not in source
    assert "docker push" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_go_live_readiness_index_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/go_live_readiness_index.py"),
        Path("src/vyro_growth/api/go_live_readiness_index.py"),
        Path("src/vyro_growth/api/operator_go_live_readiness_index.py"),
        Path("tests/test_go_live_readiness_index_service.py"),
        Path("tests/test_go_live_readiness_index_api.py"),
        Path("tests/test_operator_go_live_readiness_index_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "api.github.com" not in source
    assert "docker build" not in source
    assert "docker push" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_operator_audit_timeline_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/operator_audit_timeline.py"),
        Path("src/vyro_growth/api/operator_audit_timeline.py"),
        Path("tests/test_operator_audit_timeline_service.py"),
        Path("tests/test_operator_audit_timeline_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "openai" not in source
    assert "smartlead" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_action_readiness_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/action_readiness.py"),
        Path("src/vyro_growth/api/action_readiness.py"),
        Path("src/vyro_growth/api/operator_action_readiness.py"),
        Path("tests/test_action_readiness_service.py"),
        Path("tests/test_action_readiness_api.py"),
        Path("tests/test_operator_action_readiness_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "openai" not in source
    assert "smartlead" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_command_center_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/command_center.py"),
        Path("src/vyro_growth/api/command_center.py"),
        Path("src/vyro_growth/api/operator_dashboard.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "openai" not in source
    assert "smartlead" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_operator_dashboard_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/api/operator_dashboard.py"),
        Path("src/vyro_growth/api/operator_ui.py"),
        Path("src/vyro_growth/api/operator_review_queue.py"),
        Path("src/vyro_growth/api/operator_approval_packets.py"),
        Path("src/vyro_growth/api/operator_action_readiness.py"),
        Path("src/vyro_growth/api/operator_settings_change_requests.py"),
        Path("src/vyro_growth/api/operator_settings_execution_preflight.py"),
        Path("src/vyro_growth/api/operator_owner_handoff.py"),
        Path("src/vyro_growth/api/operator_audit_timeline.py"),
        Path("src/vyro_growth/api/operator_compliance_evidence_binder.py"),
        Path("src/vyro_growth/api/operator_go_live_readiness_index.py"),
        Path("src/vyro_growth/api/operator_launch_blockers_plan.py"),
        Path("src/vyro_growth/api/operator_staged_rollout_plan.py"),
        Path("src/vyro_growth/api/operator_owner_launch_dossier.py"),
        Path("src/vyro_growth/api/operator_provider_setup_checklist.py"),
        Path("tests/test_operator_dashboard_api.py"),
        Path("tests/test_operator_review_queue_api.py"),
        Path("tests/test_operator_review_decision_api.py"),
        Path("tests/test_operator_approval_packets_api.py"),
        Path("tests/test_operator_approval_packet_decision_api.py"),
        Path("tests/test_operator_action_readiness_api.py"),
        Path("tests/test_operator_settings_change_requests_api.py"),
        Path("tests/test_operator_settings_change_decision_api.py"),
        Path("tests/test_operator_settings_execution_preflight_api.py"),
        Path("tests/test_operator_owner_handoff_api.py"),
        Path("tests/test_operator_audit_timeline_api.py"),
        Path("tests/test_operator_compliance_evidence_binder_api.py"),
        Path("tests/test_operator_go_live_readiness_index_api.py"),
        Path("tests/test_operator_launch_blockers_plan_api.py"),
        Path("tests/test_operator_staged_rollout_plan_api.py"),
        Path("tests/test_operator_owner_launch_dossier_api.py"),
        Path("tests/test_operator_provider_setup_checklist_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "openai" not in source
    assert "smartlead" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_operator_review_and_approval_ui_do_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/api/operator_review_queue.py"),
        Path("src/vyro_growth/api/operator_approval_packets.py"),
        Path("src/vyro_growth/api/operator_ui.py"),
        Path("src/vyro_growth/api/operator_action_readiness.py"),
        Path("src/vyro_growth/api/operator_settings_change_requests.py"),
        Path("src/vyro_growth/api/operator_settings_execution_preflight.py"),
        Path("src/vyro_growth/api/operator_owner_handoff.py"),
        Path("src/vyro_growth/api/operator_audit_timeline.py"),
        Path("src/vyro_growth/api/operator_compliance_evidence_binder.py"),
        Path("src/vyro_growth/api/operator_release_candidate_runbook.py"),
        Path("src/vyro_growth/api/operator_release_artifact_manifest.py"),
        Path("src/vyro_growth/api/operator_go_live_readiness_index.py"),
        Path("src/vyro_growth/api/operator_launch_blockers_plan.py"),
        Path("src/vyro_growth/api/operator_staged_rollout_plan.py"),
        Path("src/vyro_growth/api/operator_owner_launch_dossier.py"),
        Path("src/vyro_growth/api/operator_provider_setup_checklist.py"),
        Path("tests/test_operator_review_decision_api.py"),
        Path("tests/test_operator_approval_packet_decision_api.py"),
        Path("tests/test_operator_action_readiness_api.py"),
        Path("tests/test_operator_settings_change_decision_api.py"),
        Path("tests/test_operator_settings_execution_preflight_api.py"),
        Path("tests/test_operator_owner_handoff_api.py"),
        Path("tests/test_operator_audit_timeline_api.py"),
        Path("tests/test_operator_compliance_evidence_binder_api.py"),
        Path("tests/test_operator_release_artifact_manifest_api.py"),
        Path("tests/test_operator_go_live_readiness_index_api.py"),
        Path("tests/test_operator_launch_blockers_plan_api.py"),
        Path("tests/test_operator_staged_rollout_plan_api.py"),
        Path("tests/test_operator_owner_launch_dossier_api.py"),
        Path("tests/test_operator_provider_setup_checklist_api.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "openai" not in source
    assert "smartlead" not in source
    assert "google.calendar" not in source
    assert "google ads api" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_growth_optimizer_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/growth_optimizer.py"),
        Path("src/vyro_growth/api/optimizer.py"),
        Path("src/vyro_growth/workers/growth_optimizer_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_monitoring_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/monitoring.py"),
        Path("src/vyro_growth/api/monitoring.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_contact_enrichment_does_not_call_paid_or_linkedin_providers() -> None:
    paths = [
        Path("src/vyro_growth/providers/decision_makers.py"),
        Path("src/vyro_growth/services/contact_enrichment.py"),
        Path("src/vyro_growth/workers/contact_enrichment_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "linkedin" not in source
    assert "apollo" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example
