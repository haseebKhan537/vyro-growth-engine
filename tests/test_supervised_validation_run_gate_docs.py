from __future__ import annotations

from pathlib import Path


def test_phase_77_docs_describe_owner_approval_required_run_gate() -> None:
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    security = Path("docs/SECURITY.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    deployment = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")
    health = Path("docs/OPERATOR_HEALTH.md").read_text(encoding="utf-8")

    heading = "## Phase 77 — Supervised 200-practice validation run gate"
    assert heading in roadmap
    section = roadmap.split("## Phase 77")[1].split("## ")[0]
    assert "supervised-validation-run" in roadmap
    assert "GET /internal/supervised-validation-run" in roadmap
    assert "LiveProviderSetupChecklistService" in section
    assert "SupervisedValidationRunPacketService" in section
    assert "ContactValidationService" in section
    assert "owner_approved=false" in section
    assert "supervised_validation_run_permitted=false" in section
    assert "OUTBOUND_ENABLED=false" in section
    assert "later owner approval" in section.lower() or "separate owner approval" in section.lower()

    assert "### Phase 77: supervised 200-practice validation run gate" in architecture
    assert "GET /internal/supervised-validation-run" in architecture
    assert "Cache-Control: no-store" in architecture.split("### Phase 77")[1].split("### ")[0]

    assert "GET /internal/supervised-validation-run" in security
    assert "supervised validation run gate" in security.lower() or "phase 77" in security.lower()

    assert "## Phase 77 — Supervised 200-practice validation run gate" in readme
    assert "supervised-validation-run" in readme
    assert "GET /internal/supervised-validation-run" in readme
    assert "OUTBOUND_ENABLED=false" in readme

    assert "supervised-validation-run" in deployment
    assert "supervised-validation-run" in health
