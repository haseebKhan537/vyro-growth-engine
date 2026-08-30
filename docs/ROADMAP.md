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

## Phase 4 — Decision-maker and contact enrichment
- Apollo adapter
- practice manager/administrator/owner targeting
- business email enrichment
- email verification
- suppression before qualification/outreach

## Phase 5 — AI qualification and scoring
- deterministic base scoring (started in Phase 3; remain local-only until AI rationale is grounded)
- AI-assisted rationale
- structured outputs
- evidence grounding
- specialty experiments
- lead budget allocation

## Phase 6 — Autonomous email outreach
- Smartlead adapter
- campaign assignment
- personalization grounded in evidence
- cadence engine
- send guardrails
- bounce/unsubscribe webhooks
- audit trail

## Phase 7 — Reply agent
- inbound webhook processing
- intent classification
- autonomous replies for approved classes
- escalation rules
- opt-out suppression
- pricing/information/objection handling

## Phase 8 — Calendar and Google Meet setter
- Google Calendar availability
- proposed time windows
- scheduling state machine
- recheck before booking
- Google Meet creation
- attendee invitation
- meeting brief generation

## Phase 9 — Consent-based voice agent
Only inbound leads, requested callbacks, or prospects with permission/consent to receive a call.
- call qualification
- meeting scheduling
- transcript and summary
- suppression/consent logging

## Phase 10 — Operator dashboard
- funnel metrics
- qualified meetings
- cost per meeting
- campaign performance
- source performance
- kill switch
- suppression search
- agent/audit timeline

## Phase 11 — Growth optimizer
- experiment framework
- specialty/region/contact-role attribution
- messaging tests
- spend allocation
- meeting/client conversion feedback

## Phase 12 — Production deployment
- managed PostgreSQL/Supabase
- worker/runtime deployment
- secret management
- monitoring and alerting
- backups
- CI/CD
- staged outbound rollout

## Phase 13 — Additional acquisition channels
- Google Ads
- SEO content/landing pages
- referral/partner campaigns
- inbound forms
- retargeting where appropriate
