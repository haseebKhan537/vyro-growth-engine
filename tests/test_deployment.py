from __future__ import annotations

from pathlib import Path

from vyro_growth.workers.catalog import (
    DEPLOYABLE_JOBS,
    UNDEPLOYED_OUTBOUND_JOBS,
    deployable_job_names,
    undeployed_outbound_job_names,
)

SAFE_FLAGS = (
    "OUTBOUND_ENABLED=false",
    "OPENAI_PERSONALIZATION_ENABLED=false",
    "SMARTLEAD_LIVE_ENABLED=false",
    "OPENAI_REPLY_CLASSIFICATION_ENABLED=false",
    "GOOGLE_CALENDAR_LIVE_ENABLED=false",
    "VOICE_LIVE_ENABLED=false",
)


def test_env_example_keeps_deployment_safe_defaults() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    for flag in SAFE_FLAGS:
        assert flag in env_example
    assert "INTERNAL_API_KEY=" in env_example
    assert "sk-" not in env_example
    assert "AIza" not in env_example


def test_dockerfile_is_production_safe() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8")

    assert "USER appuser" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/health" in dockerfile
    assert "OUTBOUND_ENABLED=false" in dockerfile
    assert "GOOGLE_CALENDAR_LIVE_ENABLED=false" in dockerfile
    assert "VOICE_LIVE_ENABLED=false" in dockerfile
    assert "SMARTLEAD_LIVE_ENABLED=false" in dockerfile
    assert ".env" in dockerignore
    assert "COPY .env" not in dockerfile


def test_compose_keeps_outbound_and_live_providers_off() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert 'OUTBOUND_ENABLED: "false"' in compose
    assert 'OPENAI_PERSONALIZATION_ENABLED: "false"' in compose
    assert 'SMARTLEAD_LIVE_ENABLED: "false"' in compose
    assert 'GOOGLE_CALENDAR_LIVE_ENABLED: "false"' in compose
    assert 'VOICE_LIVE_ENABLED: "false"' in compose
    assert '"vyro-growth", "worker", "--check"' in compose
    assert '"alembic", "upgrade", "head"' in compose
    assert "/health" in compose
    assert "SMARTLEAD_API_KEY:" not in compose
    assert "OPENAI_API_KEY:" not in compose
    assert "GOOGLE_CALENDAR_API_KEY:" not in compose
    assert "VOICE_API_KEY:" not in compose


def test_ci_validates_compose_without_live_calls() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "docker compose config --quiet" in workflow
    assert "vyro-growth smoke-dry-run --local-only --json" in workflow
    assert "vyro-growth check-smoke-output --file" in workflow
    assert 'OUTBOUND_ENABLED: "false"' in workflow
    assert "unset DATABASE_URL" in workflow
    assert "npx" not in workflow
    assert "openai.com" not in workflow.lower()
    assert "smartlead.com" not in workflow.lower()


def test_deployment_runbook_covers_operator_topics() -> None:
    runbook = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")

    assert "INTERNAL_API_KEY" in runbook
    assert "alembic upgrade head" in runbook
    assert "/health" in runbook
    assert "/ready" in runbook
    assert "InlineJobQueue" in runbook
    assert "pg_dump" in runbook
    assert "alembic downgrade" in runbook
    assert "OUTBOUND_ENABLED" in runbook
    assert "Do not ingest or expose PHI" in runbook
    assert "check-smoke-output" in runbook
    assert "smoke-dry-run --local-only --json" in runbook
    assert "launch-readiness" in runbook
    assert "settings-change-requests" in runbook
    assert "settings-execution-preflight" in runbook
    assert "operator-settings-execution-preflight" in runbook
    assert "owner-handoff-packet" in runbook
    assert "operator-owner-handoff-packet" in runbook
    assert "018_live_settings_change_requests" in runbook


def test_readiness_and_catalog_do_not_call_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/readiness.py"),
        Path("src/vyro_growth/workers/catalog.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "openai" not in source
    assert "smartlead" not in source
    assert "google.calendar" not in source
    assert "apollo" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source


def test_worker_catalog_excludes_outbound_send_jobs() -> None:
    names = deployable_job_names()

    assert "discover_nppes_practices" in names
    assert "generate_growth_recommendations" in names
    assert "generate_channel_plans" in names
    assert "generate_content_briefs" in names
    assert "generate_execution_plans" in names
    assert "generate_approval_packets" in names
    assert "send_email" not in names
    assert "schedule_meeting" not in names
    assert "place_consent_callback" not in names
    assert undeployed_outbound_job_names() == UNDEPLOYED_OUTBOUND_JOBS
    assert set(UNDEPLOYED_OUTBOUND_JOBS).isdisjoint(names)
    assert len(DEPLOYABLE_JOBS) == 14
