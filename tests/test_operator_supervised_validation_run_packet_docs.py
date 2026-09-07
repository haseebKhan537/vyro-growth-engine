from __future__ import annotations

from pathlib import Path


def test_phase_74_docs_describe_read_only_operator_ui() -> None:
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    security = Path("docs/SECURITY.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    deployment = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")
    health = Path("docs/OPERATOR_HEALTH.md").read_text(encoding="utf-8")

    heading = "## Phase 74 — Operator supervised validation run packet UI shell"
    heading = (
        "## Phase 74 — Operator supervised validation run packet UI shell"
    )
    assert heading in roadmap
    assert "GET /internal/operator-supervised-validation-run-packet" in roadmap
    assert "SupervisedValidationRunPacketService" in roadmap.split("## Phase 74")[1].split(
        "## "
    )[0]
    assert "owner_approved=false" in roadmap.split("## Phase 74")[1].split("## ")[0]
    assert "supervised_validation_run_permitted=false" in roadmap.split("## Phase 74")[1].split(
        "## "
    )[0]
    assert "OUTBOUND_ENABLED=false" in roadmap.split("## Phase 74")[1].split("## ")[0]

    assert "### Phase 74: operator supervised validation run packet UI" in architecture
    assert "GET /internal/operator-supervised-validation-run-packet" in architecture
    assert "Cache-Control: no-store" in architecture.split("### Phase 74")[1].split("### ")[0]

    assert "GET /internal/operator-supervised-validation-run-packet" in security
    assert "operator supervised validation run packet" in security.lower() or (
        "phase 74" in security.lower()
    )

    assert "## Phase 74 — Operator supervised validation run packet UI (read-only)" in readme
    assert "GET /internal/operator-supervised-validation-run-packet" in readme
    assert "OUTBOUND_ENABLED=false" in readme

    assert "operator-supervised-validation-run-packet" in deployment
    assert "operator-supervised-validation-run-packet" in health
