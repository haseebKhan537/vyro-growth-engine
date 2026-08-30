from __future__ import annotations

from uuid import uuid4

import pytest

from vyro_growth.cli import build_parser, main
from vyro_growth.domain import (
    BookingPlanRunStatus,
    DiscoveryRunStatus,
    EnrichmentRunStatus,
    OutreachPlanRunStatus,
    PersonalizationReadiness,
    ReplyClassificationOutcome,
    ReplyIntent,
    WebsiteMatchStatus,
)
from vyro_growth.services.booking_plan import BookingPlanJobResult
from vyro_growth.services.contact_enrichment import ContactEnrichmentResult
from vyro_growth.services.discovery import DiscoveryRunResult
from vyro_growth.services.lead_scoring import (
    MODEL_VERSION,
    PersistedScoreResult,
    ScoreBand,
    ScoringResult,
)
from vyro_growth.services.outreach_enrollment import OutreachPlanResult
from vyro_growth.services.personalization import PersonalizationJobResult
from vyro_growth.services.reply_classification import ReplyClassificationJobResult
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


def test_parser_accepts_enrich_contacts() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "enrich-contacts",
            "--organization-id",
            "11111111-1111-1111-1111-111111111111",
            "--limit",
            "3",
        ]
    )

    assert args.command == "enrich-contacts"
    assert args.limit == 3
    assert args.state is None


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


def test_cli_main_runs_contact_enrichment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = ContactEnrichmentResult(
        enrichment_run_id=uuid4(),
        organization_id=uuid4(),
        contacts_upserted=2,
        contacts_skipped=1,
        candidates_considered=3,
        status=EnrichmentRunStatus.COMPLETED,
        provider_name="stub",
    )

    class DummyService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def enrich_batch(
            self,
            _db: object,
            *,
            limit: int,
            state: str | None,
            city: str | None,
        ) -> tuple[ContactEnrichmentResult, ...]:
            assert limit == 4
            assert state == "TX"
            assert city == "AUSTIN"
            return (result,)

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.ContactEnrichmentService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())

    exit_code = main(["enrich-contacts", "--limit", "4", "--state", "TX", "--city", "AUSTIN"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "upserted=2" in output
    assert "skipped=1" in output
    assert "provider=stub" in output
    assert "enriched=1" in output


def test_parser_accepts_personalize_leads() -> None:
    parser = build_parser()
    args = parser.parse_args(["personalize-leads", "--limit", "7", "--state", "TX"])

    assert args.command == "personalize-leads"
    assert args.limit == 7
    assert args.state == "TX"
    assert args.lead_id is None


def test_cli_main_runs_personalization(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = PersonalizationJobResult(
        enrichment_run_id=uuid4(),
        lead_id=uuid4(),
        organization_id=uuid4(),
        draft_id=uuid4(),
        readiness_status=PersonalizationReadiness.READY,
        provider_name="stub",
        status=EnrichmentRunStatus.COMPLETED,
        reused_existing_draft=False,
        live_call_attempted=False,
        outbound_attempted=False,
    )

    class DummyService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def personalize_batch(
            self,
            _db: object,
            *,
            limit: int,
            state: str | None,
            city: str | None,
        ) -> tuple[PersonalizationJobResult, ...]:
            assert limit == 4
            assert state == "TX"
            assert city == "AUSTIN"
            return (result,)

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.PersonalizationService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())

    exit_code = main(["personalize-leads", "--limit", "4", "--state", "TX", "--city", "AUSTIN"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"lead_id={result.lead_id}" in output
    assert "readiness=ready" in output
    assert "provider=stub" in output
    assert "outbound_attempted=False" in output
    assert "personalized=1" in output


def test_cli_personalize_leads_rejects_both_ids() -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "personalize-leads",
                "--lead-id",
                str(uuid4()),
                "--organization-id",
                str(uuid4()),
            ]
        )


def test_cli_enrich_websites_requires_org_for_candidate_url() -> None:
    with pytest.raises(SystemExit):
        main(["enrich-websites", "--candidate-url", "https://clinic.example"])


def test_parser_accepts_classify_replies() -> None:
    parser = build_parser()
    args = parser.parse_args(["classify-replies", "--limit", "6"])

    assert args.command == "classify-replies"
    assert args.limit == 6
    assert args.message_id is None
    assert args.lead_id is None


def test_cli_main_runs_reply_classification(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = ReplyClassificationJobResult(
        classification_id=uuid4(),
        lead_id=uuid4(),
        message_id=uuid4(),
        conversation_id=uuid4(),
        intent=ReplyIntent.INTERESTED,
        outcome=ReplyClassificationOutcome.CLASSIFIED,
        provider_name="stub",
        reused_existing=False,
        suppressed=False,
        lead_stage_before="contacted",
        lead_stage_after="interested",
        outbound_attempted=False,
        live_call_attempted=False,
        operator_halt_before="halted",
        operator_halt_after="halted",
    )

    class DummyService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def classify_batch(
            self,
            _db: object,
            *,
            limit: int,
        ) -> tuple[ReplyClassificationJobResult, ...]:
            assert limit == 3
            return (result,)

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.ReplyClassificationService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())

    exit_code = main(["classify-replies", "--limit", "3"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"lead_id={result.lead_id}" in output
    assert "intent=interested" in output
    assert "provider=stub" in output
    assert "outbound_attempted=False" in output
    assert "classified=1" in output


def test_parser_accepts_plan_booking() -> None:
    parser = build_parser()
    args = parser.parse_args(["plan-booking", "--limit", "8", "--operator-request"])

    assert args.command == "plan-booking"
    assert args.limit == 8
    assert args.lead_id is None
    assert args.operator_request is True


def test_cli_main_runs_plan_booking(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = BookingPlanJobResult(
        booking_plan_run_id=uuid4(),
        planned_count=1,
        skipped_count=0,
        suppressed_count=0,
        blocked_count=0,
        reused_count=0,
        status=BookingPlanRunStatus.COMPLETED,
        items=(),
    )

    class DummyService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def plan_batch(
            self,
            _db: object,
            *,
            limit: int,
            state: str | None,
            city: str | None,
        ) -> BookingPlanJobResult:
            assert limit == 4
            assert state == "TX"
            assert city == "AUSTIN"
            return result

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.BookingPlanService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())

    exit_code = main(["plan-booking", "--limit", "4", "--state", "TX", "--city", "AUSTIN"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"id={result.booking_plan_run_id}" in output
    assert "planned=1" in output
    assert "status=completed" in output


def test_cli_plan_booking_rejects_both_ids() -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "plan-booking",
                "--lead-id",
                str(uuid4()),
                "--classification-id",
                str(uuid4()),
            ]
        )


def test_cli_plan_booking_operator_requires_lead() -> None:
    with pytest.raises(SystemExit):
        main(["plan-booking", "--operator-request"])


def test_cli_classify_replies_rejects_both_ids() -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "classify-replies",
                "--message-id",
                str(uuid4()),
                "--lead-id",
                str(uuid4()),
            ]
        )


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


def test_parser_accepts_plan_outreach() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["plan-outreach", "--limit", "8", "--campaign-name", "phase-6-dry-run"]
    )

    assert args.command == "plan-outreach"
    assert args.limit == 8
    assert args.campaign_name == "phase-6-dry-run"
    assert args.lead_id is None


def test_cli_main_runs_outreach_plan(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = OutreachPlanResult(
        outreach_plan_run_id=uuid4(),
        campaign_id=uuid4(),
        planned_count=1,
        skipped_count=0,
        suppressed_count=0,
        blocked_count=0,
        reused_count=0,
        status=OutreachPlanRunStatus.COMPLETED,
        items=(),
    )

    class DummyService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def plan_batch(
            self,
            _db: object,
            *,
            limit: int,
            state: str | None,
            city: str | None,
            campaign_id: object,
            campaign_name: str | None,
        ) -> OutreachPlanResult:
            assert limit == 4
            assert state == "TX"
            assert city == "AUSTIN"
            assert campaign_name == "phase-6-dry-run"
            assert campaign_id is None
            return result

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.OutreachEnrollmentService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())

    exit_code = main(
        [
            "plan-outreach",
            "--limit",
            "4",
            "--state",
            "TX",
            "--city",
            "AUSTIN",
            "--campaign-name",
            "phase-6-dry-run",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"id={result.outreach_plan_run_id}" in output
    assert "planned=1" in output
    assert "status=completed" in output
