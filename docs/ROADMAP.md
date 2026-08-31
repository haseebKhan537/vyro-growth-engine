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

## Phase 19 — Operator command center summary
Sanitized read-only operator summary only. No live action.
- aggregation over existing safe pipeline artifacts: discovery/enrichment/scoring, personalization drafts, outreach dry-run plans, reply follow-up plans, booking plans, consent-based voice plans, optimizer recommendations, acquisition channel plans, content briefs, execution plans, owner approval packets, review queue, and monitoring
- internal `GET /internal/operator-command-center` and CLI `operator-command-center`
- counts, latest run statuses, readiness, blocked/warning/info summaries, outstanding review counts, approval packet counts, and safe next-action labels
- IDs, statuses, counts, timestamps, and redacted labels only; no PHI, emails, phones, message bodies, draft copy, evidence snippets, secrets, or unsafe error text
- no email, enrollment, autonomous replies, calendar events, Meet links, calls, publish, ads, spend, deploy, optimizer apply, or live/scoring/campaign/provider setting changes

Future command-center work (not in this phase):
- execute an approved live action from the summary
- change operator halt, outbound, or live-provider flags

## Phase 20 — Read-only operator dashboard UI shell
Internal HTML view over the sanitized command-center summary. No live action.
- one internal `GET /internal/operator-dashboard` route that server-renders the Phase 19 summary
- overall status/readiness, outbound-disabled and operator-halt safety, pipeline counts, latest run statuses, outstanding review counts, approval packet/preflight counts, blocked/warning/info summary, and safe next-action labels
- quiet, dense, operator-focused layout with empty and failure states
- navigation/filter query only; no execute, send, enroll, book, call, publish, spend, or deploy controls
- same `INTERNAL_API_KEY` gate as other internal operator routes
- no PHI, emails, phones, message bodies, draft copy, evidence snippets, secrets, or unsafe error text in rendered HTML

Future dashboard-UI work (not in this phase):
- richer visualization or additional operator surfaces
- execute an approved live action from the UI
- change operator halt, outbound, or live-provider flags

## Phase 21 — Read-only review queue and approval packet UI drilldowns
Internal HTML list/detail views over the existing review queue and owner approval packets. No live action.
- `GET /internal/operator-review-queue` and artifact detail pages for pending and decided dry-run review items
- `GET /internal/operator-approval-packets` and packet detail pages for owner approval/preflight rows
- dashboard links to the drilldowns
- read-only filters: artifact type, status, include-decided, plan family, and preflight status
- empty states and sanitized failure/not-found pages
- same `INTERNAL_API_KEY` gate as other internal operator routes
- IDs, statuses, timestamps, safe titles/labels/categories, blocked/warning/info counts and codes, required owner decision labels, and dry-run/no-execution flags only

## Phase 22 — Operator review decision UI forms
Internal HTML decision-record form on review-item detail pages. No execution.
- `POST /internal/operator-review-queue/{artifact_type}/{artifact_id}/decision` records `approved`, `rejected`, or `needs_changes`
- optional short reviewer label and reviewer notes, sanitized/redacted before persist and render
- reuses the existing review-queue decision service and unique decision row
- POST-redirect-GET plus identical-payload short-circuit so refresh/double-submit does not create extra side effects
- success/error HTML is sanitized high-level decision metadata only
- no execute controls; operator halt is unchanged
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 23 — Owner approval packet decision UI
Internal HTML decision-record form on approval-packet detail pages. No execution.
- `POST /internal/operator-approval-packets/{packet_id}/decision` records `approved`, `rejected`, or `needs_changes`
- optional short owner/reviewer label and notes, sanitized/redacted before persist and render
- reuses/extends the existing approval-packet service with a decision-record-only path and unique decision row
- POST-redirect-GET plus identical-payload short-circuit so refresh/double-submit does not create extra side effects
- success/error HTML is sanitized high-level decision metadata only
- recording `approved` does not execute the packet or set live `owner_approved`
- approval-packet list pages and review-queue decision UI stay as they are
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 24 — Approved action readiness queue
Internal read-only queue over stored review decisions, execution plans, approval packets, and packet decision records. No execution.
- Combine existing records only; do not generate new outreach, packets, plans, or content
- JSON `GET /internal/action-readiness` and HTML `GET /internal/operator-action-readiness`
- candidates include approved review items with matching execution plans and approval packets
- explicit statuses: `blocked`, `missing_review_decision`, `missing_owner_packet_decision`, `preflight_blocked`, `approved_but_halted`, `ready_pending_explicit_live_owner_action`
- a ready-like status still requires a future explicit owner action before live execution
- filters: plan family, readiness status, blocker status, and review decision status
- dashboard and command-center links to the queue
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 25 — End-to-end dry-run smoke harness
Local-only dry-run smoke/demo command over deterministic synthetic fixture data. No live workflow.
- CLI `vyro-growth smoke-dry-run` (`--local-only` / `--dev-demo` required outside development)
- isolated in-memory demo database; does not write to `DATABASE_URL`
- seeds a synthetic practice/lead and safe public-business facts with no PHI
- exercises existing scoring, personalization, outreach, reply, booking, voice, optimizer, channel, content, review, execution-plan, approval-packet, and action-readiness services
- records operator review and approval-packet decisions only; does not execute or set live `owner_approved`
- sanitized console/JSON summary with counts, statuses, blocker codes, readiness statuses, `executed=0`, `live_action=false`, and `outbound_attempted=false`
- refuses production/live runs unless `--local-only`/`--dev-demo` is present; still refuses when `OUTBOUND_ENABLED` or a live-provider flag is true
- no NPPES/search/Apollo/campaign/AI/calendar/voice/ad/SEO provider calls, email, enrollment, calls, bookings, publish, ads, spend, or deploy

## Phase 26 — CI dry-run smoke gate
CI coverage for the Phase 25 local-only smoke harness. No live workflow.
- GitHub Actions job `smoke-dry-run` runs `vyro-growth smoke-dry-run --local-only --json` after dependency install
- CI sets `OUTBOUND_ENABLED=false` and every live-provider flag false; unsets `DATABASE_URL` and provider credentials
- helper CLI `vyro-growth check-smoke-output` fails the job when JSON is missing no-execution signals or includes forbidden sensitive values
- required signals: `executed=0`, `live_action=false`, `outbound_attempted=false`, `owner_approved=false`, `dry_run_only=true`, `no_execution=true`, `isolated_demo_database=true`
- fails closed on PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, unsafe raw errors, or invented real-world prospect facts
- does not call live providers, use real prospect data, execute approved items, or change operator halt / live settings

## Phase 27 — Launch readiness checklist and sanitized secret inventory
Read-only owner-facing preflight. No live action.
- CLI `vyro-growth launch-readiness` (`--json` optional) and internal `GET /internal/launch-readiness`
- overall status: `blocked` / `warning` / `ready_for_owner_review`
- blocker codes and next-action labels
- required configuration names only; secret inventory is variable names plus present/missing/redacted status
- operator halt, outbound/live-provider flags, documented CI smoke gate, pending owner approval packet counts, and action-readiness blocker counts
- unsafe outbound/live flags, missing required credentials, unavailable halt, and a missing smoke gate are blocked; halt-active, pending packets, and remaining readiness blockers are warnings
- no GitHub Actions, OpenAI, NPPES/search, Apollo, Smartlead, Google, calendar, voice, ads, SEO, analytics, or other live-provider calls
- no email, enrollment, autonomous replies, calls, bookings, Meet links, publish, ads, spend, deploy, packet/item execution, live `owner_approved`, or halt/live setting changes

## Phase 28 — Live settings change request queue
Record-only owner-reviewable live settings change requests. No execution.
- Database-backed request records with timestamps, statuses, idempotency keys, requested setting names, desired booleans/statuses, and optional launch-readiness finding/next-action codes
- CLI list/create/detail/decision plus `vyro-growth propose-settings-changes`; internal JSON under `/internal/settings-change-requests`
- request types: keep outbound disabled, outbound enablement review, one live-provider flag review, operator halt review, required credential configuration review by name only, and keep-safe-default notes
- never stores or prints secret values; credential requests name env/config variables only
- owner decision records are audit-only and do not apply settings, lift halt, execute packets/items, or trigger live actions
- launch readiness points at proposed requests and can optionally create them without applying anything
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 29 — Settings change request UI drilldowns
Internal operator HTML list/detail for Phase 28 live settings change requests. Record-only, no execution.
- `GET /internal/operator-settings-change-requests` and `GET /internal/operator-settings-change-requests/{request_id}`
- optional `POST /internal/operator-settings-change-requests/{request_id}/decision` records the existing audit-only owner decision
- sanitized fields only: request type, status, owner decision status, setting names, desired boolean/status, finding/next-action codes, timestamps, source, record-only/no-execution flags, and safe counts
- linked from the operator dashboard, command-center next-action labels, and launch-readiness next-action labels
- decision forms never apply settings, lift halt, enable outbound, execute requests, or set live `owner_approved`
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 30 — Approved settings execution preflight simulator
Dry-run-only simulator over recorded settings change requests and owner decisions. No execution.
- Service plus CLI `vyro-growth settings-execution-preflight` and internal JSON `GET /internal/settings-execution-preflight`
- Scans settings change requests and recorded decisions
- Sanitized output only: request IDs, request types, decision status, setting names, desired booleans/statuses, blocker/gate codes, timestamps, counts, and no-execution flags
- Reports blockers such as operator halt, outbound disabled, provider live flags false, missing credentials by variable name only, pending/rejected/needs_changes decisions, missing approval-packet decision, or absent explicit owner approval
- All live execution gates remain closed; `execution_allowed` is false unless a future explicitly approved execution phase exists
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 31 — Settings execution preflight UI shell
Internal operator HTML view of the Phase 30 dry-run simulator. Read-only, no execution.
- `GET /internal/operator-settings-execution-preflight`
- Renders existing Phase 30 preflight output as a sanitized HTML page
- Optional read-only filters: request type, decision status, execution status
- Linked from the operator dashboard, command-center next-action labels, launch-readiness next-action labels, and settings change request UI
- Sanitized fields only: overall status, request/decision counts, blocker/gate/approval codes, missing credential variable names, closed provider flag names, request IDs/types, decision status, desired booleans/statuses, timestamps, and no-execution flags
- No apply/execute/lift-halt/enable-outbound/provider/deploy/campaign/booking/call/publish/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 32 — Owner go-live handoff packet export
Read-only owner-review packet consolidating existing safe summaries. No execution.
- Service plus CLI `vyro-growth owner-handoff-packet` and internal JSON `GET /internal/owner-handoff-packet`
- Reuses launch readiness, settings change requests, settings execution preflight, owner approval packets, and approved action readiness
- Sections: launch readiness, settings change request summary, settings execution preflight summary, owner approval packet summary, approved action readiness summary, remaining manual owner checklist
- Sanitized metadata only: overall status, blocker/gate/approval codes, pending/approved/rejected counts, request IDs, packet IDs, candidate IDs, setting names, desired booleans/statuses, missing credential variable names, closed provider flag names, timestamps, and no-execution flags
- `execution_allowed=false` and `go_live_permitted=false`; this packet is not permission or machinery for going live
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 33 — Owner go-live handoff packet UI shell
Internal operator HTML view of the Phase 32 owner go-live handoff packet. Read-only, no execution.
- `GET /internal/operator-owner-handoff-packet`
- Renders existing Phase 32 handoff packet as a sanitized HTML page
- Linked from the operator dashboard, command-center next-action labels, launch-readiness next-action labels, settings change request UI, and settings execution preflight UI
- Shows all six handoff sections: launch readiness, settings change requests, settings execution preflight, owner approval packets, approved action readiness, and remaining manual owner checklist
- Sanitized fields only: overall status, blocker/gate/approval codes, pending/approved/rejected counts, request IDs, packet IDs, candidate IDs, setting names, desired booleans/statuses, missing credential variable names, closed provider flag names, timestamps, and no-execution flags
- Page states `go_live_permitted=false`, `execution_allowed=false`, and manual-review-only/no-execution semantics
- No apply/execute/lift-halt/enable-outbound/provider/deploy/campaign/booking/call/publish/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 34 — Operator activity audit timeline UI
Internal operator HTML timeline over existing activity, audit, and decision records. Read-only, no execution.
- `GET /internal/operator-audit-timeline`
- Chronological sanitized entries from stored `activities` plus review, approval-packet, and settings-change decision records
- Safe metadata only: event type, source surface, actor/source labels, timestamps, status/decision, artifact/packet/request/candidate/run IDs, reason/code labels, and no-execution/read-only flags
- Read-only filters: event type, source, status/decision, and date window (`all`, `24h`, `7d`, `30d`)
- Linked from the operator dashboard, command-center next-action labels, launch-readiness next-action labels, and owner handoff packet UI
- No apply/execute/lift-halt/enable-outbound/provider/deploy/campaign/booking/call/publish/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 35 — Compliance evidence binder export (current)
Read-only owner-review binder consolidating existing safety evidence. No execution.
- Service plus CLI `vyro-growth compliance-evidence-binder` and internal JSON `GET /internal/compliance-evidence-binder`
- Reuses launch readiness, settings execution preflight, owner handoff packet, operator audit timeline, smoke gate expectations, deployment safe defaults, and documented compliance guardrails
- Sections: outbound disabled/operator halt, no-live-provider defaults, no-execution side-effect evidence, PHI/secrets/redaction evidence, consent-based phone-only boundary, CI dry-run smoke/deploy-config gates, operator audit timeline, open manual owner checklist
- Safe evidence only: status/counts/codes, no-execution flags, operator halt status, outbound/live-provider flag states, CI gate names, route/command names, sanitized timestamps, and missing credential variable names
- `execution_allowed=false`, `go_live_permitted=false`, and `binder_is_not_go_live=true`; this binder is not permission or machinery for going live
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes

Future launch work (not in this phase):
- execute an approved item, packet, or settings request
- enable outbound or live providers
- lift operator halt
- call GitHub Actions or live providers
