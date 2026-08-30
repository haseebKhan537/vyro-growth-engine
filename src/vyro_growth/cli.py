from __future__ import annotations

import argparse
import sys

from vyro_growth.api.discovery import NppesDiscoveryRequest, run_nppes_discovery
from vyro_growth.database import SessionLocal
from vyro_growth.providers.nppes import NARROW_FILTER_ERROR, NppesSearchQuery


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

    parser.error(f"Unsupported command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
