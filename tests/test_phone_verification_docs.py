from __future__ import annotations

from pathlib import Path


def test_phase_70_docs_describe_human_queue_without_ai_calling() -> None:
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    security = Path("docs/SECURITY.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    deployment = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")

    heading = (
        "## Phase 70 — Human phone-verification task queue for NO_CONTACT_FOUND (current)"
    )
    assert heading in roadmap
    assert "human-in-the-loop" in roadmap.lower()
    assert "Do not route through `VoiceProvider`" in roadmap
    assert "no ai voice cold calling" in roadmap.lower()
    before_phase_70 = roadmap.split("## Phase 70")[0]
    assert "- human phone-verification queue for `NO_CONTACT_FOUND`" not in before_phase_70

    assert "### Phase 70: human phone-verification queue" in architecture
    assert "GET /internal/phone-verification/tasks" in architecture
    assert "POST /internal/phone-verification/tasks/{task_id}/outcome" in architecture
    assert "contact_discovery_call" in architecture

    assert "GET /internal/phone-verification/tasks" in security
    assert "POST /internal/phone-verification/tasks/{task_id}/outcome" in security
    assert "## Phone verification integrity" in security
    assert "Do not route through `VoiceProvider`" in security

    assert "## Phase 70 — Human phone-verification task queue (no AI cold calling)" in readme
    assert "queue-phone-verification" in readme
    assert "list-phone-verification" in readme
    assert "record-phone-verification" in readme
    assert "queue_phone_verification_tasks" in readme
    assert "source_provider" in readme and "phone_verification" in readme

    assert "20. `020_contact_discovery_calls`" in deployment
    assert "OUTBOUND_ENABLED=false" in readme
