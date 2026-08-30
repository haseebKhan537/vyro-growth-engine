# Architecture

## System shape
Vyro Growth Engine is an event-driven sales automation platform. Core business rules live in the application/domain layer; third-party services are accessed only through provider adapters.

## Major components

### API
FastAPI exposes health, operator controls, webhook endpoints, and later dashboard/API resources.

### Database
PostgreSQL is the system of record for organizations, contacts, leads, evidence, outreach, conversations, meetings, activities, suppressions, and operator safety controls.

### Workers
Background workers perform discovery, enrichment, scoring, campaign orchestration, reply processing, scheduling, and optimization. Worker execution must be idempotent where practical.

### Provider adapters
Integrations are isolated behind interfaces so providers can be replaced without rewriting the domain logic. Phase 2 adds an `NppesProvider` adapter for public CMS/NPPES organization discovery. Planned future adapters include Firecrawl/search, Apollo, Smartlead, OpenAI, Google Calendar/Meet, and a consent-based voice provider.

### Phase 2 discovery flow
1. Operator or worker submits a targeted NPPES query. State alone is not enough; a narrower filter (`city`, `taxonomy_description`, or `organization_name`) is required.
2. `NppesDiscoveryService` creates a `discovery_runs` audit row and pages through the NPPES v2.1 API using raw page size, a skip ceiling of 1000, and timeout/retry/backoff (including HTTP 500 and transport errors). NPPES `Errors` payloads fail the run.
3. Only active organization (`NPI-2`) records are normalized to a business-only subset and upserted into `organizations` by NPI. Sparse reruns do not wipe existing city/state/specialty.
4. Provenance is stored in `source_evidence` with the source URL and query metadata. Authorized-official personal fields are not kept in memory or persisted.
5. Duplicate NPIs within a run are skipped; reruns update existing organizations safely and append new evidence/audit history.
6. No outbound actions occur in this phase.

### Event flow
1. Practice discovered.
2. Practice normalized/deduplicated.
3. Evidence-backed enrichment completed.
4. Decision-maker/contact identified and verified.
5. Lead qualified/scored.
6. Central outbound guard checked: `OUTBOUND_ENABLED`, operator halt, action policy, then suppressions.
7. Outreach created/sent.
8. Replies arrive through provider webhook.
9. Reply agent classifies and responds within policy.
10. Interested prospect is qualified.
11. Calendar agent proposes/rechecks availability.
12. Meeting + Google Meet are created.
13. Meeting brief is generated.
14. Outcome data feeds analytics/experiments.

## Non-negotiable invariants
- No patient PHI.
- Outbound defaults off. Env enablement alone is not enough while the operator halt is active or unreadable.
- Suppression is checked immediately before external contact.
- No fabricated prospect facts.
- Material enrichment claims retain evidence/source URLs.
- External actions are auditable.
- No cold autonomous AI robocalling.

## Repository direction
`src/vyro_growth/` will evolve into layered packages: `api`, `domain`, `services`, `repositories`, `providers`, `workers`, and `observability`. Phase 1 begins compactly and will be refactored only when tests protect behavior.
