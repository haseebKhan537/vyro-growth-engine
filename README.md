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
- A global outbound kill switch is mandatory.
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

Development API trigger:
```bash
curl -X POST http://localhost:8000/internal/discovery/nppes \
  -H "Content-Type: application/json" \
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
