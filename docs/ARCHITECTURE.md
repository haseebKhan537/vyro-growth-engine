# Architecture

## System shape
Vyro Growth Engine is an event-driven sales automation platform. Core business rules live in the application/domain layer; third-party services are accessed only through provider adapters.

## Major components

### API
FastAPI exposes health, readiness, operator controls, webhook endpoints, internal dashboard summaries, operator monitoring, the operator command center, the operator dashboard UI, the operator review-queue UI, the operator approval-packet UI, the operator action-readiness UI, the operator settings-change request UI, the operator settings-execution preflight UI, the operator owner-handoff packet UI, the operator activity audit timeline UI, the operator compliance evidence binder UI, the operator release-candidate runbook UI, the operator release artifact manifest UI, the operator go-live readiness index UI, the operator launch blockers remediation plan UI, the operator staged go-live rollout plan UI, the operator owner launch dossier UI, the operator review queue, dry-run channel-plan routes, review-only content-brief routes, dry-run execution-plan routes, owner approval-packet routes, the settings-execution preflight JSON surface, the owner go-live handoff packet JSON surface, the compliance evidence binder JSON surface, the release-candidate deployment runbook JSON surface, the release artifact manifest JSON surface, the go-live readiness index JSON surface, the launch blockers remediation plan JSON surface, the staged go-live rollout plan JSON surface, the owner launch dossier JSON surface, and the provider setup checklist JSON surface. `GET /health` is liveness-only. `GET /ready` checks database connectivity and runtime config and does not call live providers. Internal operator routes such as `POST /internal/discovery/nppes`, `GET /internal/dashboard/summary`, `GET /internal/dashboard/safety`, `GET /internal/monitoring/status`, `GET /internal/operator-command-center`, `GET /internal/operator-dashboard`, `GET /internal/operator-review-queue`, `POST /internal/operator-review-queue/{artifact_type}/{artifact_id}/decision`, `GET /internal/operator-approval-packets`, `POST /internal/operator-approval-packets/{packet_id}/decision`, `GET /internal/operator-action-readiness`, `GET /internal/operator-settings-change-requests`, `POST /internal/operator-settings-change-requests/{request_id}/decision`, `GET /internal/operator-settings-execution-preflight`, `GET /internal/operator-owner-handoff-packet`, `GET /internal/operator-audit-timeline`, `GET /internal/operator-compliance-evidence-binder`, `GET /internal/operator-release-candidate-runbook`, `GET /internal/operator-release-artifact-manifest`, `GET /internal/operator-go-live-readiness-index`, `GET /internal/operator-launch-blockers-plan`, `GET /internal/operator-staged-rollout-plan`, `GET /internal/operator-owner-launch-dossier`, `GET /internal/action-readiness`, `GET /internal/review-queue`, `POST /internal/review-queue/decisions`, `POST /internal/channel-plans/run`, `GET /internal/channel-plans`, `POST /internal/content-briefs/generate`, `GET /internal/content-briefs`, `POST /internal/execution-plans/run`, `GET /internal/execution-plans`, `POST /internal/approval-packets/run`, `GET /internal/approval-packets`, `GET /internal/settings-execution-preflight`, `GET /internal/owner-handoff-packet`, `GET /internal/compliance-evidence-binder`, `GET /internal/release-candidate-runbook`, `GET /internal/release-artifact-manifest`, `GET /internal/go-live-readiness-index`, `GET /internal/launch-blockers-plan`, `GET /internal/staged-rollout-plan`, `GET /internal/owner-launch-dossier`, and `GET /internal/provider-setup-checklist` are not public: they require `INTERNAL_API_KEY` outside development and are fail-closed when that key is missing. Dashboard, monitoring, command-center, operator-dashboard, operator review-queue list, operator approval-packet list, operator action-readiness, operator settings-change request list, operator settings-execution preflight, operator owner-handoff packet, operator audit timeline, operator compliance evidence binder, operator release-candidate runbook, operator release artifact manifest, operator go-live readiness index, operator launch blockers remediation plan, operator staged go-live rollout plan, operator owner launch dossier, review-queue list, launch-readiness, settings-execution preflight, owner-handoff-packet, compliance-evidence-binder, release-candidate-runbook, release-artifact-manifest, go-live-readiness-index, launch-blockers-plan, staged-rollout-plan, owner-launch-dossier, and provider-setup-checklist routes are read-only. Recording a review, approval-packet, or settings-change decision from JSON or the HTML form writes an audit row only and does not execute the artifact, packet, or setting. Channel-plan generation writes planning drafts only and never launches or spends. Content-brief generation writes review-only outlines and never publishes. Execution-plan generation writes readiness plans only and never performs the underlying live action. Approval-packet generation writes preflight packets only and never performs the underlying live action. Settings-execution preflight simulates remaining blockers only and never applies settings. The owner handoff packet consolidates those summaries for manual review only and never executes. The operator activity audit timeline renders existing activity and decision records only and never executes. The compliance evidence binder consolidates existing safety evidence for manual review only and never executes. The operator compliance evidence binder HTML page is the same binder as a sanitized shell and never executes. The release-candidate deployment runbook consolidates existing evidence into a future-manual deploy planning packet and never deploys. The operator release-candidate runbook HTML page is the same packet as a sanitized shell and never deploys. The release artifact manifest consolidates expected source/provenance, artifact, migration, runtime command, and safety-gate inventory for owner review only and never builds, publishes, or deploys. The operator release artifact manifest HTML page is the same packet as a sanitized shell and never builds, publishes, or deploys. The operator go-live readiness index HTML page links those existing surfaces for owner review only and never executes, builds, publishes, or deploys. The go-live readiness index CLI and JSON export reuse that same index and never execute, build, publish, or deploy. The launch blockers remediation plan CLI and JSON export reuse that same index as the source of truth and never execute, apply settings, lift halt, build, publish, or deploy. The operator launch blockers remediation plan HTML page is the same plan as a sanitized shell and never executes, applies settings, lifts halt, builds, publishes, or deploys. The staged go-live rollout plan CLI and JSON export reuse existing readiness, blocker, binder, runbook, and manifest services and never execute, apply settings, lift halt, build, publish, or deploy. The operator staged go-live rollout plan HTML page is the same plan as a sanitized shell and never executes, applies settings, lifts halt, builds, publishes, or deploys. The owner launch dossier CLI and JSON export reuse existing readiness, blocker, staged-rollout, handoff, binder, runbook, manifest, settings-preflight, and audit services and never execute, apply settings, lift halt, build, publish, or deploy. The operator owner launch dossier HTML page is the same packet as a sanitized shell and never executes, applies settings, lifts halt, builds, publishes, or deploys. The provider setup checklist CLI and JSON export reuse those surfaces plus launch readiness and never execute, apply settings, lift halt, build, publish, or deploy. Outside development, a missing `INTERNAL_API_KEY` or `DATABASE_URL` also fails process start.

### Database
PostgreSQL is the system of record for organizations, contacts, leads, evidence, enrichment runs, outreach, conversations, meetings, activities, suppressions, and operator safety controls.

### Workers
Background workers perform discovery, enrichment, scoring, campaign orchestration, reply processing, scheduling, optimization, dry-run channel planning, review-only content briefing, dry-run execution planning, and owner approval-packet preflight. Worker execution must be idempotent where practical. Phase 12 documents an in-process (`inline`) runner only: operators or external cron invoke CLI commands. There is no durable queue and no autonomous outbound loop. `send_email`, `schedule_meeting`, and `place_consent_callback` remain undeployed fail-closed guards.

### Provider adapters
Integrations are isolated behind interfaces so providers can be replaced without rewriting the domain logic. Phase 2 adds an `NppesProvider` adapter for public CMS/NPPES organization discovery. Phase 3A adds `WebsiteSearchProvider` and `PublicPageFetcher` adapters for official-website resolution. Phase 3B adds a `DecisionMakerEnrichmentProvider` boundary for professional contact candidates; the default implementation is a stub that returns no invented contacts and does not call a paid provider. Phase 5 adds a `PersonalizationProvider` boundary for evidence-grounded draft generation. The default implementation is a deterministic stub. A guarded OpenAI adapter exists but makes no live call unless `OPENAI_PERSONALIZATION_ENABLED` is explicitly true and a key is configured. Phase 6 adds a `SmartleadProvider` boundary for dry-run campaign enrollment planning. The default implementation is a stub. A guarded live adapter exists but is not selected by `build_smartlead_provider()` and does not open a default HTTP session. Phase 7 adds a `ReplyClassifierProvider` boundary for inbound-reply intent classification. The default implementation is a deterministic rule stub. A guarded OpenAI adapter exists but makes no live call unless `OPENAI_REPLY_CLASSIFICATION_ENABLED` is explicitly true and a key is configured. Phase 8 adds a `BookingCalendarProvider` boundary for dry-run booking plans. The default implementation is a stub. A guarded Google Calendar / Meet adapter exists but is not selected by `build_booking_calendar_provider()` and does not open a default HTTP session. Phase 9 adds a `VoiceQualificationProvider` boundary for dry-run consent-based voice qualification plans. The default implementation is a stub. A guarded live voice adapter exists but is not selected by `build_voice_qualification_provider()` and does not open a default HTTP session. Phase 15 plans acquisition channels from stored aggregates only and does not add an ads, SEO, or search-provider adapter. Phase 16 drafts content briefs from stored aggregates and pending channel plans only and does not add an AI, ads, or SEO-provider adapter. Phase 17 and Phase 18 plan execution and owner approval packets from stored dry-run artifacts and local config only and do not add a live-action adapter. Planned future adapters include broader search/crawl, a live paid contact provider, live Google Calendar/Meet booking, a live consent-based voice provider, and owner-approved channel-launch adapters.

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
2. `ReviewQueueService` reads pending dry-run artifacts: ready personalization drafts, planned outreach enrollments, classified follow-up replies, planned booking and voice rows, pending optimizer recommendations, pending acquisition channel plans, and pending content briefs.
3. Items are normalized to artifact type/id, optional lead/organization UUIDs, a sanitized title/summary, status, timestamp, risk/safety labels, and `executable_later` (never `executed` in this phase).
4. Decisions persist on `operator_review_decisions` as `approved`, `rejected`, or `needs_changes` with reviewer, source, notes, and timestamp. Re-recording updates the current decision and writes another activity.
5. API/CLI output is titles, statuses, labels, and IDs only. It does not include message bodies, draft copy, emails, phones, evidence snippets, or PHI.
6. Existing artifact tables are not executed or applied. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

### Phase 15: dry-run acquisition channel planning
Channel planning is an operator-review layer. It does not launch ads, publish pages, spend money, or call live ad/SEO/search providers.

1. Operator or worker submits `POST /internal/channel-plans/run`, `vyro-growth plan-acquisition-channels`, or job `generate_channel_plans`. HTTP paths use the same `INTERNAL_API_KEY` gate as discovery and the dashboard. CLI and worker paths do not.
2. `ChannelPlanningService` reads stored specialty/geography aggregates and optional sanitized seed inputs (specialty, state, keywords, partner type). Missing stored facts stay missing. Seeds that look like emails, phones, secrets, or PHI are dropped.
3. Plans persist on `channel_plan_runs` / `channel_plans`. An identical sanitized snapshot plus seed fingerprint reuses the existing run.
4. Every plan includes channel, plan type, title/summary, target specialty/geography/ICP when safely known, source metric or seed references, priority, confidence, generated timestamp, `approval_status=pending_operator_review`, and dry-run/no-spend flags. Launch and spend flags remain false.
5. Pending plans appear in the Phase 14 review queue as `acquisition_channel_plan`. Recording an approval does not launch, publish, or spend.
6. API/CLI output is titles, summaries, and counts only. It does not include message bodies, draft copy, emails, phones, evidence snippets, or PHI.
7. No campaign, score, enrollment, meeting, calendar, or voice row is mutated except the channel-plan tables and one audit activity. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

### Phase 16: review-only landing page and SEO content briefs
Content briefing is planning only. It does not publish pages, launch ads, spend money, send email, or call SEO/search/AI providers.

1. Operator or worker submits `POST /internal/content-briefs/generate`, `vyro-growth draft-content-briefs`, or job `generate_content_briefs`. HTTP paths use the same `INTERNAL_API_KEY` gate as discovery and the dashboard. CLI and worker paths do not.
2. `ContentBriefService` reads stored specialty/geography aggregates, pending Phase 15 `channel_plans`, and explicit safe operator seeds. Missing facts stay missing.
3. Briefs persist on `content_brief_runs` / `content_briefs`. An identical sanitized snapshot fingerprint reuses the existing run.
4. Every brief includes type, optional channel-plan id, known specialty/geography/ICP only, title, sanitized summary, outline sections, CTA concept, compliance notes, source references, confidence/priority, generated timestamp, and `approval_status=pending_operator_review`. `published` remains false.
5. API/CLI output is titles, outlines, and counts only. It does not include outreach copy, emails, phones, evidence snippets, or PHI. Unverifiable claims are omitted.
6. Review-queue approval of a content brief is a recorded decision only and does not publish. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

### Phase 17: dry-run approved-item execution plans
Execution planning is a readiness layer. It does not send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, or apply optimizer recommendations.

1. Operator or worker submits `POST /internal/execution-plans/run`, `vyro-growth plan-approved-execution`, or job `generate_execution_plans`. HTTP paths use the same `INTERNAL_API_KEY` gate as discovery and the dashboard. CLI and worker paths do not.
2. `ExecutionPlanningService` reads only operator-approved review decisions and sanitized artifact metadata. Pending, rejected, and needs-changes items are ignored. Missing facts stay missing.
3. Plans persist on `execution_plan_runs` / `execution_plans`. An identical sanitized approved-set fingerprint reuses the existing run.
4. Every plan includes source review decision id, artifact type/id, plan type, proposed action, prerequisites, blockers/readiness, safety notes, required owner approvals, dry-run/no-execution flags, generated timestamp, and an idempotency key. `executed` remains false.
5. API/CLI output is titles, statuses, and IDs only. It does not include message bodies, draft copy, emails, phones, evidence snippets, or PHI.
6. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called.

### Phase 18: live-readiness preflight and owner approval packets
Approval packets are a readiness layer. They do not send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, or apply optimizer recommendations.

1. Operator or worker submits `POST /internal/approval-packets/run`, `vyro-growth generate-approval-packets`, or job `generate_approval_packets`. HTTP paths use the same `INTERNAL_API_KEY` gate as discovery and the dashboard. CLI and worker paths do not.
2. `ApprovalPacketService` reads stored dry-run execution plans and safe local/config metadata. It reports whether required settings are present or absent. Secret values are never returned. Missing facts stay missing.
3. Packets persist on `approval_packet_runs` / `owner_approval_packets`. An identical sanitized plan-set plus safety fingerprint reuses the existing run.
4. Every packet includes source execution plan id/run id, artifact type/id, sanitized proposed action, preflight checklist, missing prerequisites, blocked/warning/info findings, required owner decisions, dry-run/no-execution flags, generated timestamp, and an idempotency key. `executed` remains false.
5. API/CLI output is IDs, statuses, and sanitized labels only. It does not include message bodies, draft copy, emails, phones, evidence snippets, API keys, or PHI.
6. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called.

### Phase 19: operator command center summary
The command center is a read-only aggregation over stored pipeline, review, monitoring, and approval-packet state. It does not send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, or apply optimizer recommendations.

1. Operator requests `GET /internal/operator-command-center` or `vyro-growth operator-command-center`. The HTTP path uses the same `INTERNAL_API_KEY` gate as discovery and the dashboard. CLI does not.
2. `OperatorCommandCenterService` reads existing dashboard, monitoring, review-queue, execution-plan, and approval-packet aggregates. It does not write pipeline rows.
3. Output includes pipeline counts, latest run statuses, readiness, blocked/warning/info finding summaries, outstanding review counts, approval packet counts, and safe next-action labels.
4. Responses never include message bodies, draft copy, emails, phones, evidence snippets, API keys, env secret values, or PHI. Error text is redacted before it leaves the service.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called.

### Phase 20: read-only operator dashboard UI shell
The operator dashboard is a server-rendered HTML shell over the Phase 19 command-center summary. It does not send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, or apply optimizer recommendations.

1. Operator requests `GET /internal/operator-dashboard`. The route uses the same `INTERNAL_API_KEY` gate as the command-center JSON summary. Optional `section` is a read-only filter only.
2. The page calls `OperatorCommandCenterService` through the existing sanitized command-center builder. It does not write pipeline rows or change operator halt state.
3. The view shows overall status/readiness, outbound-disabled and halt safety, pipeline counts, latest run statuses, outstanding review counts, approval packet/preflight counts, blocked/warning/info findings, and safe next-action labels.
4. Rendered HTML never includes message bodies, draft copy, emails, phones, evidence snippets, API keys, env secret values, PHI, or raw error text. There are no execute/send/enroll/book/call/publish/spend/deploy controls.
5. Empty databases render empty states. Render failures return a sanitized HTML error page. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

### Phase 21: read-only review queue and approval packet UI drilldowns
The review-queue and approval-packet pages are server-rendered HTML drilldowns over existing sanitized artifacts. They do not send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, or apply optimizer recommendations.

1. Operator requests `GET /internal/operator-review-queue` or `GET /internal/operator-approval-packets`. Artifact and packet detail routes use the same `INTERNAL_API_KEY` gate. Filters are read-only query parameters only.
2. The pages call `ReviewQueueService.list_queue` / `get_item` and `ApprovalPacketService.latest` / `get_packet`. They do not record decisions, generate new runs, write pipeline rows, or change operator halt state.
3. List and detail views show artifact type/id, status, decision or preflight status, timestamps, safe titles/labels/categories, blocked/warning/info counts and codes, required owner decision labels, and dry-run/no-execution flags.
4. Rendered HTML never includes message bodies, draft copy, emails, phones, evidence snippets, API keys, env secret values, PHI, or raw error text. There are no execute/send/enroll/book/call/publish/spend/deploy controls. Review-item and approval-packet detail pages include a decision-record form only.
5. Empty databases and unmatched filters render empty states. Missing items and render failures return sanitized HTML pages. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

### Phase 22: operator review decision UI forms
The review-item detail page can record `approved`, `rejected`, or `needs_changes` through the existing review-queue service. It does not execute the artifact, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, apply optimizer recommendations, or approve owner approval packets for live readiness.

1. Operator submits `POST /internal/operator-review-queue/{artifact_type}/{artifact_id}/decision` from the review-item detail form. The route uses the same `INTERNAL_API_KEY` gate as other internal operator routes.
2. The handler calls `ReviewQueueService.record_decision`. Identical resubmits reuse the existing unique decision row. A successful POST redirects (303) to the sanitized detail page so refresh does not create a duplicate write.
3. Reviewer labels and notes are sanitized/redacted before persist and again before HTML render. Invalid decisions and missing items return generic sanitized pages. No PHI, emails, phones, message bodies, draft copy, evidence snippets, secrets, or raw error text are shown.
4. There is no execute control on any operator HTML page.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

### Phase 23: owner approval packet decision UI
The approval-packet detail page can record `approved`, `rejected`, or `needs_changes` through the existing approval-packet service. It does not execute the packet, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, apply optimizer recommendations, or set live owner-approved state.

1. Operator submits `POST /internal/operator-approval-packets/{packet_id}/decision` from the packet detail form. The route uses the same `INTERNAL_API_KEY` gate as other internal operator routes.
2. The handler calls `ApprovalPacketService.record_decision`. Identical resubmits reuse the existing unique decision row. A successful POST redirects (303) to the sanitized detail page so refresh does not create a duplicate write.
3. Owner/reviewer labels and notes are sanitized/redacted before persist and again before HTML render. Invalid decisions and missing packets return generic sanitized pages. No PHI, emails, phones, message bodies, draft copy, evidence snippets, secrets, or raw error text are shown.
4. Recording `approved` does not execute the packet or change `owner_approved`. Approval-packet list pages stay without a form. Review-queue decision UI is unchanged. There is no execute control.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

### Phase 24: approved action readiness queue
The approved action readiness queue is a read-only join of stored review decisions, dry-run execution plans, owner approval packets, and packet decision records. It does not generate new artifacts, execute approved items or packets, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, apply optimizer recommendations, or set live owner-approved state.

1. Operator requests `GET /internal/action-readiness`, `GET /internal/operator-action-readiness`, or `vyro-growth action-readiness`. HTTP paths use the same `INTERNAL_API_KEY` gate as other internal operator routes. CLI does not.
2. `ActionReadinessService` reads existing stored records only. It does not write pipeline rows or change operator halt state.
3. Candidates include artifact type/id, plan family, review and packet decision status, preflight status, dry-run/no-execution flags, executed/live-action flags (false), blocker and missing-approval codes, timestamps, and sanitized labels.
4. Explicit readiness statuses are `blocked`, `missing_review_decision`, `missing_owner_packet_decision`, `preflight_blocked`, `approved_but_halted`, and `ready_pending_explicit_live_owner_action`. A ready-like status still requires a future explicit owner action before live execution.
5. Rendered HTML and JSON never include message bodies, draft copy, emails, phones, evidence snippets, API keys, env secret values, PHI, or raw error text. There are no execute/send/enroll/book/call/publish/spend/deploy controls.
6. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called.

### Phase 25: end-to-end dry-run smoke harness
The smoke harness is a local-only demo over deterministic synthetic fixture data. It does not send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, apply optimizer recommendations, execute approved items or packets, or set live owner-approved state.

1. Operator runs `vyro-growth smoke-dry-run`. Outside development, `--local-only` or `--dev-demo` is required. The command refuses `OUTBOUND_ENABLED=true` and any live-provider flag.
2. The CLI creates an isolated in-memory demo database. It does not use `DATABASE_URL` and does not change operator halt on runtime data.
3. The smoke runner seeds a synthetic practice/lead and safe public-business facts, then calls existing dry-run services through scoring, personalization, outreach, replies, booking, voice, optimizer, channel plans, content briefs, review decisions, execution plans, approval packets, packet decision records, and action readiness.
4. Output is IDs, statuses, counts, timestamps, blocker/readiness codes, and `executed=0` / `live_action=false` / `outbound_attempted=false` flags only. No PHI, emails, phones, message bodies, draft copy, evidence snippets, secrets, or unsafe error text.
5. Operator halt on the demo session is seeded halted if missing and otherwise left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called.

### Phase 26: CI dry-run smoke gate
CI proves the Phase 25 local-only smoke harness stays safe, deterministic, and usable. It does not send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, apply optimizer recommendations, execute approved items or packets, or set live owner-approved state.

1. GitHub Actions job `smoke-dry-run` installs dependencies, sets `OUTBOUND_ENABLED=false` and every live-provider flag false, and unsets `DATABASE_URL` plus provider credentials.
2. CI runs `vyro-growth smoke-dry-run --local-only --json` against the isolated in-memory demo fixture. Unexpected refusals fail the job.
3. `vyro-growth check-smoke-output` parses the sanitized JSON and requires `executed=0`, `live_action=false`, `outbound_attempted=false`, `owner_approved=false`, `dry_run_only=true`, `no_execution=true`, and `isolated_demo_database=true`.
4. The checker fails closed if output includes PHI, emails, phones, message bodies, draft copy, evidence snippets, secrets, live-provider enablement, or unsafe error text.
5. Operator halt and live/runtime settings are not changed. No live provider is called.

### Phase 27: launch readiness checklist
The launch readiness checklist is a read-only owner-facing preflight over local config, operator halt, stored approval packets, the action-readiness queue, and the documented CI smoke gate. It does not send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, apply optimizer recommendations, execute approved items or packets, or set live owner-approved state.

1. Operator runs `vyro-growth launch-readiness` or `GET /internal/launch-readiness`. HTTP uses the same `INTERNAL_API_KEY` gate as other internal operator routes. CLI does not.
2. `LaunchReadinessService` reuses existing readiness, halt, credential-presence, action-readiness, and local CI workflow inspection. It does not write pipeline rows, call GitHub Actions, or change operator halt state.
3. Output is overall status (`blocked` / `warning` / `ready_for_owner_review`), blocker codes, next-action labels, required configuration names, secret names with present/missing/redacted status, outbound/live-provider booleans, CI smoke-gate presence, pending packet counts, and action-readiness blocker counts.
4. Secret values, PHI, emails, phones, message bodies, draft copy, evidence snippets, and unsafe error text are never included. `ready_for_owner_review` is not permission to enable outbound.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called.

### Phase 28: live settings change request queue
The live settings change request queue is a record-only owner review surface over proposed setting names and desired booleans/statuses. It does not send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, apply optimizer recommendations, execute approved items or packets, or set live owner-approved state.

1. Operator runs `vyro-growth settings-change-requests`, `vyro-growth create-settings-change-request`, `vyro-growth settings-change-request --id`, `vyro-growth record-settings-change-decision`, `vyro-growth propose-settings-changes`, or the matching `/internal/settings-change-requests` routes. HTTP uses the same `INTERNAL_API_KEY` gate as other internal operator routes. CLI does not.
2. `SettingsChangeRequestService` stores setting names, desired booleans/statuses, statuses, timestamps, idempotency keys, and optional launch-readiness finding/next-action codes. Duplicate creates with the same idempotency key reuse the existing row.
3. Request types cover keep-outbound-disabled, outbound enablement review, one live-provider flag review, operator halt review, required credential configuration review by name only, and keep-safe-default notes. Secret values are never stored.
4. Recording `approved` is an audit record only. It does not apply the setting, lift halt, execute packets/items, or set live `owner_approved`.
5. Launch readiness points at proposed requests and can optionally create them. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called.

### Phase 29: settings change request UI drilldowns
The settings-change request pages are server-rendered HTML drilldowns over Phase 28 records. They do not apply settings, lift halt, enable outbound, execute requests, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, or set live owner-approved state.

1. Operator requests `GET /internal/operator-settings-change-requests` or a request detail route. The decision form posts to `POST /internal/operator-settings-change-requests/{request_id}/decision`. Routes use the same `INTERNAL_API_KEY` gate as other internal operator routes. Filters are read-only query parameters only.
2. The pages call `SettingsChangeRequestService.list_requests` / `get_request` / `record_decision`. Recording a decision never applies the setting or changes operator halt state.
3. List and detail views show request type, status, owner decision status, requested setting names, desired boolean/status, finding/next-action codes, timestamps, source, record-only/no-execution flags, and safe counts.
4. Rendered HTML never includes secret values, environment values, API keys, tokens, provider secrets, message bodies, draft copy, emails, phones, evidence snippets, PHI, or raw error text. There is no apply, execute, enable outbound, or lift-halt control.
5. Identical resubmits reuse the existing unique decision row. A successful POST redirects (303) to the sanitized detail page so refresh does not create a duplicate write. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default.

### Phase 30: approved settings execution preflight simulator
The settings-execution preflight is a dry-run simulator over Phase 28/29 request and decision records. It does not apply settings, lift halt, enable outbound, execute requests, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, or set live owner-approved state.

1. Operator runs `vyro-growth settings-execution-preflight` or `GET /internal/settings-execution-preflight`. HTTP uses the same `INTERNAL_API_KEY` gate as other internal operator routes. CLI does not.
2. `SettingsExecutionPreflightService` reads existing settings-change requests, owner decisions, operator halt, local flag/credential presence, and approval-packet decision counts. It does not write pipeline rows or change operator halt state.
3. Output is request IDs, request types, decision status, setting names, desired booleans/statuses, blocker/gate codes, missing credential names, timestamps, counts, and no-execution flags. `execution_allowed` remains false because a future explicitly approved execution phase does not exist.
4. Secret values, PHI, emails, phones, message bodies, draft copy, evidence snippets, and unsafe error text are never included. An approved decision is not permission to apply the setting.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called.

### Phase 31: settings execution preflight UI shell
The settings-execution preflight HTML page is a sanitized read-only shell over the Phase 30 simulator. It does not apply settings, lift halt, enable outbound, execute requests, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, or set live owner-approved state.

1. Operator requests `GET /internal/operator-settings-execution-preflight`. The route uses the same `INTERNAL_API_KEY` gate as other internal operator routes. Filters are read-only query parameters only.
2. The page calls `SettingsExecutionPreflightService.simulate` through the existing JSON builder. It never writes pipeline rows or changes operator halt state.
3. The view shows overall status, request and decision counts, blocker/gate/approval codes, missing credential variable names, closed provider flag names, request IDs/types, decision status, desired booleans/statuses, timestamps, and no-execution flags.
4. Rendered HTML never includes secret values, environment values, API keys, tokens, provider secrets, message bodies, draft copy, emails, phones, evidence snippets, PHI, or raw error text. There is no apply, execute, enable outbound, or lift-halt control.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. This page is a blocker view, not permission or machinery for going live.

### Phase 32: owner go-live handoff packet
The owner go-live handoff packet is a sanitized read-only export over launch readiness, settings change requests, settings execution preflight, owner approval packets, and approved action readiness. It does not apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, or set live owner-approved state.

1. Operator runs `vyro-growth owner-handoff-packet` or `GET /internal/owner-handoff-packet`. HTTP uses the same `INTERNAL_API_KEY` gate as other internal operator routes. CLI does not.
2. `OwnerHandoffPacketService` reuses existing read-only services. It does not write pipeline rows, apply settings, or change operator halt state.
3. Output is overall status, blocker/gate/approval codes, pending/approved/rejected counts, request IDs, packet IDs, candidate IDs, setting names, desired booleans/statuses, missing credential variable names, closed provider flag names, timestamps, and no-execution flags.
4. Secret values, PHI, emails, phones, message bodies, draft copy, evidence snippets, and unsafe error text are never included. `execution_allowed` and `go_live_permitted` remain false because a future explicitly approved execution phase does not exist.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called. This packet is for manual owner review only, not permission or machinery for going live.

### Phase 33: owner go-live handoff packet UI shell
The owner go-live handoff HTML page is a sanitized read-only shell over the Phase 32 packet. It does not apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, or set live owner-approved state.

1. Operator requests `GET /internal/operator-owner-handoff-packet`. The route uses the same `INTERNAL_API_KEY` gate as other internal operator routes.
2. The page calls `OwnerHandoffPacketService.build` through the existing JSON builder. It never writes pipeline rows or changes operator halt state.
3. The view shows the six handoff sections: launch readiness, settings change requests, settings execution preflight, owner approval packets, approved action readiness, and remaining manual owner checklist. Fields are statuses, counts, blocker/gate/approval codes, request IDs, packet IDs, candidate IDs, setting names, desired booleans/statuses, missing credential variable names, closed provider flag names, timestamps, and no-execution flags.
4. Rendered HTML never includes secret values, environment values, API keys, tokens, provider secrets, message bodies, draft copy, emails, phones, evidence snippets, PHI, or raw error text. There is no apply, execute, enable outbound, or lift-halt control.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. The page states `go_live_permitted=false` and `execution_allowed=false`. This is a read-only manual-review view, not permission or machinery for going live.

### Phase 34: operator activity audit timeline UI
The operator activity audit timeline is a sanitized read-only HTML view over existing activity, audit, and decision records. It does not create or mutate records, execute approved items, apply settings, lift halt, enable outbound, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, or set live owner-approved state.

1. Operator requests `GET /internal/operator-audit-timeline`. The route uses the same `INTERNAL_API_KEY` gate as other internal operator routes. Filters are read-only query parameters only.
2. `OperatorAuditTimelineService` reads stored `activities` plus review, approval-packet, and settings-change decision records. It never writes pipeline rows or changes operator halt state.
3. The view shows event type, sanitized actor/source labels, timestamps, status/decision, artifact/packet/request/candidate/run IDs, reason/code labels, and no-execution/read-only flags.
4. Rendered HTML never includes secret values, environment values, API keys, tokens, provider secrets, message bodies, draft copy, emails, phones, evidence snippets, PHI, or raw error text. There is no apply, execute, enable outbound, or lift-halt control.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. This is a read-only history view, not permission or machinery for going live.

### Phase 35: compliance evidence binder export
The compliance evidence binder is a sanitized read-only export over launch readiness, settings execution preflight, owner handoff, operator audit timeline, CI smoke/deploy-config gates, deployment safe defaults, and documented compliance guardrails. It does not apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, or set live owner-approved state.

1. Operator runs `vyro-growth compliance-evidence-binder` or `GET /internal/compliance-evidence-binder`. HTTP uses the same `INTERNAL_API_KEY` gate as other internal operator routes. CLI does not.
2. `ComplianceEvidenceBinderService` reuses existing read-only services and local file inspection. It does not write pipeline rows, apply settings, or change operator halt state.
3. Output is statuses, counts, codes, no-execution flags, operator halt status, outbound/live-provider flag states, CI gate names, route/command names, sanitized timestamps, and missing credential variable names.
4. Secret values, PHI, emails, phones, message bodies, draft copy, evidence snippets, and unsafe error text are never included. `execution_allowed` and `go_live_permitted` remain false because a future explicitly approved execution phase does not exist.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called. This binder is for manual owner review only, not permission or machinery for going live.

### Phase 36: compliance evidence binder UI shell
The compliance evidence binder HTML page is a sanitized read-only shell over the Phase 35 binder. It does not apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, deploy, or set live owner-approved state.

1. Operator requests `GET /internal/operator-compliance-evidence-binder`. The route uses the same `INTERNAL_API_KEY` gate as other internal operator routes.
2. The page calls `ComplianceEvidenceBinderService.build` through the existing JSON builder. It never writes pipeline rows or changes operator halt state.
3. The view shows every binder section: outbound disabled/operator halt, no-live-provider defaults, no-execution side-effect evidence, PHI/secrets/redaction evidence, consent-based phone-only boundary, CI dry-run smoke/deploy-config gates, documented compliance guardrails, operator audit timeline summary, reused read-only summaries, and remaining manual owner checklist. Fields are statuses, counts, codes, no-execution flags, halt/outbound/live-provider states, CI gate names, route/command names, sanitized timestamps, and missing credential variable names.
4. Rendered HTML never includes secret values, environment values, API keys, tokens, provider secrets, message bodies, draft copy, emails, phones, evidence snippets, PHI, or raw error text. There is no apply, execute, enable outbound, or lift-halt control.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. The page states `go_live_permitted=false`, `execution_allowed=false`, and `binder_is_not_go_live=true`. This is a read-only owner-review view, not permission or machinery for going live.

### Phase 37: release-candidate deployment runbook export
The release-candidate deployment runbook is a sanitized read-only planning export over launch readiness, settings execution preflight, owner handoff, compliance evidence binder, operator audit timeline, CI smoke/deploy-config gates, deployment safe defaults, and documented compliance guardrails. It does not deploy, apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, or set live owner-approved state.

1. Operator runs `vyro-growth release-candidate-runbook` or `GET /internal/release-candidate-runbook`. HTTP uses the same `INTERNAL_API_KEY` gate as other internal operator routes. CLI does not.
2. `ReleaseCandidateRunbookService` reuses existing read-only services and local file inspection. It does not write pipeline rows, apply settings, change operator halt state, or call GitHub Actions or deployment providers.
3. Output is statuses, counts, codes, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text. Deployment and rollback steps are instructions only.
4. Secret values, PHI, emails, phones, message bodies, draft copy, evidence snippets, and unsafe error text are never included. `execution_allowed`, `go_live_permitted`, and `deployment_allowed` remain false because a future explicitly approved execution/deployment phase does not exist.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called. This runbook is for future manual owner review only, not a deployment mechanism or permission to go live.

### Phase 38: release-candidate deployment runbook UI shell
The release-candidate runbook HTML page is a sanitized read-only shell over the Phase 37 runbook. It does not deploy, apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, or set live owner-approved state.

1. Operator requests `GET /internal/operator-release-candidate-runbook`. The route uses the same `INTERNAL_API_KEY` gate as other internal operator routes.
2. The page calls `ReleaseCandidateRunbookService.build` through the existing JSON builder. It never writes pipeline rows, changes operator halt state, or deploys.
3. The view shows every runbook section: release candidate identity and repo branch expectations, required CI gates and local dry-run verification commands, required safe environment defaults and missing credential variable names only, operator halt and outbound-disabled verification, manual deployment sequence as instructions only, rollback checklist as instructions only, post-deploy read-only verification endpoints/commands, documented guardrails, reused read-only summaries, and remaining unresolved blockers/manual owner checklist items. Fields are statuses, counts, codes, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text.
4. Rendered HTML never includes secret values, environment values, API keys, tokens, provider secrets, message bodies, draft copy, emails, phones, evidence snippets, PHI, or raw error text. There is no apply, execute, enable outbound, lift-halt, or deploy control.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. The page states `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, and `runbook_is_not_deployment=true`. This is a read-only owner-review view, not a deployment mechanism or permission to go live.

### Phase 39: release artifact manifest and provenance export
The release artifact manifest is a sanitized read-only owner-review export over release-candidate runbook, compliance evidence binder, launch readiness, settings execution preflight, owner handoff, operator audit timeline, CI smoke/deploy-config gates, deployment safe defaults, and documented compliance guardrails. It describes expected source/provenance, artifact paths, migration revision filenames/ids, runtime commands, and safety gates. It does not build containers, publish artifacts, deploy, apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, or set live owner-approved state.

1. Operator runs `vyro-growth release-artifact-manifest` or `GET /internal/release-artifact-manifest`. HTTP uses the same `INTERNAL_API_KEY` gate as other internal operator routes. CLI does not.
2. `ReleaseArtifactManifestService` reuses existing read-only services and local file inspection, including `.git` metadata when present. It does not write pipeline rows, apply settings, change operator halt state, call GitHub Actions or GitHub provider APIs, build containers, or publish artifacts.
3. Output is statuses, counts, codes, filenames, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text.
4. Secret values, PHI, emails, phones, message bodies, draft copy, evidence snippets, and unsafe error text are never included. `execution_allowed`, `go_live_permitted`, `deployment_allowed`, `build_allowed`, and `artifact_publish_allowed` remain false because a future explicitly approved execution/deployment/build phase does not exist.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called. This manifest is for owner/operator review only, not a build, artifact publishing, deployment mechanism, or permission to go live.

### Phase 40: release artifact manifest UI shell
The release artifact manifest HTML page is a sanitized read-only shell over the Phase 39 manifest. It does not build containers, publish artifacts, deploy, apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, or set live owner-approved state.

1. Operator requests `GET /internal/operator-release-artifact-manifest`. The route uses the same `INTERNAL_API_KEY` gate as other internal operator routes.
2. The page calls `ReleaseArtifactManifestService.build` through the existing JSON builder. It never writes pipeline rows, changes operator halt state, builds containers, publishes artifacts, or deploys.
3. The view shows every manifest section: source and provenance expectations, artifact inventory, migration inventory, runtime command inventory, safety gate inventory, no-build/no-deploy evidence, reused read-only summaries, and remaining unresolved blockers/manual owner checklist items. Fields are statuses, counts, codes, filenames, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text.
4. Rendered HTML never includes secret values, environment values, API keys, tokens, provider secrets, message bodies, draft copy, emails, phones, evidence snippets, PHI, or raw error text. There is no apply, execute, enable outbound, lift-halt, build, publish, or deploy control.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. The page states `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `build_allowed=false`, `artifact_publish_allowed=false`, `runbook_is_not_deployment=true`, and `manifest_is_not_a_build_or_deploy=true`. This is a read-only owner-review view, not a build, artifact publishing, deployment mechanism, or permission to go live.

### Phase 41: operator go-live readiness index UI
The go-live readiness index HTML page is a sanitized read-only index of existing owner/operator readiness, evidence, runbook, manifest, and audit surfaces. It does not build containers, publish artifacts, deploy, apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, or set live owner-approved state.

1. Operator requests `GET /internal/operator-go-live-readiness-index`. The route uses the same `INTERNAL_API_KEY` gate as other internal operator routes.
2. The page reuses existing read-only builders/summaries. It never writes pipeline rows, changes operator halt state, builds containers, publishes artifacts, deploys, or executes.
3. The view shows live-blocking flags, summary cards for all major readiness surfaces with statuses/counts/codes/route names/command names, and a manual owner checklist rollup. Fields are statuses, counts, codes, route names, command names, flag names/states, missing credential variable names, sanitized timestamps, and checklist labels.
4. Rendered HTML never includes secret values, environment values, API keys, tokens, provider secrets, message bodies, draft copy, emails, phones, evidence snippets, PHI, or raw error text. There is no apply, execute, enable outbound, lift-halt, build, publish, or deploy control.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. The page states `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `build_allowed=false`, `artifact_publish_allowed=false`, and that this is an index/review view only, not permission to go live and not an execution surface.

### Phase 42: go-live readiness index CLI and JSON export
The go-live readiness index CLI and JSON route are a sanitized read-only export of the Phase 41 index. They do not build containers, publish artifacts, deploy, apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, or set live owner-approved state.

1. Operator runs `vyro-growth go-live-readiness-index` or `GET /internal/go-live-readiness-index`. HTTP uses the same `INTERNAL_API_KEY` gate as other internal operator routes. CLI does not.
2. The export reuses `GoLiveReadinessIndexService` and `index_payload`. It never writes pipeline rows, changes operator halt state, builds containers, publishes artifacts, deploys, or executes.
3. Output is the same safe rollup as the HTML index: live-blocking flags, surface statuses/counts/codes/routes/commands, operator audit timeline counts, and the manual owner checklist rollup. Fields are statuses, counts, codes, route names, command names, flag names/states, missing credential variable names, sanitized timestamps, and checklist labels.
4. Secret values, PHI, emails, phones, message bodies, draft copy, evidence snippets, and unsafe error text are never included. `execution_allowed`, `go_live_permitted`, `deployment_allowed`, `build_allowed`, and `artifact_publish_allowed` remain false.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called. This export is for owner/operator review only, not permission to go live and not an execution surface.

### Phase 43: launch blockers remediation plan export
The launch blockers remediation plan CLI and JSON route are a sanitized read-only planning export of existing Phase 42 go-live readiness index blockers. They do not build containers, publish artifacts, deploy, apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, or set live owner-approved state.

1. Operator runs `vyro-growth launch-blockers-plan` or `GET /internal/launch-blockers-plan`. HTTP uses the same `INTERNAL_API_KEY` gate as other internal operator routes. CLI does not.
2. The export reuses `GoLiveReadinessIndexService` as the source of truth and does not duplicate readiness calculations. It never writes pipeline rows, changes operator halt state, builds containers, publishes artifacts, deploys, or executes.
3. Output is a deterministic remediation plan grouped by readiness surface or blocker category. Fields are blocker codes, surface keys/labels, current statuses, recommended manual remediation steps, owner approval types, step kinds, route names, command names, config names, sanitized timestamps, and counts.
4. Secret values, PHI, emails, phones, message bodies, draft copy, evidence snippets, and unsafe error text are never included. `execution_allowed`, `go_live_permitted`, `deployment_allowed`, `settings_applied`, `halt_changed`, and `owner_approved` remain false.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called. This export is a remediation planning export only, not permission to go live and not an execution surface.

### Phase 44: operator launch blockers remediation plan UI
The launch blockers remediation plan HTML page is a sanitized read-only shell over the existing Phase 43 plan. It does not build containers, publish artifacts, deploy, apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, or set live owner-approved state.

1. Operator requests `GET /internal/operator-launch-blockers-plan`. The route uses the same `INTERNAL_API_KEY` gate as other internal operator routes.
2. The page calls `LaunchBlockersPlanService` through the existing sanitized plan builder. It does not recalculate readiness, write pipeline rows, change operator halt state, build containers, publish artifacts, deploy, or execute.
3. The view shows overall status, generated timestamp, read-only / no-execution / no-go-live flags, operator halt before/after, outbound/live-provider/deployment/build/publish permission flags, source go-live readiness index references, related safe routes and CLI commands, grouped remediation steps, blocker codes, missing credential names, closed provider flag names, and safe local git metadata.
4. Rendered HTML never includes secret values, environment values, API keys, tokens, provider secrets, message bodies, draft copy, emails, phones, evidence snippets, PHI, or raw error text. There is no apply, execute, enable outbound, lift-halt, build, publish, or deploy control.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. The page states `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, and that this is a remediation planning view only, not permission to go live and not an execution surface.

### Phase 45: staged go-live rollout plan export
The staged go-live rollout plan CLI and JSON route are a sanitized read-only planning export over existing readiness, blocker, binder, runbook, manifest, and launch-readiness surfaces. They do not build containers, publish artifacts, deploy, apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, or set live owner-approved state.

1. Operator runs `vyro-growth staged-rollout-plan` or `GET /internal/staged-rollout-plan`. HTTP uses the same `INTERNAL_API_KEY` gate as other internal operator routes. CLI does not.
2. The export reuses `GoLiveReadinessIndexService`, `LaunchBlockersPlanService`, `LaunchReadinessService`, `ComplianceEvidenceBinderService`, `ReleaseCandidateRunbookService`, and `ReleaseArtifactManifestService` as source material and does not duplicate readiness calculations. It never writes pipeline rows, changes operator halt state, builds containers, publishes artifacts, deploys, or executes.
3. Output is a deterministic staged plan: stage 0 safe defaults and operator halt verification; stage 1 credential/configuration preparation by variable name only; stage 2 local dry-run verification and CI gates; stage 3 owner review of packets/checklists/readiness surfaces; stage 4 future manual deployment preparation only; stage 5 future owner-approved live enablement prerequisites only. Fields are stage keys/labels, statuses, blocker/gate codes, owner approval types, checklist labels, route names, command names, config names, sanitized timestamps, and counts.
4. Secret values, PHI, emails, phones, message bodies, draft copy, evidence snippets, and unsafe error text are never included. `execution_allowed`, `go_live_permitted`, `deployment_allowed`, `settings_applied`, `halt_changed`, and `owner_approved` remain false.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called. This export is a staged rollout planning export only, not permission to go live and not an execution surface.

### Phase 46: operator staged go-live rollout plan UI
The staged go-live rollout plan HTML page is a sanitized read-only shell over the existing Phase 45 plan. It does not build containers, publish artifacts, deploy, apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, or set live owner-approved state.

1. Operator requests `GET /internal/operator-staged-rollout-plan`. The route uses the same `INTERNAL_API_KEY` gate as other internal operator routes.
2. The page calls `StagedRolloutPlanService` through the existing sanitized plan builder. It does not recalculate readiness, write pipeline rows, change operator halt state, build containers, publish artifacts, deploy, or execute.
3. The view shows overall status, generated timestamp, read-only / no-execution / no-go-live flags, operator halt before/after, outbound/live-provider/deployment/build/publish permission flags, source references for the readiness index, launch blockers plan, launch readiness, compliance binder, runbook, and manifest, related safe routes and CLI commands, stages 0-5, blocker/gate codes, missing credential names, closed provider flag names, and safe local git metadata.
4. Rendered HTML never includes secret values, environment values, API keys, tokens, provider secrets, message bodies, draft copy, emails, phones, evidence snippets, PHI, or raw error text. There is no apply, execute, enable outbound, lift-halt, build, publish, or deploy control.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. The page states `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `staged_rollout_plan_is_not_go_live=true`, and that this is a staged rollout planning view only, not permission to go live and not an execution surface.

### Phase 47: owner launch dossier export
The owner launch dossier CLI and JSON route are a sanitized read-only review export over existing readiness, blocker, staged-rollout, handoff, binder, runbook, manifest, settings-preflight, and audit surfaces. They do not build containers, publish artifacts, deploy, apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, or set live owner-approved state.

1. Operator runs `vyro-growth owner-launch-dossier` or `GET /internal/owner-launch-dossier`. HTTP uses the same `INTERNAL_API_KEY` gate as other internal operator routes. CLI does not. HTTP responses return `Cache-Control: no-store`.
2. The export reuses `StagedRolloutPlanService`, `OwnerHandoffPacketService`, `SettingsExecutionPreflightService`, and `OperatorAuditTimelineService` as source material and does not duplicate readiness calculations. It never writes pipeline rows, changes operator halt state, builds containers, publishes artifacts, deploys, or executes.
3. Output is a deterministic owner packet: generated timestamp, packet kind/purpose, overall status rollup, live-blocking flags, operator halt before/after, source references, blocker/gate code rollups, missing credential names, safe route/CLI inventory, safe local git metadata, settings-preflight and operator-audit summaries, and a concise non-executable next-action list.
4. Secret values, PHI, emails, phones, message bodies, draft copy, evidence snippets, and unsafe error text are never included. `execution_allowed`, `go_live_permitted`, `deployment_allowed`, `settings_applied`, `halt_changed`, and `owner_approved` remain false.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called. This export is a review export only, not permission to go live and not an execution surface.

### Phase 48: operator owner launch dossier UI
The owner launch dossier HTML page is a sanitized read-only shell over the existing Phase 47 dossier. It does not build containers, publish artifacts, deploy, apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, or set live owner-approved state.

1. Operator requests `GET /internal/operator-owner-launch-dossier`. The route uses the same `INTERNAL_API_KEY` gate as other internal operator routes.
2. The page calls `OwnerLaunchDossierService` through the existing sanitized dossier builder. It does not recalculate readiness, write pipeline rows, change operator halt state, build containers, publish artifacts, deploy, or execute.
3. The view shows overall status, generated timestamp, packet kind and purpose, read-only / no-execution / no-go-live / no-deployment flags, operator halt before/after, outbound/live-provider/deployment/build/publish permission flags, source references for each included surface, blocker and gate code rollups, missing credential names, related safe routes and CLI commands, safe local git metadata, settings-preflight and operator-audit summaries, and a non-executable owner next-action summary.
4. Rendered HTML never includes secret values, environment values, API keys, tokens, provider secrets, message bodies, draft copy, emails, phones, evidence snippets, PHI, or raw error text. There is no apply, execute, enable outbound, lift-halt, build, publish, or deploy control.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. The page states `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `owner_launch_dossier_is_not_go_live=true`, and that this is a launch dossier review view only, not permission to go live and not an execution surface.

### Phase 49: provider credential/setup checklist export
The provider setup checklist CLI and JSON route are a sanitized read-only planning export over existing launch-readiness, go-live index, launch-blocker, staged-rollout, owner-launch-dossier, settings-preflight, and release-candidate runbook surfaces. They do not build containers, publish artifacts, deploy, apply settings, lift halt, enable outbound, execute requests, packets, or approved items, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish content, launch ads, spend money, or set live owner-approved state.

1. Operator runs `vyro-growth provider-setup-checklist` or `GET /internal/provider-setup-checklist`. HTTP uses the same `INTERNAL_API_KEY` gate as other internal operator routes. CLI does not. HTTP responses return `Cache-Control: no-store`.
2. The export reuses `OwnerLaunchDossierService` and `LaunchReadinessService` as source material and does not duplicate readiness calculations. It never writes pipeline rows, changes operator halt state, builds containers, publishes artifacts, deploys, or executes.
3. Output is a deterministic provider setup checklist: generated timestamp, packet kind/purpose, overall status rollup, live-blocking flags, operator halt before/after, missing credential names, closed provider/live flag names, provider setup categories with required owner approval types, blocker/gate code rollups, safe route/CLI inventory, safe local git metadata, local verification gates, and a concise non-executable next-action list.
4. Secret values, PHI, emails, phones, message bodies, draft copy, evidence snippets, and unsafe error text are never included. `execution_allowed`, `go_live_permitted`, `deployment_allowed`, `settings_applied`, `halt_changed`, and `owner_approved` remain false.
5. Operator halt is read and left unchanged. `OUTBOUND_ENABLED` remains false by default. No live provider is called. This export is a planning/export layer only, not permission to go live and not an execution surface.

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
