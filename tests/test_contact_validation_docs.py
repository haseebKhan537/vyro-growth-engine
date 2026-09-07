from __future__ import annotations

from pathlib import Path


def test_phase_71_docs_describe_dry_run_measurement_without_live_send() -> None:
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    security = Path("docs/SECURITY.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    heading = (
        "## Phase 71 — Contact-enrichment validation harness and 200-practice "
        "measurement plan"
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


def test_phase_72_docs_describe_read_only_operator_ui() -> None:
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    security = Path("docs/SECURITY.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    deployment = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")
    health = Path("docs/OPERATOR_HEALTH.md").read_text(encoding="utf-8")

    heading = "## Phase 72 — Operator contact-validation UI shell"
    assert heading in roadmap
    assert "GET /internal/operator-contact-validation" in roadmap
    assert "ContactValidationService" in roadmap
    assert "max_cohort_size" in roadmap
    assert "OUTBOUND_ENABLED=false" in roadmap.split("## Phase 72")[1].split("## ")[0]

    assert "### Phase 72: operator contact-validation UI" in architecture
    assert "GET /internal/operator-contact-validation" in architecture
    assert "Cache-Control: no-store" in architecture.split("### Phase 72")[1].split("### ")[0]

    assert "GET /internal/operator-contact-validation" in security
    assert "operator contact-validation ui" in security.lower()

    assert "## Phase 72 — Operator contact-validation UI (read-only)" in readme
    assert "GET /internal/operator-contact-validation" in readme
    assert "OUTBOUND_ENABLED=false" in readme

    assert "operator-contact-validation" in deployment
    assert "operator-contact-validation" in health
