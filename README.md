# Vyro Growth Engine

Autonomous B2B client-acquisition platform for **Vyro Medical Billing**.

## Objective

The system's primary success event is a **qualified decision-maker at a US medical practice expressing genuine interest in Vyro's medical billing services and booking a Google Meet with the Vyro team**.

The owner should not need to manually research prospects, copy/paste outreach, decide follow-up timing, read every reply, maintain spreadsheets, or schedule meetings.

## Core pipeline

Practice discovery → enrichment → decision-maker identification → contact verification → qualification/scoring → personalized outreach → automated follow-up → reply classification → autonomous reply handling → lead qualification → calendar availability → Google Meet creation → qualified meeting → analytics/optimization.

## Safety and compliance principles

- No patient PHI in this sales system.
- No indiscriminate cold AI robocalling.
- Voice automation is limited to inbound leads, requested callbacks, or prospects who have consented to a call.
- Permanent unsubscribe/suppression controls are mandatory.
- Dual outbound kill switch: `OUTBOUND_ENABLED` must be explicitly true, and the persistent operator halt must be lifted. Either halt path fails closed.
- Prospect facts must be evidence-backed; AI must not invent enrichment details.
- Every external action must be auditable.
- Sales infrastructure remains architecturally separate from any future HIPAA billing/operations environment.

## Local development

### Prerequisites
- Python 3.12+
- Docker and Docker Compose

### Setup
```bash
git clone https://github.com/haseebKhan537/vyro-growth-engine.git
cd vyro-growth-engine
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
```

### Start the stack
```bash
docker compose up --build -d postgres
alembic upgrade head
uvicorn vyro_growth.main:app --reload --host 0.0.0.0 --port 8000
```

Or run the full stack with Docker Compose:
```bash
docker compose up --build
```

### Verify
```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
vyro-growth check-config
```

Expected `/health` includes `"outbound_enabled": false` and `"live_providers_enabled": false`. `/ready` is HTTP 200 only when the database is reachable and required settings are present.

### Quality checks
```bash
ruff check .
mypy src
pytest -q
vyro-growth smoke-dry-run --local-only --json
vyro-growth launch-readiness --json
vyro-growth settings-execution-preflight --json
vyro-growth owner-handoff-packet --json
vyro-growth compliance-evidence-binder --json
vyro-growth release-candidate-runbook --json
vyro-growth release-artifact-manifest --json
vyro-growth go-live-readiness-index --json
vyro-growth launch-blockers-plan --json
```

CI runs those checks on every pull request. After install it also runs a dedicated dry-run smoke gate: `vyro-growth smoke-dry-run --local-only --json` with `OUTBOUND_ENABLED=false` and every live-provider flag disabled, then `vyro-growth check-smoke-output` to fail the build if the sanitized JSON reports live side effects or contains forbidden sensitive values. The smoke gate does not use `DATABASE_URL` or provider credentials.

## Phase 2 — NPPES practice discovery

Phase 2 ingests public NPPES organization records only. It does not send outbound messages, enrich contacts beyond registry data, or call Apollo/scraping/OpenAI/calendar/voice integrations.

### Run a bounded discovery job

Start PostgreSQL and apply migrations first:
```bash
docker compose up --build -d postgres
alembic upgrade head
```

CLI:
```bash
vyro-growth discover-nppes --state TX --city Austin --max-records 50
```

Internal HTTP trigger (`POST /internal/discovery/nppes`) is not a public API. In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header. CLI and worker discovery jobs do not use this HTTP key.

Development (no key configured):
```bash
curl -X POST http://localhost:8000/internal/discovery/nppes \
  -H "Content-Type: application/json" \
  -d '{"state":"TX","city":"Austin","max_records":25}'
```

Authorized internal trigger:
```bash
curl -X POST http://localhost:8000/internal/discovery/nppes \
  -H "Content-Type: application/json" \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
  -d '{"state":"TX","city":"Austin","max_records":25}'
```

Worker job name: `discover_nppes_practices`

Queries require a narrow filter (`city`, `taxonomy_description`, or `organization_name`). State alone is rejected.

Each run writes:
- deduplicated `organizations` rows keyed by NPI
- `source_evidence` rows with NPPES query/source metadata
- a `discovery_runs` audit row with counts, timestamps, and status
- an `activities` audit row for completed or failed runs

Optional live NPPES integration test:
```bash
NPPES_INTEGRATION_TESTS=1 pytest -q -m integration
```

## Phase 3 foundation — deterministic lead scoring

Local-only scoring of discovered organizations and leads. Phase 4 upgrades the same CLI and worker. It uses persisted NPI, location, specialty, website, contact, and `source_evidence` fields. It does not call Apollo, scraping, OpenAI, Google, Smartlead, Twilio, Vapi, Retell, or NPPES, and it does not send outreach or qualify a lead.

CLI:
```bash
vyro-growth score-leads --organization-id <uuid>
vyro-growth score-leads --lead-id <uuid>
vyro-growth score-leads --limit 50
```

Worker job name: `score_discovered_leads`

## Phase 4 — Advanced ICP qualification

Prioritize organizations from stored public/business evidence only. Scoring remains outbound-disabled and does not call live paid or external providers.

Each run writes:
- a `lead_scores` row with total score, `deterministic-icp-v2` model version, band, reason codes, and factor/reason rationale
- an `activities` audit row (`lead_scored`) only when the score changes
- a `discovered` lead for the organization if one does not already exist

Bands: `hot`, `high`, `medium`, `low`, `research`, `disqualified`.

Material reasons link back to stored `source_evidence` (`evidence_id`, `source_url`, `claim_type`) when available. Missing, ambiguous, and conflicting facts score 0 for that factor and are not inferred. Website practice-size, ownership, provider-count, billing, and website business-contact signals are used only after a verified website match. Billing/RCM points require an explicit stored phrase.

Identical reruns reuse the existing same-version score only when the canonical rationale matches, including evidence pointers and observed values. They do not create duplicate leads, activities, or outreach rows. Leads are not auto-qualified.

## Phase 3A — Official website discovery

Resolve a discovered NPPES organization's official practice website and extract evidence-backed public business facts. This layer does not send email, place calls, create contacts, or call later-phase providers.

CLI:
```bash
vyro-growth enrich-websites --organization-id <uuid>
vyro-growth enrich-websites --organization-id <uuid> --candidate-url https://practice.example
vyro-growth enrich-websites --limit 25 --state TX
```

Worker job name: `enrich_organization_websites`

A page is stored as the official website only when it is `verified` against the NPPES organization (name plus conservative location/identity evidence). `ambiguous` and `no-match` outcomes are recorded and do not invent a website.

When a site is verified, the extractor may persist only these public B2B facts, each with source URL, confidence, timestamp, and snippet:

- specialty/services
- locations
- practice size signals
- provider count
- independent vs larger-group signals
- contact page URL
- public business phone
- public business email if present
- billing/revenue-cycle signals only when explicitly stated

Patient portals, appointment flows, reviews, and other PHI-like pages are blocked. Tests use HTML fixtures and in-memory fetchers; CI does not call live websites.

Each run writes:

- `organizations.website` only on verified matches, plus `website_match_status`
- `source_evidence` rows for the match outcome and each extracted fact
- an `enrichment_runs` audit row
- an `activities` audit row

## Phase 3B — Decision-maker and contact enrichment foundation

Persist professional decision-maker candidates behind a provider interface. This layer does not send email, place calls, scrape LinkedIn, or call a live paid contact API. Tests and CI use a stub that returns no invented people.

CLI:
```bash
vyro-growth enrich-contacts --organization-id <uuid>
vyro-growth enrich-contacts --limit 25 --state TX
```

Worker job name: `enrich_decision_makers`

Roles are ranked in this order and stored only when the provider (or a test double) actually supplied them:

- Owner / Physician Owner
- Practice Administrator
- Practice Manager
- Office Manager
- Executive Director
- COO
- CEO for smaller independent groups
- Revenue Cycle Manager
- Billing Manager
- Operations Manager

Clinical contacts are skipped unless owner/operator evidence is present. Missing emails, phones, titles, and confidence stay unknown. Reruns upsert by a durable dedupe key instead of creating duplicates.

Each run writes:

- `contacts` rows with professional fields, role category, source provider, source timestamp, confidence, verification status, and provenance
- `source_evidence` rows for each persisted contact
- an `enrichment_runs` audit row
- an `activities` audit row

A live paid adapter is not implemented. Tests do not require provider credentials. Expected future env vars (unused): `CONTACT_ENRICHMENT_API_KEY`, `CONTACT_ENRICHMENT_API_BASE_URL`.

## Phase 5 — Evidence-grounded personalization (dry-run)

Generate structured personalization drafts for scored/enriched leads using only stored public/business evidence. Output is evidence-grounded and outbound-disabled. CI and default local development use a deterministic stub and do not require a live OpenAI API key.

CLI:
```bash
vyro-growth personalize-leads --organization-id <uuid>
vyro-growth personalize-leads --lead-id <uuid>
vyro-growth personalize-leads --limit 25 --state TX
```

Worker job name: `personalize_scored_leads`

Each draft includes:

- one-sentence practice summary
- why Vyro may be relevant
- personalized opening line
- recommended outreach angle
- suggested offer, defaulting to Complimentary Revenue Leakage Analysis
- missing-data notes
- evidence references to stored `source_evidence` and scoring factors
- confidence and readiness (`ready`, `needs_more_evidence`, `blocked`)

Unknown facts stay unknown. The generator does not invent practice facts, pain points, provider counts, revenue, denial rates, A/R, payer mix, billing software, contacts, emails, phones, testimonials, or Vyro performance claims.

Each run writes:

- a `personalization_drafts` row (reused on identical evidence fingerprints)
- a `source_evidence` provenance row
- an `enrichment_runs` audit row (`source=personalization`)
- an `activities` audit row

No email is sent, no calls are placed, no calendar events are booked, and leads are not enrolled in outreach tools. `OUTBOUND_ENABLED` remains false by default. Live OpenAI is gated behind `OPENAI_PERSONALIZATION_ENABLED=false` unless explicitly enabled with a key; tests never require that key.

## Phase 6 — Dry-run Smartlead enrollment planning

Prepare and audit campaign enrollment intent without sending email or contacting prospects. CI and default local development use a deterministic Smartlead stub. Live Smartlead is not called.

CLI:
```bash
vyro-growth plan-outreach --lead-id <uuid>
vyro-growth plan-outreach --limit 25 --state TX --campaign-name phase-6-dry-run
```

Worker job name: `plan_outreach_enrollments`

Eligible leads need:

- stage `qualified` or `ready_for_outreach`
- a stored score band of `hot`, `high`, or `medium`
- a professional contact with a business email
- a Phase 5 personalization draft with `readiness_status=ready`

Missing personalization, ineligible scores/stages, and email/domain/organization suppressions are skipped with audited reasons. Re-running the same campaign/lead/contact plan reuses the existing enrollment row.

Each run writes:

- a dry-run `campaigns` row when the named campaign does not exist (`active=false`, `dry_run_only=true`)
- `campaign_enrollments` rows (`planned`, `skipped`, `suppressed`, or `blocked`)
- an `outreach_plan_runs` audit row
- `activities` audit rows

No email is sent, no live Smartlead campaign enrollment occurs, lead stage is not advanced to `contacted`, and no `outreach_messages` rows are created. `OUTBOUND_ENABLED` remains false by default. `SMARTLEAD_LIVE_ENABLED=false`; tests never require a live key.

## Phase 7 — Reply classification (dry-run)

Classify stored inbound replies and apply conservative CRM/conversation updates. This layer does not send email, generate autonomous replies, place calls, book meetings, create Google Meet links, or enroll live campaigns. CI and default local development use a deterministic rule stub and do not require a live OpenAI API key.

CLI:
```bash
vyro-growth classify-replies --message-id <uuid>
vyro-growth classify-replies --lead-id <uuid>
vyro-growth classify-replies --limit 25
```

Worker job name: `classify_inbound_replies`

Intents: `interested`, `not_interested`, `unsubscribe`, `wrong_person`, `out_of_office`, `referral`, `needs_more_info`, `meeting_request`, `hostile`, `spam`, `unknown`.

Conservative state rules:

- `contacted` can move to `replied`, then `interested` for genuine interest or a meeting request
- meeting requests never create calendar events and never move to `meeting_ready` or `meeting_booked`
- explicit unsubscribe / opt-out creates or confirms a permanent suppression and moves the lead to `suppressed` when the current stage allows it
- out-of-office and spam do not advance the lead
- a reply on a `discovered` or `ready_for_outreach` lead does not jump into `contacted`

Each run writes:

- a `reply_classifications` row (reused on the same inbound message, provider id, or content hash)
- conversation status/summary updates
- an `activities` audit row (`reply_classified`, `reply_skipped`, `reply_suppressed`, `reply_blocked`, `reply_unknown`, or `reply_classification_failed`)

`OUTBOUND_ENABLED` remains false by default. Persistent operator halt is preserved. Live OpenAI classification is gated behind `OPENAI_REPLY_CLASSIFICATION_ENABLED=false` unless explicitly enabled with a key; tests never require that key.

## Phase 8 — Dry-run calendar booking planning

Prepare and audit meeting drafts from already-consented contexts without creating calendar events or Google Meet links. CI and default local development use a deterministic calendar stub. Live Google Calendar is not called.

CLI:
```bash
vyro-growth plan-booking --lead-id <uuid>
vyro-growth plan-booking --classification-id <uuid>
vyro-growth plan-booking --lead-id <uuid> --operator-request --request-key ops-1
vyro-growth plan-booking --limit 25 --state TX
```

Worker job name: `plan_booking_slots`

Eligible booking contexts need one of:

- a stored inbound reply classified as `meeting_request`
- an explicit operator-created booking request (`--operator-request`)

Mere `interested` replies are not enough. Email, domain, and organization suppressions skip the lead with an audited reason. Re-running the same lead/contact/classification/request key reuses the existing booking plan.

Each run writes:

- `booking_plans` rows (`planned`, `skipped`, `suppressed`, or `blocked`) with proposed slots, requested window if present, provider name, status, idempotency key, and audit JSON
- a `booking_plan_runs` audit row
- `activities` audit rows

No Google Calendar event is created, no Google Meet link is created, no email is sent, no calls are placed, and no live campaign enrollment occurs. Lead stage may move from `interested` or `qualification_pending` to `meeting_ready` and never to `meeting_booked`. `OUTBOUND_ENABLED` remains false by default. `GOOGLE_CALENDAR_LIVE_ENABLED=false`; tests never require a live key.

## Phase 9 — Consent-based voice qualification (dry-run)

Prepare and audit voice qualification drafts from already-consented contexts without placing calls. CI and default local development use a deterministic stub. Live voice providers are not called.

CLI:
```bash
vyro-growth plan-voice-qualification --lead-id <uuid>
vyro-growth plan-voice-qualification --message-id <uuid>
vyro-growth plan-voice-qualification --meeting-id <uuid>
vyro-growth plan-voice-qualification --lead-id <uuid> --operator-request \
  --consent-timestamp 2026-08-30T15:00:00+00:00 --permitted-phone 5551112222 \
  --consent-evidence-id ops-1 --request-key ops-1
vyro-growth plan-voice-qualification --limit 25 --state TX
```

Worker job name: `plan_voice_qualifications`

Eligible voice contexts need one of:

- a stored inbound reply that explicitly requests or approves a call
- an operator-created request with consent proof (`--operator-request` plus timestamp, channel/source, and permitted phone)
- a stored meeting or booking plan that includes permission to call

Mere `interested` or `meeting_request` replies without call-approval language are not enough. Missing consent proof, suppressions, operator halt on live adapters, and suspected PHI skip or block the plan with an audited reason. Re-running the same lead/contact/consent/request key reuses the existing plan.

Each run writes:

- `voice_qualification_plans` rows (`planned`, `skipped`, `suppressed`, or `blocked`) with consent proof fields, safe B2B facts, provider name, status, idempotency key, and audit JSON
- a `voice_qualification_runs` audit row
- `activities` audit rows

No phone call is placed, no email is sent, no Google Calendar event or Meet link is created, no meeting is booked, and no live campaign enrollment occurs. `OUTBOUND_ENABLED` remains false by default. `VOICE_LIVE_ENABLED=false`; tests never require a live key.

## Phase 10 — Operator dashboard foundation (read-only)

Inspect pipeline health, dry-run activity, and safety status without enabling outreach, booking, or live providers. There is no frontend in this phase.

CLI:
```bash
vyro-growth dashboard-summary
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/dashboard/summary \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/dashboard/safety \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

The summary includes:

- discovered organizations and leads, including lead-stage counts
- website enrichment coverage and decision-maker contact counts
- latest ICP score bands
- personalization drafts
- outreach, booking, and voice qualification plan counts (planned/skipped/suppressed/blocked)
- reply classification intent/outcome counts
- suppressions and persistent operator halt
- latest run timestamp/status per phase
- safety flags: `OUTBOUND_ENABLED`, live-provider defaults, live calendar/Meet/call artifact counts

Responses are counts and statuses only. They do not include message bodies, draft copy, emails, phones, or PHI. The service does not write pipeline rows, send email, place calls, book meetings, or call live providers. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 11 — Growth optimizer foundation (dry-run)

Analyze stored dashboard/pipeline metrics and produce recommendation drafts for operator review. This layer does not apply recommendations, change campaigns or scoring thresholds, send email, place calls, book meetings, or call live providers.

CLI:
```bash
vyro-growth recommend-growth
```

Worker job name: `generate_growth_recommendations`

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl -X POST http://localhost:8000/internal/optimizer/run \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/optimizer/recommendations \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Each recommendation includes:

- category (ICP thresholds, specialty/geography signals, website or decision-maker coverage, personalization readiness, outreach plan patterns, reply intent trends, booking/voice bottlenecks, or safety risk)
- priority, confidence, rationale, and source metric references
- generated timestamp
- `approval_status=pending_operator_review`
- `applied=false`

Identical sanitized snapshots reuse the existing optimizer run. Output is counts and review text only: no message bodies, draft copy, emails, phones, evidence snippets, or PHI. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged. No live AI or paid/external provider is called.

## Phase 12 — Production deployment foundation

Make the service deployable and operable without turning on live outreach. This phase adds fail-closed production config, health/readiness probes, a hardened container image, Compose ops profiles, and a runbook. It does not deploy to a public cloud or call paid providers.

```bash
vyro-growth check-config
vyro-growth worker --check
vyro-growth worker --list
docker compose --profile ops run --rm migrate
```

See `docs/DEPLOYMENT.md` for required environment variables, migration order, worker/scheduler assumptions, backup/restore, and rollback. `OUTBOUND_ENABLED` and every live-provider flag remain false by default. Persistent operator halt is unchanged.

## Phase 13 — Observability and audit monitoring foundation

Inspect job/run health, sanitized failures, safety flags, Phase 12 readiness, and pending operator-review counts without enabling outreach or live providers.

CLI:

```bash
vyro-growth system-status
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/monitoring/status \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

The snapshot includes:

- latest run status by phase and deployable job name
- recent failures with redacted error text
- safety flags: `OUTBOUND_ENABLED`, operator halt, live-provider flags, live artifact counts
- Phase 12 readiness/config state and `ready_for_manual_rollout`
- pending review counts for drafts, enrollment plans, booking plans, voice plans, optimizer recommendations, acquisition channel plans, and content briefs
- findings with severity `blocked`, `warning`, or `info`

Responses are counts, statuses, and sanitized messages only. They do not include message bodies, draft copy, emails, phones, evidence snippets, API keys, or PHI. The service does not write pipeline rows, send email, place calls, book meetings, or call live providers. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

See `docs/OPERATOR_HEALTH.md` for the pre-rollout checklist.

## Phase 14 — Operator review queue (decision recording only)

List pending dry-run artifacts in one queue and record `approved`, `rejected`, or `needs_changes`. Recording a decision does not execute the artifact: no email, live enrollment, calendar event, Meet link, phone call, autonomous reply, or optimizer apply.

CLI:
```bash
vyro-growth review-queue
vyro-growth review-queue --include-decided
vyro-growth record-review --artifact-type personalization_draft --artifact-id <uuid> --decision approved
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/review-queue \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl -X POST http://localhost:8000/internal/review-queue/decisions \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"artifact_type":"optimizer_recommendation","artifact_id":"<uuid>","decision":"approved"}'
```

Each review item includes:

- artifact type and id
- lead/organization UUIDs when present
- sanitized title/summary
- current status and created timestamp
- risk/safety labels
- `executable_later` (a later phase may execute an approved item; this phase never does)
- `executed=false`

Pending artifacts include personalization drafts, outreach enrollment plans, reply follow-up classifications, booking plans, voice qualification plans, optimizer recommendations, acquisition channel plans, and content briefs.

Output is IDs, statuses, and sanitized labels only: no message bodies, draft copy, emails, phones, evidence snippets, or PHI. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 15 — Acquisition channel planning foundation (dry-run)

Plan non-outbound acquisition channels from stored specialty/geography aggregates and explicit operator seed inputs. This layer does not launch campaigns, publish pages, spend money, or call live ad/SEO/search providers.

CLI:
```bash
vyro-growth plan-acquisition-channels
vyro-growth plan-acquisition-channels --seed-specialty "Family Medicine" --seed-state TX \
  --seed-keyword "medical billing" --seed-partner-type "specialty association"
vyro-growth list-channel-plans
```

Worker job name: `generate_channel_plans`

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl -X POST http://localhost:8000/internal/channel-plans/run \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"seed_specialty":"Family Medicine","seed_state":"TX"}'
curl http://localhost:8000/internal/channel-plans \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Each plan includes:

- channel (`google_search_ads`, `seo_content`, `referral_partner`, or `specialty_geography`)
- plan type (keyword group, landing-page topic, partner campaign, or positioning)
- title/summary
- target specialty/geography/ICP only when safely known from stored aggregates or seeds
- source metric or seed input references
- priority, confidence, generated timestamp
- `approval_status=pending_operator_review`
- dry-run/no-spend flags; launch and spend remain false

Identical sanitized snapshots and seeds reuse the existing run. Pending plans appear in `vyro-growth review-queue` as `acquisition_channel_plan`. Recording an approval does not launch, publish, or spend. Output is counts and review text only: no message bodies, draft copy, emails, phones, evidence snippets, or PHI. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged. No live ad, SEO, search, or paid/external provider is called.

## Phase 16 — Landing page brief and SEO content draft foundation

Generate review-only landing page and SEO content briefs from stored aggregate ICP signals, pending Phase 15 acquisition channel plans, and explicit safe operator seeds. This layer does not publish pages, commit website content, launch ads, spend money, send email, or call OpenAI, Google Ads, Search Console, Analytics, SEO, or search APIs.

CLI:
```bash
vyro-growth draft-content-briefs
vyro-growth draft-content-briefs --specialty "Family Medicine" --brief-type specialty_landing_page
vyro-growth list-content-briefs
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl -X POST http://localhost:8000/internal/content-briefs/generate \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"seeds":[{"brief_type":"seo_article","specialty":"Family Medicine","topic":"billing operations questions"}]}'
curl http://localhost:8000/internal/content-briefs \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Worker job name: `generate_content_briefs`

Each brief includes type, optional channel-plan id, known specialty/geography/ICP only, title, sanitized summary, outline sections, CTA concept, compliance notes, source metric/seed references, confidence/priority, generated timestamp, `pending_operator_review`, and `published=false`. Approval in the review queue records a decision only and does not publish. Unverifiable claims (clients, savings, certifications, years of experience, case studies, testimonials, provider counts, revenue improvement) and patient-facing medical advice are omitted.

## Phase 17 — Approved-item execution plan foundation (dry-run)

Turn operator-approved review artifacts into structured, auditable execution plans without performing the underlying live action. This layer does not send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish pages, launch ads, spend money, deploy, or apply optimizer recommendations.

CLI:
```bash
vyro-growth plan-approved-execution
vyro-growth plan-approved-execution --artifact-type personalization_draft
vyro-growth list-execution-plans
```

Worker job name: `generate_execution_plans`

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl -X POST http://localhost:8000/internal/execution-plans/run \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
curl http://localhost:8000/internal/execution-plans \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Each plan includes source review decision id, artifact type/id, plan type, proposed action, prerequisites/checklist, blockers and readiness status, safety notes, required owner approvals, dry-run/no-execution flags, generated timestamp, and an idempotency key. Non-approved artifacts are ignored. Identical approved-set fingerprints reuse the existing run. Output is IDs, statuses, and sanitized labels only: no message bodies, draft copy, emails, phones, evidence snippets, or PHI. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 18 — Live-readiness preflight and owner approval packets (no execution)

Inspect dry-run execution plans and safe local/config metadata to produce sanitized owner approval packets. This layer does not send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish pages, launch ads, spend money, deploy, or apply optimizer recommendations.

CLI:
```bash
vyro-growth generate-approval-packets
vyro-growth generate-approval-packets --plan-type outreach_enrollment
vyro-growth list-approval-packets
```

Worker job name: `generate_approval_packets`

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl -X POST http://localhost:8000/internal/approval-packets/run \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
curl http://localhost:8000/internal/approval-packets \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Each packet includes source execution plan id/run id, artifact type/id, sanitized proposed action, preflight checklist, missing prerequisites, blocked/warning/info findings, required owner decisions, dry-run/no-execution flags, generated timestamp, and an idempotency key. Preflight reports whether required settings are present or absent and never prints secret values. Identical plan-set fingerprints reuse the existing run. Output is IDs, statuses, and sanitized labels only: no message bodies, draft copy, emails, phones, evidence snippets, API keys, or PHI. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 19 — Operator command center summary (read-only)

Aggregate existing safe pipeline artifacts into one sanitized operator summary. This layer does not send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish pages, launch ads, spend money, deploy, or apply optimizer recommendations.

CLI:
```bash
vyro-growth operator-command-center
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/operator-command-center \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

The summary includes pipeline counts, latest run statuses, readiness, blocked/warning/info finding counts, outstanding review counts, approval packet counts, and safe next-action labels. Output is IDs, statuses, counts, timestamps, and redacted labels only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 20 — Read-only operator dashboard UI shell

Open one internal HTML view of the sanitized command-center summary. This layer does not send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish pages, launch ads, spend money, deploy, apply optimizer recommendations, or change live/scoring/campaign/provider/deployment settings.

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/operator-dashboard \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

The page is a quiet, dense operator view: overall status and readiness, outbound-disabled and operator-halt safety, pipeline counts, latest run statuses, outstanding review counts, approval packet/preflight counts, blocked/warning/info findings, and safe next-action labels. Optional `?section=` values (`safety`, `pipeline`, `runs`, `review`, `packets`, `findings`, `actions`) are read-only filters. There are no execute/send/enroll/book/call/publish/spend/deploy controls.

Rendered HTML is counts, statuses, timestamps, and redacted labels only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. Empty databases show empty states. Render failures return a sanitized error page. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 21 — Read-only review queue and approval packet UI drilldowns

Open internal HTML list/detail views of the existing review queue and owner approval packets. These pages do not record new decisions, execute artifacts, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish pages, launch ads, spend money, deploy, apply optimizer recommendations, or change live/scoring/campaign/provider/deployment settings.

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/operator-review-queue \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl "http://localhost:8000/internal/operator-review-queue?include_decided=true&status=approved" \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-approval-packets \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl "http://localhost:8000/internal/operator-approval-packets?plan_family=outreach_enrollment&preflight_status=blocked" \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

The Phase 20 dashboard links to both drilldowns. Review-queue filters include artifact type, status, and include-decided. Approval-packet filters include plan family and preflight status. Detail pages show sanitized titles/labels/categories, blocked/warning/info counts and codes, required owner decision labels, timestamps, and dry-run/no-execution flags. Review-item and approval-packet detail pages include a decision-record form; they do not execute.

Rendered HTML is IDs, statuses, counts, timestamps, and redacted labels only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. Empty and unmatched filters show empty states. Missing items and render failures return sanitized pages. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 22 — Operator review decision UI forms

Record `approved`, `rejected`, or `needs_changes` from a review-item detail page. This writes a decision/audit record through the existing review-queue service. It does not execute the artifact, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish pages, launch ads, spend money, deploy, apply optimizer recommendations, approve owner approval packets for live readiness, or change live/scoring/campaign/provider/deployment settings or operator halt state.

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl -X POST http://localhost:8000/internal/operator-review-queue/optimizer_recommendation/<uuid>/decision \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "decision=approved&reviewer=ops&reviewer_notes=record+only"
```

The form accepts a decision value, an optional short reviewer label, and optional notes. Notes are sanitized/redacted before they are stored and again before they are rendered. A successful submit redirects to the detail page and shows the saved high-level decision metadata. Submitting the same decision twice, or refreshing after redirect, does not create a second decision row or execute anything. Invalid decisions and missing items return generic sanitized HTML. There is no execute control.

Rendered HTML is IDs, statuses, timestamps, redacted labels, and sanitized reviewer notes only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 23 — Owner approval packet decision UI (record only)

Record `approved`, `rejected`, or `needs_changes` from an approval-packet detail page. This writes a decision/audit record through the existing approval-packet service. It does not execute the packet, trigger the underlying live action, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish pages, launch ads, spend money, deploy, apply optimizer recommendations, set live owner-approved state, or change live/scoring/campaign/provider/deployment settings or operator halt state.

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl -X POST http://localhost:8000/internal/operator-approval-packets/<packet-uuid>/decision \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "decision=approved&reviewer=ops&reviewer_notes=record+only"
```

The form accepts a decision value, an optional short owner/reviewer label, and optional notes. Notes are sanitized/redacted before they are stored and again before they are rendered. A successful submit redirects to the packet detail page and shows the saved high-level decision metadata. Submitting the same decision twice, or refreshing after redirect, does not create a second decision row or execute anything. Invalid decisions and missing packets return generic sanitized HTML. Approval-packet list pages stay without a form. Review-queue decision UI is unchanged. There is no execute control.

Rendered HTML is IDs, statuses, timestamps, redacted labels, and sanitized owner notes only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 24 — Approved action readiness queue (read-only)

Show which stored review items, execution plans, and approval packets are theoretically ready, which remain blocked, and why. This layer combines existing records only. It does not generate new artifacts, execute approved items or packets, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish pages, launch ads, spend money, deploy, apply optimizer recommendations, set live owner-approved state, or change live/scoring/campaign/provider/deployment settings or operator halt state.

CLI:
```bash
vyro-growth action-readiness
vyro-growth action-readiness --plan-family outreach_enrollment --readiness-status missing_owner_packet_decision
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/action-readiness \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl "http://localhost:8000/internal/operator-action-readiness?readiness_status=preflight_blocked" \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

The queue shows candidate/action id, artifact type/id, plan family, review decision status, approval-packet decision status, preflight status, dry-run/no-execution flags, executed/live-action flags (false), blocker and missing-approval codes, timestamps, and sanitized labels. Readiness statuses include `blocked`, `missing_review_decision`, `missing_owner_packet_decision`, `preflight_blocked`, `approved_but_halted`, and `ready_pending_explicit_live_owner_action`. A ready-like status still requires a future explicit owner action before live execution. There are no execute/send/enroll/book/call/publish/spend/deploy controls.

Rendered HTML and JSON are IDs, statuses, counts, timestamps, codes, and redacted labels only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 25 — End-to-end dry-run smoke harness (local demo only)

Run one local-only dry-run smoke command against deterministic synthetic fixture data. This is not a live workflow. It does not scrape websites, call NPPES/search/Apollo/campaign/AI/calendar/voice/ad/SEO providers, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, deploy, apply optimizer recommendations, execute approved review items or approval packets, or set live `owner_approved`.

CLI:
```bash
vyro-growth smoke-dry-run --local-only
vyro-growth smoke-dry-run --dev-demo --json
```

Outside `ENVIRONMENT=development`, `--local-only` or `--dev-demo` is required. The command still refuses to run when `OUTBOUND_ENABLED` is true or any live-provider flag is enabled. The CLI uses an isolated in-memory demo database and does not write to `DATABASE_URL` or change operator halt on runtime data.

The command seeds a synthetic practice and lead plus safe public-business facts (no PHI), then exercises existing dry-run services: scoring, personalization, outreach planning, reply classification, booking, voice, optimizer, channel plans, content briefs, operator review decisions, execution plans, owner approval packets, packet decision records, and the action-readiness queue.

Output is a sanitized console or JSON summary: counts, statuses, blocker codes, readiness statuses, timestamps, and flags including `executed=0`, `live_action=false`, and `outbound_attempted=false`. It does not include PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, unsafe raw error text, or invented real-world prospect facts. `OUTBOUND_ENABLED` remains false by default.

## Phase 26 — CI dry-run smoke gate (no live providers)

CI runs the Phase 25 local-only smoke harness on every pull request without live providers, real data, outbound, bookings, calls, publishing, ads, deployment, or spending.

GitHub Actions job `smoke-dry-run`:

```bash
vyro-growth smoke-dry-run --local-only --json
vyro-growth check-smoke-output --file "$RUNNER_TEMP/smoke-output.json"
```

The job sets `OUTBOUND_ENABLED=false` and every live-provider flag to false, unsets `DATABASE_URL` and provider credentials, and fails if the smoke command refuses unexpectedly or reports a live side effect. `check-smoke-output` requires sanitized JSON signals including `executed=0`, `live_action=false`, `outbound_attempted=false`, `owner_approved=false`, `dry_run_only=true`, `no_execution=true`, and `isolated_demo_database=true`. It also fails if the output includes PHI, real emails or phones, message bodies, outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw errors, or invented real-world prospect facts.

This gate is not a production workflow and does not change operator halt, live settings, or runtime data.

## Phase 27 — Launch readiness checklist (read-only)

Print a sanitized go/no-go checklist of what remains blocked before any live acquisition activity can be approved. This layer does not execute approved items or packets, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, deploy, call GitHub Actions or live providers, set live `owner_approved`, or change operator halt / outbound / live-provider settings. Secret values are never printed.

CLI:
```bash
vyro-growth launch-readiness
vyro-growth launch-readiness --json
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/launch-readiness \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Output is a sanitized console or JSON checklist: overall status (`blocked`, `warning`, or `ready_for_owner_review`), blocker codes, next-action labels, required configuration names, secret inventory as variable names plus present/missing/redacted status, operator halt, outbound and live-provider flag booleans, whether the CI smoke gate is documented, pending owner approval packet counts, and action-readiness blocker counts. The command exits nonzero only when overall status is `blocked`. `ready_for_owner_review` is not permission to enable outbound or lift halt.

## Phase 28 — Live settings change request queue (record only)

Record proposed live-settings changes for owner review without applying them. This layer does not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign settings, scoring thresholds, or operator halt. It does not set live `owner_approved`, call providers, send email, enroll campaigns, generate sendable replies, place calls, book meetings, publish content, launch ads, spend money, deploy, or execute approved packets, items, or settings requests. Secret values are never stored or printed.

CLI:
```bash
vyro-growth settings-change-requests
vyro-growth settings-change-requests --json --status pending
vyro-growth create-settings-change-request --request-type keep_outbound_disabled --setting-name OUTBOUND_ENABLED
vyro-growth create-settings-change-request --request-type request_provider_live_flag_review --setting-name SMARTLEAD_LIVE_ENABLED
vyro-growth settings-change-request --id <uuid> --json
vyro-growth record-settings-change-decision --id <uuid> --decision approved
vyro-growth propose-settings-changes --json
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/settings-change-requests \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl -X POST http://localhost:8000/internal/settings-change-requests \
  -H "Content-Type: application/json" \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
  -d '{"request_type":"keep_outbound_disabled","requested_setting_names":["OUTBOUND_ENABLED"]}'
curl -X POST http://localhost:8000/internal/settings-change-requests/propose-from-launch-readiness \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Request types: `keep_outbound_disabled`, `request_outbound_enablement_review`, `request_provider_live_flag_review`, `request_operator_halt_review`, `request_credential_configuration_review`, and `keep_safe_default`. Credential reviews name env/config variables only. Duplicate creates with the same idempotency key reuse the existing row. Recording `approved` is an audit record and does not apply the setting or lift halt. `vyro-growth launch-readiness` points at proposed requests without creating them unless `propose-settings-changes` is run.

## Phase 29 — Settings change request UI drilldowns (record only)

Open internal HTML list/detail views of Phase 28 live settings change requests. Recording a decision from a detail page writes the existing audit-only owner decision. It does not apply settings, lift operator halt, enable outbound, execute requests, send email, enroll campaigns, generate sendable replies, book meetings, create Meet links, place calls, publish pages, launch ads, spend money, deploy, or set live `owner_approved`.

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/operator-settings-change-requests \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl "http://localhost:8000/internal/operator-settings-change-requests?status=pending&request_type=keep_outbound_disabled" \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl -X POST http://localhost:8000/internal/operator-settings-change-requests/<request-uuid>/decision \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "decision=approved&reviewer=ops&reviewer_notes=record+only"
```

The Phase 20 dashboard, command-center next-action labels, and launch-readiness next-action labels link to this queue. Filters include request type, status, and owner decision status. Detail pages show sanitized request type, status, owner decision status, requested setting names, desired boolean/status, finding/next-action codes, timestamps, source, and record-only/no-execution flags. The form accepts a decision value, an optional short owner/reviewer label, and optional notes. Notes are sanitized/redacted before they are stored and again before they are rendered. A successful submit redirects to the detail page and shows the saved high-level decision metadata. Submitting the same decision twice, or refreshing after redirect, does not create a second decision row or apply anything. Invalid decisions and missing requests return generic sanitized HTML. There is no apply, execute, enable outbound, or lift-halt control.

Rendered HTML is IDs, statuses, setting names, codes, timestamps, redacted labels, and sanitized owner notes only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 30 — Approved settings execution preflight simulator (dry-run only)

Evaluate recorded settings-change requests and owner decisions and explain what would still block real execution. This layer does not apply settings, lift operator halt, enable outbound, execute requests, set live `owner_approved`, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, deploy, or call live providers. It is not permission or machinery for going live.

CLI:
```bash
vyro-growth settings-execution-preflight
vyro-growth settings-execution-preflight --json
vyro-growth settings-execution-preflight --json --decision-status approved
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/settings-execution-preflight \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl "http://localhost:8000/internal/settings-execution-preflight?decision_status=approved" \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Output is a sanitized console or JSON simulation: request IDs, request types, decision status, setting names, desired booleans/statuses, blocker/gate codes, missing credential names, timestamps, counts, and no-execution flags. Live execution gates stay closed. `execution_allowed` remains false because a future explicitly approved execution phase does not exist. There is no apply/execute endpoint or button.

JSON is IDs, statuses, setting names, codes, timestamps, counts, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 31 — Settings execution preflight UI shell (read-only)

Open an internal HTML view of the Phase 30 settings-execution preflight simulator. Operators can inspect remaining go-live blockers in the browser. This layer does not apply settings, lift operator halt, enable outbound, execute requests, set live `owner_approved`, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, deploy, or call live providers. It is a read-only blocker view, not permission or machinery for going live.

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/operator-settings-execution-preflight \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl "http://localhost:8000/internal/operator-settings-execution-preflight?decision_status=approved" \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

The Phase 20 dashboard, command-center next-action labels, launch-readiness next-action labels, and settings change request UI link to this page. Filters include request type, decision status, and execution status. The page shows overall status, request/decision counts, blocker/gate/approval codes, missing credential variable names, closed provider flag names, request IDs/types, decision status, desired booleans/statuses, timestamps, and no-execution flags. There are no apply, execute, lift-halt, enable-outbound, provider, deploy, campaign, booking, call, publish, or spend controls.

Rendered HTML is IDs, statuses, setting names, codes, timestamps, counts, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 32 — Owner go-live handoff packet export (read-only)

Export a single sanitized owner-review packet that consolidates launch readiness, settings change requests, settings execution preflight, owner approval packets, and approved action readiness. This layer does not apply settings, lift operator halt, enable outbound, execute requests, packets, or approved items, set live `owner_approved`, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, deploy, or call live providers. It is for manual owner review only and is not permission or machinery for going live.

CLI:
```bash
vyro-growth owner-handoff-packet
vyro-growth owner-handoff-packet --json
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/owner-handoff-packet \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Output is a sanitized Markdown or JSON packet with sections for launch readiness, settings change requests, settings execution preflight, owner approval packets, approved action readiness, and the remaining manual owner checklist. Fields are statuses, counts, blocker/gate/approval codes, request IDs, packet IDs, candidate IDs, setting names, desired booleans/statuses, missing credential variable names, closed provider flag names, timestamps, and no-execution flags. `execution_allowed` and `go_live_permitted` remain false because a future explicitly approved execution phase does not exist. There is no apply/execute endpoint or button.

JSON is IDs, statuses, setting names, codes, timestamps, counts, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 33 — Owner go-live handoff packet UI shell (read-only)

Open an internal HTML view of the Phase 32 owner go-live handoff packet. Operators can inspect the consolidated manual-review packet in the browser. This layer does not apply settings, lift operator halt, enable outbound, execute requests, packets, or approved items, set live `owner_approved`, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, deploy, or call live providers. It is a read-only manual-review view, not permission or machinery for going live.

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/operator-owner-handoff-packet \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

The Phase 20 dashboard, command-center next-action labels, launch-readiness next-action labels, settings change request UI, and settings execution preflight UI link to this page. The page shows the six handoff sections: launch readiness, settings change requests, settings execution preflight, owner approval packets, approved action readiness, and remaining manual owner checklist. Fields are statuses, counts, blocker/gate/approval codes, request IDs, packet IDs, candidate IDs, setting names, desired booleans/statuses, missing credential variable names, closed provider flag names, timestamps, and no-execution flags. The page states `go_live_permitted=false` and `execution_allowed=false`. There are no apply, execute, lift-halt, enable-outbound, provider, deploy, campaign, booking, call, publish, or spend controls.

Rendered HTML is IDs, statuses, setting names, codes, timestamps, counts, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 34 — Operator activity audit timeline UI (read-only)

Open an internal HTML timeline of existing activity, audit, and decision records. Operators can inspect recent system and decision history in the browser. This layer does not create, mutate, approve, reject, apply, execute, publish, deploy, spend, enroll, call, book, or contact anyone. It does not set live `owner_approved`, lift operator halt, enable outbound, or call live providers.

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/operator-audit-timeline \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl "http://localhost:8000/internal/operator-audit-timeline?event_type=operator_review_decision&status=approved&window=7d" \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

The Phase 20 dashboard, command-center next-action labels, launch-readiness next-action labels, and owner handoff packet UI link to this page. Filters include event type, source, status/decision, and date window. The page shows event type, sanitized actor/source labels, timestamps, status/decision, artifact/packet/request/candidate/run IDs, reason/code labels, and no-execution/read-only flags. There are no apply, execute, lift-halt, enable-outbound, provider, deploy, campaign, booking, call, publish, or spend controls.

Rendered HTML is IDs, statuses, codes, timestamps, labels, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 35 — Compliance evidence binder export (read-only)

Export a single sanitized owner-review binder that consolidates existing safety evidence: outbound disabled and operator halt, no-live-provider defaults, no-execution side effects, PHI/secrets/redaction, consent-based phone-only boundary, CI dry-run smoke and deploy-config gates, operator audit timeline, and open manual owner checklist items. This layer does not apply settings, lift operator halt, enable outbound, execute requests, packets, or approved items, set live `owner_approved`, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, deploy, or call live providers. It is for manual owner review only and is not permission or machinery for going live.

CLI:
```bash
vyro-growth compliance-evidence-binder
vyro-growth compliance-evidence-binder --json
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/compliance-evidence-binder \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Output is a sanitized Markdown or JSON packet with the evidence sections above plus compact reused summaries of launch readiness, settings execution preflight, and the owner handoff packet. Fields are statuses, counts, codes, no-execution flags, operator halt status, outbound/live-provider flag states, CI gate names, route/command names, sanitized timestamps, and missing credential variable names. `execution_allowed`, `go_live_permitted`, and `binder_is_not_go_live` remain false/true respectively because a future explicitly approved execution phase does not exist. There is no apply/execute endpoint or button.

JSON is statuses, setting names, codes, timestamps, counts, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 36 — Compliance evidence binder UI shell (read-only)

Open an internal HTML view of the Phase 35 compliance evidence binder. Operators can inspect the sanitized safety binder in the browser. This layer does not apply settings, lift operator halt, enable outbound, execute requests, packets, or approved items, set live `owner_approved`, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, deploy, or call live providers. It is a read-only owner-review view, not permission or machinery for going live.

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/operator-compliance-evidence-binder \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

The Phase 20 dashboard, command-center next-action labels, launch-readiness next-action labels, owner handoff packet UI, and operator audit timeline UI link to this page. The page shows all binder sections: outbound disabled/operator halt, no-live-provider defaults, no-execution side-effect evidence, PHI/secrets/redaction evidence, consent-based phone-only boundary, CI dry-run smoke/deploy-config gates, documented compliance guardrails, operator audit timeline summary, reused read-only summaries, and remaining manual owner checklist. Fields are statuses, counts, codes, no-execution flags, halt/outbound/live-provider states, CI gate names, route/command names, sanitized timestamps, and missing credential variable names. The page states `go_live_permitted=false`, `execution_allowed=false`, and `binder_is_not_go_live=true`. There are no apply, execute, lift-halt, enable-outbound, provider, deploy, campaign, booking, call, publish, or spend controls.

Rendered HTML is statuses, setting names, codes, timestamps, counts, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 37 — Release-candidate deployment runbook export (read-only)

Export a sanitized release-candidate deployment runbook that consolidates existing safety evidence into future-manual deployment steps, CI/local dry-run verification commands, safe environment defaults, operator halt and outbound-disabled checks, rollback instructions, post-deploy read-only verification, and remaining owner blockers. This layer does not deploy, apply settings, lift operator halt, enable outbound, execute requests, packets, or approved items, set live `owner_approved`, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, or call live providers. It is a runbook for future manual owner review only and is not a deployment mechanism or permission to go live.

CLI:
```bash
vyro-growth release-candidate-runbook
vyro-growth release-candidate-runbook --json
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/release-candidate-runbook \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Output is a sanitized Markdown or JSON packet with sections for release candidate identity and repo branch expectations, required CI gates and local dry-run verification commands, safe environment defaults and missing credential variable names only, operator halt and outbound-disabled verification, a manual deployment sequence as instructions only, a rollback checklist as instructions only, post-deploy read-only verification endpoints/commands, and unresolved blockers/manual owner checklist items. Fields are statuses, counts, codes, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text. `execution_allowed`, `go_live_permitted`, `deployment_allowed`, and `runbook_is_not_deployment` remain false/true respectively because a future explicitly approved execution/deployment phase does not exist. There is no apply/execute/deploy endpoint or button.

JSON is statuses, setting names, codes, timestamps, counts, command names, route names, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 38 — Release-candidate deployment runbook UI shell (read-only)

Open an internal HTML view of the Phase 37 release-candidate deployment runbook. The owner can inspect the future manual deployment plan, rollback checklist, safe defaults, and remaining blockers in the browser. This layer does not deploy, apply settings, lift operator halt, enable outbound, execute requests, packets, or approved items, set live `owner_approved`, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, or call live providers. It is a read-only owner-review view, not a deployment mechanism or permission to go live.

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/operator-release-candidate-runbook \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

The Phase 20 dashboard, command-center next-action labels, launch-readiness next-action labels, owner handoff packet UI, operator audit timeline UI, and compliance evidence binder UI link to this page. The page shows all runbook sections: release candidate identity and repo branch expectations, required CI gates and local dry-run verification commands, required safe environment defaults and missing credential variable names only, operator halt and outbound-disabled verification, a manual deployment sequence as instructions only, a rollback checklist as instructions only, post-deploy read-only verification endpoints/commands, documented guardrails, reused read-only summaries, and remaining unresolved blockers/manual owner checklist items. Fields are statuses, counts, codes, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text. The page states `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, and `runbook_is_not_deployment=true`. There are no apply, execute, lift-halt, enable-outbound, provider, deploy, campaign, booking, call, publish, or spend controls.

Rendered HTML is statuses, setting names, codes, timestamps, counts, command names, route names, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 39 — Release artifact manifest and provenance export (read-only)

Export a sanitized release artifact manifest that describes what would be included in a future release candidate: expected branch/SHA inputs, artifact paths, Alembic revision filenames/ids, runtime commands, container/deployment config files, safety gates, and remaining owner blockers. This layer does not build containers, publish artifacts, deploy, apply settings, lift operator halt, enable outbound, execute requests, packets, or approved items, set live `owner_approved`, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, or call live providers. It is an owner-review manifest only and is not a build, artifact publishing, deployment mechanism, or permission to go live.

CLI:
```bash
vyro-growth release-artifact-manifest
vyro-growth release-artifact-manifest --json
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/release-artifact-manifest \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Output is a sanitized Markdown or JSON packet with sections for source/provenance expectations, artifact inventory, migration inventory, runtime command inventory, safety gate inventory, no-build/no-deploy evidence, and unresolved blockers/manual owner checklist items. Local git metadata is read from `.git` files when present and never calls GitHub. Fields are statuses, counts, codes, filenames, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text. `execution_allowed`, `go_live_permitted`, `deployment_allowed`, `build_allowed`, `artifact_publish_allowed`, `runbook_is_not_deployment`, and `manifest_is_not_a_build_or_deploy` remain false/true respectively because a future explicitly approved execution/deployment/build phase does not exist. There is no build/publish/deploy endpoint or button.

JSON is statuses, setting names, codes, timestamps, counts, filenames, command names, route names, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 40 — Release artifact manifest UI shell (read-only)

Open an internal HTML view of the Phase 39 release artifact manifest. The owner can inspect release provenance, artifact inventory, migration inventory, runtime commands, safety gates, and remaining blockers in the browser. This layer does not build containers, publish artifacts, deploy, apply settings, lift operator halt, enable outbound, execute requests, packets, or approved items, set live `owner_approved`, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, or call live providers. It is a read-only owner-review view, not a build, artifact publishing, deployment mechanism, or permission to go live.

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/operator-release-artifact-manifest \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

The Phase 20 dashboard, command-center next-action labels, launch-readiness next-action labels, owner handoff packet UI, operator audit timeline UI, compliance evidence binder UI, and release-candidate runbook UI link to this page. The page shows all manifest sections: source and provenance expectations, artifact inventory, migration inventory, runtime command inventory, safety gate inventory, no-build/no-deploy evidence, reused read-only summaries, and remaining unresolved blockers/manual owner checklist items. Fields are statuses, counts, codes, filenames, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text. The page states `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `build_allowed=false`, `artifact_publish_allowed=false`, `runbook_is_not_deployment=true`, and `manifest_is_not_a_build_or_deploy=true`. There are no apply, execute, lift-halt, enable-outbound, provider, build, publish, deploy, campaign, booking, call, or spend controls.

Rendered HTML is statuses, setting names, codes, timestamps, counts, filenames, command names, route names, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 41 — Operator go-live readiness index UI (read-only)

Open an internal HTML index of existing owner/operator readiness, evidence, runbook, manifest, and audit surfaces. The owner can review statuses, counts, blocker codes, and remaining checklist items in one browser page. This layer does not build containers, publish artifacts, deploy, apply settings, lift operator halt, enable outbound, execute requests, packets, or approved items, set live `owner_approved`, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, or call live providers. It is a read-only index/review view, not permission to go live and not an execution surface.

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/operator-go-live-readiness-index \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

The Phase 20 dashboard, command-center next-action labels, launch-readiness next-action labels, owner handoff packet UI, operator audit timeline UI, compliance evidence binder UI, release-candidate runbook UI, and release artifact manifest UI link to this page. The page shows summary cards for operator dashboard/command center, launch readiness, settings execution preflight, owner handoff packet, compliance evidence binder, release-candidate runbook, release artifact manifest, and operator audit timeline, plus a manual owner checklist rollup. Fields are statuses, counts, codes, route names, command names, flag names/states, missing credential variable names, sanitized timestamps, and checklist labels. The page states `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `build_allowed=false`, `artifact_publish_allowed=false`, `OUTBOUND_ENABLED=false`, and that this is an index/review view only. There are no apply, execute, lift-halt, enable-outbound, provider, build, publish, deploy, campaign, booking, call, or spend controls.

Rendered HTML is statuses, setting names, codes, timestamps, counts, route names, command names, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 42 — Go-live readiness index CLI and JSON export (read-only)

Export the existing Phase 41 go-live readiness index as sanitized Markdown or JSON. This is the same rollup as the HTML index, for owner review and future monitoring without using the browser UI. This layer does not build containers, publish artifacts, deploy, apply settings, lift operator halt, enable outbound, execute requests, packets, or approved items, set live `owner_approved`, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, or call live providers. It is a review export only, not permission to go live and not an execution surface.

CLI:
```bash
vyro-growth go-live-readiness-index
vyro-growth go-live-readiness-index --json
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/go-live-readiness-index \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Output is a sanitized Markdown or JSON packet with the same safe readiness rollup: operator dashboard / command center, launch readiness, settings execution preflight, owner handoff packet, compliance evidence binder, release-candidate runbook, release artifact manifest, operator audit timeline counts, live-blocking flags, and the manual owner checklist rollup. Fields are statuses, counts, codes, routes, commands, flag names/states, missing credential variable names, sanitized timestamps, and checklist labels. `execution_allowed`, `go_live_permitted`, `deployment_allowed`, `build_allowed`, and `artifact_publish_allowed` remain false. `OUTBOUND_ENABLED=false`. The export states it is not permission to go live. There is no apply/execute/deploy/build/publish endpoint or button.

JSON is statuses, setting names, codes, timestamps, counts, route names, command names, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 43 — Launch blockers remediation plan export (read-only)

Export existing Phase 42 go-live readiness index blockers as a sanitized remediation plan. This layer reuses the index as the source of truth and does not recalculate readiness. It does not build containers, publish artifacts, deploy, apply settings, lift operator halt, enable outbound, execute requests, packets, or approved items, set live `owner_approved`, send email, enroll campaigns, generate sendable replies, place calls, book meetings, create Meet links, publish content, launch ads, spend money, or call live providers. It is a remediation planning export only, not permission to go live and not an execution surface.

CLI:
```bash
vyro-growth launch-blockers-plan
vyro-growth launch-blockers-plan --json
```

Internal HTTP (not a public API). In local development it may run without a key. Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/launch-blockers-plan \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

Output is a sanitized Markdown or JSON packet grouped by readiness surface or blocker category. Each step includes blocker code, surface key/label, current status, recommended manual remediation step, required owner approval type if any, step kind (configuration, credential, legal/compliance, deployment, provider setup, or manual review), and safe route/CLI/config-name references. `execution_allowed`, `go_live_permitted`, `deployment_allowed`, `settings_applied`, `halt_changed`, and `owner_approved` remain false. `OUTBOUND_ENABLED=false`. The export states it is not permission to go live. There is no apply/execute/deploy/build/publish endpoint or button.

JSON is statuses, setting names, codes, timestamps, counts, route names, command names, and flags only: no PHI, emails, phones, message bodies, draft copy, evidence snippets, API keys, tokens, provider secrets, env secret values, or unsafe raw error text. `OUTBOUND_ENABLED` remains false by default. Operator halt is read and left unchanged.

## Phase 1

Production foundation:

- Python 3.12+
- FastAPI
- SQLAlchemy 2.x
- PostgreSQL / Supabase-compatible persistence
- Pydantic v2
- Alembic migrations
- Background-worker abstraction
- Structured logging
- Docker / Docker Compose
- pytest, Ruff, mypy where practical
- Lead state machine
- Kill switch and suppression primitives
- Provider interfaces for future integrations

See `docs/ROADMAP.md` for the full build sequence.
