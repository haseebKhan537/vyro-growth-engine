from __future__ import annotations

from pathlib import Path


def test_phase_75_docs_describe_read_only_final_safety_audit() -> None:
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    security = Path("docs/SECURITY.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    deployment = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")
    health = Path("docs/OPERATOR_HEALTH.md").read_text(encoding="utf-8")

    heading = "## Phase 75 — Final safety and repository audit packet (current)"
    assert heading in roadmap
    assert "final-safety-audit" in roadmap
    assert "GET /internal/final-safety-audit" in roadmap
    section = roadmap.split("## Phase 75")[1].split("## ")[0]
    assert "LaunchReadinessService" in section
    assert "ContactValidationService" in section
    assert "owner_approved=false" in section
    assert "supervised_validation_run_permitted=false" in section
    assert "OUTBOUND_ENABLED=false" in section

    assert "### Phase 75: final safety and repository audit packet" in architecture
    assert "GET /internal/final-safety-audit" in architecture
    assert "Cache-Control: no-store" in architecture.split("### Phase 75")[1].split("### ")[0]

    assert "GET /internal/final-safety-audit" in security
    assert "final safety" in security.lower() or "phase 75" in security.lower()

    assert "## Phase 75 — Final safety and repository audit packet" in readme
    assert "final-safety-audit" in readme
    assert "GET /internal/final-safety-audit" in readme
    assert "OUTBOUND_ENABLED=false" in readme

    assert "final-safety-audit" in deployment
    assert "final-safety-audit" in health
