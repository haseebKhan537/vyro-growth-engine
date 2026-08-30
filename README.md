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
```

Expected response includes `"outbound_enabled": false`.

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

Identical reruns reuse the existing same-version score and do not create duplicate leads, activities, or outreach rows. Leads are not auto-qualified.

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
