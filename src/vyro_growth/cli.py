from __future__ import annotations

import argparse
import sys
from uuid import UUID

from vyro_growth.api.discovery import NppesDiscoveryRequest, run_nppes_discovery
from vyro_growth.config import get_settings
from vyro_growth.database import SessionLocal
from vyro_growth.providers.decision_makers import build_decision_maker_provider
from vyro_growth.providers.nppes import NARROW_FILTER_ERROR, NppesSearchQuery
from vyro_growth.providers.personalization import build_personalization_provider
from vyro_growth.providers.reply_classification import build_reply_classifier
from vyro_growth.providers.smartlead import build_smartlead_provider
from vyro_growth.providers.website import HeuristicWebsiteSearchProvider
from vyro_growth.providers.website_client import build_public_page_fetcher
from vyro_growth.services.contact_enrichment import ContactEnrichmentService
from vyro_growth.services.lead_scoring import LeadScoringService
from vyro_growth.services.outreach_enrollment import OutreachEnrollmentService
from vyro_growth.services.personalization import PersonalizationService
from vyro_growth.services.reply_classification import ReplyClassificationService
from vyro_growth.services.website_enrichment import WebsiteEnrichmentService


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


if __name__ == "__main__":
    sys.exit(main())
