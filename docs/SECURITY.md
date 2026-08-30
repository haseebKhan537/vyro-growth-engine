# Security and Compliance Guardrails

## Data boundary
This repository is a sales/prospecting system. It must not ingest, store, process, or transmit patient PHI.

## Outbound controls
- `OUTBOUND_ENABLED` defaults to `false`. No outreach-like action may proceed unless this is explicitly `true`.
- A second operator halt can still block outbound when the env flag is accidentally enabled:
  - settings-backed `OUTBOUND_HALTED` (defaults `false`)
  - persistent `operator_controls.outbound_halted` for the `global` key
- The persistent halt is seeded **halted**. Outbound requires both env enablement and an explicit operator lift via `set_operator_halt`.
- If the persistent halt row is missing or unreadable, the guard fails closed (`operator_halt_unavailable`).
- If a suppression lookup cannot be completed, the guard fails closed (`suppression_check_unavailable`).
- Actions without an identifiable email, domain, or phone fail closed (`target_unidentified`).
- Consent-based phone actions fail closed unless the caller passes `consent_to_call=True`. This is a gate only; there is no live dialer.
- Email, domain, organization, and phone suppressions are checked immediately before every outbound action.
- Future email, calendar, Smartlead, and consent-based phone adapters/workers must call `OutboundGuard.require_allowed` (or use the guarded wrappers / `SafetyCheckedWorkerRunner`) before sending, scheduling, enrolling, or dialing.
- Permanent unsubscribe records must be durable and honored across campaigns.
- Every external action must create an audit/activity record.

## Voice
Do not implement indiscriminate cold AI robocalling. Voice automation is restricted to inbound leads, requested callbacks, or prospects with documented permission/consent.

## Internal HTTP triggers
- `POST /internal/discovery/nppes` is an internal operator trigger, not a public API.
- NPPES discovery itself remains a non-outbound ingestion job. CLI (`vyro-growth discover-nppes`) and worker job `discover_nppes_practices` do not use the HTTP key.
- The HTTP trigger requires explicit authorization via `INTERNAL_API_KEY` and the `X-Internal-Api-Key` header.
- Outside development, a missing or blank `INTERNAL_API_KEY` fails closed. A missing or invalid request key is rejected.
- In development, an empty configured key is allowed for local use. If a key is configured, the request must match it.
- Do not expose this route on a public ingress. Prefer CLI or worker execution in deployed environments.

## Secrets
- Never commit API keys, passwords, OAuth refresh tokens, SMTP credentials, or private keys.
- Use environment variables or deployment secret stores.
- `.env` is gitignored.
- Loggers must redact credentials and authorization headers, including `X-Internal-Api-Key`.

## Official website fetching
- Website enrichment may fetch public HTTP(S) pages only. It is not outreach.
- Block login, portal, patient, appointment, billing-portal, and review paths.
- Reject private/reserved hosts and IP literals. Do not follow redirects into those targets.
- Bound every request with timeout, max bytes, max redirects, and inter-request delay.
- Do not send credentials, cookies, or authenticated session material.
- Do not scrape, store, or process patient data, portal data, appointment data, or reviews that include health details.
- Extract only allowlisted public B2B facts. Never invent a missing phone, email, count, or billing signal.
- Store source URL, extracted value, confidence, timestamp, and evidence snippet for each claim.
- Official website is persisted only after a conservative NPPES match (`verified`). Ambiguous and no-match runs leave `organizations.website` unchanged.

## Decision-maker contact enrichment
- Do not call a live paid contact provider in CI or local tests. The stub returns no invented people.
- Do not scrape LinkedIn or bypass provider terms.
- Store professional/business contact fields only. Do not invent names, titles, emails, phones, roles, or confidence. Unknown stays unknown.
- Drop irrelevant clinical contacts unless the record includes owner/operator evidence.
- Contact enrichment is not outreach. `OUTBOUND_ENABLED` remains false by default and operator halt semantics are unchanged.

## ICP scoring integrity
- Score only stored public/business evidence. Do not invent practice size, revenue, denials, A/R, payer mix, billing software, decision-makers, emails, phones, score evidence, or confidence.
- Unknown, missing, ambiguous, and conflicting facts remain unknown. Website-derived ICP signals require a verified website match.
- Billing/revenue-cycle points require an explicit stored claim. Do not infer billing software or financials.
- Scoring is not outreach. It must not send email, place calls, book calendar events, or contact prospects.
- Do not call Apollo, Smartlead, OpenAI, Google, Twilio, Vapi, Retell, or any live paid/external provider from scoring.
- `OUTBOUND_ENABLED` remains false by default. Operator halt semantics are unchanged.

## Personalization integrity
- Personalization drafts are evidence-grounded and outbound-disabled. They are not outreach.
- Use only stored public/business evidence and explicit prospect/business data. Do not invent practice facts, pain points, provider counts, revenue, denial rates, A/R, payer mix, billing software, contacts, emails, phones, testimonials, or Vyro performance claims.
- Unknown facts remain unknown and are listed as missing-data notes.
- Do not scrape patient data or collect PHI.
- Do not send email, place calls, book calendar events, or enroll leads.
- Do not call Apollo, Smartlead, Google, Twilio, Vapi, Retell, or any live paid/external provider from this layer.
- The OpenAI adapter is a guarded boundary. Default `OPENAI_PERSONALIZATION_ENABLED=false`. CI and local tests use the stub and do not require a live key. Never commit API keys.
- `OUTBOUND_ENABLED` remains false by default. Operator halt semantics are unchanged.

## Smartlead outreach planning
- Phase 6 plans dry-run campaign enrollments only. It does not send email or enroll leads into a live Smartlead campaign.
- Use only stored public/business evidence, scored leads, professional contacts, and Phase 5 personalization drafts. Do not invent practice facts, contacts, emails, phones, pain points, revenue, denial rates, A/R, payer mix, billing software, testimonials, or Vyro performance claims.
- Honor email, domain, and organization-level suppressions. Fail closed if a suppression lookup cannot be completed.
- The default provider is a stub. `build_smartlead_provider()` never returns the live adapter. `SMARTLEAD_LIVE_ENABLED=false` by default. CI and local tests do not require a live key.
- The guarded live adapter still requires outbound enablement and a lifted operator halt. Phase 6 does not open a default HTTP session; a future owner-approved step must inject a live client.
- Do not place calls, book calendar events, scrape patient data, or collect PHI.
- `OUTBOUND_ENABLED` remains false by default. Operator halt semantics are unchanged.

## Reply classification integrity
- Classification is dry-run only. It is not outreach and does not generate a reply to send.
- Operate from stored inbound message text/metadata or test fixtures. Do not poll a live mailbox or call Smartlead/OpenAI/Google/Twilio by default.
- Do not infer medical conditions, patient details, revenue, denial rates, A/R, payer mix, billing software, or other private business facts from a reply.
- Explicit unsubscribe / opt-out language must create or confirm a permanent suppression record.
- Lead/conversation updates are conservative and must use `ALLOWED_TRANSITIONS`. Never advance into `contacted` or `meeting_booked` from this layer. Do not book calendar events or create Google Meet links.
- The OpenAI reply classifier is a guarded boundary. Default `OPENAI_REPLY_CLASSIFICATION_ENABLED=false`. CI and local tests use the rule stub and do not require a live key. Never commit API keys.
- `OUTBOUND_ENABLED` remains false by default. Operator halt semantics are unchanged; classification must not lift the halt.

## Enrichment integrity
- AI-generated prospect facts are not authoritative.
- Store source URLs and confidence/evidence for material enrichment claims.
- Do not use unverifiable claims in personalization.

## Least privilege
Each provider integration should receive only the scopes required for its job. Production service accounts should be separate from personal accounts when possible.

## Separation from billing operations
Future HIPAA/RCM systems must be separate services/data stores with their own controls, access policies, BAAs, and audit requirements. Do not extend this sales database into a patient billing database.
