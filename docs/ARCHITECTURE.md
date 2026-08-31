# Architecture

## System shape
Vyro Growth Engine is an event-driven sales automation platform. Core business rules live in the application/domain layer; third-party services are accessed only through provider adapters.

## Major components

### API
FastAPI exposes health, readiness, operator controls, webhook endpoints, internal dashboard summaries, operator monitoring, and the operator review queue. `GET /health` is liveness-only. `GET /ready` checks database connectivity and runtime config and does not call live providers. Internal operator routes such as `POST /internal/discovery/nppes`, `GET /internal/dashboard/summary`, `GET /internal/dashboard/safety`, `GET /internal/monitoring/status`, `POST /internal/content-briefs/generate`, `GET /internal/content-briefs`, `POST /internal/channel-plans`, `GET /internal/review-queue`, and `POST /internal/review-queue/decisions` are not public: they require `INTERNAL_API_KEY` outside development and are fail-closed when that key is missing. Dashboard, monitoring, and review-queue list routes are read-only. Recording a review decision writes an audit row only and does not execute the artifact. Outside development, a missing `INTERNAL_API_KEY` or `DATABASE_URL` also fails process start.

### Database
PostgreSQL is the system of record for organizations, contacts, leads, evidence, enrichment runs, outreach, conversations, meetings, activities, suppressions, and operator safety controls.

### Workers
Background workers perform discovery, enrichment, scoring, campaign orchestration, reply processing, scheduling, and optimization. Worker execution must be idempotent where practical. Phase 12 documents an in-process (`inline`) runner only: operators or external cron invoke CLI commands. There is no durable queue and no autonomous outbound loop. `send_email`, `schedule_meeting`, and `place_consent_callback` remain undeployed fail-closed guards.

### Provider adapters
Integrations are isolated behind interfaces so providers can be replaced without rewriting the domain logic. Phase 2 adds an `NppesProvider` adapter for public CMS/NPPES organization discovery. Phase 3A adds `WebsiteSearchProvider` and `PublicPageFetcher` adapters for official-website resolution. Phase 3B adds a `DecisionMakerEnrichmentProvider` boundary for professional contact candidates; the default implementation is a stub that returns no invented contacts and does not call a paid provider. Phase 5 adds a `PersonalizationProvider` boundary for evidence-grounded draft generation. The default implementation is a deterministic stub. A guarded OpenAI adapter exists but makes no live call unless `OPENAI_PERSONALIZATION_ENABLED` is explicitly true and a key is configured. Phase 6 adds a `SmartleadProvider` boundary for dry-run campaign enrollment planning. The default implementation is a stub. A guarded live adapter exists but is not selected by `build_smartlead_provider()` and does not open a default HTTP session. Phase 7 adds a `ReplyClassifierProvider` boundary for inbound-reply intent classification. The default implementation is a deterministic rule stub. A guarded OpenAI adapter exists but makes no live call unless `OPENAI_REPLY_CLASSIFICATION_ENABLED` is explicitly true and a key is configured. Phase 8 adds a `BookingCalendarProvider` boundary for dry-run booking plans. The default implementation is a stub. A guarded Google Calendar / Meet adapter exists but is not selected by `build_booking_calendar_provider()` and does not open a default HTTP session. Phase 9 adds a `VoiceQualificationProvider` boundary for dry-run consent-based voice qualification plans. The default implementation is a stub. A guarded live voice adapter exists but is not selected by `build_voice_qualification_provider()` and does not open a default HTTP session. Planned future adapters include broader search/crawl, a live paid contact provider, live Google Calendar/Meet booking, and a live consent-based voice provider.

### Phase 2 discovery flow
1. Operator or worker submits a targeted NPPES query through the CLI, worker job, or the internal HTTP trigger. The HTTP path is authorization-gated; CLI and worker paths are not. State alone is not enough; a narrower filter (`city`, `taxonomy_description`, or `organization_name`) is required.
2. `NppesDiscoveryService` creates a `discovery_runs` audit row and pages through the NPPES v2.1 API using raw page size, a skip ceiling of 1000, and timeout/retry/backoff (including HTTP 500 and transport errors). NPPES `Errors` payloads fail the run.
3. Only active organization (`NPI-2`) records are normalized to a business-only subset and upserted into `organizations` by NPI. Sparse reruns do not wipe existing city/state/specialty.
4. Provenance is stored in `source_evidence` with the source URL and query metadata. Authorized-official personal fields are not kept in memory or persisted.
5. Duplicate NPIs within a run are skipped; reruns update existing organizations safely and append new evidence/audit history.
6. No outbound actions occur in this phase.

### Phase 3 foundation: deterministic lead scoring
Scoring began as a local-only 0–100 total from persisted organization/lead/contact/evidence fields. Phase 4 upgrades that engine; the CLI and worker entrypoints are unchanged.

### Phase 4: advanced ICP qualification
Scoring uses only stored public/business evidence. It does not call NPPES, Apollo, scraping, OpenAI, Google, Smartlead, Twilio, Vapi, Retell, or any other live provider.

1. Operator or worker submits `vyro-growth score-leads` or job `score_discovered_leads` with a lead id, organization id, or batch limit. There is no HTTP trigger.
2. `LeadScoringService` builds a snapshot from stored NPPES identity/specialty/location facts, website match status, website enrichment facts, contact-enrichment signals, and already-stored public business contacts. Missing, ambiguous, and conflicting facts stay unknown.
3. Website-derived practice-size, provider-count, independence, larger-group, billing/RCM, and website business-contact signals are scored only when a verified website match exists and the claim is explicitly stored. Billing/revenue-cycle points require an allowlisted phrase in source evidence.
4. The result is an integer 0–100 total, a band (`hot`, `high`, `medium`, `low`, `research`, `disqualified`), reason codes, and evidence links (`evidence_id`, `source_url`, `claim_type`) on material factors. `fabricated_facts` is always false.
5. A `lead_scores` row and an `activities` audit row are written on change. Reruns reuse the latest same-version score only when the canonical rationale is identical, including evidence pointers, observed values, missing fields, and research reasons. Identical reuse does not add another activity, lead, or outreach row. A missing lead is created in `discovered` and is not auto-qualified.
6. No outbound actions occur.

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

### Phase 5: evidence-grounded personalization
Personalization is dry-run only. It does not send email, place calls, book meetings, enroll leads, or call live paid providers by default.

1. Operator or worker submits `vyro-growth personalize-leads` or job `personalize_scored_leads` with a lead id, organization id, or batch limit. There is no HTTP trigger.
2. `PersonalizationService` builds an evidence pack from stored organization fields, `source_evidence`, the latest lead score/factors, and professional contact name/title/role only. Missing facts stay unknown.
3. The `PersonalizationProvider` is the only generation boundary. CI and local runs use `StubPersonalizationProvider`, which interpolates stored values and never invents business facts. A guarded OpenAI adapter with structured JSON schema, prompt versioning, token/cost placeholders, and retry/backoff exists but does not run unless explicitly enabled with a key.
4. Output is a structured draft: practice summary, why Vyro may be relevant, opening line, outreach angle, suggested offer (default Complimentary Revenue Leakage Analysis), missing-data notes, evidence references, confidence, and readiness.
5. Every material claim must map to stored evidence, a scoring factor, or an organization field. Ungrounded or malformed provider output fails the run without persisting a draft.
6. Each run writes `enrichment_runs` and `activities`. No outreach rows are created. `OUTBOUND_ENABLED` remains false by default.

### Phase 6: dry-run Smartlead enrollment planning
Outreach planning is dry-run only. It does not send email, enroll a live Smartlead campaign, place calls, or book meetings.

1. Operator or worker submits `vyro-growth plan-outreach` or job `plan_outreach_enrollments` with a lead id or batch limit. There is no HTTP trigger.
2. `OutreachEnrollmentService` loads stored scored leads, professional contacts with business email, and Phase 5 personalization drafts with `readiness_status=ready`. Missing data stays missing; facts are not invented.
3. Eligibility requires stage `qualified` or `ready_for_outreach` and a score band of `hot`, `high`, or `medium`. Email, domain, and organization suppressions skip the lead with an audited reason.
4. The `SmartleadProvider` is the only enrollment boundary. CI and local runs use `StubSmartleadProvider`, which returns a dry-run plan id and never calls Smartlead. `build_smartlead_provider()` always returns the stub.
5. A guarded live adapter exists as a future boundary. It requires `SMARTLEAD_LIVE_ENABLED`, outbound enablement, and a lifted operator halt, and still refuses to open HTTP unless a test injects a client.
6. Re-running the same campaign/lead/contact key reuses the planned enrollment. Lead stage is not advanced to `contacted`. No `outreach_messages` rows are written.
7. `OUTBOUND_ENABLED` remains false by default. Operator halt semantics are unchanged.

### Phase 7: inbound reply classification
Reply classification is dry-run only. It does not send email, generate replies for sending, place calls, book meetings, create Google Meet links, or enroll campaigns.

1. Operator or worker submits `vyro-growth classify-replies` or job `classify_inbound_replies` with a stored inbound `outreach_messages` id, a lead id, or a batch limit. There is no HTTP trigger and no live mailbox poll.
2. `ReplyClassificationService` loads stored inbound text/metadata (or a test fixture that is persisted as inbound). It does not scrape patient data or infer revenue, denial rates, A/R, payer mix, billing software, or medical conditions.
3. The `ReplyClassifierProvider` is the only classification boundary. CI and local runs use `StubReplyClassifier`, a deterministic keyword/rule adapter. A guarded OpenAI adapter exists but does not run unless explicitly enabled with a key.
4. Output is a structured intent plus confidence, matched signals, and an outcome: `classified`, `skipped`, `suppressed`, `blocked`, or `unknown`.
5. Lead stage changes use `ALLOWED_TRANSITIONS` only. The service never advances into `contacted`, `meeting_ready`, or `meeting_booked`. Meeting requests stop at `interested`. Unsubscribe replies create or confirm a permanent suppression and move the lead to `suppressed` when allowed.
6. Identical inbound message id, provider message id, or lead/content hash reuses the existing classification. Each attempt writes `activities`. No outbound `outreach_messages`, meetings, or campaign enrollments are created. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

### Phase 8: dry-run booking planning
Booking planning is dry-run only. It does not create Google Calendar events, Google Meet links, send email, place calls, or enroll campaigns.

1. Operator or worker submits `vyro-growth plan-booking` or job `plan_booking_slots` with a stored `meeting_request` classification, a lead id, an operator request, or a batch limit. There is no HTTP trigger.
2. `BookingPlanService` accepts only already-consented contexts: a stored inbound reply classified as `meeting_request`, or an explicit operator-created booking request. Mere interest without a meeting request is skipped.
3. The `BookingCalendarProvider` is the only scheduling boundary. CI and local runs use `StubBookingCalendarProvider`, which returns deterministic proposed-only slots and never creates events or Meet links. `build_booking_calendar_provider()` always returns the stub.
4. A guarded live adapter exists as a future boundary. It requires `GOOGLE_CALENDAR_LIVE_ENABLED`, outbound enablement, and a lifted operator halt, and still refuses to open HTTP unless a test injects a client.
5. Results persist as `booking_plans` with proposed slots, requested window if present, provider name, status, idempotency key, and audit JSON. Re-running the same lead/contact/classification/request key reuses the planned row.
6. Lead stage may move from `interested` or `qualification_pending` to `meeting_ready` using `ALLOWED_TRANSITIONS`. This phase never writes `meetings` rows and never advances to `meeting_booked`.
7. `OUTBOUND_ENABLED` remains false by default. Operator halt semantics are unchanged.

### Phase 9: dry-run consent-based voice qualification
Voice qualification planning is dry-run only. It does not place calls, send email, create calendar events, create Google Meet links, or enroll campaigns.

1. Operator or worker submits `vyro-growth plan-voice-qualification` or job `plan_voice_qualifications` with a stored inbound call-request reply, a lead id plus operator consent proof, a stored meeting/booking permission context, or a batch limit. There is no HTTP trigger.
2. `VoiceQualificationService` accepts only explicit permission/consent contexts. Mere interest or a meeting request without call-approval language is skipped. Missing consent proof is skipped with an audited reason.
3. Consent proof persisted on every planned row includes source, timestamp, channel, evidence/reference id if available, and the permitted business phone.
4. The `VoiceQualificationProvider` is the only generation boundary. CI and local runs use `StubVoiceQualificationProvider`, which returns a dry-run plan and never places a call. `build_voice_qualification_provider()` always returns the stub.
5. A guarded live adapter exists as a future boundary. It requires `VOICE_LIVE_ENABLED`, outbound enablement, consent, and a lifted operator halt, and still refuses to open HTTP unless a test injects a client.
6. Only safe B2B qualification facts are stored (provider count, specialty, billing setup, voluntarily stated denial/A/R pain, decision-maker status, urgency, current vendor status, preferred follow-up). Facts are never invented. Suspected PHI in an input payload is blocked and audited without persisting the PHI text.
7. Re-running the same lead/contact/consent/request key reuses the planned row. Lead stage is not advanced. No meetings, outbound messages, or campaign enrollments are created.
8. `OUTBOUND_ENABLED` remains false by default. Operator halt semantics are unchanged.

### Phase 10: operator dashboard foundation
The dashboard is read-only reporting over stored pipeline state. It does not send email, classify new replies, plan outreach, book meetings, place calls, or call live providers.

1. Operator requests `GET /internal/dashboard/summary`, `GET /internal/dashboard/safety`, or `vyro-growth dashboard-summary`. The HTTP paths use the same `INTERNAL_API_KEY` gate as discovery. CLI does not.
2. `DashboardAnalyticsService` counts existing organizations, leads, enrichment runs, scores, drafts, outreach plans, reply classifications, booking plans, voice qualification plans, suppressions, and operator halt state.
3. Safety cards report `OUTBOUND_ENABLED`, settings and persistent halt, live-provider flags, and planned/skipped/suppressed/blocked counts. Latest run timestamps/statuses are included per phase.
4. Responses contain counts, statuses, and timestamps only. They do not include message bodies, draft copy, emails, phones, evidence snippets, or other prospect/PHI fields.
5. No `activities`, meetings, enrollments, or outbound rows are written. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

### Phase 11: dry-run growth optimizer recommendations
The optimizer is an operator-review layer. It does not apply recommendations or change campaigns, scoring thresholds, provider settings, outbound behavior, calendars, or voice flows.

1. Operator or worker submits `POST /internal/optimizer/run`, `vyro-growth recommend-growth`, or job `generate_growth_recommendations`. HTTP paths use the same `INTERNAL_API_KEY` gate as discovery and the dashboard. CLI and worker paths do not.
2. `GrowthOptimizerService` reads `DashboardAnalyticsService` plus stored count aggregates (specialty/state stage mix, skip reasons, coverage gaps). It does not invent prospect facts or call live providers.
3. Recommendations are persisted on `optimizer_runs` / `optimizer_recommendations`. An identical sanitized snapshot fingerprint reuses the existing run.
4. Every recommendation includes category, priority, confidence, rationale, source metric references, generated timestamp, and `approval_status=pending_operator_review`. `applied` remains false.
5. API/CLI output is titles, rationales, and counts only. It does not include message bodies, draft copy, emails, phones, evidence snippets, or PHI.
6. No campaign, score, enrollment, meeting, calendar, or voice row is mutated except the optimizer tables and one audit activity. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

### Phase 12: production deployment foundation
Deployment is configuration, containers, probes, and runbooks only. It does not send email, enroll campaigns, book meetings, place calls, or call paid providers.

1. `require_valid_runtime_settings` runs at API start and via `vyro-growth check-config` / `vyro-growth worker --check`. Outside development, `INTERNAL_API_KEY` and `DATABASE_URL` are required. A live-provider flag without its key also fails closed.
2. `GET /health` reports process liveness, `OUTBOUND_ENABLED`, and whether any live-provider flag is on. `GET /ready` adds a `SELECT 1` database check and config issues.
3. The API image runs as a non-root user, defaults every live-provider flag to false, and probes `/health`. Compose `ops` profiles run `alembic upgrade head` and a worker catalog check without executing outbound jobs.
4. Operators follow `docs/DEPLOYMENT.md` for migration order, worker/cron assumptions, backup/restore, and rollback. Persistent operator halt is unchanged.

### Phase 13: observability and audit monitoring foundation
Monitoring is read-only operational visibility. It does not send email, enroll campaigns, book meetings, place calls, or call live providers.

1. Operator requests `GET /internal/monitoring/status` or `vyro-growth system-status`. The HTTP path uses the same `INTERNAL_API_KEY` gate as discovery and the dashboard. CLI does not.
2. `OperatorMonitoringService` reads existing run, activity, safety, and Phase 12 readiness tables. It does not write pipeline rows.
3. Output includes latest run status by phase, sanitized recent failures, safety flags, readiness/config state, pending operator-review counts, activity action counts, and findings (`blocked`, `warning`, `info`).
4. Responses never include message bodies, draft copy, emails, phones, evidence snippets, API keys, or PHI. Error text is redacted before it leaves the service.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

### Phase 14: operator review queue
The review queue is a decision-recording layer. It does not send email, enroll campaigns, book meetings, place calls, generate sendable autonomous replies, or apply optimizer recommendations.

1. Operator requests `GET /internal/review-queue`, `POST /internal/review-queue/decisions`, `vyro-growth review-queue`, or `vyro-growth record-review`. HTTP paths use the same `INTERNAL_API_KEY` gate as discovery and the dashboard. CLI does not.
2. `ReviewQueueService` reads pending dry-run artifacts: ready personalization drafts, planned outreach enrollments, classified follow-up replies, planned booking and voice rows, pending optimizer recommendations, and pending content briefs.
3. Items are normalized to artifact type/id, optional lead/organization UUIDs, a sanitized title/summary, status, timestamp, risk/safety labels, and `executable_later` (never `executed` in this phase).
4. Decisions persist on `operator_review_decisions` as `approved`, `rejected`, or `needs_changes` with reviewer, source, notes, and timestamp. Re-recording updates the current decision and writes another activity.
5. API/CLI output is titles, statuses, labels, and IDs only. It does not include message bodies, draft copy, emails, phones, evidence snippets, or PHI.
6. Existing artifact tables are not executed or applied. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

### Phase 16: review-only landing page and SEO content briefs
Content briefing is planning only. It does not publish pages, launch ads, spend money, send email, or call SEO/search/AI providers.

1. Operator or worker submits `POST /internal/content-briefs/generate`, `vyro-growth draft-content-briefs`, or job `generate_content_briefs`. HTTP paths use the same `INTERNAL_API_KEY` gate as discovery and the dashboard. CLI and worker paths do not.
2. `ContentBriefService` reads stored specialty/geography aggregates, pending `acquisition_channel_plans`, and explicit safe operator seeds. Missing facts stay missing.
3. Briefs persist on `content_brief_runs` / `content_briefs`. An identical sanitized snapshot fingerprint reuses the existing run.
4. Every brief includes type, optional channel-plan id, known specialty/geography/ICP only, title, sanitized summary, outline sections, CTA concept, compliance notes, source references, confidence/priority, generated timestamp, and `approval_status=pending_operator_review`. `published` remains false.
5. API/CLI output is titles, outlines, and counts only. It does not include outreach copy, emails, phones, evidence snippets, or PHI. Unverifiable claims are omitted.
6. Review-queue approval of a content brief is a recorded decision only and does not publish. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

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
