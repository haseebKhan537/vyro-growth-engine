from __future__ import annotations

import argparse
import sys
from uuid import UUID

from vyro_growth.api.discovery import NppesDiscoveryRequest, run_nppes_discovery
from vyro_growth.database import SessionLocal
from vyro_growth.providers.nppes import NARROW_FILTER_ERROR, NppesSearchQuery
from vyro_growth.services.lead_scoring import LeadScoringService


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
        if args.lead_id and args.organization_id:
            parser.error("Provide --lead-id or --organization-id, not both")
        service = LeadScoringService()
        with SessionLocal() as db:
            if args.lead_id:
                results = [service.score_lead(db, UUID(args.lead_id))]
            elif args.organization_id:
                results = [service.score_organization(db, UUID(args.organization_id))]
            else:
                results = list(service.score_batch(db, limit=args.limit))
        for item in results:
            print(
                "Scored lead:",
                f"id={item.lead_id}",
                f"organization_id={item.organization_id}",
                f"score={item.scoring.total}",
                f"band={item.scoring.band.value}",
                f"model={item.scoring.model_version}",
            )
        print(f"scored={len(results)}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
