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
```

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
