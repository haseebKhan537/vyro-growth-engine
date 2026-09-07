from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from vyro_growth.cli import build_parser, main
from vyro_growth.domain import (
    ApprovalPacketRunStatus,
    BookingPlanRunStatus,
    ChannelPlanRunStatus,
    ContentBriefRunStatus,
    DiscoveryRunStatus,
    EnrichmentRunStatus,
    ExecutionPlanRunStatus,
    FindingCode,
    FindingSeverity,
    NextActionCode,
    OptimizerRunStatus,
    OutreachPlanRunStatus,
    PersonalizationReadiness,
    RecommendationApprovalStatus,
    ReplyClassificationOutcome,
    ReplyIntent,
    VoiceQualificationRunStatus,
    WebsiteMatchStatus,
)
from vyro_growth.services.action_readiness import (
    ActionReadinessCandidate,
    ActionReadinessResult,
)
from vyro_growth.services.approval_packets import ApprovalPacketRunResult, ApprovalPacketView
from vyro_growth.services.booking_plan import BookingPlanJobResult
from vyro_growth.services.channel_planning import ChannelPlanRunResult, ChannelPlanView
from vyro_growth.services.command_center import (
    ApprovalPacketSummary,
    CommandCenterSummary,
    FindingCounts,
    NextAction,
    OutstandingReviewSummary,
    PipelineCounts,
)
from vyro_growth.services.contact_enrichment import ContactEnrichmentResult
from vyro_growth.services.contact_enrichment_metrics import ContactEnrichmentHitRate
from vyro_growth.services.content_brief import ContentBriefRunResult, ContentBriefView
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
from vyro_growth.services.email_verification import EmailVerificationRunResult
from vyro_growth.services.email_verification_metrics import EmailVerificationFunnel
from vyro_growth.services.execution_planning import ExecutionPlanRunResult, ExecutionPlanView
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
from vyro_growth.services.monitoring import (
    ActivityActionCount,
    LatestJobStatus,
    MonitoringReadiness,
    MonitoringSafety,
    MonitoringSnapshot,
    OperationalFinding,
    PendingReviewCounts,
)
from vyro_growth.services.outreach_enrollment import OutreachPlanResult
from vyro_growth.services.personalization import PersonalizationJobResult
from vyro_growth.services.phone_verification import (
    PhoneVerificationQueueResult,
    PhoneVerificationTaskView,
)
from vyro_growth.services.reply_classification import ReplyClassificationJobResult
from vyro_growth.services.review_queue import (
    ReviewDecisionResult,
    ReviewItem,
    ReviewQueueResult,
)
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


def test_parser_accepts_contact_enrichment_metrics() -> None:
    parser = build_parser()
    args = parser.parse_args(["contact-enrichment-metrics", "--json"])

    assert args.command == "contact-enrichment-metrics"
    assert args.json is True


def test_cli_main_runs_contact_enrichment_metrics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    metrics = ContactEnrichmentHitRate(
        generated_at=datetime.now(tz=UTC),
        packet_kind="contact_enrichment_hit_rate",
        purpose="contact_enrichment_validation_only",
        read_only=True,
        dry_run_only=True,
        no_execution=True,
        outbound_attempted=False,
        live_call_attempted=False,
        execution_allowed=False,
        owner_approved=False,
        spend_attempted=False,
        campaign_launched=False,
        halt_changed=False,
        outbound_enabled=False,
        operator_halt_status="halted",
        operator_halt_before="halted",
        operator_halt_after="halted",
        live_providers_enabled=False,
        live_providers={"decision_maker": False},
        decision_maker_live_enabled=False,
        contact_enrichment_is_not_outbound=True,
        organizations_considered=2,
        organizations_with_candidate=1,
        organizations_with_business_email=1,
        organizations_with_provider_verified_email=1,
        organizations_with_decision_maker_role=1,
        organizations_with_verified_decision_maker_email=1,
        no_contact_found_count=1,
        provider_error_count=0,
        candidate_count=1,
        organizations_with_candidate_rate=0.5,
        organizations_with_business_email_rate=0.5,
        organizations_with_provider_verified_email_rate=0.5,
        organizations_with_decision_maker_role_rate=0.5,
        organizations_with_verified_decision_maker_email_rate=0.5,
        no_contact_found_rate=0.5,
        provider_error_rate=0.0,
        candidates_by_role_category={"practice_manager": 1},
        candidates_by_verification_status={"provider_verified": 1},
        skipped_by_reason={"no_contact_found": 1},
        provider_errors_by_category={},
        cli_command="contact-enrichment-metrics",
        http_route="/internal/contact-enrichment/metrics",
    )

    class DummyService:
        def summarize(self, _db: object, _settings: object) -> ContactEnrichmentHitRate:
            return metrics

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.ContactEnrichmentMetricsService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: object())

    exit_code = main(["contact-enrichment-metrics", "--json"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"organizations_considered": 2' in output
    assert '"organizations_with_verified_decision_maker_email": 1' in output
    assert '"outbound_attempted": false' in output
    assert '"live_call_attempted": false' in output
    assert "owner@austinfamily.example" not in output


def test_parser_accepts_verify_emails() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "verify-emails",
            "--organization-id",
            "11111111-1111-1111-1111-111111111111",
            "--limit",
            "3",
        ]
    )

    assert args.command == "verify-emails"
    assert args.limit == 3
    assert args.state is None


def test_parser_accepts_email_verification_metrics() -> None:
    parser = build_parser()
    args = parser.parse_args(["email-verification-metrics", "--json"])

    assert args.command == "email-verification-metrics"
    assert args.json is True


def test_cli_main_runs_email_verification(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = EmailVerificationRunResult(
        enrichment_run_id=uuid4(),
        organization_id=uuid4(),
        contacts_considered=2,
        verified_count=1,
        no_verified_email_count=1,
        inferred_count=1,
        promoted_count=0,
        reused_count=0,
        status=EnrichmentRunStatus.COMPLETED,
        provider_name="stub",
        items=(),
    )

    class DummyService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def verify_batch(
            self,
            _db: object,
            *,
            limit: int,
            state: str | None,
            city: str | None,
        ) -> tuple[EmailVerificationRunResult, ...]:
            assert limit == 4
            assert state == "TX"
            assert city == "AUSTIN"
            return (result,)

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.EmailVerificationService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())

    exit_code = main(["verify-emails", "--limit", "4", "--state", "TX", "--city", "AUSTIN"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "no_verified_email=1" in output
    assert "verified_runs=1" in output
    assert "owner@austinfamily.example" not in output


def test_cli_main_runs_email_verification_metrics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    metrics = EmailVerificationFunnel(
        generated_at=datetime.now(tz=UTC),
        packet_kind="email_verification_funnel",
        purpose="email_verification_validation_only",
        read_only=True,
        dry_run_only=True,
        no_execution=True,
        outbound_attempted=False,
        live_call_attempted=False,
        smtp_attempted=False,
        execution_allowed=False,
        owner_approved=False,
        spend_attempted=False,
        campaign_launched=False,
        halt_changed=False,
        outbound_enabled=False,
        operator_halt_status="halted",
        operator_halt_before="halted",
        operator_halt_after="halted",
        live_providers_enabled=False,
        live_providers={"email_verification": False},
        email_verification_live_enabled=False,
        email_verification_smtp_enabled=False,
        email_verification_is_not_outbound=True,
        contacts_considered=2,
        contacts_with_business_email=2,
        contacts_with_verified_safe_email=1,
        no_verified_email_count=1,
        inferred_candidate_count=1,
        inferred_unverified_count=1,
        inferred_promoted_count=0,
        provider_error_count=0,
        verified_email_rate=0.5,
        no_verified_email_rate=0.5,
        inferred_candidate_rate=0.5,
        inferred_promoted_rate=0.0,
        verdicts_by_status={"valid": 1, "unverified": 1},
        outcomes_by_status={"verified": 1, "no_verified_email": 1},
        inferred_by_status={"unverified": 1},
        skipped_by_reason={"no_verified_email": 1},
        provider_errors_by_category={},
        cli_command="email-verification-metrics",
        http_route="/internal/email-verification/metrics",
    )

    class DummyService:
        def summarize(self, _db: object, _settings: object) -> EmailVerificationFunnel:
            return metrics

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.EmailVerificationMetricsService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: object())

    exit_code = main(["email-verification-metrics", "--json"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"contacts_considered": 2' in output
    assert '"contacts_with_verified_safe_email": 1' in output
    assert '"smtp_attempted": false' in output
    assert '"outbound_attempted": false' in output
    assert "owner@austinfamily.example" not in output


def test_parser_accepts_contact_validation_plan_and_report() -> None:
    parser = build_parser()
    plan = parser.parse_args(
        [
            "contact-validation-plan",
            "--json",
            "--state",
            "TX",
            "--city",
            "Austin",
            "--specialty",
            "Family Medicine",
            "--max-cohort-size",
            "200",
        ]
    )
    report = parser.parse_args(
        [
            "contact-validation-report",
            "--json",
            "--taxonomy-description",
            "Family Medicine",
        ]
    )

    assert plan.command == "contact-validation-plan"
    assert plan.json is True
    assert plan.state == "TX"
    assert plan.max_cohort_size == 200
    assert report.command == "contact-validation-report"
    assert report.taxonomy_description == "Family Medicine"
    packet = parser.parse_args(
        [
            "supervised-validation-run-packet",
            "--json",
            "--state",
            "TX",
            "--max-cohort-size",
            "200",
        ]
    )
    assert packet.command == "supervised-validation-run-packet"
    assert packet.json is True
    assert packet.state == "TX"
    assert packet.max_cohort_size == 200


def _phone_task_view() -> PhoneVerificationTaskView:
    now = datetime.now(tz=UTC)
    return PhoneVerificationTaskView(
        task_id=uuid4(),
        organization_id=uuid4(),
        lead_id=None,
        enrichment_run_id=None,
        contact_id=None,
        status="queued",
        queued_reason="no_contact_found",
        source="cli",
        reused=False,
        dry_run=True,
        no_execution=True,
        executed=False,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        voice_provider_used=False,
        autodial_attempted=False,
        suppression_created=False,
        contact_fact_created=False,
        has_name=False,
        has_title=False,
        has_phone=False,
        has_email=False,
        role_category=None,
        has_operator_label=False,
        has_operator_notes=False,
        queued_at=now,
        completed_at=None,
    )


def test_parser_accepts_phone_verification_commands() -> None:
    parser = build_parser()
    queued = parser.parse_args(
        [
            "queue-phone-verification",
            "--organization-id",
            "11111111-1111-1111-1111-111111111111",
            "--limit",
            "3",
        ]
    )
    listed = parser.parse_args(["list-phone-verification", "--json", "--include-completed"])
    recorded = parser.parse_args(
        [
            "record-phone-verification",
            "--task-id",
            "00000000-0000-0000-0000-000000000001",
            "--outcome",
            "do_not_contact",
            "--phone",
            "5125550199",
        ]
    )

    assert queued.command == "queue-phone-verification"
    assert queued.limit == 3
    assert listed.command == "list-phone-verification"
    assert listed.json is True
    assert listed.include_completed is True
    assert recorded.command == "record-phone-verification"
    assert recorded.outcome == "do_not_contact"


def test_cli_main_lists_phone_verification_without_exposing_phone(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    item = _phone_task_view()
    result = PhoneVerificationQueueResult(
        generated_at=datetime.now(tz=UTC),
        queued_count=1,
        decided_count=0,
        by_status={"queued": 1},
        suppression_created_count=0,
        contact_fact_created_count=0,
        executed_count=0,
        outbound_attempted=False,
        live_call_attempted=False,
        voice_provider_used=False,
        autodial_attempted=False,
        operator_halt_status="halted",
        operator_halt_before="halted",
        operator_halt_after="halted",
        outbound_enabled=False,
        items=(item,),
    )

    class DummyService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def list_tasks(self, *_args: object, **_kwargs: object) -> PhoneVerificationQueueResult:
            return result

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.PhoneVerificationService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: object())

    exit_code = main(["list-phone-verification", "--json"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"queued_count": 1' in output
    assert '"live_call_attempted": false' in output
    assert '"voice_provider_used": false' in output
    assert "5125550199" not in output
    assert "jordan.blake@austinfamily.example" not in output


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
            decision_maker_live_enabled=False,
            email_verification_live_enabled=False,
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


def test_parser_accepts_system_status() -> None:
    parser = build_parser()
    args = parser.parse_args(["system-status"])

    assert args.command == "system-status"


def test_cli_main_runs_system_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = MonitoringSnapshot(
        generated_at=datetime.now(tz=UTC),
        read_only=True,
        overall_severity=FindingSeverity.INFO,
        latest_runs=(
            LatestJobStatus(
                phase="discovery",
                job_name="discover_nppes_practices",
                implemented=True,
                status="completed",
                started_at=None,
                finished_at=None,
                run_id=uuid4(),
            ),
        ),
        recent_failures=(),
        safety=MonitoringSafety(
            outbound_enabled=False,
            outbound_halted_settings=False,
            operator_halt_status="halted",
            operator_halt_reason="incident",
            live_providers_enabled=False,
            live_providers={"smartlead": False, "voice": False},
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
        readiness=MonitoringReadiness(
            status="ready",
            environment="development",
            database="ok",
            config_ok=True,
            config_issues=(),
            outbound_enabled=False,
            live_providers_enabled=False,
            live_providers={"smartlead": False},
            ready_for_manual_rollout=True,
        ),
        pending_review=PendingReviewCounts(
            personalization_drafts=1,
            enrollment_plans=2,
            booking_plans=0,
            voice_plans=0,
            optimizer_recommendations=1,
            channel_plans=0,
            content_briefs=0,
        ),
        activity_summary=(ActivityActionCount(action="seeded", count=1),),
        findings=(
            OperationalFinding(
                FindingSeverity.INFO,
                FindingCode.SAFE_DEFAULTS,
                "Outbound and live-provider flags remain disabled.",
            ),
        ),
    )

    class DummyService:
        def snapshot(self, _db: object, _settings: object) -> MonitoringSnapshot:
            return snapshot

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.OperatorMonitoringService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: object())

    exit_code = main(["system-status"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "overall=info" in output
    assert "outbound_enabled=False" in output
    assert "operator_halt=halted" in output
    assert "ready_for_manual_rollout=True" in output
    assert "drafts=1" in output
    assert "optimizer=1" in output
    assert "job=discover_nppes_practices" in output
    assert "code=safe_defaults" in output
    assert "action=seeded" in output


def test_parser_accepts_operator_command_center() -> None:
    parser = build_parser()
    args = parser.parse_args(["operator-command-center"])

    assert args.command == "operator-command-center"


def test_cli_main_runs_operator_command_center(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = CommandCenterSummary(
        generated_at=datetime.now(tz=UTC),
        read_only=True,
        overall_severity=FindingSeverity.INFO,
        safety=MonitoringSafety(
            outbound_enabled=False,
            outbound_halted_settings=False,
            operator_halt_status="halted",
            operator_halt_reason="incident",
            live_providers_enabled=False,
            live_providers={"voice": False},
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
        readiness=MonitoringReadiness(
            status="ready",
            environment="development",
            database="ok",
            config_ok=True,
            config_issues=(),
            outbound_enabled=False,
            live_providers_enabled=False,
            live_providers={"voice": False},
            ready_for_manual_rollout=True,
        ),
        pipeline=PipelineCounts(
            organizations=3,
            leads=2,
            discovery_runs=1,
            website_enrichment_runs=1,
            decision_maker_contacts=1,
            latest_scores=2,
            personalization_drafts=1,
            outreach_plans_planned=1,
            reply_classifications=1,
            booking_plans=1,
            voice_qualification_plans=0,
            optimizer_recommendations=1,
            channel_plans=0,
            content_briefs=0,
            execution_plans=0,
            approval_packets=0,
        ),
        latest_runs=(
            LatestJobStatus(
                phase="discovery",
                job_name="discover_nppes_practices",
                implemented=True,
                status="completed",
                started_at=None,
                finished_at=None,
                run_id=uuid4(),
            ),
        ),
        recent_failures=(),
        finding_counts=FindingCounts(blocked=0, warning=0, info=1, total=1),
        findings=(
            OperationalFinding(
                FindingSeverity.INFO,
                FindingCode.SAFE_DEFAULTS,
                "Outbound and live-provider flags remain disabled.",
            ),
        ),
        outstanding_review=OutstandingReviewSummary(
            pending_count=2,
            decided_count=0,
            approved_count=0,
            rejected_count=0,
            needs_changes_count=0,
            by_artifact_type={"personalization_draft": 1},
            executed_count=0,
        ),
        approval_packets=ApprovalPacketSummary(
            packets=0,
            by_preflight_status={},
            by_plan_family={},
            owner_approved=0,
            executed=0,
            latest_run_status="not_started",
            latest_run_id=None,
        ),
        next_actions=(
            NextAction(
                code=NextActionCode.REVIEW_PENDING_ARTIFACTS.value,
                label="Review 2 pending dry-run artifact(s) in the operator review queue.",
                severity="info",
            ),
            NextAction(
                code=NextActionCode.KEEP_OUTBOUND_DISABLED.value,
                label="Keep OUTBOUND_ENABLED=false.",
                severity="info",
            ),
        ),
        executed_count=0,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
    )

    class DummyService:
        def summarize(self, _db: object, _settings: object) -> CommandCenterSummary:
            return summary

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.OperatorCommandCenterService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: object())

    exit_code = main(["operator-command-center"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "overall=info" in output
    assert "read_only=True" in output
    assert "outbound_enabled=False" in output
    assert "organizations=3" in output
    assert "pending=2" in output
    assert "packets=0" in output
    assert "code=review_pending_artifacts" in output
    assert "Keep OUTBOUND_ENABLED=false." in output
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


def test_parser_accepts_content_brief_commands() -> None:
    parser = build_parser()
    draft = parser.parse_args(
        [
            "draft-content-briefs",
            "--specialty",
            "Family Medicine",
            "--brief-type",
            "specialty_landing_page",
        ]
    )
    listed = parser.parse_args(["list-content-briefs"])

    assert draft.command == "draft-content-briefs"
    assert draft.specialty == "Family Medicine"
    assert listed.command == "list-content-briefs"


def test_cli_main_runs_draft_content_briefs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    brief = ContentBriefView(
        id=uuid4(),
        brief_key="specialty_landing_page:family-medicine",
        brief_type="specialty_landing_page",
        source_channel_plan_id=None,
        specialty="Family Medicine",
        geography="TX",
        icp_label=None,
        priority="low",
        confidence=0.6,
        title="Specialty landing page brief: Family Medicine / TX",
        summary="Review-only specialty landing page outline.",
        outline_sections=("Audience: Family Medicine / TX.",),
        recommended_cta="Invite a practice decision-maker to request a conversation.",
        compliance_notes=("Review-only brief. Do not publish this page or article.",),
        source_references={"source_kind": "operator_seed"},
        generated_at=datetime.now(tz=UTC),
        approval_status=RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
        published=False,
        publish_attempted=False,
        dry_run_only=True,
    )
    result = ContentBriefRunResult(
        content_brief_run_id=uuid4(),
        status=ContentBriefRunStatus.COMPLETED,
        model_version="content-brief-v1",
        snapshot_fingerprint="abc123",
        brief_count=1,
        reused_existing=False,
        published_count=0,
        dry_run_only=True,
        published=False,
        publish_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        ads_launched=False,
        spend_attempted=False,
        generated_at=datetime.now(tz=UTC),
        operator_halt_before="halted",
        operator_halt_after="halted",
        briefs=(brief,),
    )

    class DummyService:
        def generate(
            self, _db: object, _settings: object, **_kwargs: object
        ) -> ContentBriefRunResult:
            return result

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.ContentBriefService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: object())

    exit_code = main(["draft-content-briefs", "--specialty", "Family Medicine"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"id={result.content_brief_run_id}" in output
    assert "briefs=1" in output
    assert "published=False" in output
    assert "outbound_attempted=False" in output
    assert "ads_launched=False" in output
    assert "key=specialty_landing_page:family-medicine" in output


def test_parser_accepts_plan_acquisition_channels() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "plan-acquisition-channels",
            "--seed-specialty",
            "Family Medicine",
            "--seed-state",
            "TX",
            "--seed-keyword",
            "medical billing",
        ]
    )

    assert args.command == "plan-acquisition-channels"
    assert args.seed_specialty == "Family Medicine"
    assert args.seed_state == "TX"
    assert args.seed_keywords == ["medical billing"]


def test_cli_main_runs_plan_acquisition_channels(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = ChannelPlanView(
        id=uuid4(),
        plan_key="google_search_ads:family-medicine:tx",
        channel="google_search_ads",
        plan_type="keyword_group",
        title="Search ads concept for Family Medicine in TX",
        summary="Keyword-group concept from stored aggregates.",
        target_specialty="Family Medicine",
        target_geography="TX",
        target_icp=None,
        priority="medium",
        confidence=0.62,
        source_metrics={"organizations": 1},
        seed_input_refs={},
        generated_at=datetime.now(tz=UTC),
        approval_status=RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
        dry_run_only=True,
        no_spend=True,
        launched=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        outbound_attempted=False,
    )
    result = ChannelPlanRunResult(
        channel_plan_run_id=uuid4(),
        status=ChannelPlanRunStatus.COMPLETED,
        model_version="channel-planning-v1",
        snapshot_fingerprint="abc123",
        plan_count=1,
        reused_existing=False,
        dry_run_only=True,
        no_spend=True,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        outbound_attempted=False,
        live_call_attempted=False,
        generated_at=datetime.now(tz=UTC),
        operator_halt_before="halted",
        operator_halt_after="halted",
        plans=(plan,),
    )

    class DummyService:
        def plan(self, _db: object, seeds: object = None) -> ChannelPlanRunResult:
            del seeds
            return result

        def latest(self, _db: object) -> ChannelPlanRunResult:
            return result

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.ChannelPlanningService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())

    exit_code = main(["plan-acquisition-channels", "--seed-state", "TX"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"id={result.channel_plan_run_id}" in output
    assert "plans=1" in output
    assert "no_spend=True" in output
    assert "spend_attempted=False" in output
    assert "approval=pending_operator_review" in output
    assert "key=google_search_ads:family-medicine:tx" in output
    assert "launched=False" in output

    list_code = main(["list-channel-plans"])
    assert list_code == 0


def test_parser_accepts_execution_plan_commands() -> None:
    parser = build_parser()
    planned = parser.parse_args(
        [
            "plan-approved-execution",
            "--artifact-type",
            "personalization_draft",
        ]
    )
    listed = parser.parse_args(["list-execution-plans"])

    assert planned.command == "plan-approved-execution"
    assert planned.artifact_type == "personalization_draft"
    assert listed.command == "list-execution-plans"


def test_cli_main_runs_plan_approved_execution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_id = uuid4()
    plan = ExecutionPlanView(
        id=uuid4(),
        source_review_decision_id=uuid4(),
        source_artifact_type="personalization_draft",
        source_artifact_id=artifact_id,
        lead_id=None,
        organization_id=None,
        plan_type="personalization_draft",
        proposed_action="Prepare later owner-approved outreach from this dry-run draft",
        readiness_status="blocked",
        dry_run_only=True,
        no_execution=True,
        executed=False,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        owner_approval_required=True,
        owner_approved=False,
        generated_at=datetime.now(tz=UTC),
        idempotency_key="abc123",
        prerequisites=({"code": "artifact_operator_approved", "label": "approved", "met": True},),
        blockers=({"code": "execution_disabled_in_this_phase", "label": "dry-run only"},),
        safety_notes=("No email is sent from this plan",),
        required_owner_approvals=("Owner approval before any live outreach send",),
    )
    result = ExecutionPlanRunResult(
        execution_plan_run_id=uuid4(),
        status=ExecutionPlanRunStatus.COMPLETED,
        model_version="execution-planning-v1",
        snapshot_fingerprint="abc123",
        plan_count=1,
        reused_existing=False,
        reused_count=0,
        ignored_non_approved_count=0,
        executed_count=0,
        dry_run_only=True,
        no_execution=True,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        generated_at=datetime.now(tz=UTC),
        operator_halt_before="halted",
        operator_halt_after="halted",
        plans=(plan,),
    )

    class DummyService:
        def generate(
            self, _db: object, _settings: object, **_kwargs: object
        ) -> ExecutionPlanRunResult:
            return result

        def latest(self, _db: object) -> ExecutionPlanRunResult:
            return result

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.ExecutionPlanningService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: object())

    exit_code = main(["plan-approved-execution"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"id={result.execution_plan_run_id}" in output
    assert "plans=1" in output
    assert "executed=0" in output
    assert "no_execution=True" in output
    assert "outbound_attempted=False" in output
    assert f"artifact_id={artifact_id}" in output

    list_code = main(["list-execution-plans"])
    assert list_code == 0


def test_parser_accepts_approval_packet_commands() -> None:
    parser = build_parser()
    generated = parser.parse_args(
        [
            "generate-approval-packets",
            "--plan-type",
            "outreach_enrollment",
        ]
    )
    listed = parser.parse_args(["list-approval-packets"])

    assert generated.command == "generate-approval-packets"
    assert generated.plan_type == "outreach_enrollment"
    assert listed.command == "list-approval-packets"


def test_cli_main_runs_generate_approval_packets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_id = uuid4()
    packet = ApprovalPacketView(
        id=uuid4(),
        source_execution_plan_id=uuid4(),
        source_execution_plan_run_id=uuid4(),
        source_artifact_type="personalization_draft",
        source_artifact_id=artifact_id,
        plan_family="personalization_draft",
        proposed_action="Prepare later owner-approved outreach from this dry-run draft",
        preflight_status="blocked",
        dry_run_only=True,
        no_execution=True,
        executed=False,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        owner_approval_required=True,
        owner_approved=False,
        generated_at=datetime.now(tz=UTC),
        idempotency_key="abc123",
        preflight_checklist=(
            {"code": "execution_plan_present", "label": "present", "met": True},
        ),
        missing_prerequisites=(
            {"code": "owner_live_action_approval", "label": "owner", "met": False},
        ),
        findings=(
            {
                "severity": "blocked",
                "code": "execution_disabled_in_this_phase",
                "message": "dry-run only",
            },
        ),
        required_owner_decisions=("Owner approval before any live outreach send",),
    )
    result = ApprovalPacketRunResult(
        approval_packet_run_id=uuid4(),
        status=ApprovalPacketRunStatus.COMPLETED,
        model_version="approval-packets-v1",
        snapshot_fingerprint="abc123",
        packet_count=1,
        reused_existing=False,
        reused_count=0,
        missing_plan_count=0,
        executed_count=0,
        dry_run_only=True,
        no_execution=True,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        generated_at=datetime.now(tz=UTC),
        operator_halt_before="halted",
        operator_halt_after="halted",
        packets=(packet,),
    )

    class DummyService:
        def generate(
            self, _db: object, _settings: object, **_kwargs: object
        ) -> ApprovalPacketRunResult:
            return result

        def latest(self, _db: object) -> ApprovalPacketRunResult:
            return result

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.ApprovalPacketService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: object())

    exit_code = main(["generate-approval-packets"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"id={result.approval_packet_run_id}" in output
    assert "packets=1" in output
    assert "executed=0" in output
    assert "no_execution=True" in output
    assert "outbound_attempted=False" in output
    assert f"artifact_id={artifact_id}" in output

    list_code = main(["list-approval-packets"])
    assert list_code == 0


def test_parser_accepts_action_readiness() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "action-readiness",
            "--plan-family",
            "outreach_enrollment",
            "--readiness-status",
            "missing_owner_packet_decision",
            "--blocker-status",
            "blocked",
            "--decision-status",
            "approved",
        ]
    )

    assert args.command == "action-readiness"
    assert args.plan_family == "outreach_enrollment"
    assert args.readiness_status == "missing_owner_packet_decision"
    assert args.blocker_status == "blocked"
    assert args.decision_status == "approved"


def test_cli_main_runs_action_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate_id = uuid4()
    artifact_id = uuid4()
    result = ActionReadinessResult(
        generated_at=datetime.now(tz=UTC),
        candidate_count=1,
        by_readiness_status={"missing_owner_packet_decision": 1},
        by_plan_family={"outreach_enrollment": 1},
        by_blocker_status={"blocked": 1},
        by_decision_status={"approved": 1},
        dry_run_only=True,
        no_execution=True,
        executed_count=0,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        live_action=False,
        read_only=True,
        explicit_live_owner_action_required=True,
        operator_halt_status="halted",
        operator_halt_before="halted",
        operator_halt_after="halted",
        candidates=(
            ActionReadinessCandidate(
                candidate_id=candidate_id,
                artifact_type="outreach_enrollment_plan",
                artifact_id=artifact_id,
                plan_family="outreach_enrollment",
                sanitized_label="Prepare later owner-approved campaign enrollment",
                review_decision_status="approved",
                packet_decision_status="missing",
                preflight_status="blocked",
                readiness_status="missing_owner_packet_decision",
                blocker_status="blocked",
                dry_run_only=True,
                no_execution=True,
                executed=False,
                execution_attempted=False,
                outbound_attempted=False,
                live_call_attempted=False,
                recommendation_applied=False,
                spend_attempted=False,
                campaign_launched=False,
                pages_published=False,
                ads_launched=False,
                owner_approved=False,
                live_action=False,
                explicit_live_owner_action_required=True,
                generated_at=datetime.now(tz=UTC),
                execution_plan_id=None,
                approval_packet_id=None,
                review_decision_id=None,
                packet_decision_id=None,
                blocker_codes=("execution_disabled_in_this_phase",),
                missing_approval_codes=("missing_owner_packet_decision",),
                missing_prerequisite_codes=(),
            ),
        ),
    )

    class DummyService:
        def list_queue(
            self, _db: object, _settings: object, **_kwargs: object
        ) -> ActionReadinessResult:
            return result

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.ActionReadinessService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: object())

    exit_code = main(["action-readiness"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "candidates=1" in output
    assert "executed=0" in output
    assert "live_action=False" in output
    assert "read_only=True" in output
    assert "explicit_live_owner_action_required=True" in output
    assert f"id={candidate_id}" in output
    assert f"artifact_id={artifact_id}" in output
    assert "readiness=missing_owner_packet_decision" in output


def test_parser_accepts_launch_readiness() -> None:
    parser = build_parser()
    args = parser.parse_args(["launch-readiness", "--json"])

    assert args.command == "launch-readiness"
    assert args.json is True


def test_parser_accepts_settings_change_request_commands() -> None:
    parser = build_parser()
    listed = parser.parse_args(
        [
            "settings-change-requests",
            "--json",
            "--status",
            "pending",
            "--request-type",
            "keep_outbound_disabled",
        ]
    )
    created = parser.parse_args(
        [
            "create-settings-change-request",
            "--request-type",
            "request_provider_live_flag_review",
            "--setting-name",
            "VOICE_LIVE_ENABLED",
            "--desired-boolean",
            "true",
            "--idempotency-key",
            "voice-flag-review",
        ]
    )
    detail = parser.parse_args(
        ["settings-change-request", "--id", "00000000-0000-0000-0000-000000000001"]
    )
    decided = parser.parse_args(
        [
            "record-settings-change-decision",
            "--id",
            "00000000-0000-0000-0000-000000000001",
            "--decision",
            "approved",
        ]
    )
    proposed = parser.parse_args(["propose-settings-changes", "--json"])
    preflight = parser.parse_args(
        [
            "settings-execution-preflight",
            "--json",
            "--request-type",
            "keep_outbound_disabled",
            "--decision-status",
            "approved",
        ]
    )

    assert listed.command == "settings-change-requests"
    assert listed.json is True
    assert created.command == "create-settings-change-request"
    assert created.setting_names == ["VOICE_LIVE_ENABLED"]
    assert created.desired_boolean == "true"
    assert detail.command == "settings-change-request"
    assert decided.decision == "approved"
    assert proposed.command == "propose-settings-changes"
    assert preflight.command == "settings-execution-preflight"
    assert preflight.json is True
    assert preflight.request_type == "keep_outbound_disabled"
    handoff = parser.parse_args(["owner-handoff-packet", "--json"])
    assert handoff.command == "owner-handoff-packet"
    assert handoff.json is True
    binder = parser.parse_args(["compliance-evidence-binder", "--json"])
    assert binder.command == "compliance-evidence-binder"
    assert binder.json is True
    runbook = parser.parse_args(["release-candidate-runbook", "--json"])
    assert runbook.command == "release-candidate-runbook"
    assert runbook.json is True
    manifest = parser.parse_args(["release-artifact-manifest", "--json"])
    assert manifest.command == "release-artifact-manifest"
    assert manifest.json is True
    index = parser.parse_args(["go-live-readiness-index", "--json"])
    assert index.command == "go-live-readiness-index"
    assert index.json is True
    plan = parser.parse_args(["launch-blockers-plan", "--json"])
    assert plan.command == "launch-blockers-plan"
    assert plan.json is True
    staged = parser.parse_args(["staged-rollout-plan", "--json"])
    assert staged.command == "staged-rollout-plan"
    assert staged.json is True
    dossier = parser.parse_args(["owner-launch-dossier", "--json"])
    assert dossier.command == "owner-launch-dossier"
    assert dossier.json is True
    checklist = parser.parse_args(["provider-setup-checklist", "--json"])
    assert checklist.command == "provider-setup-checklist"
    assert checklist.json is True
    rehearsal = parser.parse_args(["go-live-rehearsal-checklist", "--json"])
    assert rehearsal.command == "go-live-rehearsal-checklist"
    assert rehearsal.json is True
    outcome = parser.parse_args(["rehearsal-outcome-report", "--json"])
    assert outcome.command == "rehearsal-outcome-report"
    assert outcome.json is True
    pilot = parser.parse_args(["supervised-pilot-plan", "--json"])
    assert pilot.command == "supervised-pilot-plan"
    assert pilot.json is True
    go_no_go = parser.parse_args(["supervised-pilot-go-no-go", "--json"])
    assert go_no_go.command == "supervised-pilot-go-no-go"
    assert go_no_go.json is True
    first_send = parser.parse_args(["supervised-pilot-first-send-preflight", "--json"])
    assert first_send.command == "supervised-pilot-first-send-preflight"
    assert first_send.json is True
    control_map = parser.parse_args(
        ["supervised-pilot-launch-rehearsal-control-map", "--json"]
    )
    assert control_map.command == "supervised-pilot-launch-rehearsal-control-map"
    assert control_map.json is True
    validation_packet = parser.parse_args(["supervised-validation-run-packet", "--json"])
    assert validation_packet.command == "supervised-validation-run-packet"
    assert validation_packet.json is True


def test_parser_accepts_check_config_and_worker() -> None:
    parser = build_parser()
    check_args = parser.parse_args(["check-config"])
    worker_args = parser.parse_args(["worker", "--list", "--check"])

    assert check_args.command == "check-config"
    assert worker_args.command == "worker"
    assert worker_args.list is True
    assert worker_args.check is True


def test_cli_check_config_reports_safe_defaults(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["check-config"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "config_ok=true" in output
    assert "outbound_enabled=False" in output
    assert "live_providers_enabled=False" in output
    assert "live_google_calendar=false" in output
    assert "live_voice=false" in output


def test_cli_check_config_fails_closed_in_production(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from vyro_growth.config import Settings

    monkeypatch.setattr(
        "vyro_growth.cli.get_settings",
        lambda: Settings(environment="production", internal_api_key=""),
    )

    exit_code = main(["check-config"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "config_ok=false" in captured.out
    assert "INTERNAL_API_KEY" in captured.err


def test_cli_worker_lists_jobs_without_running_them(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["worker", "--list"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "discover_nppes_practices" in output
    assert "verify_contact_emails" in output
    assert "queue_phone_verification_tasks" in output
    assert "generate_growth_recommendations" in output
    assert "generate_channel_plans" in output
    assert "generate_content_briefs" in output
    assert "undeployed_outbound=send_email,schedule_meeting,place_consent_callback" in output


def test_cli_worker_check_validates_config(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["worker", "--check"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "config_ok=true" in output
    assert "queue=inline" in output
    assert "scheduler=operator_or_external_cron" in output
    assert "outbound_enabled=False" in output


def test_parser_accepts_review_queue_and_record_review() -> None:
    parser = build_parser()
    listed = parser.parse_args(["review-queue", "--include-decided"])
    recorded = parser.parse_args(
        [
            "record-review",
            "--artifact-type",
            "personalization_draft",
            "--artifact-id",
            "00000000-0000-0000-0000-000000000001",
            "--decision",
            "approved",
            "--notes",
            "ok",
            "--reviewer",
            "ops",
        ]
    )

    assert listed.command == "review-queue"
    assert listed.include_decided is True
    assert recorded.command == "record-review"
    assert recorded.decision == "approved"
    assert recorded.reviewer == "ops"


def test_cli_main_runs_review_queue(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_id = uuid4()
    result = ReviewQueueResult(
        generated_at=datetime.now(tz=UTC),
        pending_count=1,
        decided_count=0,
        by_artifact_type={"personalization_draft": 1},
        by_decision={},
        executed_count=0,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        operator_halt_status="halted",
        items=(
            ReviewItem(
                artifact_type="personalization_draft",
                artifact_id=artifact_id,
                lead_id=None,
                organization_id=None,
                title="Personalization draft ready for operator review",
                summary="Evidence-grounded dry-run draft. Full copy is withheld from this queue.",
                status="pending_operator_review",
                created_at=datetime.now(tz=UTC),
                risk_labels=("decision_record_only", "not_executed"),
                executable_later=True,
                executed=False,
                decision=None,
            ),
        ),
    )

    class DummyService:
        def list_queue(
            self, _db: object, _settings: object, **_kwargs: object
        ) -> ReviewQueueResult:
            return result

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.ReviewQueueService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: object())

    exit_code = main(["review-queue"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "pending=1" in output
    assert "executed=0" in output
    assert "outbound_attempted=False" in output
    assert f"id={artifact_id}" in output
    assert "type=personalization_draft" in output


def test_cli_main_runs_record_review(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_id = uuid4()
    result = ReviewDecisionResult(
        decision_id=uuid4(),
        artifact_type="booking_plan",
        artifact_id=artifact_id,
        decision="approved",
        reviewer="ops",
        source="cli",
        reviewer_notes=None,
        decided_at=datetime.now(tz=UTC),
        executed=False,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        operator_halt_before="halted",
        operator_halt_after="halted",
    )

    class DummyService:
        def record_decision(self, _db: object, **_kwargs: object) -> ReviewDecisionResult:
            return result

    class DummySession:
        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("vyro_growth.cli.ReviewQueueService", DummyService)
    monkeypatch.setattr("vyro_growth.cli.SessionLocal", lambda: DummySession())

    exit_code = main(
        [
            "record-review",
            "--artifact-type",
            "booking_plan",
            "--artifact-id",
            str(artifact_id),
            "--decision",
            "approved",
            "--reviewer",
            "ops",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"id={result.decision_id}" in output
    assert "decision=approved" in output
    assert "executed=False" in output
    assert "outbound_attempted=False" in output
    assert "recommendation_applied=False" in output
