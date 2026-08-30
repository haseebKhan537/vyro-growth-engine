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
