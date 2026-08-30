# Architecture

## System shape
Vyro Growth Engine is an event-driven sales automation platform. Core business rules live in the application/domain layer; third-party services are accessed only through provider adapters.

## Major components

### API
FastAPI exposes health, operator controls, webhook endpoints, and later dashboard/API resources. Internal operator routes such as `POST /internal/discovery/nppes` are not public: they require `INTERNAL_API_KEY` outside development and are fail-closed when that key is missing.

### Database
PostgreSQL is the system of record for organizations, contacts, leads, evidence, enrichment runs, outreach, conversations, meetings, activities, suppressions, and operator safety controls.

### Workers
Background workers perform discovery, enrichment, scoring, campaign orchestration, reply processing, scheduling, and optimization. Worker execution must be idempotent where practical.

### Provider adapters
Integrations are isolated behind interfaces so providers can be replaced without rewriting the domain logic. Phase 2 adds an `NppesProvider` adapter for public CMS/NPPES organization discovery. Phase 3A adds `WebsiteSearchProvider` and `PublicPageFetcher` adapters for official-website resolution. Phase 3B adds a `DecisionMakerEnrichmentProvider` boundary for professional contact candidates; the default implementation is a stub that returns no invented contacts and does not call a paid provider. Planned future adapters include broader search/crawl, a live paid contact provider, Smartlead, OpenAI, Google Calendar/Meet, and a consent-based voice provider.

### Phase 2 discovery flow
1. Operator or worker submits a targeted NPPES query through the CLI, worker job, or the internal HTTP trigger. The HTTP path is authorization-gated; CLI and worker paths are not. State alone is not enough; a narrower filter (`city`, `taxonomy_description`, or `organization_name`) is required.
2. `NppesDiscoveryService` creates a `discovery_runs` audit row and pages through the NPPES v2.1 API using raw page size, a skip ceiling of 1000, and timeout/retry/backoff (including HTTP 500 and transport errors). NPPES `Errors` payloads fail the run.
3. Only active organization (`NPI-2`) records are normalized to a business-only subset and upserted into `organizations` by NPI. Sparse reruns do not wipe existing city/state/specialty.
4. Provenance is stored in `source_evidence` with the source URL and query metadata. Authorized-official personal fields are not kept in memory or persisted.
5. Duplicate NPIs within a run are skipped; reruns update existing organizations safely and append new evidence/audit history.
6. No outbound actions occur in this phase.

### Phase 3 foundation: deterministic lead scoring
Scoring uses only persisted local fields (`organizations`, `leads`, `contacts`, `source_evidence`). It does not call NPPES, Apollo, scraping, OpenAI, Google, Smartlead, Twilio, Vapi, or any other provider.

1. Operator or worker submits `vyro-growth score-leads` or job `score_discovered_leads` with a lead id, organization id, or batch limit. There is no HTTP trigger.
2. `LeadScoringService` builds a snapshot from stored values only. Missing fields score 0 and are listed; unknown specialty fit is not assumed; websites and contacts are never inferred from a name.
3. The result is an integer 0–100 total plus an auditable rationale (`factors`, `missing_fields`, `used_fields`, `fabricated_facts: false`).
4. A `lead_scores` row and an `activities` audit row are written. A missing lead for an organization is created in `discovered` and is not auto-qualified.
5. No outbound actions occur.

### Phase 3A: official website discovery
Website enrichment is public-page-only. It does not contact prospects, create contacts, or call later-phase providers.

1. Operator or worker submits `vyro-growth enrich-websites` or job `enrich_organization_websites` with an organization id, optional candidate URL, or a batch limit. There is no HTTP trigger.
2. Candidates come from the operator URL, an existing `organizations.website`, and a `WebsiteSearchProvider`. The default search adapter is a name-heuristic generator, not a live search API.
3. `HttpPublicPageFetcher` requests public HTTP(S) HTML only: timeouts, size caps, redirect limits, rate limits, portal/review path blocks, and private/reserved address rejection. Directory hosts are ignored.
4. A page is `verified` only when the organization name and conservative location/identity evidence match. Otherwise the run is `ambiguous` or `no_match`. Facts are extracted only after a verified match.
5. Extracted facts are allowlisted public B2B signals with source URL, value, confidence, timestamp, and snippet. Missing facts are omitted, never invented.
6. `organizations.website` is set only on verified matches. Sparse reruns do not wipe an existing website. Each run writes `enrichment_runs`, `source_evidence`, and an `activities` row.
7. No outbound actions occur.

### Phase 3B: decision-maker and contact enrichment foundation
Contact enrichment identifies professional decision-makers. It does not send email, place calls, scrape LinkedIn, or call a live paid provider.

1. Operator or worker submits `vyro-growth enrich-contacts` or job `enrich_decision_makers` with an organization id or a batch limit. There is no HTTP trigger.
2. `ContactEnrichmentService` builds a typed request from the stored organization plus website-enrichment evidence (`ownership_signal`, provider count, official website, and public business contact facts). Missing website facts stay unknown.
3. The `DecisionMakerEnrichmentProvider` is the only integration boundary. CI and local runs use `StubDecisionMakerEnrichmentProvider`, which returns no contacts and never invents names, titles, emails, phones, roles, or confidence.
4. Provider results are classified and ranked: Owner/Physician Owner, Practice Administrator, Practice Manager, Office Manager, Executive Director, COO, CEO (only for smaller independent groups), Revenue Cycle Manager, Billing Manager, Operations Manager. Irrelevant clinical contacts are dropped unless owner/operator evidence is present.
5. Only professional/business fields are stored on `contacts`: name, title, role category, business email/phone if supplied, source provider, source timestamp, confidence, verification status, and provenance. Unknown values remain unknown. Contacts are deduplicated across reruns.
6. Each run writes `enrichment_runs`, `source_evidence`, and an `activities` row. No outbound actions occur. A live paid adapter is not wired; expected future env vars are documented in `.env.example` and are not required for tests.

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
