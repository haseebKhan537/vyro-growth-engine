from __future__ import annotations

from pathlib import Path


def test_phase_73_docs_describe_read_only_owner_run_packet() -> None:
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    security = Path("docs/SECURITY.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    deployment = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")
    health = Path("docs/OPERATOR_HEALTH.md").read_text(encoding="utf-8")

    heading = "## Phase 73 — Supervised validation owner approval/run packet"
    assert heading in roadmap
    assert "supervised-validation-run-packet" in roadmap
    assert "GET /internal/supervised-validation-run-packet" in roadmap
    assert "ContactValidationService" in roadmap.split("## Phase 73")[1].split("## ")[0]
    assert "owner_approved=false" in roadmap.split("## Phase 73")[1].split("## ")[0]
    assert "supervised_validation_run_permitted=false" in roadmap.split("## Phase 73")[1].split(
        "## "
    )[0]
    assert "OUTBOUND_ENABLED=false" in roadmap.split("## Phase 73")[1].split("## ")[0]

    assert "### Phase 73: supervised validation owner approval/run packet" in architecture
    assert "GET /internal/supervised-validation-run-packet" in architecture
    assert "Cache-Control: no-store" in architecture.split("### Phase 73")[1].split("### ")[0]

    assert "GET /internal/supervised-validation-run-packet" in security
    assert "supervised validation owner" in security.lower() or "phase 73" in security.lower()

    assert "## Phase 73 — Supervised validation owner approval/run packet" in readme
    assert "supervised-validation-run-packet" in readme
    assert "GET /internal/supervised-validation-run-packet" in readme
    assert "OUTBOUND_ENABLED=false" in readme

    assert "supervised-validation-run-packet" in deployment
    assert "supervised-validation-run-packet" in health
