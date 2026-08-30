from __future__ import annotations

from uuid import uuid4

import pytest

from vyro_growth.cli import build_parser, main
from vyro_growth.domain import DiscoveryRunStatus
from vyro_growth.services.discovery import DiscoveryRunResult


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

    exit_code = main(["discover-nppes", "--state", "TX", "--max-records", "5"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "fetched=2" in output
    assert "status=completed" in output


def test_cli_main_requires_filter() -> None:
    with pytest.raises(SystemExit):
        main(["discover-nppes"])
