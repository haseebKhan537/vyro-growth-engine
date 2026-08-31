from __future__ import annotations

import argparse
import sys
from uuid import UUID

from vyro_growth.api.discovery import NppesDiscoveryRequest, run_nppes_discovery
from vyro_growth.config import (
    RuntimeConfigError,
    get_settings,
    live_provider_flags,
    require_valid_runtime_settings,
    validate_runtime_settings,
)
from vyro_growth.database import SessionLocal
from vyro_growth.domain import VoiceConsentChannel, VoiceConsentSource
from vyro_growth.providers.calendar_booking import build_booking_calendar_provider
from vyro_growth.providers.decision_makers import build_decision_maker_provider
from vyro_growth.providers.nppes import NARROW_FILTER_ERROR, NppesSearchQuery
from vyro_growth.providers.personalization import build_personalization_provider
from vyro_growth.providers.reply_classification import build_reply_classifier
from vyro_growth.providers.smartlead import build_smartlead_provider
from vyro_growth.providers.voice_qualification import (
    build_voice_qualification_provider,
    parse_consent_timestamp,
)
from vyro_growth.providers.website import HeuristicWebsiteSearchProvider
from vyro_growth.providers.website_client import build_public_page_fetcher
from vyro_growth.services.booking_plan import BookingPlanService
from vyro_growth.services.channel_planning import (
    ChannelPlanningService,
    ChannelPlanRunResult,
    ChannelPlanSeeds,
)
from vyro_growth.services.contact_enrichment import ContactEnrichmentService
from vyro_growth.services.dashboard import DashboardAnalyticsService, DashboardSummary
from vyro_growth.services.growth_optimizer import GrowthOptimizerService, OptimizerRunResult
from vyro_growth.services.lead_scoring import LeadScoringService
from vyro_growth.services.monitoring import MonitoringSnapshot, OperatorMonitoringService
from vyro_growth.services.outreach_enrollment import OutreachEnrollmentService
from vyro_growth.services.personalization import PersonalizationService
from vyro_growth.services.reply_classification import ReplyClassificationService
from vyro_growth.services.review_queue import (
    ReviewDecisionResult,
    ReviewQueueError,
    ReviewQueueResult,
    ReviewQueueService,
)
from vyro_growth.services.voice_qualification import (
    VoiceConsentInput,
    VoiceQualificationService,
)
from vyro_growth.services.website_enrichment import WebsiteEnrichmentService
from vyro_growth.workers.catalog import DEPLOYABLE_JOBS, UNDEPLOYED_OUTBOUND_JOBS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vyro-growth")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser(
        "discover-nppes",
        help="Run a bounded NPPES practice discovery job",
    )
    discover.add_argument("--state", help="Two-letter state code")
    discover.add_argument("--city", help="City name")
    discover.add_argument("--taxonomy-description", help="Taxonomy/specialty description")
    discover.add_argument("--organization-name", help="Organization name")
    discover.add_argument("--max-records", type=int, help="Maximum records to import")

    score = subparsers.add_parser(
        "score-leads",
        help="Score discovered organizations from stored public/business evidence only",
    )
    score.add_argument("--lead-id", help="Existing lead UUID")
    score.add_argument("--organization-id", help="Organization UUID")
    score.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum organizations to score when no id is provided",
    )

    enrich = subparsers.add_parser(
        "enrich-websites",
        help="Resolve official practice websites and extract public business facts",
    )
    enrich.add_argument("--organization-id", help="Organization UUID")
    enrich.add_argument("--candidate-url", help="Optional official-website candidate to verify")
    enrich.add_argument("--state", help="Limit batch enrichment to a two-letter state code")
    enrich.add_argument("--city", help="Limit batch enrichment to a city")
    enrich.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum organizations to enrich when no organization id is provided",
    )
    enrich.add_argument(
        "--reenrich",
        action="store_true",
        help="Re-check organizations that already have a verified website",
    )

    contacts = subparsers.add_parser(
        "enrich-contacts",
        help="Persist professional decision-maker contacts from the stub enrichment provider",
    )
    contacts.add_argument("--organization-id", help="Organization UUID")
    contacts.add_argument("--state", help="Limit batch enrichment to a two-letter state code")
    contacts.add_argument("--city", help="Limit batch enrichment to a city")
    contacts.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum organizations to enrich when no organization id is provided",
    )

    personalize = subparsers.add_parser(
        "personalize-leads",
        help=(
            "Generate evidence-grounded personalization drafts (dry-run, outbound-disabled)"
        ),
    )
    personalize.add_argument("--lead-id", help="Existing lead UUID")
    personalize.add_argument("--organization-id", help="Organization UUID")
    personalize.add_argument(
        "--state",
        help="Limit batch personalization to a two-letter state code",
    )
    personalize.add_argument("--city", help="Limit batch personalization to a city")
    personalize.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum organizations to personalize when no id is provided",
    )

    outreach = subparsers.add_parser(
        "plan-outreach",
        help="Create a dry-run Smartlead enrollment plan without sending email",
    )
    outreach.add_argument("--lead-id", help="Existing lead UUID")
    outreach.add_argument("--campaign-id", help="Existing campaign UUID")
    outreach.add_argument(
        "--campaign-name",
        help="Campaign name to reuse or create (default: phase-6-dry-run)",
    )
    outreach.add_argument("--state", help="Limit batch planning to a two-letter state code")
    outreach.add_argument("--city", help="Limit batch planning to a city")
    outreach.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum leads to plan when no lead id is provided",
    )

    classify = subparsers.add_parser(
        "classify-replies",
        help=(
            "Classify stored inbound replies and update CRM state (dry-run, no outbound)"
        ),
    )
    classify.add_argument("--message-id", help="Inbound outreach message UUID")
    classify.add_argument("--lead-id", help="Lead UUID with stored inbound messages")
    classify.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum unclassified inbound messages when no id is provided",
    )

    booking = subparsers.add_parser(
        "plan-booking",
        help="Create a dry-run booking plan without calendar events or Meet links",
    )
    booking.add_argument("--lead-id", help="Existing lead UUID")
    booking.add_argument("--classification-id", help="Stored meeting-request classification UUID")
    booking.add_argument(
        "--operator-request",
        action="store_true",
        help="Plan from an explicit operator booking request instead of a stored reply",
    )
    booking.add_argument(
        "--request-key",
        help="Idempotency key for an operator booking request (default: operator)",
    )
    booking.add_argument("--window-start", help="Optional requested window start (ISO-8601)")
    booking.add_argument("--window-end", help="Optional requested window end (ISO-8601)")
    booking.add_argument("--state", help="Limit batch planning to a two-letter state code")
    booking.add_argument("--city", help="Limit batch planning to a city")
    booking.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum meeting-request classifications to plan when no id is provided",
    )

    voice = subparsers.add_parser(
        "plan-voice-qualification",
        help="Create a dry-run consent-based voice qualification plan without placing calls",
    )
    voice.add_argument("--lead-id", help="Existing lead UUID")
    voice.add_argument("--message-id", help="Stored inbound reply UUID that requested a call")
    voice.add_argument("--meeting-id", help="Stored meeting UUID with permission to call")
    voice.add_argument("--booking-plan-id", help="Stored booking plan UUID with permission to call")
    voice.add_argument(
        "--operator-request",
        action="store_true",
        help="Plan from an explicit operator voice request with consent proof",
    )
    voice.add_argument(
        "--request-key",
        help="Idempotency key for an operator voice request (default: operator)",
    )
    voice.add_argument(
        "--consent-source",
        help="Consent source (inbound_reply/operator_request/meeting_permission)",
    )
    voice.add_argument(
        "--consent-channel",
        help="Consent channel (email/inbound_call/operator/booking)",
    )
    voice.add_argument("--consent-timestamp", help="Consent timestamp (ISO-8601)")
    voice.add_argument("--consent-evidence-id", help="Consent evidence or reference id")
    voice.add_argument("--permitted-phone", help="Permitted business phone for the consent proof")
    voice.add_argument("--state", help="Limit batch planning to a two-letter state code")
    voice.add_argument("--city", help="Limit batch planning to a city")
    voice.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum inbound call-request messages to plan when no id is provided",
    )

    subparsers.add_parser(
        "dashboard-summary",
        help="Print a read-only pipeline and safety summary (no outbound side effects)",
    )
    subparsers.add_parser(
        "system-status",
        help=(
            "Print a read-only operator monitoring snapshot: run health, sanitized "
            "failures, safety, readiness, and pending review counts"
        ),
    )
    subparsers.add_parser(
        "recommend-growth",
        help=(
            "Generate dry-run growth optimizer recommendations for operator review "
            "(does not apply changes or send outreach)"
        ),
    )
    channels = subparsers.add_parser(
        "plan-acquisition-channels",
        help=(
            "Generate dry-run acquisition channel plans for operator review "
            "(does not launch campaigns, publish pages, or spend)"
        ),
    )
    channels.add_argument("--seed-specialty", help="Optional operator specialty seed")
    channels.add_argument("--seed-state", help="Optional operator geography/state seed")
    channels.add_argument(
        "--seed-keyword",
        action="append",
        dest="seed_keywords",
        help="Optional operator keyword seed (repeatable)",
    )
    channels.add_argument("--seed-partner-type", help="Optional operator partner-type seed")
    subparsers.add_parser(
        "list-channel-plans",
        help="List the latest dry-run acquisition channel plans (no launch or spend)",
    )
    review = subparsers.add_parser(
        "review-queue",
        help=(
            "List pending dry-run artifacts for operator review "
            "(records no execution and sends no outreach)"
        ),
    )
    review.add_argument(
        "--include-decided",
        action="store_true",
        help="Include artifacts that already have an operator decision",
    )
    review.add_argument(
        "--artifact-type",
        help="Limit the queue to one artifact type",
    )
    decide = subparsers.add_parser(
        "record-review",
        help=(
            "Record an approval, rejection, or needs-changes decision "
            "without executing the artifact"
        ),
    )
    decide.add_argument("--artifact-type", required=True, help="Review artifact type")
    decide.add_argument("--artifact-id", required=True, help="Review artifact UUID")
    decide.add_argument(
        "--decision",
        required=True,
        choices=("approved", "rejected", "needs_changes"),
        help="Operator decision to record",
    )
    decide.add_argument("--notes", help="Optional sanitized reviewer notes")
    decide.add_argument("--reviewer", help="Reviewer label (default: operator)")
    subparsers.add_parser(
        "check-config",
        help="Validate runtime settings without connecting to live providers",
    )
    worker = subparsers.add_parser(
        "worker",
        help="Inspect the in-process worker catalog (no durable queue, no outbound)",
    )
    worker.add_argument(
        "--list",
        action="store_true",
        help="List deployable dry-run job names",
    )
    worker.add_argument(
        "--check",
        action="store_true",
        help="Validate runtime config and print the job catalog summary",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "discover-nppes":
        query = NppesSearchQuery(
            state=args.state,
            city=args.city,
            taxonomy_description=args.taxonomy_description,
            organization_name=args.organization_name,
        )
        if not query.has_narrow_filter():
            parser.error(NARROW_FILTER_ERROR)

        request = NppesDiscoveryRequest(
            state=args.state,
            city=args.city,
            taxonomy_description=args.taxonomy_description,
            organization_name=args.organization_name,
            max_records=args.max_records,
        )
        with SessionLocal() as db:
            result = run_nppes_discovery(db, request)
        print(
            "Discovery run completed:",
            f"id={result.discovery_run_id}",
            f"fetched={result.records_fetched}",
            f"upserted={result.records_upserted}",
            f"skipped={result.records_skipped}",
            f"status={result.status.value}",
        )
        return 0

    if args.command == "score-leads":
        return _run_score_leads(parser, args)

    if args.command == "enrich-websites":
        return _run_enrich_websites(parser, args)

    if args.command == "enrich-contacts":
        return _run_enrich_contacts(args)

    if args.command == "personalize-leads":
        return _run_personalize_leads(parser, args)

    if args.command == "plan-outreach":
        return _run_plan_outreach(args)

    if args.command == "classify-replies":
        return _run_classify_replies(parser, args)

    if args.command == "plan-booking":
        return _run_plan_booking(parser, args)

    if args.command == "plan-voice-qualification":
        return _run_plan_voice_qualification(parser, args)

    if args.command == "dashboard-summary":
        return _run_dashboard_summary()

    if args.command == "system-status":
        return _run_system_status()

    if args.command == "recommend-growth":
        return _run_recommend_growth()

    if args.command == "plan-acquisition-channels":
        return _run_plan_acquisition_channels(args)

    if args.command == "list-channel-plans":
        return _run_list_channel_plans()

    if args.command == "review-queue":
        return _run_review_queue(args)

    if args.command == "record-review":
        return _run_record_review(args)

    if args.command == "check-config":
        return _run_check_config()

    if args.command == "worker":
        return _run_worker(args)

    parser.error(f"Unsupported command: {args.command}")
    return 1


def _run_score_leads(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.lead_id and args.organization_id:
        parser.error("Provide --lead-id or --organization-id, not both")
    scoring_service = LeadScoringService()
    with SessionLocal() as db:
        if args.lead_id:
            score_results = [scoring_service.score_lead(db, UUID(args.lead_id))]
        elif args.organization_id:
            score_results = [scoring_service.score_organization(db, UUID(args.organization_id))]
        else:
            score_results = list(scoring_service.score_batch(db, limit=args.limit))
    for score_item in score_results:
        print(
            "Scored lead:",
            f"id={score_item.lead_id}",
            f"organization_id={score_item.organization_id}",
            f"score={score_item.scoring.total}",
            f"band={score_item.scoring.band.value}",
            f"model={score_item.scoring.model_version}",
        )
    print(f"scored={len(score_results)}")
    return 0


def _run_enrich_websites(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.candidate_url and not args.organization_id:
        parser.error("--candidate-url requires --organization-id")
    settings = get_settings()
    enrichment_service = WebsiteEnrichmentService(
        HeuristicWebsiteSearchProvider(),
        build_public_page_fetcher(
            timeout_seconds=settings.website_fetch_timeout_seconds,
            max_bytes=settings.website_fetch_max_bytes,
            max_redirects=settings.website_fetch_max_redirects,
            rate_limit_seconds=settings.website_rate_limit_seconds,
            user_agent=settings.website_user_agent,
        ),
        max_pages_per_org=settings.website_max_pages_per_org,
    )
    with SessionLocal() as db:
        if args.organization_id:
            enrichment_results = [
                enrichment_service.enrich_organization(
                    db,
                    UUID(args.organization_id),
                    candidate_url=args.candidate_url,
                    skip_verified=not args.reenrich and not args.candidate_url,
                )
            ]
        else:
            enrichment_results = list(
                enrichment_service.enrich_batch(
                    db,
                    limit=args.limit,
                    skip_verified=not args.reenrich,
                    state=args.state,
                    city=args.city,
                )
            )
    for enrichment_item in enrichment_results:
        print(
            "Website enrichment:",
            f"organization_id={enrichment_item.organization_id}",
            f"match={enrichment_item.match_status.value}",
            f"website={enrichment_item.official_website or '-'}",
            f"facts={enrichment_item.facts_extracted}",
            f"status={enrichment_item.status.value}",
        )
    print(f"enriched={len(enrichment_results)}")
    return 0


def _run_enrich_contacts(args: argparse.Namespace) -> int:
    service = ContactEnrichmentService(build_decision_maker_provider())
    with SessionLocal() as db:
        if args.organization_id:
            contact_results = [service.enrich_organization(db, UUID(args.organization_id))]
        else:
            contact_results = list(
                service.enrich_batch(
                    db,
                    limit=args.limit,
                    state=args.state,
                    city=args.city,
                )
            )
    for item in contact_results:
        print(
            "Contact enrichment:",
            f"organization_id={item.organization_id}",
            f"upserted={item.contacts_upserted}",
            f"skipped={item.contacts_skipped}",
            f"provider={item.provider_name}",
            f"status={item.status.value}",
        )
    print(f"enriched={len(contact_results)}")
    return 0


def _run_personalize_leads(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.lead_id and args.organization_id:
        parser.error("Provide --lead-id or --organization-id, not both")
    service = PersonalizationService(build_personalization_provider())
    with SessionLocal() as db:
        if args.lead_id:
            results = [service.personalize_lead(db, UUID(args.lead_id))]
        elif args.organization_id:
            results = [service.personalize_organization(db, UUID(args.organization_id))]
        else:
            results = list(
                service.personalize_batch(
                    db,
                    limit=args.limit,
                    state=args.state,
                    city=args.city,
                )
            )
    for item in results:
        print(
            "Personalization:",
            f"lead_id={item.lead_id}",
            f"organization_id={item.organization_id}",
            f"draft_id={item.draft_id or '-'}",
            f"readiness={item.readiness_status.value if item.readiness_status else '-'}",
            f"provider={item.provider_name}",
            f"reused={item.reused_existing_draft}",
            f"outbound_attempted={item.outbound_attempted}",
            f"status={item.status.value}",
        )
    print(f"personalized={len(results)}")
    return 0


def _run_plan_outreach(args: argparse.Namespace) -> int:
    campaign_id = UUID(args.campaign_id) if args.campaign_id else None
    service = OutreachEnrollmentService(build_smartlead_provider())
    with SessionLocal() as db:
        if args.lead_id:
            result = service.plan_lead(
                db,
                UUID(args.lead_id),
                campaign_id=campaign_id,
                campaign_name=args.campaign_name,
            )
        else:
            result = service.plan_batch(
                db,
                limit=args.limit,
                state=args.state,
                city=args.city,
                campaign_id=campaign_id,
                campaign_name=args.campaign_name,
            )
    print(
        "Outreach plan:",
        f"id={result.outreach_plan_run_id}",
        f"campaign_id={result.campaign_id}",
        f"planned={result.planned_count}",
        f"skipped={result.skipped_count}",
        f"suppressed={result.suppressed_count}",
        f"blocked={result.blocked_count}",
        f"reused={result.reused_count}",
        f"status={result.status.value}",
    )
    return 0


def _run_classify_replies(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.message_id and args.lead_id:
        parser.error("Provide --message-id or --lead-id, not both")
    service = ReplyClassificationService(build_reply_classifier())
    with SessionLocal() as db:
        if args.message_id:
            results = [service.classify_message(db, UUID(args.message_id))]
        elif args.lead_id:
            results = list(service.classify_lead(db, UUID(args.lead_id)))
        else:
            results = list(service.classify_batch(db, limit=args.limit))
    for item in results:
        print(
            "Reply classification:",
            f"lead_id={item.lead_id}",
            f"message_id={item.message_id or '-'}",
            f"intent={item.intent.value if item.intent else '-'}",
            f"outcome={item.outcome.value}",
            f"provider={item.provider_name}",
            f"reused={item.reused_existing}",
            f"suppressed={item.suppressed}",
            f"stage={item.lead_stage_after}",
            f"outbound_attempted={item.outbound_attempted}",
        )
    print(f"classified={len(results)}")
    return 0


def _run_plan_booking(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.lead_id and args.classification_id and not args.operator_request:
        parser.error("Provide --lead-id or --classification-id, not both")
    if args.operator_request and not args.lead_id:
        parser.error("--operator-request requires --lead-id")
    requested_window = _requested_window(args.window_start, args.window_end)
    service = BookingPlanService(build_booking_calendar_provider())
    with SessionLocal() as db:
        if args.classification_id and not args.lead_id:
            result = service.plan_classification(db, UUID(args.classification_id))
        elif args.lead_id:
            result = service.plan_lead(
                db,
                UUID(args.lead_id),
                classification_id=(
                    UUID(args.classification_id) if args.classification_id else None
                ),
                operator_request=args.operator_request,
                request_key=args.request_key,
                requested_window=requested_window,
            )
        else:
            result = service.plan_batch(
                db,
                limit=args.limit,
                state=args.state,
                city=args.city,
            )
    print(
        "Booking plan:",
        f"id={result.booking_plan_run_id}",
        f"planned={result.planned_count}",
        f"skipped={result.skipped_count}",
        f"suppressed={result.suppressed_count}",
        f"blocked={result.blocked_count}",
        f"reused={result.reused_count}",
        f"status={result.status.value}",
    )
    return 0


def _requested_window(start: str | None, end: str | None) -> dict[str, object] | None:
    if not start and not end:
        return None
    window: dict[str, object] = {}
    if start:
        window["starts_at"] = start
    if end:
        window["ends_at"] = end
    return window


def _run_plan_voice_qualification(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    selected = [
        bool(args.lead_id),
        bool(args.message_id),
        bool(args.meeting_id),
        bool(args.booking_plan_id),
    ]
    if sum(1 for item in selected if item) > 1 and not args.lead_id:
        parser.error("Provide one of --lead-id, --message-id, --meeting-id, or --booking-plan-id")
    if args.operator_request and not args.lead_id:
        parser.error("--operator-request requires --lead-id")
    consent = _voice_consent_input(args)
    service = VoiceQualificationService(build_voice_qualification_provider())
    with SessionLocal() as db:
        if args.message_id and not args.lead_id:
            result = service.plan_message(db, UUID(args.message_id))
        elif args.meeting_id and not args.lead_id:
            result = service.plan_meeting(db, UUID(args.meeting_id), consent=consent)
        elif args.lead_id:
            result = service.plan_lead(
                db,
                UUID(args.lead_id),
                message_id=UUID(args.message_id) if args.message_id else None,
                meeting_id=UUID(args.meeting_id) if args.meeting_id else None,
                booking_plan_id=UUID(args.booking_plan_id) if args.booking_plan_id else None,
                operator_request=args.operator_request,
                request_key=args.request_key,
                consent=consent,
            )
        else:
            result = service.plan_batch(
                db,
                limit=args.limit,
                state=args.state,
                city=args.city,
            )
    print(
        "Voice qualification:",
        f"id={result.voice_qualification_run_id}",
        f"planned={result.planned_count}",
        f"skipped={result.skipped_count}",
        f"suppressed={result.suppressed_count}",
        f"blocked={result.blocked_count}",
        f"reused={result.reused_count}",
        f"status={result.status.value}",
    )
    return 0


def _voice_consent_input(args: argparse.Namespace) -> VoiceConsentInput | None:
    source = _voice_source(args.consent_source)
    channel = _voice_channel(args.consent_channel)
    consented_at = parse_consent_timestamp(args.consent_timestamp)
    permitted_phone = args.permitted_phone
    evidence_id = args.consent_evidence_id
    if (
        source is None
        and channel is None
        and consented_at is None
        and not permitted_phone
        and not evidence_id
    ):
        return None
    return VoiceConsentInput(
        source=source,
        channel=channel,
        consented_at=consented_at,
        permitted_phone=permitted_phone,
        evidence_reference_id=evidence_id,
    )


def _voice_source(value: str | None) -> VoiceConsentSource | None:
    if not value:
        return None
    try:
        return VoiceConsentSource(value)
    except ValueError:
        return None


def _voice_channel(value: str | None) -> VoiceConsentChannel | None:
    if not value:
        return None
    try:
        return VoiceConsentChannel(value)
    except ValueError:
        return None


def _run_dashboard_summary() -> int:
    settings = get_settings()
    with SessionLocal() as db:
        summary = DashboardAnalyticsService().summarize(db, settings)
    _print_dashboard_summary(summary)
    return 0


def _print_dashboard_summary(summary: DashboardSummary) -> None:
    safety = summary.safety
    print(
        "Dashboard safety:",
        f"outbound_enabled={safety.outbound_enabled}",
        f"operator_halt={safety.operator_halt_status}",
        f"planned={safety.planned_count}",
        f"skipped={safety.skipped_count}",
        f"suppressed={safety.suppressed_count}",
        f"blocked={safety.blocked_count}",
        f"live_calendar_events={safety.live_calendar_events}",
        f"live_meet_links={safety.live_meet_links}",
        f"live_phone_calls={safety.live_phone_calls}",
        f"phi_fields_present={safety.phi_fields_present}",
    )
    print(
        "Discovery:",
        f"organizations={summary.discovery.organizations}",
        f"leads={summary.discovery.leads}",
        f"runs={summary.discovery.discovery_runs}",
    )
    print(
        "Website enrichment:",
        f"runs={summary.website_enrichment.enrichment_runs}",
        f"match={summary.website_enrichment.by_match_status}",
    )
    print(
        "Decision-makers:",
        f"contacts={summary.decision_maker_enrichment.contacts}",
        f"runs={summary.decision_maker_enrichment.enrichment_runs}",
    )
    print(
        "Scoring:",
        f"latest={summary.scoring.latest_scores}",
        f"bands={summary.scoring.by_band}",
    )
    print(
        "Personalization:",
        f"drafts={summary.personalization.drafts}",
        f"readiness={summary.personalization.by_readiness}",
    )
    print(
        "Outreach plans:",
        f"planned={summary.outreach_plans.planned_count}",
        f"skipped={summary.outreach_plans.skipped_count}",
        f"suppressed={summary.outreach_plans.suppressed_count}",
        f"blocked={summary.outreach_plans.blocked_count}",
    )
    print(
        "Reply classifications:",
        f"total={summary.reply_classifications.classifications}",
        f"outcomes={summary.reply_classifications.by_outcome}",
    )
    print(
        "Booking plans:",
        f"planned={summary.booking_plans.planned_count}",
        f"events_created={summary.booking_plans.events_created}",
        f"meet_links_created={summary.booking_plans.meet_links_created}",
    )
    print(
        "Voice qualification plans:",
        f"planned={summary.voice_qualification_plans.planned_count}",
        f"calls_placed={summary.voice_qualification_plans.calls_placed}",
    )
    print(
        "Suppressions:",
        f"records={summary.suppressions.records}",
        f"reasons={summary.suppressions.by_reason}",
    )
    for run in summary.latest_runs:
        print(
            "Latest run:",
            f"phase={run.phase}",
            f"status={run.status}",
            f"run_id={run.run_id or '-'}",
        )


def _run_system_status() -> int:
    settings = get_settings()
    with SessionLocal() as db:
        snapshot = OperatorMonitoringService().snapshot(db, settings)
    _print_system_status(snapshot)
    return 0


def _print_system_status(snapshot: MonitoringSnapshot) -> None:
    safety = snapshot.safety
    readiness = snapshot.readiness
    pending = snapshot.pending_review
    print(
        "System status:",
        f"overall={snapshot.overall_severity.value}",
        f"read_only={snapshot.read_only}",
        f"ready_for_manual_rollout={readiness.ready_for_manual_rollout}",
    )
    print(
        "Safety:",
        f"outbound_enabled={safety.outbound_enabled}",
        f"operator_halt={safety.operator_halt_status}",
        f"live_providers_enabled={safety.live_providers_enabled}",
        f"live_calendar_events={safety.live_calendar_events}",
        f"live_meet_links={safety.live_meet_links}",
        f"live_phone_calls={safety.live_phone_calls}",
        f"phi_fields_present={safety.phi_fields_present}",
    )
    print(
        "Readiness:",
        f"status={readiness.status}",
        f"environment={readiness.environment}",
        f"database={readiness.database}",
        f"config_ok={readiness.config_ok}",
    )
    print(
        "Pending review:",
        f"drafts={pending.personalization_drafts}",
        f"enrollments={pending.enrollment_plans}",
        f"bookings={pending.booking_plans}",
        f"voice={pending.voice_plans}",
        f"optimizer={pending.optimizer_recommendations}",
        f"channel_plans={pending.channel_plans}",
        f"total={pending.total}",
    )
    for run in snapshot.latest_runs:
        print(
            "Latest run:",
            f"phase={run.phase}",
            f"job={run.job_name or '-'}",
            f"status={run.status}",
            f"run_id={run.run_id or '-'}",
        )
    for failure in snapshot.recent_failures:
        print(
            "Failure:",
            f"phase={failure.phase}",
            f"status={failure.status}",
            f"error={failure.error_message or '-'}",
        )
    for finding in snapshot.findings:
        print(
            "Finding:",
            f"severity={finding.severity.value}",
            f"code={finding.code.value}",
            f"message={finding.message}",
        )
    for item in snapshot.activity_summary:
        print("Activity:", f"action={item.action}", f"count={item.count}")


def _run_recommend_growth() -> int:
    settings = get_settings()
    with SessionLocal() as db:
        result = GrowthOptimizerService().recommend(db, settings)
    _print_optimizer_result(result)
    return 0


def _print_optimizer_result(result: OptimizerRunResult) -> None:
    print(
        "Optimizer run:",
        f"id={result.optimizer_run_id}",
        f"recommendations={result.recommendation_count}",
        f"reused={result.reused_existing}",
        f"applied={result.applied_count}",
        "approval=pending_operator_review",
        f"outbound_attempted={result.outbound_attempted}",
        f"status={result.status.value}",
    )
    for item in result.recommendations:
        print(
            "Recommendation:",
            f"key={item.recommendation_key}",
            f"category={item.category}",
            f"priority={item.priority}",
            f"confidence={item.confidence}",
            f"approval={item.approval_status}",
            f"applied={item.applied}",
        )


def _run_plan_acquisition_channels(args: argparse.Namespace) -> int:
    seeds = ChannelPlanSeeds(
        specialty=args.seed_specialty,
        geography=args.seed_state,
        keywords=tuple(args.seed_keywords or ()),
        partner_type=args.seed_partner_type,
    )
    with SessionLocal() as db:
        result = ChannelPlanningService().plan(db, seeds=seeds)
    _print_channel_plan_result(result)
    return 0


def _run_list_channel_plans() -> int:
    with SessionLocal() as db:
        result = ChannelPlanningService().latest(db)
    if result is None:
        print("Channel plans: status=not_started plans=0")
        return 0
    _print_channel_plan_result(result)
    return 0


def _print_channel_plan_result(result: ChannelPlanRunResult) -> None:
    print(
        "Channel plan run:",
        f"id={result.channel_plan_run_id}",
        f"plans={result.plan_count}",
        f"reused={result.reused_existing}",
        "approval=pending_operator_review",
        f"dry_run_only={result.dry_run_only}",
        f"no_spend={result.no_spend}",
        f"spend_attempted={result.spend_attempted}",
        f"campaign_launched={result.campaign_launched}",
        f"pages_published={result.pages_published}",
        f"outbound_attempted={result.outbound_attempted}",
        f"status={result.status.value}",
    )
    for item in result.plans:
        print(
            "Channel plan:",
            f"key={item.plan_key}",
            f"channel={item.channel}",
            f"type={item.plan_type}",
            f"priority={item.priority}",
            f"confidence={item.confidence}",
            f"approval={item.approval_status}",
            f"launched={item.launched}",
            f"spend_attempted={item.spend_attempted}",
        )


def _run_check_config() -> int:
    settings = get_settings()
    issues = validate_runtime_settings(settings)
    flags = live_provider_flags(settings)
    print(f"environment={settings.environment}")
    print(f"outbound_enabled={settings.outbound_enabled}")
    print(f"live_providers_enabled={any(flags.values())}")
    for name, enabled in flags.items():
        print(f"live_{name}={str(enabled).lower()}")
    if issues:
        for issue in issues:
            print(f"config_issue={issue}", file=sys.stderr)
        print("config_ok=false")
        return 1
    print("config_ok=true")
    return 0


def _run_worker(args: argparse.Namespace) -> int:
    if args.list:
        for job in DEPLOYABLE_JOBS:
            print(f"{job.name}\t{job.cli}\t{job.description}")
        print("undeployed_outbound=" + ",".join(UNDEPLOYED_OUTBOUND_JOBS))
        if not args.check:
            return 0
    settings = get_settings()
    try:
        require_valid_runtime_settings(settings)
    except RuntimeConfigError as exc:
        print(f"config_invalid={exc}", file=sys.stderr)
        return 1
    print("config_ok=true")
    print(f"environment={settings.environment}")
    print(f"outbound_enabled={settings.outbound_enabled}")
    print("queue=inline")
    print(f"jobs={len(DEPLOYABLE_JOBS)}")
    print("scheduler=operator_or_external_cron")
    return 0


def _run_review_queue(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        try:
            result = ReviewQueueService().list_queue(
                db,
                settings,
                include_decided=args.include_decided,
                artifact_type=args.artifact_type,
            )
        except ReviewQueueError as exc:
            print(f"Review queue error: {exc.message}")
            return 1
    _print_review_queue(result)
    return 0


def _print_review_queue(result: ReviewQueueResult) -> None:
    print(
        "Review queue:",
        f"pending={result.pending_count}",
        f"decided={result.decided_count}",
        f"shown={len(result.items)}",
        f"executed={result.executed_count}",
        f"outbound_attempted={result.outbound_attempted}",
        f"recommendation_applied={result.recommendation_applied}",
        f"operator_halt={result.operator_halt_status}",
    )
    for item in result.items:
        print(
            "Review item:",
            f"type={item.artifact_type}",
            f"id={item.artifact_id}",
            f"status={item.status}",
            f"executable_later={item.executable_later}",
            f"executed={item.executed}",
            f"title={item.title}",
        )


def _run_record_review(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        try:
            result = ReviewQueueService().record_decision(
                db,
                artifact_type=args.artifact_type,
                artifact_id=UUID(args.artifact_id),
                decision=args.decision,
                reviewer=args.reviewer,
                source="cli",
                reviewer_notes=args.notes,
            )
        except ReviewQueueError as exc:
            print(f"Review decision error: {exc.message}")
            return 1
        except ValueError:
            print("Review decision error: artifact id must be a UUID")
            return 1
    _print_review_decision(result)
    return 0


def _print_review_decision(result: ReviewDecisionResult) -> None:
    print(
        "Review decision:",
        f"id={result.decision_id}",
        f"type={result.artifact_type}",
        f"artifact_id={result.artifact_id}",
        f"decision={result.decision}",
        f"reviewer={result.reviewer}",
        f"source={result.source}",
        f"executed={result.executed}",
        f"outbound_attempted={result.outbound_attempted}",
        f"recommendation_applied={result.recommendation_applied}",
    )


if __name__ == "__main__":
    sys.exit(main())
