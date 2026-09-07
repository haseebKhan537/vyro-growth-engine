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
- decision-maker/contact enrichment provider foundation (stub default; guarded live people-search adapter disabled and unused in CI)
- sanitized contact-enrichment hit-rate metrics (counts/rates only; no live sending)

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

## Phase 35 — Compliance evidence binder export
Read-only owner-review binder consolidating existing safety evidence. No execution.
- Service plus CLI `vyro-growth compliance-evidence-binder` and internal JSON `GET /internal/compliance-evidence-binder`
- Reuses launch readiness, settings execution preflight, owner handoff packet, operator audit timeline, smoke gate expectations, deployment safe defaults, and documented compliance guardrails
- Sections: outbound disabled/operator halt, no-live-provider defaults, no-execution side-effect evidence, PHI/secrets/redaction evidence, consent-based phone-only boundary, CI dry-run smoke/deploy-config gates, operator audit timeline, open manual owner checklist
- Safe evidence only: status/counts/codes, no-execution flags, operator halt status, outbound/live-provider flag states, CI gate names, route/command names, sanitized timestamps, and missing credential variable names
- `execution_allowed=false`, `go_live_permitted=false`, and `binder_is_not_go_live=true`; this binder is not permission or machinery for going live
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 36 — Compliance evidence binder UI shell
Internal operator HTML view of the Phase 35 compliance evidence binder. Read-only, no execution.
- `GET /internal/operator-compliance-evidence-binder`
- Renders existing Phase 35 binder output as a sanitized HTML page
- Linked from the operator dashboard, command-center next-action labels, launch-readiness next-action labels, owner handoff packet UI, and operator audit timeline UI
- Shows all binder sections: outbound disabled/operator halt, no-live-provider defaults, no-execution side-effect evidence, PHI/secrets/redaction evidence, consent-based phone-only boundary, CI dry-run smoke/deploy-config gates, documented compliance guardrails, operator audit timeline summary, reused read-only summaries, and remaining manual owner checklist
- Sanitized fields only: statuses, counts, codes, no-execution flags, halt/outbound/live-provider states, CI gate names, route/command names, sanitized timestamps, and missing credential variable names
- Page states `go_live_permitted=false`, `execution_allowed=false`, and `binder_is_not_go_live=true`
- No apply/execute/lift-halt/enable-outbound/provider/deploy/campaign/booking/call/publish/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 37 — Release-candidate deployment runbook export
Read-only owner/operator planning export consolidating existing safe summaries. No deployment.
- Service plus CLI `vyro-growth release-candidate-runbook` and internal JSON `GET /internal/release-candidate-runbook`
- Reuses launch readiness, settings execution preflight, owner handoff packet, compliance evidence binder, operator audit timeline, deployment safe defaults, CI smoke/deploy-config gate names, and documented compliance guardrails
- Sections: release candidate identity and repo branch expectations, required CI gates and local dry-run verification commands, safe environment defaults and missing credential variable names only, operator halt and outbound-disabled verification, manual deployment sequence as instructions only, rollback checklist as instructions only, post-deploy read-only verification endpoints/commands, and unresolved blockers/manual owner checklist items
- Safe metadata only: statuses, counts, codes, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text
- `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, and `runbook_is_not_deployment=true`; this runbook is not a deployment mechanism or permission to go live
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 38 — Release-candidate deployment runbook UI shell
Internal operator HTML view of the Phase 37 release-candidate deployment runbook. Read-only, no deployment.
- `GET /internal/operator-release-candidate-runbook`
- Renders existing Phase 37 runbook as a sanitized HTML page
- Linked from the operator dashboard, command-center next-action labels, launch-readiness next-action labels, owner handoff packet UI, operator audit timeline UI, and compliance evidence binder UI
- Shows all runbook sections: release candidate identity and repo branch expectations, required CI gates and local dry-run verification commands, required safe environment defaults and missing credential variable names only, operator halt and outbound-disabled verification, manual deployment sequence as instructions only, rollback checklist as instructions only, post-deploy read-only verification endpoints/commands, documented guardrails, reused read-only summaries, and remaining unresolved blockers/manual owner checklist items
- Sanitized fields only: statuses, counts, codes, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text
- Page states `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, and `runbook_is_not_deployment=true`
- No apply/execute/lift-halt/enable-outbound/provider/deploy/campaign/booking/call/publish/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 39 — Release artifact manifest and provenance export
Read-only owner/operator review export describing a future release candidate. No build, publish, or deploy.
- Service plus CLI `vyro-growth release-artifact-manifest` and internal JSON `GET /internal/release-artifact-manifest`
- Reuses release-candidate runbook, compliance evidence binder, launch readiness, settings execution preflight, owner handoff packet, operator audit timeline, deployment safe defaults, CI smoke/deploy-config gate names, and documented compliance guardrails
- Sections: source/provenance expectations including local git metadata if safely available, artifact inventory, migration inventory (revision filenames/ids only), runtime command inventory, safety gate inventory, no-build/no-deploy evidence, and unresolved blockers/manual owner checklist items
- Local git inspection reads `.git` files only and does not call GitHub Actions or GitHub provider APIs
- Safe metadata only: statuses, counts, codes, filenames, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text
- `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, `build_allowed=false`, `artifact_publish_allowed=false`, `runbook_is_not_deployment=true`, and `manifest_is_not_a_build_or_deploy=true`; this manifest is not a build, artifact publishing, deployment mechanism, or permission to go live
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 40 — Release artifact manifest UI shell
Internal operator HTML view of the Phase 39 release artifact manifest. Read-only, no build, publish, or deploy.
- `GET /internal/operator-release-artifact-manifest`
- Renders existing Phase 39 manifest as a sanitized HTML page
- Linked from the operator dashboard, command-center next-action labels, launch-readiness next-action labels, owner handoff packet UI, operator audit timeline UI, compliance evidence binder UI, and release-candidate runbook UI
- Shows all manifest sections: source and provenance expectations, artifact inventory, migration inventory, runtime command inventory, safety gate inventory, no-build/no-deploy evidence, reused read-only summaries, and remaining unresolved blockers/manual owner checklist items
- Sanitized fields only: statuses, counts, codes, filenames, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text
- Page states `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `build_allowed=false`, `artifact_publish_allowed=false`, `runbook_is_not_deployment=true`, and `manifest_is_not_a_build_or_deploy=true`
- No apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 41 — Operator go-live readiness index UI
Internal operator HTML index of existing owner/operator readiness, evidence, runbook, manifest, and audit surfaces. Read-only, no execution.
- `GET /internal/operator-go-live-readiness-index`
- Reuses existing read-only builders/summaries and links to the existing JSON and HTML surfaces
- Summary cards show statuses, counts, blocker codes, route names, and command names only
- Live-blocking flags: `OUTBOUND_ENABLED=false`, operator halt status, closed live-provider flags, `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, `build_allowed=false`, `artifact_publish_allowed=false`, and existing not-go-live / not-deployment / not-build booleans
- Manual owner checklist rollup uses codes, statuses, counts, route names, command names, and checklist labels only
- Page states this is an index/review view only, not permission to go live and not an execution surface
- No apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 42 — Go-live readiness index CLI and JSON export
Sanitized read-only CLI and internal JSON export of the Phase 41 go-live readiness index. Review export only, no execution.
- CLI `vyro-growth go-live-readiness-index` with Markdown output and `--json` output
- Internal JSON `GET /internal/go-live-readiness-index`
- Reuses existing Phase 41 `GoLiveReadinessIndexService` and payload helper
- Same safe readiness rollup: operator dashboard / command center, launch readiness, settings execution preflight, owner handoff packet, compliance evidence binder, release-candidate runbook, release artifact manifest, operator audit timeline counts, and manual owner checklist rollup
- Live-blocking flags using safe metadata only: `OUTBOUND_ENABLED=false`, operator halt status, closed live-provider flags, `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, `build_allowed=false`, `artifact_publish_allowed=false`, and that the index is not permission to go live
- Safe metadata only: statuses, counts, codes, routes, commands, flag names/states, missing credential variable names, sanitized timestamps, and checklist labels
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes
- This is a review export only, not permission to go live and not an execution surface

## Phase 43 — Launch blockers remediation plan export
Sanitized read-only CLI and internal JSON export that turns Phase 42 go-live readiness index blockers into operator-friendly manual remediation steps. Planning/export only, no execution.
- CLI `vyro-growth launch-blockers-plan` with Markdown output and `--json` output
- Internal JSON `GET /internal/launch-blockers-plan`
- Reuses existing Phase 42 `GoLiveReadinessIndexService` / payload as the source of truth and does not duplicate readiness calculations
- Deterministic remediation plan grouped by readiness surface or blocker category
- Safe metadata only: blocker code, surface key/label, current status, recommended manual remediation step, required owner approval type if any, step kind (configuration, credential, legal/compliance, deployment, provider setup, or manual review), and safe route/CLI/config-name references
- Live-blocking flags using safe metadata only: `read_only=true`, `no_execution=true`, `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `OUTBOUND_ENABLED=false`, `owner_approved=false`, and that this plan is not permission to go live
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes
- This is a remediation planning export only, not permission to go live and not an execution surface

## Phase 44 — Operator launch blockers remediation plan UI
Internal operator HTML shell of the Phase 43 launch blockers remediation plan. Read-only, no execution.
- `GET /internal/operator-launch-blockers-plan`
- Reuses existing Phase 43 `LaunchBlockersPlanService` / payload and does not duplicate readiness calculations
- Linked from the operator dashboard, go-live readiness index UI, and related readiness surfaces
- Renders overall status, generated timestamp, read-only / no-execution / no-go-live flags, operator halt before/after, outbound/live-provider/deployment/build/publish permission flags, source go-live readiness index references, related safe routes and CLI commands, grouped remediation steps, blocker codes, missing credential names, closed provider flag names, and safe local git metadata
- Safe metadata only: statuses, codes, route names, command names, config names, flag names/states, missing credential variable names, sanitized timestamps, and recommended manual remediation steps
- Page states this is a remediation planning view only, not permission to go live and not an execution surface
- No apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 45 — Staged go-live rollout plan export
Sanitized read-only CLI and internal JSON export that consolidates the go-live readiness index, launch blockers remediation plan, compliance evidence binder, release-candidate runbook, release artifact manifest, and launch readiness checks into a staged manual rollout plan. Planning/export only, no execution.
- CLI `vyro-growth staged-rollout-plan` with Markdown output and `--json` output
- Internal JSON `GET /internal/staged-rollout-plan`
- Reuses existing readiness/blocker/runbook/binder/manifest/launch-readiness services as source material and does not duplicate source-of-truth readiness logic
- Deterministic stage groups: stage 0 safe defaults and operator halt verification; stage 1 credential/configuration preparation by variable name only; stage 2 local dry-run verification and CI gates; stage 3 owner review of packets/checklists/readiness surfaces; stage 4 future manual deployment preparation only; stage 5 future owner-approved live enablement prerequisites only
- Safe metadata only: stage key/label, status, blocker/gate codes, required owner approval type if any, manual checklist items, and safe route/CLI/config-name references
- Live-blocking flags using safe metadata only: `read_only=true`, `no_execution=true`, `manual_review_only=true`, `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `OUTBOUND_ENABLED=false`, `owner_approved=false`, and `staged_rollout_plan_is_not_go_live=true`
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes
- This is a staged rollout planning export only, not permission to go live and not an execution surface

## Phase 46 — Operator staged go-live rollout plan UI
Internal operator HTML shell of the Phase 45 staged go-live rollout plan. Read-only, no execution.
- `GET /internal/operator-staged-rollout-plan`
- Reuses existing Phase 45 `StagedRolloutPlanService` / payload and does not duplicate readiness calculations
- Linked from the operator dashboard, go-live readiness index UI, launch blockers plan UI, and related readiness surfaces
- Renders overall status, generated timestamp, read-only / no-execution / no-go-live flags, operator halt before/after, outbound/live-provider/deployment/build/publish permission flags, source references for readiness index, launch blockers plan, launch readiness, compliance binder, runbook, and manifest, related safe routes and CLI commands, stages 0-5 with stage labels, status, blocker/gate codes, required approval type, checklist items, related routes/commands/config names, missing credential names, closed provider flag names, and safe local git metadata
- Safe metadata only: statuses, codes, route names, command names, config names, flag names/states, missing credential variable names, sanitized timestamps, and checklist labels
- Page states this is a staged rollout planning view only, not permission to go live and not an execution surface
- No apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 47 — Owner launch dossier export
Sanitized read-only CLI and internal JSON export that consolidates the go-live readiness index, launch blockers remediation plan, staged go-live rollout plan, owner go-live handoff packet, compliance evidence binder, release-candidate runbook, release artifact manifest, settings execution preflight summary, and operator audit summary into one owner/operator review packet. Export/review only, no execution.
- CLI `vyro-growth owner-launch-dossier` with Markdown output and `--json` output
- Internal JSON `GET /internal/owner-launch-dossier`
- Reuses existing readiness/blocker/staged-rollout/handoff/binder/runbook/manifest/preflight/audit services as source material and does not duplicate source-of-truth readiness logic
- Deterministic source-surface rollup plus a concise non-executable owner next-action summary
- Safe metadata only: statuses, blocker/gate codes, missing credential variable names, route names, command names, config names, sanitized timestamps, counts, and safe local git metadata
- Live-blocking flags using safe metadata only: `read_only=true`, `no_execution=true`, `no_go_live=true`, `no_deployment=true`, `manual_review_only=true`, `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `OUTBOUND_ENABLED=false`, `owner_approved=false`, and `owner_launch_dossier_is_not_go_live=true`
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes
- HTTP responses return `Cache-Control: no-store`
- This is a review export only, not permission to go live and not an execution surface

## Phase 48 — Operator owner launch dossier UI
Internal operator HTML shell of the Phase 47 owner launch dossier. Read-only, no execution.
- `GET /internal/operator-owner-launch-dossier`
- Reuses existing Phase 47 `OwnerLaunchDossierService` / payload and does not duplicate readiness calculations
- Linked from the operator dashboard, go-live readiness index UI, launch blockers plan UI, staged rollout plan UI, and related readiness surfaces
- Renders overall status, generated timestamp, packet kind and purpose, read-only / no-execution / no-go-live / no-deployment flags, operator halt before/after and unchanged proof, outbound/live-provider/deployment/build/publish permission flags, source references for each included readiness/export surface, blocker and gate code rollups, missing credential/config names only, related safe routes and CLI commands, safe local git metadata, settings execution preflight summary, operator audit summary, and a non-executable owner next-action summary
- Safe metadata only: statuses, codes, route names, command names, config names, flag names/states, missing credential variable names, sanitized timestamps, and counts
- Page states this is a launch dossier review view only, not permission to go live and not an execution surface
- No apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 49 — Provider credential/setup checklist export
Sanitized read-only CLI and internal JSON export that consolidates launch readiness, go-live readiness index, launch blockers plan, staged rollout plan, owner launch dossier, settings execution preflight, and release-candidate runbook surfaces into one provider credential/setup checklist. Planning/export only, no execution.
- CLI `vyro-growth provider-setup-checklist` with Markdown output and `--json` output
- Internal JSON `GET /internal/provider-setup-checklist`
- Reuses existing readiness/blocker/staged-rollout/dossier/preflight/runbook services as source material and does not duplicate source-of-truth readiness logic
- Deterministic provider setup categories: email/outreach, enrichment, calendar, voice, ads/analytics, deployment, and database/storage, using config names only
- Safe metadata only: category key/label, status, required owner approval type, missing credential variable names, closed provider/live flag names, blocker/gate codes, and safe route/CLI/config-name references
- Live-blocking flags using safe metadata only: `read_only=true`, `no_execution=true`, `no_go_live=true`, `no_deployment=true`, `manual_review_only=true`, `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `OUTBOUND_ENABLED=false`, `owner_approved=false`, and `provider_setup_checklist_is_not_go_live=true`
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes
- HTTP responses return `Cache-Control: no-store`
- This is a planning/export layer only, not permission to go live and not an execution surface

## Phase 50 — Operator provider setup checklist UI
Internal operator HTML shell of the Phase 49 provider credential/setup checklist. Read-only, no execution.
- `GET /internal/operator-provider-setup-checklist`
- Reuses existing Phase 49 `ProviderSetupChecklistService` / payload and does not duplicate readiness calculations
- Linked from the operator dashboard, owner launch dossier UI, go-live readiness index UI, launch blockers plan UI, staged rollout plan UI, and related readiness surfaces
- Renders overall status, generated timestamp, packet kind and purpose, read-only / no-execution / no-go-live / no-deployment flags, operator halt before/after and unchanged proof, missing credential variable names only, closed provider/live flag names only, provider setup categories (email/outreach, enrichment, calendar, voice, ads/analytics, deployment, database/storage), required owner approval type per category, blocker and gate code rollups, related safe routes and CLI commands, safe local git metadata, local verification gates, and non-executable owner preparation steps
- Safe metadata only: statuses, codes, route names, command names, config names, flag names/states, missing credential variable names, sanitized timestamps, and counts
- Page states this is a provider setup review view only, not permission to go live and not an execution surface
- No apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 51 — Manual go-live rehearsal checklist export
Sanitized read-only CLI and internal JSON export that consolidates launch readiness, go-live readiness index, launch blockers plan, staged rollout plan, owner launch dossier, provider setup checklist, release-candidate runbook, release artifact manifest, and settings execution preflight into one manual go-live rehearsal checklist. Checklist/export only, no execution.
- CLI `vyro-growth go-live-rehearsal-checklist` with Markdown output and `--json` output
- Internal JSON `GET /internal/go-live-rehearsal-checklist`
- Reuses existing readiness/blocker/staged-rollout/dossier/provider-setup/runbook/manifest/preflight services as source material and does not duplicate source-of-truth readiness logic
- Rehearsal steps are manual instructions only, not runnable automation; command names and routes are references only
- Expected safe assertions such as `executed=0`, `OUTBOUND_ENABLED=false`, `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `owner_approved=false`, and halt unchanged
- Required owner approval type per rehearsal gate, blocker/gate code rollups, missing credential/config names only, closed provider/live flag names only, rollback/abort guidance as review text only, safe local git metadata, and non-executable owner next steps
- Live-blocking flags using safe metadata only: `read_only=true`, `no_execution=true`, `no_go_live=true`, `no_deployment=true`, `manual_review_only=true`, `rehearsal_is_not_a_script_runner=true`, `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `OUTBOUND_ENABLED=false`, `owner_approved=false`, and `go_live_rehearsal_checklist_is_not_go_live=true`
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes
- HTTP responses return `Cache-Control: no-store`
- This is a checklist/export only, not a script runner, not permission to go live, and not an execution surface

## Phase 52 — Operator go-live rehearsal checklist UI
Internal operator HTML shell of the Phase 51 manual go-live rehearsal checklist. Read-only, no execution.
- `GET /internal/operator-go-live-rehearsal-checklist`
- Reuses existing Phase 51 `GoLiveRehearsalChecklistService` / payload and does not duplicate readiness calculations
- Linked from the operator dashboard, provider setup checklist UI, owner launch dossier UI, go-live readiness index, staged rollout UI, launch blockers UI, release candidate runbook UI, release artifact manifest UI, and related readiness surfaces
- Renders overall status, generated timestamp, packet kind and purpose, read-only / no-execution / no-go-live / no-deployment flags, operator halt before/after and unchanged proof, manual rehearsal steps with `runnable=false` and `executed=0`, expected safe assertions such as `OUTBOUND_ENABLED=false`, `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `owner_approved=false`, and halt unchanged, required owner approval type per rehearsal gate, blocker/gate code rollups, missing credential/config names only, closed provider/live flag names only, rollback and abort guidance as review text only, related safe routes and CLI commands, safe local git metadata, and non-executable owner next steps
- Safe metadata only: statuses, codes, route names, command names, config names, flag names/states, missing credential variable names, sanitized timestamps, and counts
- Page states this is a manual rehearsal review view only, not permission to go live and not an execution surface
- No apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 53 — Rehearsal outcome report export
Sanitized read-only CLI and internal JSON export that summarizes the current Phase 51 manual go-live rehearsal checklist into a compact outcome packet. Report/export only, no execution.
- CLI `vyro-growth rehearsal-outcome-report` with Markdown output and `--json` output
- Internal JSON `GET /internal/rehearsal-outcome-report`
- Reuses existing Phase 51 `GoLiveRehearsalChecklistService` as the source of truth and does not recalculate rehearsal state independently
- Compact counts of rehearsal steps by status, kind, and required owner approval type
- Count of expected safe assertions passed/failed and a safe list of failed assertion keys only
- Blocker/gate code rollups, missing credential/config names only, closed provider/live flag names only, manual-only outcome summary, related safe route/CLI references, safe local git metadata, and non-executable owner next steps
- Live-blocking flags using safe metadata only: `read_only=true`, `no_execution=true`, `no_go_live=true`, `no_deployment=true`, `manual_review_only=true`, `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `OUTBOUND_ENABLED=false`, `owner_approved=false`, and `rehearsal_outcome_report_is_not_go_live=true`
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes
- HTTP responses return `Cache-Control: no-store`
- This is an outcome report/export only, not permission to go live and not an execution surface

## Phase 54 — Operator rehearsal outcome report UI
Internal operator HTML shell of the Phase 53 rehearsal outcome report. Read-only, no execution.
- `GET /internal/operator-rehearsal-outcome-report`
- Reuses existing Phase 53 `RehearsalOutcomeReportService` / payload and does not duplicate readiness calculations
- Linked from the operator dashboard, go-live rehearsal checklist UI, provider setup checklist UI, owner launch dossier UI, go-live readiness index, staged rollout UI, launch blockers UI, release candidate runbook UI, release artifact manifest UI, and related readiness surfaces
- Renders overall status, generated timestamp, packet kind and purpose, read-only / no-execution / no-go-live / no-deployment flags, operator halt before/after and unchanged proof, rehearsal step count and counts by status/kind/required owner approval type, expected safe assertion pass/fail counts, failed safe assertion keys only, remaining owner approval type rollups, blocker/gate code rollups, missing credential/config names only, closed provider/live flag names only, outcome summary as sanitized review text only, related safe routes and CLI commands, safe local git metadata, and non-executable owner next steps
- Safe metadata only: statuses, codes, route names, command names, config names, flag names, missing credential variable names, sanitized timestamps, and counts
- Page states this is an outcome report review view only, not permission to go live and not an execution surface
- No apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 55 — Supervised pilot launch plan export
Sanitized read-only CLI and internal JSON export that consolidates the go-live readiness index, launch blockers plan, staged rollout plan, owner launch dossier, provider setup checklist, manual go-live rehearsal checklist, rehearsal outcome report, and settings execution preflight into one supervised small-pilot plan. Planning/export only, no execution.
- CLI `vyro-growth supervised-pilot-plan` with Markdown output and `--json` output
- Internal JSON `GET /internal/supervised-pilot-plan`
- Reuses existing readiness/blocker/staged-rollout/dossier/provider-setup/rehearsal/outcome/preflight services as source material and does not duplicate source-of-truth readiness logic
- Practical small-pilot scope recommendation using safe counts only: suggested max leads, max drafts, max manually reviewed sends, max daily activity, and stop conditions
- Pilot prerequisites grouped by category: website credibility, email/domain setup, email/outreach setup, enrichment credentials, calendar setup, compliance review, owner approvals, and monitoring
- Safety assertions such as `OUTBOUND_ENABLED=false`, `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `owner_approved=false`, `halt_changed=false`, and `spend_allowed=false`
- Manual pilot runbook steps as review text only, each `runnable=false` and `executed=0`
- Pilot abort/rollback criteria as review text only
- Blocker/gate code rollups, missing credential/config names only, closed provider/live flag names only, related safe route/CLI references, safe local git metadata, and non-executable owner next steps
- Live-blocking flags using safe metadata only: `read_only=true`, `no_execution=true`, `no_go_live=true`, `no_deployment=true`, `no_spend=true`, `manual_review_only=true`, `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `OUTBOUND_ENABLED=false`, `owner_approved=false`, `spend_allowed=false`, and `supervised_pilot_plan_is_not_go_live=true`
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes
- HTTP responses return `Cache-Control: no-store`
- This is a supervised pilot planning export only, not permission to go live and not an execution surface

## Phase 56 — Operator supervised pilot launch plan UI
Internal operator HTML shell of the Phase 55 supervised pilot launch plan. Read-only, no execution.
- `GET /internal/operator-supervised-pilot-plan`
- Reuses existing Phase 55 `SupervisedPilotPlanService` / payload and does not duplicate readiness calculations
- Linked from the operator dashboard, go-live readiness index, launch blockers UI, staged rollout UI, owner launch dossier UI, provider setup checklist UI, go-live rehearsal checklist UI, rehearsal outcome report UI, release candidate runbook UI, release artifact manifest UI, and related readiness surfaces
- Renders overall status, generated timestamp, packet kind and purpose, read-only / no-execution / no-go-live / no-deployment / no-spend / dry-run-only / manual-review-only flags, operator halt before/status/after and unchanged proof, a safe count-only pilot scope recommendation, grouped prerequisites for website, email/domain, outreach, enrichment credentials, calendar, compliance, owner approvals, and monitoring, safety assertions and failed assertion keys, blocker/gate rollups, missing credential/config names only, closed provider/live flag names only, manual runbook steps with `runnable=false` and `executed=0`, abort/rollback criteria as review text only, related safe routes and CLI commands, safe local git metadata, and non-executable owner next steps
- Safe metadata only: statuses, codes, route names, command names, config names, flag names, missing credential variable names, sanitized timestamps, and counts
- Page states this is a supervised pilot planning review view only, not permission to go live and not an execution surface
- No apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 57 — Supervised pilot candidate readiness export
Sanitized read-only CLI and internal JSON export that summarizes whether the current system has a safe small-pilot candidate pool ready for owner review. Review/export only, no execution.
- CLI `vyro-growth supervised-pilot-candidates` with Markdown output and `--json` output
- Internal JSON `GET /internal/supervised-pilot-candidates`
- Reuses existing discovery/enrichment/scoring/outreach readiness aggregates plus the supervised pilot plan, provider setup, rehearsal outcome, launch readiness, and operator halt state
- Safe metadata only: generated timestamp, packet kind/purpose, overall status, explicit no-execution flags, unchanged halt proof, candidate scope counts, candidate pool counts by generic readiness/status/stage/source/specialty/state buckets, scoring distribution counts, missing prerequisite/gate codes, suppression/kill-switch rollups, blocked-count reasons, safe next-step codes/labels, related routes/commands, and safe local git metadata
- Live-blocking flags using safe metadata only: `read_only=true`, `no_execution=true`, `no_go_live=true`, `no_outbound=true`, `no_provider_calls=true`, `no_spend=true`, `dry_run_only=true`, `manual_review_only=true`, `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `OUTBOUND_ENABLED=false`, `owner_approved=false`, and `supervised_pilot_candidates_is_not_go_live=true`
- Does not expose practice names, provider names, NPI numbers, street addresses, emails, phones, websites, raw evidence snippets, message bodies, outreach drafts, PHI, patient data, secrets, env values, or unsafe errors
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes
- HTTP responses return `Cache-Control: no-store`
- This is a candidate readiness review export only, not permission to go live and not an execution surface

## Phase 58 — Operator supervised pilot candidate readiness UI
Internal operator HTML shell of the Phase 57 supervised pilot candidate readiness export. Read-only, no execution.
- `GET /internal/operator-supervised-pilot-candidates`
- Reuses existing Phase 57 `SupervisedPilotCandidateService` / payload and does not duplicate candidate readiness calculations
- Linked from the operator dashboard, go-live readiness index, supervised pilot plan UI, launch blockers UI, staged rollout UI, owner launch dossier UI, provider setup checklist UI, rehearsal outcome UI, release/readiness pages, and related readiness surfaces
- Renders overall status, generated timestamp, packet kind and purpose, read-only / no-execution / no-go-live / no-outbound / no-provider-calls / no-deployment / no-spend / dry-run-only / manual-review-only flags, operator halt before/status/after and unchanged proof, a safe count-only candidate scope recommendation, candidate counts by readiness/status/stage/source/specialty/state, scoring distribution counts, website match counts, outreach status counts, suppression/kill-switch rollups, blocked counts by generic reason, missing prerequisite/blocker/gate codes, missing credential/config names only, closed provider/live flag names only, related safe routes and CLI commands, safe local git metadata, and non-executable owner next steps
- Safe metadata only: statuses, codes, route names, command names, config names, flag names, missing credential variable names, specialty categories, state abbreviations, generic source names, sanitized timestamps, and counts
- Page states this is a candidate readiness review view only, not permission to go live and not an execution surface
- No apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend/candidate-selection/contact controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 59 — Supervised pilot go/no-go packet export
Sanitized read-only CLI and internal JSON export that combines the supervised pilot plan, candidate readiness, provider setup checklist, rehearsal outcome report, launch readiness / go-live readiness index, review/action readiness queues, owner approval/settings request rollups, and operator halt state into one owner go/no-go decision packet. Review/export only, no execution.
- CLI `vyro-growth supervised-pilot-go-no-go` with Markdown output and `--json` output
- Internal JSON `GET /internal/supervised-pilot-go-no-go`
- Reuses existing supervised-pilot-plan, candidate-readiness, provider-setup, rehearsal-outcome, launch-readiness / go-live-index, review/action-readiness, owner-approval, settings-request, and operator-halt surfaces
- Safe metadata only: generated timestamp, packet kind/purpose, overall go/no-go status (`blocked` / `warning` / `ready_for_owner_review` / `info`), explicit no-execution flags, unchanged halt proof, prerequisite and candidate readiness summaries using counts/codes only, go/no-go gates with code/status/label/blocking boolean/route/command names, owner decision prerequisite type/code names only, missing credential/config names only, closed provider/live flag names only, blocked reason counts only, safe next-step codes/labels, related routes/commands, and safe local git metadata
- Live-blocking flags using safe metadata only: `read_only=true`, `no_execution=true`, `no_go_live=true`, `no_outbound=true`, `no_provider_calls=true`, `no_spend=true`, `dry_run_only=true`, `manual_review_only=true`, `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `OUTBOUND_ENABLED=false`, `owner_approved=false`, and `supervised_pilot_go_no_go_is_not_go_live=true`
- Does not expose practice names, provider names, NPI numbers, street addresses, emails, phones, websites, raw evidence snippets, message bodies, outreach drafts, PHI, patient data, secrets, env values, or unsafe errors
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes
- HTTP responses return `Cache-Control: no-store`
- This is a go/no-go review export only, not permission to go live and not an execution surface

## Phase 60 — Operator supervised pilot go/no-go UI
Internal operator HTML shell of the Phase 59 supervised pilot go/no-go packet. Read-only, no execution.
- `GET /internal/operator-supervised-pilot-go-no-go`
- Reuses existing Phase 59 `SupervisedPilotGoNoGoService` / payload and does not duplicate go/no-go readiness calculations
- Linked from the operator dashboard, go-live readiness index, supervised pilot plan UI, supervised pilot candidate UI, launch blockers UI, staged rollout UI, owner launch dossier UI, provider setup checklist UI, rehearsal outcome UI, release/readiness pages, and related readiness surfaces
- Renders overall status, generated timestamp, packet kind and purpose, read-only / no-execution / no-go-live / no-outbound / no-provider-calls / no-deployment / no-spend / dry-run-only / manual-review-only flags, operator halt before/status/after and unchanged proof, prerequisite category summary using counts/statuses only, candidate readiness summary using counts/codes only, blocked reason counts, review queue / action readiness / approval packet / settings request count rollups, go/no-go gates with code/status/label/blocking boolean/route/command names, owner decision prerequisite type/code names only, missing credential/config names only, closed provider/live flag names only, blocker/gate codes, related safe routes and CLI commands, safe local git metadata, and non-executable owner next steps
- Safe metadata only: statuses, codes, route names, command names, config names, flag names, missing credential variable names, specialty categories, state abbreviations, generic source names, sanitized timestamps, and counts
- Page states this is a go/no-go review view only, not permission to go live and not an execution surface
- No apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend/candidate-selection/contact controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 61 — Supervised pilot first-send preflight export
Sanitized read-only CLI and internal JSON export that consolidates the supervised pilot go/no-go packet, supervised pilot plan, candidate readiness, provider setup checklist, rehearsal outcome, launch readiness / go-live index, review/action readiness queues, owner approval/settings request rollups, and operator halt state into one first-send preflight. Review/export only, no execution.
- CLI `vyro-growth supervised-pilot-first-send-preflight` with Markdown output and `--json` output
- Internal JSON `GET /internal/supervised-pilot-first-send-preflight`
- Reuses existing Phase 59 `SupervisedPilotGoNoGoService` and Phase 55 `SupervisedPilotPlanService` as source material and does not recalculate readiness independently
- Safe metadata only: generated timestamp, packet kind/purpose, overall status reused from go/no-go, explicit no-execution / no-send flags, unchanged halt proof, count-only first-send scope (`suggested_max_first_sends=0`), candidate/queue count rollups, expected safe assertion pass/fail counts and failed keys only, preflight checks with code/status/label/blocking boolean/route/command names, abort/stop conditions as review text only, owner decision type/code names only, missing credential/config names only, closed provider/live flag names only, related routes/commands, and safe local git metadata
- Live-blocking flags using safe metadata only: `read_only=true`, `no_execution=true`, `no_go_live=true`, `no_outbound=true`, `no_provider_calls=true`, `no_spend=true`, `dry_run_only=true`, `manual_review_only=true`, `execution_allowed=false`, `first_send_allowed=false`, `first_send_attempted=false`, `first_send_executed=0`, `sends_executed=0`, `go_live_permitted=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `OUTBOUND_ENABLED=false`, `owner_approved=false`, `supervised_pilot_first_send_preflight_is_not_go_live=true`, and `first_send_preflight_is_not_a_send=true`
- Does not expose practice names, provider names, NPI numbers, street addresses, emails, phones, websites, raw evidence snippets, message bodies, outreach drafts, PHI, patient data, secrets, env values, or unsafe errors
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes
- HTTP responses return `Cache-Control: no-store`
- This is a first-send preflight/export only, not permission to send, not permission to go live, and not an execution surface

## Phase 62 — Operator supervised pilot first-send preflight UI
Internal operator HTML shell of the Phase 61 supervised pilot first-send preflight packet. Read-only, no execution.
- `GET /internal/operator-supervised-pilot-first-send-preflight`
- Reuses existing Phase 61 `SupervisedPilotFirstSendPreflightService` / payload and does not duplicate first-send readiness calculations
- Linked from the operator dashboard, go-live readiness index, supervised pilot plan UI, supervised pilot candidate UI, supervised pilot go/no-go UI, launch blockers UI, staged rollout UI, owner launch dossier UI, provider setup checklist UI, rehearsal outcome UI, release/readiness pages, and related readiness surfaces
- Renders overall status, generated timestamp, packet kind and purpose, read-only / no-execution / no-go-live / no-outbound / no-provider-calls / no-deployment / no-spend / dry-run-only / manual-review-only flags, first-send flags (`first_send_allowed=false`, `first_send_attempted=false`, `first_send_executed=0`, `sends_executed=0`), operator halt before/status/after and unchanged proof, first-send scope recommendation counts, candidate/queue counts, prerequisite / candidate-readiness / blocked-reason counts, expected safe assertion pass/fail counts and failed keys, preflight checks with code/status/label/blocking boolean/route/command names, abort/stop conditions as review text only, owner decision prerequisite type/code names only, missing credential/config names only, closed provider/live flag names only, blocker/gate codes, related safe routes and CLI commands, safe local git metadata, and non-executable owner next steps
- Safe metadata only: statuses, codes, route names, command names, config names, flag names, missing credential variable names, specialty categories, state abbreviations, generic source names, sanitized timestamps, and counts
- Page states this is a first-send preflight review view only, not permission to send, not permission to go live, and not an execution surface
- No apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend/candidate-selection/send/contact controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 63 — Supervised pilot launch rehearsal control map export
Sanitized read-only CLI and internal JSON export that maps existing readiness surfaces into one supervised-pilot launch rehearsal control map. Control-map/export only, no execution.
- CLI `vyro-growth supervised-pilot-launch-rehearsal-control-map` with Markdown output and `--json` output
- Internal JSON `GET /internal/supervised-pilot-launch-rehearsal-control-map`
- Reuses existing Phase 61 `SupervisedPilotFirstSendPreflightService` as source material and does not recalculate readiness independently
- Maps operator halt and `OUTBOUND_ENABLED=false` gates, supervised pilot plan/candidates/go-no-go/first-send preflight references, owner approval packet references and remaining approval types, settings change request/preflight references, launch blockers, readiness index, rehearsal checklist, outcome report, provider setup checklist, compliance evidence binder, and release runbook/manifest surfaces
- Required commands/routes by name only, blocking status rollups and safe counts only, and next safe owner/operator review steps
- Live-blocking flags using safe metadata only: `read_only=true`, `no_execution=true`, `no_go_live=true`, `no_outbound=true`, `no_provider_calls=true`, `no_spend=true`, `no_first_send=true`, `dry_run_only=true`, `manual_review_only=true`, `execution_allowed=false`, `first_send_allowed=false`, `first_send_attempted=false`, `first_send_executed=0`, `sends_executed=0`, `go_live_permitted=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `OUTBOUND_ENABLED=false`, `owner_approved=false`, `supervised_pilot_launch_rehearsal_control_map_is_not_go_live=true`, `rehearsal_control_map_is_not_a_script_runner=true`, and `control_map_is_not_execution=true`
- Does not expose practice names, provider names, NPI numbers, street addresses, emails, phones, websites, raw evidence snippets, message bodies, outreach drafts, PHI, patient data, secrets, env values, or unsafe errors
- Reuses existing sanitization/redaction and internal API auth
- same `INTERNAL_API_KEY` gate as other internal operator routes
- HTTP responses return `Cache-Control: no-store`
- This is a control-map/export only, not a script runner, not permission to send, not permission to go live, and not an execution surface

## Phase 64 — Operator supervised pilot launch rehearsal control map UI
Internal operator HTML shell of the Phase 63 supervised pilot launch rehearsal control map. Read-only, no execution.
- `GET /internal/operator-supervised-pilot-launch-rehearsal-control-map`
- Reuses existing Phase 63 `SupervisedPilotLaunchRehearsalControlMapService` / payload and does not duplicate control-map readiness calculations
- Linked from the operator dashboard, go-live readiness index, supervised pilot plan UI, supervised pilot candidate UI, supervised pilot go/no-go UI, first-send preflight UI, launch blockers UI, staged rollout UI, owner launch dossier UI, provider setup checklist UI, rehearsal outcome UI, release/readiness pages, and related readiness surfaces
- Renders overall status, generated timestamp, packet kind and purpose, read-only / no-execution / no-go-live / no-outbound / no-provider-calls / no-deployment / no-spend / no-first-send / dry-run-only / manual-review-only flags, first-send flags (`first_send_allowed=false`, `first_send_attempted=false`, `first_send_executed=0`, `sends_executed=0`), operator halt before/status/after and unchanged proof, source first-send / go-no-go / pilot-plan / candidate rollups, candidate / review / action / settings / approval counts only, control counts by category/status, blocking/warning/info counts, control map rows with code/category/status/blocking boolean/route/command/label, owner decision prerequisite type/code names only, missing credential/config names only, closed provider/live flag names only, blocker/gate/blocking control codes, related safe routes and CLI commands, safe local git metadata, and non-executable owner next steps
- Safe metadata only: statuses, codes, route names, command names, config names, flag names, missing credential variable names, specialty categories, state abbreviations, generic source names, sanitized timestamps, and counts
- Page states this is a control-map review view only, not a script runner, not permission to send, not permission to go live, and not an execution surface
- No apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend/candidate-selection/send/contact controls
- same `INTERNAL_API_KEY` gate as other internal operator routes

## Phase 66 — Live decision-maker enrichment provider foundation and hit-rate metrics
Dry-run / provider-plumbing / measurement only. Does not send email, enroll leads, call prospects, book meetings, spend money, publish content, execute packets, lift halt, or enable live outbound.
- Guarded live people-search adapter (`LiveDecisionMakerProvider`) behind `DecisionMakerEnrichmentProvider`, disabled by default
- `DECISION_MAKER_LIVE_ENABLED=false`; API key/base URL unused unless explicitly enabled with an injected HTTP client
- Retry/backoff for 429/500/502/503/504; auth/client errors are non-retryable
- Structured provider output parsed into existing `DecisionMakerCandidate` objects; no invented contacts
- `build_decision_maker_provider()` remains dry-run only for CI and local smoke runs
- Waterfall sequencing is people-search then a free website-staff fallback
- Sanitized hit-rate metrics via `vyro-growth contact-enrichment-metrics` and `GET /internal/contact-enrichment/metrics`
- Counts/rates only: organizations considered, with candidate, with business email, with provider-verified email, with decision-maker-role, with verified decision-maker-role email, plus safe role/verification/skip/error buckets
- `NO_CONTACT_FOUND` is a normal outcome, not a failure
- Never expose emails, phones, websites, NPI, addresses, practice/provider names, evidence snippets, message bodies, secrets, tokens, raw env values, or unsafe errors
- No LinkedIn/Sales Navigator provider, AI voice cold-calling, list purchase, or job-response automation
- `OUTBOUND_ENABLED=false`; operator halt unchanged

## Phase 67 — Person-level website staff extraction fallback (current)
Dry-run website fallback only. Does not send email, enroll leads, call prospects, book meetings, spend money, publish content, execute packets, lift halt, or enable live outbound.
- `STAFF_MEMBER` website fact type for evidence-backed public name + title pairs
- Public business staff pages are prioritized: `/about`, `/our-team`, `/staff`, `/meet-the-team`, `/leadership`, and similar safe paths
- Extraction runs only after a verified official-website match, from same-host public pages
- Stored facts include source URL, extracted value, confidence, timestamp, and a safe evidence snippet
- Website-staff candidates feed the existing decision-maker classification and role-ranking path unchanged
- Names, titles, emails, phones, credentials, staff counts, and relationships are never invented
- Patient portals, reviews, intake forms, authenticated areas, and social-network pages are not scraped
- No LinkedIn/Sales Navigator automation
- `OUTBOUND_ENABLED=false`; operator halt unchanged

Future contact-enrichment work (not in this phase):
- email verification before send
- email-pattern inference followed by verification
- job-posting intent signals
- human phone-verification queue for `NO_CONTACT_FOUND`
- live sending or campaign enrollment

Future launch work (not in this phase):
- execute an approved item, packet, or settings request
- enable outbound or live providers
- lift operator halt
- call GitHub Actions or live providers
