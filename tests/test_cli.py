from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from vyro_growth.cli import build_parser, main
from vyro_growth.domain import (
    BookingPlanRunStatus,
    DiscoveryRunStatus,
    EnrichmentRunStatus,
    OptimizerRunStatus,
    OutreachPlanRunStatus,
    PersonalizationReadiness,
    RecommendationApprovalStatus,
    ReplyClassificationOutcome,
    ReplyIntent,
    VoiceQualificationRunStatus,
    WebsiteMatchStatus,
)
from vyro_growth.services.booking_plan import BookingPlanJobResult
from vyro_growth.services.contact_enrichment import ContactEnrichmentResult
from vyro_growth.services.dashboard import (
    BookingPlanSummary,
    DashboardSummary,
    DecisionMakerSummary,
    DiscoverySummary,
    LatestRunSnapshot,
    OutreachPlanSummary,
    PersonalizationSummary,
    ReplyClassificationSummary,
    SafetyCard,
    ScoringSummary,
    SuppressionSummary,
    VoiceQualificationSummary,
    WebsiteEnrichmentSummary,
)
from vyro_growth.services.discovery import DiscoveryRunResult
from vyro_growth.services.growth_optimizer import (
    OptimizerRecommendationView,
    OptimizerRunResult,
)
from vyro_growth.services.lead_scoring import (
    MODEL_VERSION,
    PersistedScoreResult,
    ScoreBand,
    ScoringResult,
)
from vyro_growth.services.outreach_enrollment import OutreachPlanResult
from vyro_growth.services.personalization import PersonalizationJobResult
from vyro_growth.services.reply_classification import ReplyClassificationJobResult
from vyro_growth.services.voice_qualification import VoiceQualificationJobResult
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


def test_parser_accepts_plan_voice_qualification() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["plan-voice-qualification", "--limit", "8", "--operator-request"]
    )

    assert args.command == "plan-voice-qualification"
    assert args.limit == 8
    assert args.lead_id is None
    assert args.operator_request is True


def test_cli_main_runs_plan_voice_qualification(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = VoiceQualificationJobResult(
        voice_qualification_run_id=uuid4(),
        planned_count=1,
        skipped_count=0,
        suppressed_count=0,
        blocked_count=0,
        reused_count=0,
        status=VoiceQualificationRunStatus.COMPLETED,
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
        ) -> VoiceQualificationJobResult:
            assert limit == 4
            assert state == "TX"
            assert city == "AUSTIN"
            return result

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.VoiceQualificationService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())

    exit_code = main(
        ["plan-voice-qualification", "--limit", "4", "--state", "TX", "--city", "AUSTIN"]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"id={result.voice_qualification_run_id}" in output
    assert "planned=1" in output
    assert "status=completed" in output


def test_cli_plan_voice_qualification_operator_requires_lead() -> None:
    with pytest.raises(SystemExit):
        main(["plan-voice-qualification", "--operator-request"])


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


def test_parser_accepts_dashboard_summary() -> None:
    parser = build_parser()
    args = parser.parse_args(["dashboard-summary"])

    assert args.command == "dashboard-summary"


def test_cli_main_runs_dashboard_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = DashboardSummary(
        generated_at=datetime.now(tz=UTC),
        read_only=True,
        safety=SafetyCard(
            outbound_enabled=False,
            outbound_halted_settings=False,
            operator_halt_status="halted",
            operator_halt_reason="incident",
            operator_halt_updated_at=None,
            openai_personalization_enabled=False,
            openai_reply_classification_enabled=False,
            smartlead_live_enabled=False,
            google_calendar_live_enabled=False,
            voice_live_enabled=False,
            planned_count=2,
            skipped_count=1,
            suppressed_count=0,
            blocked_count=0,
            suppression_records=1,
            live_calendar_events=0,
            live_meet_links=0,
            live_phone_calls=0,
            live_send_attempted_enrollments=0,
            outbound_attempted_classifications=0,
            booking_events_created=0,
            booking_meet_links_created=0,
            voice_calls_placed=0,
            phi_fields_present=False,
        ),
        discovery=DiscoverySummary(
            organizations=3,
            leads=2,
            leads_by_stage={"discovered": 2},
            discovery_runs=1,
            records_fetched=3,
            records_upserted=3,
            records_skipped=0,
        ),
        website_enrichment=WebsiteEnrichmentSummary(
            organizations=3,
            by_match_status={"verified": 1},
            enrichment_runs=1,
            by_run_status={"completed": 1},
        ),
        decision_maker_enrichment=DecisionMakerSummary(
            contacts=1,
            by_role_category={"practice_manager": 1},
            enrichment_runs=1,
            by_run_status={"completed": 1},
        ),
        scoring=ScoringSummary(scores_total=1, latest_scores=1, by_band={"hot": 1}),
        personalization=PersonalizationSummary(
            drafts=1,
            by_readiness={"ready": 1},
            enrichment_runs=1,
        ),
        outreach_plans=OutreachPlanSummary(
            plan_runs=1,
            enrollments=1,
            by_status={"planned": 1},
            planned_count=1,
            skipped_count=0,
            suppressed_count=0,
            blocked_count=0,
        ),
        reply_classifications=ReplyClassificationSummary(
            classifications=1,
            by_intent={"meeting_request": 1},
            by_outcome={"classified": 1},
        ),
        booking_plans=BookingPlanSummary(
            plan_runs=1,
            plans=1,
            by_status={"planned": 1},
            planned_count=1,
            skipped_count=0,
            suppressed_count=0,
            blocked_count=0,
            events_created=0,
            meet_links_created=0,
        ),
        voice_qualification_plans=VoiceQualificationSummary(
            plan_runs=1,
            plans=1,
            by_status={"planned": 1},
            planned_count=1,
            skipped_count=0,
            suppressed_count=0,
            blocked_count=0,
            calls_placed=0,
            live_call_attempted=0,
        ),
        suppressions=SuppressionSummary(
            records=1,
            by_reason={"unsubscribe": 1},
            with_email=1,
            with_domain=0,
            with_phone=0,
            with_organization=0,
        ),
        latest_runs=(
            LatestRunSnapshot(
                phase="discovery",
                implemented=True,
                status="completed",
                started_at=None,
                finished_at=None,
                run_id=uuid4(),
            ),
        ),
    )

    class DummyService:
        def summarize(self, _db: object, _settings: object) -> DashboardSummary:
            return summary

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.DashboardAnalyticsService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: object())

    exit_code = main(["dashboard-summary"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "outbound_enabled=False" in output
    assert "operator_halt=halted" in output
    assert "organizations=3" in output
    assert "planned=1" in output
    assert "calls_placed=0" in output
    assert "phi_fields_present=False" in output


def test_parser_accepts_recommend_growth() -> None:
    parser = build_parser()
    args = parser.parse_args(["recommend-growth"])

    assert args.command == "recommend-growth"


def test_cli_main_runs_recommend_growth(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recommendation = OptimizerRecommendationView(
        id=uuid4(),
        recommendation_key="website_enrichment_gap",
        category="website_enrichment_gap",
        priority="medium",
        confidence=0.72,
        title="Review website enrichment coverage gaps",
        rationale="2 of 3 organizations lack a verified official website match.",
        source_metrics={"organizations": 3, "orgs_without_verified_website": 2},
        generated_at=datetime.now(tz=UTC),
        approval_status=RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
        applied=False,
    )
    result = OptimizerRunResult(
        optimizer_run_id=uuid4(),
        status=OptimizerRunStatus.COMPLETED,
        model_version="growth-optimizer-v1",
        snapshot_fingerprint="abc123",
        recommendation_count=1,
        reused_existing=False,
        applied_count=0,
        dry_run_only=True,
        outbound_attempted=False,
        live_call_attempted=False,
        generated_at=datetime.now(tz=UTC),
        operator_halt_before="halted",
        operator_halt_after="halted",
        recommendations=(recommendation,),
    )

    class DummyService:
        def recommend(self, _db: object, _settings: object) -> OptimizerRunResult:
            return result

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.GrowthOptimizerService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: object())

    exit_code = main(["recommend-growth"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"id={result.optimizer_run_id}" in output
    assert "recommendations=1" in output
    assert "applied=0" in output
    assert "outbound_attempted=False" in output
    assert "approval=pending_operator_review" in output
    assert "key=website_enrichment_gap" in output
    assert "applied=False" in output
