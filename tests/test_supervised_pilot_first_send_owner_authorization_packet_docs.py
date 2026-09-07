from pathlib import Path


def test_phase_65_docs_describe_read_only_owner_authorization_packet() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    security = Path("docs/SECURITY.md").read_text(encoding="utf-8")
    deployment = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")
    operator_health = Path("docs/OPERATOR_HEALTH.md").read_text(encoding="utf-8")
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")

    assert "Phase 65" in readme
    assert "vyro-growth supervised-pilot-first-send-owner-authorization-packet" in readme
    assert "/internal/supervised-pilot-first-send-owner-authorization-packet" in readme
    assert "this_packet_is_not_approval" in readme
    assert "first_send_allowed=false" in readme
    assert "approval_records_mutated" in readme or "does not create or mutate approval" in readme.lower()

    assert "Phase 65" in architecture
    assert "supervised-pilot-first-send-owner-authorization-packet" in architecture
    assert "not approval" in architecture.lower()

    assert "Phase 65" in security
    assert "supervised-pilot-first-send-owner-authorization-packet" in security

    assert "vyro-growth supervised-pilot-first-send-owner-authorization-packet" in deployment
    assert "/internal/supervised-pilot-first-send-owner-authorization-packet" in deployment

    assert "supervised-pilot-first-send-owner-authorization-packet" in operator_health
    assert "Phase 65" in roadmap
    assert "supervised-pilot-first-send-owner-authorization-packet" in roadmap
