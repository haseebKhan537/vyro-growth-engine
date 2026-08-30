# Architecture

## System shape
Vyro Growth Engine is an event-driven sales automation platform. Core business rules live in the application/domain layer; third-party services are accessed only through provider adapters.

## Major components

### API
FastAPI exposes health, operator controls, webhook endpoints, and later dashboard/API resources.

### Database
PostgreSQL is the system of record for organizations, contacts, leads, evidence, outreach, conversations, meetings, activities, and suppressions.

### Workers
Background workers perform discovery, enrichment, scoring, campaign orchestration, reply processing, scheduling, and optimization. Worker execution must be idempotent where practical.

### Provider adapters
Integrations are isolated behind interfaces so providers can be replaced without rewriting the domain logic. Planned adapters include NPPES/CMS, Firecrawl/search, Apollo, Smartlead, OpenAI, Google Calendar/Meet, and a consent-based voice provider.

### Event flow
1. Practice discovered.
2. Practice normalized/deduplicated.
3. Evidence-backed enrichment completed.
4. Decision-maker/contact identified and verified.
5. Lead qualified/scored.
6. Suppression and global-send gates checked.
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
- Outbound defaults off.
- Suppression is checked immediately before external contact.
- No fabricated prospect facts.
- Material enrichment claims retain evidence/source URLs.
- External actions are auditable.
- No cold autonomous AI robocalling.

## Repository direction
`src/vyro_growth/` will evolve into layered packages: `api`, `domain`, `services`, `repositories`, `providers`, `workers`, and `observability`. Phase 1 begins compactly and will be refactored only when tests protect behavior.
