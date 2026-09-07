from __future__ import annotations

from pathlib import Path


def test_phase_71_docs_describe_dry_run_measurement_without_live_send() -> None:
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    security = Path("docs/SECURITY.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    heading = (
        "## Phase 71 — Contact-enrichment validation harness and 200-practice "
        "measurement plan (current)"
    )
    assert heading in roadmap
    assert "contact-validation-plan" in roadmap
    assert "contact-validation-report" in roadmap
    assert "NO_CONTACT_FOUND" in roadmap
    assert "owner review" in roadmap.lower() or "go/no-go" in roadmap.lower()
    assert "OUTBOUND_ENABLED=false" in roadmap.split("## Phase 71")[1].split("## ")[0]

    assert "### Phase 71: contact-enrichment validation harness" in architecture
    assert "GET /internal/contact-validation/plan" in architecture
    assert "GET /internal/contact-validation/report" in architecture
    assert "200" in architecture

    assert "GET /internal/contact-validation/plan" in security
    assert "GET /internal/contact-validation/report" in security
    assert "## Contact-enrichment validation integrity" in security

    assert "## Phase 71 — Contact-enrichment validation harness (dry-run measurement)" in readme
    assert "contact-validation-plan" in readme
    assert "contact-validation-report" in readme
    assert "OUTBOUND_ENABLED=false" in readme
    assert "owner explicitly approves" in readme.lower() or "owner-approved" in readme.lower()
