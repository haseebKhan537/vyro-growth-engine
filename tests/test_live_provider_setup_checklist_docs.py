from __future__ import annotations

from pathlib import Path


def test_phase_76_docs_describe_read_only_live_provider_setup_checklist() -> None:
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    security = Path("docs/SECURITY.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    deployment = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")
    health = Path("docs/OPERATOR_HEALTH.md").read_text(encoding="utf-8")

    heading = "## Phase 76 — Owner live-provider setup checklist"
    assert heading in roadmap
    section = roadmap.split("## Phase 76")[1].split("## ")[0]
    assert "live-provider-setup-checklist" in roadmap
    assert "GET /internal/live-provider-setup-checklist" in roadmap
    assert "ProviderSetupChecklistService" in section
    assert "LaunchReadinessService" in section
    assert "SupervisedValidationRunPacketService" in section
    assert "owner_approved=false" in section
    assert "supervised_validation_run_permitted=false" in section
    assert "OUTBOUND_ENABLED=false" in section

    assert "### Phase 76: owner live-provider setup checklist" in architecture
    assert "GET /internal/live-provider-setup-checklist" in architecture
    assert "Cache-Control: no-store" in architecture.split("### Phase 76")[1].split("### ")[0]

    assert "GET /internal/live-provider-setup-checklist" in security
    assert "live-provider setup" in security.lower() or "phase 76" in security.lower()

    assert "## Phase 76 — Owner live-provider setup checklist" in readme
    assert "live-provider-setup-checklist" in readme
    assert "GET /internal/live-provider-setup-checklist" in readme
    assert "OUTBOUND_ENABLED=false" in readme

    assert "live-provider-setup-checklist" in deployment
    assert "live-provider-setup-checklist" in health
