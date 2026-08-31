# Vyro Growth Engine Roadmap

## Definition of success
A qualified decision-maker at a US medical practice expresses genuine interest in Vyro Medical Billing and a meeting is automatically booked on the Vyro calendar with a Google Meet link.

## Phase 1 — Production foundation
- FastAPI service
- PostgreSQL/Supabase-compatible schema
- Alembic migrations
- lead lifecycle state machine
- suppression model
- global outbound kill switch
- audit/activity model
- provider interfaces
- worker abstraction
- structured logging
- Docker and local development stack
- tests and CI

## Phase 2 — Practice discovery
- NPPES organization discovery
- CMS/NPI normalization
- deduplication
- specialty/location targeting
- discovery scheduling
- source evidence retention

## Phase 3 — Research and enrichment
- deterministic local lead scoring from existing organization/evidence fields (no external providers)
- official website resolution with verified / ambiguous / no-match outcomes
- conservative public-page fetch adapter (timeout, rate limit, portal/PHI path blocks)
- provider count, location, contact, and ownership-signal extraction
- billing/revenue-cycle signals only when explicitly stated
- evidence-backed enrichment only, with source URL, confidence, timestamp, and snippet
- confidence scoring
- decision-maker/contact enrichment provider foundation (stub only; no live paid provider, no outreach)

## Phase 4 — Advanced ICP qualification
- explainable deterministic scoring from stored NPPES, website, contact, and public-business evidence
- score bands: HOT, HIGH, MEDIUM, LOW, RESEARCH, DISQUALIFIED
- positive and negative reason codes linked to stored source evidence
- graceful handling of missing, ambiguous, and conflicting facts
- idempotent reruns with no outbound side effects
- live paid contact adapter remains future work (not started; no credentials required)

## Phase 5 — Evidence-grounded personalization
- provider interface plus deterministic stub for CI/local dry-run drafts
- guarded OpenAI adapter boundary with structured JSON schema (disabled by default; no live key required)
- prompt/schema version audit metadata, token/cost limit placeholders, retry/backoff for future live calls
- persistence for personalization drafts with evidence references and idempotent reruns
- no invented practice facts; unknown stays unknown
- outbound remains disabled; no email, calls, calendar, or enrollment
- specialty experiments and lead budget allocation remain future work

## Phase 6 — Autonomous email outreach
- Smartlead provider interface plus deterministic stub (dry-run enrollment planning; no live send)
- guarded live Smartlead adapter boundary, disabled by default and not used in CI
- campaign/enrollment persistence with idempotent reruns
- suppression checks for email, domain, and organization
- operator halt / `OUTBOUND_ENABLED` enforcement before any live outbound-like action
- cadence engine, bounce/unsubscribe webhooks, and live campaign enrollment remain future work

## Phase 7 — Reply classification foundation
Dry-run inbound classification only. No autonomous replies, booking, or calls.
- reply classifier provider interface plus deterministic rule stub
- guarded OpenAI boundary disabled by default and unused in CI
- structured intents: interested, not interested, unsubscribe, wrong person, out of office, referral, needs more info, meeting request, hostile, spam, unknown
- persisted classifications with content-hash / provider-id / message idempotency
- conservative lead/conversation transitions using the existing state machine
- explicit unsubscribe creates or confirms suppression records
- audit rows for classified, skipped, suppressed, blocked, unknown, and failed replies
- CLI `classify-replies` and worker job `classify_inbound_replies`

Future reply-agent work (not in this phase):
- inbound webhook processing
- autonomous replies for approved classes
- escalation rules
- pricing/information/objection handling that sends mail

## Phase 8 — Calendar and Google Meet booking foundation
Dry-run booking plans only. No calendar events, Google Meet links, email, or calls.
- booking/calendar provider interface plus deterministic stub
- guarded Google Calendar / Meet adapter boundary, disabled by default and unused in CI
- persisted booking plans with proposed slots, requested window, and idempotency
- accept only stored `meeting_request` replies or operator-created booking requests
- conservative lead transitions using `ALLOWED_TRANSITIONS`; never `meeting_booked`
- suppression, `OUTBOUND_ENABLED=false`, and persistent operator halt preserved
- CLI `plan-booking` and worker job `plan_booking_slots`

Future setter work (not in this phase):
- live Google Calendar availability
- recheck before booking
- Google Meet creation
- attendee invitation
- meeting brief generation

## Phase 9 — Consent-based voice qualification foundation
Dry-run voice qualification plans only. No calls, email, meetings, or campaign enrollment.
- voice qualification provider interface plus deterministic stub
- guarded live voice adapter boundary, disabled by default and unused in CI
- persisted voice qualification plans with consent proof and idempotency
- accept only explicit consent contexts: inbound call-request replies, operator requests with consent proof, or stored meeting/booking permission
- store only safe B2B qualification facts; block suspected PHI
- suppression, `OUTBOUND_ENABLED=false`, and persistent operator halt preserved
- CLI `plan-voice-qualification` and worker job `plan_voice_qualifications`

Future voice-agent work (not in this phase):
- live call placement
- transcript and summary
- meeting scheduling from a call
- cold AI robocalling remains forbidden

## Phase 10 — Operator dashboard foundation
Read-only analytics over existing pipeline state. No outbound, booking, or live provider actions.
- internal dashboard summary and safety endpoints
- phase-by-phase counts and latest run status
- safety cards: `OUTBOUND_ENABLED`, operator halt, live-provider flags, planned/skipped/suppressed/blocked counts
- CLI `dashboard-summary`
- no polished frontend in this phase

Future dashboard work (not in this phase):
- funnel visualization
- qualified-meeting and cost-per-meeting reporting
- campaign/source performance charts
- suppression search UI
- agent/audit timeline UI

## Phase 11 — Growth optimizer foundation
Dry-run operator-review recommendations only. No automatic campaign, scoring, provider, calendar, or voice changes.
- deterministic optimizer over stored dashboard/pipeline aggregates
- persisted idempotent optimizer runs and recommendation drafts
- categories: ICP thresholds, specialty/geography signals, enrichment and personalization gaps, outreach/reply patterns, booking/voice bottlenecks, safety flags
- every recommendation includes category, priority, confidence, rationale, source metrics, generated timestamp, and `pending_operator_review`
- CLI `recommend-growth`, worker job `generate_growth_recommendations`, and internal HTTP run/list routes
- no live AI or paid/external provider calls

Future optimizer work (not in this phase):
- experiment framework
- messaging tests
- spend allocation
- meeting/client conversion feedback
- operator-approved apply/rollback of a recommendation

## Phase 12 — Production deployment foundation
Deployable and operable without live outbound or paid-provider traffic.
- production-safe Dockerfile and Compose ops profiles
- fail-closed runtime validation for missing internal/security settings
- `/health` liveness and `/ready` readiness probes
- worker catalog, `check-config`, and startup/runbook documentation
- backup/restore and rollback expectations
- CI validation of container/compose configuration (no secrets, no live calls)

Future deployment work (not in this phase):
- managed PostgreSQL/Supabase provisioning
- secret-manager wiring beyond environment variables
- automated off-site backups
- staged outbound rollout after explicit owner approval

## Phase 13 — Observability and audit monitoring foundation
Operator-visible health over existing runs and activities. No live outbound.
- structured operational summaries of latest job/run status by phase
- sanitized recent failures and activity action counts
- safety status: operator halt, `OUTBOUND_ENABLED`, live-provider flags
- Phase 12 readiness/config status and pending operator-review counts
- findings with severity `blocked`, `warning`, or `info`
- CLI `system-status` and internal `GET /internal/monitoring/status`
- operator health-check docs before any manual rollout

Future observability work (not in this phase):
- paging/alerting integrations
- long-retention metrics backends
- public status pages

## Phase 14 — Operator review queue foundation
Recorded operator decisions only. No outbound execution.
- one review queue over pending dry-run artifacts: personalization drafts, outreach enrollment plans, reply follow-up classifications, booking plans, voice qualification plans, optimizer recommendations, and acquisition channel plans
- normalized review items with artifact type/id, safe lead/organization references, title/summary, status, timestamp, risk labels, and executable-later (not executed)
- persisted `approved` / `rejected` / `needs_changes` decisions with reviewer notes and timestamps
- CLI `review-queue` / `record-review` and internal HTTP list/decision routes
- sanitized output; approval is a recorded decision, not execution

Future review-queue work (not in this phase):
- execute an approved outreach enrollment
- generate or send an approved reply
- create an approved calendar event or Meet link
- place an approved consent-based call
- apply an approved optimizer recommendation
- launch an approved acquisition channel plan

## Phase 15 — Acquisition channel planning foundation
Dry-run channel plans only. No campaign launch, page publish, or spend.
- deterministic plans from stored specialty/geography aggregates and explicit operator seed inputs
- channels: Google Search Ads keyword-group concepts, SEO/content/landing-page topics, referral/partner ideas, specialty/geography positioning
- persisted idempotent channel-plan runs with `pending_operator_review`, dry-run/no-spend flags, and source metric or seed references
- CLI `plan-acquisition-channels` / `list-channel-plans`, worker job `generate_channel_plans`, and internal HTTP run/list routes
- review-queue enrollment as `acquisition_channel_plan`; approval remains record-only
- no live ad, SEO, search, analytics, or paid-provider calls

Future channel work (not in this phase):
- live Google Ads campaign creation or spend
- publishing landing pages or SEO content
- inbound forms
- retargeting
- partner outreach

## Phase 16 — Landing page brief and SEO content draft foundation
Review-only content planning. No publishing, ads, spend, or prospect contact.
- deterministic briefs from stored aggregate ICP signals, pending Phase 15 channel plans, and explicit safe operator seeds
- brief types: specialty landing page, geography landing page, Google Ads landing page concept, SEO article outline, referral/partner page concept
- persisted idempotent brief runs with source references, compliance notes, and `pending_operator_review`
- CLI `draft-content-briefs` / `list-content-briefs`, worker job `generate_content_briefs`, and internal HTTP generate/list routes
- review-queue and monitoring integration; approval remains decision-recording only
- no OpenAI, Google Ads, Search Console, Analytics, SEO, or search API calls

Future content work (not in this phase):
- publish a landing page or article
- launch Google Ads or spend budget
- generate full page/article copy
- contact prospects from a brief

## Phase 17 — Approved-item execution plan foundation
Dry-run execution plans only. No live action.
- deterministic plans from approved operator review decisions and sanitized artifact metadata
- artifact types: personalization drafts, outreach enrollment plans, reply follow-up classifications, booking plans, voice qualification plans, optimizer recommendations, acquisition channel plans, and content briefs
- persisted idempotent execution-plan runs with prerequisites, blockers, safety notes, required owner approvals, and dry-run/no-execution flags
- CLI `plan-approved-execution` / `list-execution-plans`, worker job `generate_execution_plans`, and internal HTTP run/list routes
- non-approved artifacts are ignored; approval still does not execute
- no email, enrollment, autonomous replies, calendar events, Meet links, calls, publish, ads, spend, deploy, or optimizer apply

Future execution work (not in this phase):
- execute an approved outreach enrollment
- generate or send an approved reply
- create an approved calendar event or Meet link
- place an approved consent-based call
- apply an approved optimizer recommendation
- launch an approved acquisition channel plan
- publish an approved content brief

## Phase 18 — Live-readiness preflight and owner approval packets
Approval/readiness planning only. No live action.
- deterministic preflight over dry-run execution plans and safe local/config metadata
- plan families: outreach enrollment, reply follow-up, booking, consent-based voice, optimizer apply, channel launch, content publish, and personalization draft review
- persisted idempotent owner approval packets with preflight checklist, missing prerequisites, blocked/warning/info findings, required owner decisions, and dry-run/no-execution flags
- CLI `generate-approval-packets` / `list-approval-packets`, worker job `generate_approval_packets`, and internal HTTP run/list routes
- secret presence is reported as boolean only; secret values are never printed
- no email, enrollment, autonomous replies, calendar events, Meet links, calls, publish, ads, spend, deploy, or optimizer apply

Future live-readiness work (not in this phase):
- execute an approved outreach enrollment
- generate or send an approved reply
- create an approved calendar event or Meet link
- place an approved consent-based call
- apply an approved optimizer recommendation
- launch an approved acquisition channel plan
- publish an approved content brief

## Phase 19 — Operator command center summary (current)
Sanitized read-only operator summary only. No live action.
- aggregation over existing safe pipeline artifacts: discovery/enrichment/scoring, personalization drafts, outreach dry-run plans, reply follow-up plans, booking plans, consent-based voice plans, optimizer recommendations, acquisition channel plans, content briefs, execution plans, owner approval packets, review queue, and monitoring
- internal `GET /internal/operator-command-center` and CLI `operator-command-center`
- counts, latest run statuses, readiness, blocked/warning/info summaries, outstanding review counts, approval packet counts, and safe next-action labels
- IDs, statuses, counts, timestamps, and redacted labels only; no PHI, emails, phones, message bodies, draft copy, evidence snippets, secrets, or unsafe error text
- no email, enrollment, autonomous replies, calendar events, Meet links, calls, publish, ads, spend, deploy, optimizer apply, or live/scoring/campaign/provider setting changes

Future command-center work (not in this phase):
- polished frontend
- execute an approved live action from the summary
- change operator halt, outbound, or live-provider flags
