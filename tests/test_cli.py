from __future__ import annotations

from uuid import uuid4

import pytest

from vyro_growth.cli import build_parser, main
from vyro_growth.domain import DiscoveryRunStatus
from vyro_growth.services.discovery import DiscoveryRunResult
from vyro_growth.domain import EnrichmentRunStatus, WebsiteMatchStatus
from vyro_growth.services.lead_scoring import (
    MODEL_VERSION,
    PersistedScoreResult,
    ScoreBand,
    ScoringResult,
)
from vyro_growth.services.website_enrichment import WebsiteEnrichmentResult


def test_parser_accepts_discover_nppes_without_filters() -> None:
    parser = build_parser()
    args = parser.parse_args(["discover-nppes"])

    assert args.command == "discover-nppes"
    assert args.state is None
    assert args.city is None


def test_parser_accepts_state_and_city() -> None:
    parser = build_parser()
    args = parser.parse_args(["discover-nppes", "--state", "TX", "--city", "Austin"])

    assert args.command == "discover-nppes"
    assert args.state == "TX"
    assert args.city == "Austin"


def test_cli_main_runs_discovery(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = DiscoveryRunResult(
        discovery_run_id=uuid4(),
        records_fetched=2,
        records_upserted=2,
        records_skipped=0,
        status=DiscoveryRunStatus.COMPLETED,
    )
    monkeypatch.setattr("vyro_growth.cli.run_nppes_discovery", lambda *_args, **_kwargs: result)

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())

    exit_code = main(["discover-nppes", "--state", "TX", "--city", "Austin", "--max-records", "5"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "fetched=2" in output
    assert "status=completed" in output


def test_cli_main_requires_filter() -> None:
    with pytest.raises(SystemExit):
        main(["discover-nppes"])


def test_cli_main_rejects_state_only() -> None:
    with pytest.raises(SystemExit):
        main(["discover-nppes", "--state", "TX"])


def test_cli_main_rejects_whitespace_only_city() -> None:
    with pytest.raises(SystemExit):
        main(["discover-nppes", "--state", "TX", "--city", "   "])


def test_parser_accepts_score_leads() -> None:
    parser = build_parser()
    args = parser.parse_args(["score-leads", "--limit", "10"])

    assert args.command == "score-leads"
    assert args.limit == 10
    assert args.lead_id is None
    assert args.organization_id is None


def test_cli_main_runs_scoring(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    persisted = PersistedScoreResult(
        lead_id=uuid4(),
        organization_id=uuid4(),
        lead_score_id=uuid4(),
        lead_created=True,
        scoring=ScoringResult(
            total=72,
            model_version=MODEL_VERSION,
            band=ScoreBand.HIGH,
            factors=(),
            missing_fields=(),
            used_fields=("organization.npi",),
            fabricated_facts=False,
            external_providers_called=(),
        ),
    )

    class DummyService:
        def score_batch(self, _db: object, *, limit: int) -> tuple[PersistedScoreResult, ...]:
            assert limit == 10
            return (persisted,)

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.LeadScoringService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())

    exit_code = main(["score-leads", "--limit", "10"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"id={persisted.lead_id}" in output
    assert "score=72" in output
    assert "band=high" in output
    assert "scored=1" in output


def test_parser_accepts_enrich_websites() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "enrich-websites",
            "--organization-id",
            "11111111-1111-1111-1111-111111111111",
            "--candidate-url",
            "https://clinic.example",
        ]
    )

    assert args.command == "enrich-websites"
    assert args.candidate_url == "https://clinic.example"
    assert args.reenrich is False


def test_cli_main_runs_website_enrichment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = WebsiteEnrichmentResult(
        enrichment_run_id=uuid4(),
        organization_id=uuid4(),
        match_status=WebsiteMatchStatus.VERIFIED,
        official_website="https://austinfamilymedicine.com",
        facts_extracted=6,
        pages_fetched=1,
        candidates_considered=1,
        status=EnrichmentRunStatus.COMPLETED,
    )

    class DummyService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def enrich_batch(
            self,
            _db: object,
            *,
            limit: int,
            skip_verified: bool,
            state: str | None,
            city: str | None,
        ) -> tuple[WebsiteEnrichmentResult, ...]:
            assert limit == 5
            assert skip_verified is True
            assert state == "TX"
            assert city == "AUSTIN"
            return (result,)

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.WebsiteEnrichmentService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())

    exit_code = main(["enrich-websites", "--limit", "5", "--state", "TX", "--city", "AUSTIN"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "match=verified" in output
    assert "facts=6" in output
    assert "enriched=1" in output


def test_cli_enrich_websites_requires_org_for_candidate_url() -> None:
    with pytest.raises(SystemExit):
        main(["enrich-websites", "--candidate-url", "https://clinic.example"])


def test_cli_score_leads_rejects_both_ids() -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "score-leads",
                "--lead-id",
                str(uuid4()),
                "--organization-id",
                str(uuid4()),
            ]
        )
