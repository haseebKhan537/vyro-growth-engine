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

## Production runtime validation
- Outside `development`, process start fails closed unless `INTERNAL_API_KEY` and `DATABASE_URL` are set.
- `vyro-growth check-config` performs the same validation without connecting to Smartlead, Apollo, OpenAI, Google Calendar, voice, or other paid providers.
- If a live-provider flag is true, its corresponding key is required. Defaults keep every live flag false.
- `/ready` reports config issues and database availability. It must not call live providers or return secrets.

## Internal HTTP triggers
- `POST /internal/discovery/nppes`, `GET /internal/dashboard/summary`, `GET /internal/dashboard/safety`, `GET /internal/monitoring/status`, `GET /internal/operator-command-center`, `GET /internal/operator-dashboard`, `GET /internal/operator-review-queue`, `POST /internal/operator-review-queue/{artifact_type}/{artifact_id}/decision`, `GET /internal/operator-approval-packets`, `POST /internal/operator-approval-packets/{packet_id}/decision`, `GET /internal/operator-action-readiness`, `GET /internal/action-readiness`, `GET /internal/review-queue`, `POST /internal/review-queue/decisions`, `POST /internal/execution-plans/run`, and `GET /internal/execution-plans` are internal operator routes, not a public API.
- NPPES discovery itself remains a non-outbound ingestion job. CLI (`vyro-growth discover-nppes`) and worker job `discover_nppes_practices` do not use the HTTP key.
- Dashboard, monitoring, command-center, operator-dashboard, operator review-queue UI, operator approval-packet UI, and operator action-readiness UI routes are read-only. CLI (`vyro-growth dashboard-summary`, `vyro-growth system-status`, `vyro-growth operator-command-center`, `vyro-growth action-readiness`) does not use the HTTP key and does not write pipeline state. The HTML dashboard and drilldowns are HTTP-only and do not change operator halt state.
- Review-queue list is read-only over stored artifacts. `record-review` writes a decision and audit row only; it does not execute the artifact.
- These routes require explicit authorization via `INTERNAL_API_KEY` and the `X-Internal-Api-Key` header.
- Outside development, a missing or blank `INTERNAL_API_KEY` fails closed. A missing or invalid request key is rejected.
- In development, an empty configured key is allowed for local use. If a key is configured, the request must match it.
- Do not expose these routes on a public ingress. Prefer CLI or worker execution in deployed environments.

## Secrets
- Never commit API keys, passwords, OAuth refresh tokens, SMTP credentials, or private keys.
- Use environment variables or deployment secret stores.
- `.env` is gitignored. `.dockerignore` excludes `.env` from images.
- Loggers must redact credentials and authorization headers, including `X-Internal-Api-Key`.
- Container images and Compose defaults keep `OUTBOUND_ENABLED` and live-provider flags false.

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

## Booking plan integrity
- Phase 8 plans dry-run meeting drafts only. It does not create Google Calendar events or Google Meet links.
- Accept only stored `meeting_request` reply classifications or explicit operator-created booking requests. Do not infer consent from generic interest.
- Use only stored public/business identifiers and requested windows supplied by the operator or stored request. Do not invent prospect availability, emails, phones, or practice facts.
- Honor email, domain, and organization-level suppressions. Fail closed if a suppression lookup cannot be completed.
- The default provider is a stub. `build_booking_calendar_provider()` never returns the live adapter. `GOOGLE_CALENDAR_LIVE_ENABLED=false` by default. CI and local tests do not require a live key.
- The guarded live adapter still requires outbound enablement and a lifted operator halt. Phase 8 does not open a default HTTP session; a future owner-approved step must inject a live client.
- Do not send email, generate sendable autonomous replies, place calls, or enroll live campaigns.
- Lead updates, if any, must use `ALLOWED_TRANSITIONS` and must not enter `meeting_booked`.
- `OUTBOUND_ENABLED` remains false by default. Operator halt semantics are unchanged.

## Voice qualification integrity
- Phase 9 plans dry-run consent-based voice qualification only. It does not place phone calls.
- Accept only explicit permission/consent contexts: a stored inbound reply requesting or approving a call, an operator-created request with consent proof, or a stored meeting/booking context that includes permission to call.
- Consent proof is required before a plan can be created. Persist source, timestamp, channel, evidence/reference id if available, and the permitted business phone. Missing proof is skipped or blocked with an audited reason.
- Do not implement indiscriminate cold AI robocalling. Phone automation is only for consent/inbound/permission-based contexts.
- Store only safe B2B qualification facts. Never invent prospect facts. If suspected PHI appears in an input payload, skip or block and audit the reason without persisting the PHI.
- Honor email, domain, organization, and phone suppressions. Fail closed if a suppression lookup cannot be completed.
- The default provider is a stub. `build_voice_qualification_provider()` never returns the live adapter. `VOICE_LIVE_ENABLED=false` by default. CI and local tests do not require a live key.
- The guarded live adapter still requires outbound enablement, documented consent, and a lifted operator halt. Phase 9 does not open a default HTTP session; a future owner-approved step must inject a live client.
- Do not send email, generate sendable autonomous replies, create calendar events, create Google Meet links, book meetings, or enroll live campaigns.
- `OUTBOUND_ENABLED` remains false by default. Operator halt semantics are unchanged.

## Dashboard integrity
- Phase 10 dashboard summaries are read-only. They do not send email, generate replies, place calls, book meetings, create calendar events or Meet links, enroll campaigns, or call live paid/external providers.
- Report counts, run statuses, timestamps, and safety flags only. Do not return message bodies, personalization copy, emails, phones, evidence snippets, voice facts, or other prospect/PHI fields.
- Do not invent prospect facts to fill empty metrics. Missing pipeline state is reported as zero or `not_started`.
- `OUTBOUND_ENABLED` remains false by default. Operator halt is displayed and must not be lifted by dashboard reads.

## Growth optimizer integrity
- Phase 11 recommendations are dry-run drafts for operator review. They are never auto-applied.
- Do not change campaigns, scoring thresholds, provider settings, outbound behavior, calendars, or voice flows from this layer.
- Use only stored dashboard/pipeline counts and public/business aggregates. Do not invent prospect facts, emails, phones, message copy, or conversion outcomes.
- Do not return message bodies, personalization copy, emails, phones, evidence snippets, or PHI in API/CLI output.
- Do not call live AI, Smartlead, Google Calendar, voice, or other paid/external providers. No optimizer AI provider is wired.
- Do not send email, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, create calendar events, or enroll campaigns.
- `OUTBOUND_ENABLED` remains false by default. Operator halt is read and must not be lifted by the optimizer.

## Deployment integrity
- Phase 12 is configuration, containers, probes, and runbooks only. It does not send email, enroll campaigns, create calendar events or Meet links, place calls, or enable autonomous replies.
- Do not commit secrets or bake credentials into images. `.dockerignore` must exclude `.env`.
- Production and other non-development environments fail closed when `INTERNAL_API_KEY` or `DATABASE_URL` is missing.
- Keep `OUTBOUND_ENABLED=false` and all live-provider flags disabled in `.env.example`, Dockerfile, and Compose defaults.
- Health and readiness checks must not call Smartlead, Apollo, OpenAI, Google Calendar, voice providers, or other paid/external services.
- Persistent operator halt semantics are unchanged. Deployment tooling must not lift the halt.

## Monitoring integrity
- Phase 13 operator status is read-only. It does not send email, generate replies, place calls, book meetings, create calendar events or Meet links, enroll campaigns, or call live paid/external providers.
- Report counts, run statuses, timestamps, safety flags, readiness/config state, and sanitized failures only. Do not return message bodies, personalization copy, emails, phones, evidence snippets, voice facts, API keys, or other prospect/PHI fields.
- Stored error messages must be redacted before they appear in CLI or HTTP output. If PHI-like tokens remain, replace the message with a safe placeholder.
- Do not invent prospect facts to fill empty metrics. Missing pipeline state is reported as zero or `not_started`.
- `OUTBOUND_ENABLED` remains false by default. Operator halt is displayed and must not be lifted by monitoring reads.

## Operator review queue integrity
- Phase 14 records operator decisions only. Approval is not execution.
- Do not send email, generate sendable autonomous replies, enroll live campaigns, create calendar events, create Google Meet links, place calls, or apply optimizer recommendations from this layer.
- Do not change scoring thresholds, campaign settings, provider settings, or live flags.
- Report sanitized titles, statuses, labels, and IDs only. Do not return message bodies, personalization copy, emails, phones, evidence snippets, voice facts, API keys, or other prospect/PHI fields.
- Sanitize reviewer notes on write. Do not persist or expose suspected PHI, emails, phones, or secrets from notes.
- Do not invent prospect facts to fill empty queue rows. Missing artifacts are an empty pending list.
- `OUTBOUND_ENABLED` remains false by default. Operator halt is read and must not be lifted by review listing or decision recording.

## Acquisition channel planning integrity
- Phase 15 channel plans are dry-run drafts for operator review. They never launch campaigns, publish pages, or spend money.
- Do not call Google Ads, Search Console, Analytics, SEO APIs, search APIs, Apollo, Smartlead, OpenAI, Google Calendar, voice providers, or other paid/external providers from this layer.
- Use only stored specialty/geography aggregates and explicitly supplied seed inputs. Do not invent prospect facts, partner names, search volume, CPC, or conversion outcomes.
- Drop seed inputs that look like emails, phones, secrets, or PHI. Missing facts remain missing.
- Do not return message bodies, personalization copy, emails, phones, evidence snippets, or PHI in API/CLI output.
- Do not send email, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, create calendar events, or enroll campaigns.
- Review-queue approval of a channel plan is a recorded decision only. It must not launch, publish, or spend.
- `OUTBOUND_ENABLED` remains false by default. Operator halt is read and must not be lifted by channel planning.

## Approved-item execution planning integrity
- Phase 17 execution plans are dry-run readiness records only. They never perform the underlying live action.
- Do not send email, enroll live campaigns, generate sendable autonomous replies, create calendar events, create Google Meet links, place calls, publish pages or content, launch ads, spend money, deploy, apply optimizer recommendations, or change scoring/campaign/provider settings.
- Do not call OpenAI, Smartlead, Apollo, Google Calendar, Google Ads, Search Console, Analytics, SEO/search, voice providers, or other paid/external providers from this layer.
- Read only approved operator review decisions and sanitized artifact metadata. Ignore pending, rejected, and needs-changes items.
- Do not invent prospect facts. Missing facts remain missing.
- Do not return message bodies, personalization copy, emails, phones, evidence snippets, API keys, provider secrets, or PHI in API/CLI output.
- Keep `executed`, `execution_attempted`, outbound, call, spend, launch, publish, and apply flags false.
- `OUTBOUND_ENABLED` remains false by default. Operator halt is read and must not be lifted by execution planning.

## Owner approval packet integrity
- Phase 18 owner approval packets are live-readiness records only. They never perform the underlying live action.
- Do not send email, enroll live campaigns, generate sendable autonomous replies, create calendar events, create Google Meet links, place calls, publish pages or content, launch ads, spend money, deploy, apply optimizer recommendations, or change scoring/campaign/provider settings.
- Do not call OpenAI, Smartlead, Apollo, Google Calendar, Google Ads, Search Console, Analytics, SEO/search, voice providers, or other paid/external providers from this layer.
- Preflight inspects only dry-run execution plans and safe local/config metadata. Report setting presence as boolean only. Never print API keys, tokens, provider secrets, or environment secret values.
- Do not invent prospect facts. Missing facts remain missing.
- Do not return message bodies, personalization copy, emails, phones, evidence snippets, API keys, provider secrets, or PHI in API/CLI output.
- Keep `executed`, `execution_attempted`, outbound, call, spend, launch, publish, and apply flags false.
- `OUTBOUND_ENABLED` remains false by default. Operator halt is read and must not be lifted by approval-packet generation.

## Operator command center integrity
- Phase 19 command-center output is a sanitized read-only summary. It never performs the underlying live action.
- Do not send email, enroll live campaigns, generate sendable autonomous replies, create calendar events, create Google Meet links, place calls, publish pages or content, launch ads, spend money, deploy, apply optimizer recommendations, or change scoring/campaign/provider/live/deployment settings.
- Do not call OpenAI, Smartlead, Apollo, Google Calendar, Google Ads, Search Console, Analytics, SEO/search, voice providers, or other paid/external providers from this layer.
- Return IDs, artifact types, statuses, counts, timestamps, redacted labels, and high-level category summaries only.
- Do not return PHI, emails, phones, message bodies, full outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw error text, or invented prospect facts.
- Keep executed, outbound, call, spend, launch, publish, and apply flags false.
- `OUTBOUND_ENABLED` remains false by default. Operator halt is read and must not be lifted by the command center.

## Operator dashboard UI integrity
- Phase 20 operator dashboard HTML is a sanitized read-only shell over the Phase 19 command-center summary. It never performs the underlying live action.
- Do not send email, enroll live campaigns, generate sendable autonomous replies, create calendar events, create Google Meet links, place calls, publish pages or content, launch ads, spend money, deploy, apply optimizer recommendations, or change scoring/campaign/provider/live/deployment settings or operator halt state.
- Do not call OpenAI, Smartlead, Apollo, Google Calendar, Google Ads, Search Console, Analytics, SEO/search, voice providers, or other paid/external providers from this layer.
- Render IDs, artifact types, statuses, counts, timestamps, redacted labels, and high-level category summaries only.
- Do not render PHI, emails, phones, message bodies, full outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw error text, or invented prospect facts.
- Do not add execute/send/enroll/book/call/publish/spend/deploy controls. Navigation and `section` filters are read-only.
- Keep executed, outbound, call, spend, launch, publish, and apply flags false.
- `OUTBOUND_ENABLED` remains false by default. Operator halt is read and must not be lifted by the dashboard UI.

## Operator review queue and approval packet UI integrity
- Phase 21 review-queue and approval-packet HTML pages are sanitized drilldowns. Phase 22 adds a decision-record form on review-item detail pages. Phase 23 adds a decision-record form on approval-packet detail pages. None of these layers perform the underlying live action.
- Do not send email, enroll live campaigns, generate sendable autonomous replies, create calendar events, create Google Meet links, place calls, publish pages or content, launch ads, spend money, deploy, apply optimizer recommendations, or change scoring/campaign/provider/live/deployment settings or operator halt state.
- Do not call OpenAI, Smartlead, Apollo, Google Calendar, Google Ads, Search Console, Analytics, SEO/search, voice providers, or other paid/external providers from this layer.
- Render artifact type/id, status, decision or preflight status, timestamps, safe titles/labels/categories, blocked/warning/info counts and codes, required owner decision labels, and dry-run/no-execution flags only.
- Sanitize and redact reviewer notes before persist and before any HTML/JSON render. Do not render PHI, emails, phones, message bodies, full outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw error text, or invented prospect facts.
- The HTML form may record `approved`, `rejected`, or `needs_changes` through the existing review-queue or approval-packet service. It must not execute approved items or packets. Recording an approval-packet decision must not set live owner-approved state.
- Validation errors must be generic. Double-submit and refresh must not create execution side effects or duplicate decision rows.
- Keep executed, outbound, call, spend, launch, publish, and apply flags false.
- `OUTBOUND_ENABLED` remains false by default. Operator halt is read and must not be lifted by these UI pages.

## Approved action readiness queue integrity
- Phase 24 action readiness is a sanitized read-only queue over stored review, plan, packet, and packet-decision records. It never performs the underlying live action.
- Do not generate new outreach, packets, plans, content, campaigns, meetings, calls, or provider actions from this layer.
- Do not send email, enroll live campaigns, generate sendable autonomous replies, create calendar events, create Google Meet links, place calls, publish pages or content, launch ads, spend money, deploy, apply optimizer recommendations, set live owner-approved state, or change scoring/campaign/provider/live/deployment settings or operator halt state.
- Do not call OpenAI, Smartlead, Apollo, Google Calendar, Google Ads, Search Console, Analytics, SEO/search, voice providers, or other paid/external providers from this layer.
- Render candidate/action id, artifact type/id, plan family, review and packet decision status, preflight status, dry-run/no-execution flags, executed/live-action flags, blocker and missing-approval codes, timestamps, and redacted labels only.
- Do not render PHI, emails, phones, message bodies, full outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw error text, or invented prospect facts.
- Do not add execute/send/enroll/book/call/publish/spend/deploy controls. A ready-like status still requires a future explicit owner action before live execution.
- Keep executed, outbound, call, spend, launch, publish, apply, and live owner-approved flags false.
- `OUTBOUND_ENABLED` remains false by default. Operator halt is read and must not be lifted by the readiness queue.

## Dry-run smoke harness integrity
- Phase 25 smoke is a local-only dry-run/demo over deterministic synthetic fixture data. It never performs a live workflow.
- Do not use real prospect data, PHI, real emails, or real phone numbers. Seed synthetic demo records only.
- Do not scrape websites or call NPPES, search, Apollo, campaign, generative-AI, calendar, voice, ad, or SEO providers.
- Do not send email, enroll live campaigns, generate sendable autonomous replies, create calendar events, create Google Meet links, place calls, publish pages or content, launch ads, spend money, deploy, apply optimizer recommendations, execute approved review items or approval packets, or set live owner-approved state.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt on runtime data. The CLI uses an isolated in-memory demo database.
- Refuse production/live execution unless `--local-only` or `--dev-demo` is present. Still refuse when outbound or a live-provider flag is enabled.
- Print IDs, statuses, counts, timestamps, blocker/readiness codes, and `executed=0` / `live_action=false` / `outbound_attempted=false` flags only.
- Do not print PHI, emails, phones, message bodies, full outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw error text, or invented real-world prospect facts.

## CI dry-run smoke gate integrity
- Phase 26 CI runs the Phase 25 local-only smoke harness on pull requests. It never performs a live workflow.
- Keep `OUTBOUND_ENABLED=false` and every live-provider flag disabled in the smoke job. Unset `DATABASE_URL` and provider credentials so CI cannot read live secrets for that gate.
- Fail the job if `vyro-growth smoke-dry-run --local-only --json` refuses unexpectedly or reports `executed`, `live_action`, `outbound_attempted`, `owner_approved`, or other live side-effect flags other than the dry-run defaults.
- `vyro-growth check-smoke-output` must require `dry_run_only=true`, `no_execution=true`, and `isolated_demo_database=true`.
- Fail CI if logs or JSON expose PHI, real emails, real phones, message bodies, full outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw errors, or invented real-world prospect facts.
- Do not call live providers, use real prospect data, execute approved items or packets, or change operator halt / live settings from CI.

## Launch readiness checklist integrity
- Phase 27 launch readiness is a sanitized read-only checklist over local config, operator halt, stored packets, the action-readiness queue, and the documented CI smoke gate. It never performs a live workflow.
- Do not call GitHub Actions, OpenAI, NPPES/search, Apollo, Smartlead, Google, calendar, voice, ads, SEO, analytics, deployment, or other live providers.
- Do not send email, enroll live campaigns, generate sendable autonomous replies, create calendar events, create Google Meet links, place calls, publish pages or content, launch ads, spend money, deploy, apply optimizer recommendations, execute approved review items or approval packets, or set live owner-approved state.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Print overall status, blocker codes, next-action labels, required configuration names, secret names with present/missing/redacted status, flag booleans, CI smoke-gate presence, pending packet counts, and action-readiness blocker counts only.
- Do not print PHI, emails, phones, message bodies, full outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw error text, or invented real-world prospect facts.
- `ready_for_owner_review` is not permission to enable outbound or lift halt.

## Live settings change request integrity
- Phase 28 live settings change requests are record-only owner-reviewable proposals. They never perform a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not set live `owner_approved`, call providers, send email, enroll campaigns, generate sendable replies, place calls, book meetings, publish content, launch ads, spend money, deploy, or execute approved packets, items, or settings requests.
- Store setting names and desired booleans/statuses only. Credential requests must name env/config variables and must never store secret values.
- Duplicate creates with the same idempotency key must not create duplicate rows. Decision records are audit-only and must not apply the setting or lift halt.
- Print request IDs, statuses, blocker/finding/next-action codes, requested setting names, desired booleans, owner decision status, timestamps, and no-execution flags only.
- Do not print PHI, emails, phones, message bodies, full outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw error text, or invented real-world prospect facts.

## Enrichment integrity
- AI-generated prospect facts are not authoritative.
- Store source URLs and confidence/evidence for material enrichment claims.
- Do not use unverifiable claims in personalization.

## Least privilege
Each provider integration should receive only the scopes required for its job. Production service accounts should be separate from personal accounts when possible.

## Separation from billing operations
Future HIPAA/RCM systems must be separate services/data stores with their own controls, access policies, BAAs, and audit requirements. Do not extend this sales database into a patient billing database.
