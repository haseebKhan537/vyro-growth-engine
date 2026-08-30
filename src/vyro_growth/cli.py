from __future__ import annotations

import argparse
import sys
from uuid import UUID

from vyro_growth.api.discovery import NppesDiscoveryRequest, run_nppes_discovery
from vyro_growth.config import get_settings
from vyro_growth.database import SessionLocal
from vyro_growth.providers.nppes import NARROW_FILTER_ERROR, NppesSearchQuery
from vyro_growth.providers.website import HeuristicWebsiteSearchProvider
from vyro_growth.providers.website_client import build_public_page_fetcher
from vyro_growth.services.lead_scoring import LeadScoringService
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
        help="Score discovered organizations or leads from local data only",
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


if __name__ == "__main__":
    sys.exit(main())
