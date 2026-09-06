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
- `POST /internal/discovery/nppes`, `GET /internal/dashboard/summary`, `GET /internal/dashboard/safety`, `GET /internal/monitoring/status`, `GET /internal/operator-command-center`, `GET /internal/operator-dashboard`, `GET /internal/operator-review-queue`, `POST /internal/operator-review-queue/{artifact_type}/{artifact_id}/decision`, `GET /internal/operator-approval-packets`, `POST /internal/operator-approval-packets/{packet_id}/decision`, `GET /internal/operator-action-readiness`, `GET /internal/operator-settings-change-requests`, `POST /internal/operator-settings-change-requests/{request_id}/decision`, `GET /internal/operator-settings-execution-preflight`, `GET /internal/operator-owner-handoff-packet`, `GET /internal/operator-audit-timeline`, `GET /internal/operator-compliance-evidence-binder`, `GET /internal/operator-release-candidate-runbook`, `GET /internal/operator-release-artifact-manifest`, `GET /internal/operator-go-live-readiness-index`, `GET /internal/operator-launch-blockers-plan`, `GET /internal/operator-staged-rollout-plan`, `GET /internal/operator-owner-launch-dossier`, `GET /internal/operator-provider-setup-checklist`, `GET /internal/operator-go-live-rehearsal-checklist`, `GET /internal/operator-rehearsal-outcome-report`, `GET /internal/operator-supervised-pilot-plan`, `GET /internal/operator-supervised-pilot-candidates`, `GET /internal/owner-handoff-packet`, `GET /internal/compliance-evidence-binder`, `GET /internal/release-candidate-runbook`, `GET /internal/release-artifact-manifest`, `GET /internal/go-live-readiness-index`, `GET /internal/launch-blockers-plan`, `GET /internal/staged-rollout-plan`, `GET /internal/owner-launch-dossier`, `GET /internal/provider-setup-checklist`, `GET /internal/go-live-rehearsal-checklist`, `GET /internal/rehearsal-outcome-report`, `GET /internal/supervised-pilot-plan`, `GET /internal/supervised-pilot-candidates`, `GET /internal/supervised-pilot-go-no-go`, `GET /internal/action-readiness`, `GET /internal/review-queue`, `POST /internal/review-queue/decisions`, `POST /internal/execution-plans/run`, and `GET /internal/execution-plans` are internal operator routes, not a public API.
- NPPES discovery itself remains a non-outbound ingestion job. CLI (`vyro-growth discover-nppes`) and worker job `discover_nppes_practices` do not use the HTTP key.
- Dashboard, monitoring, command-center, operator-dashboard, operator review-queue UI, operator approval-packet UI, operator action-readiness UI, operator settings-change request list, operator settings-execution preflight, operator owner-handoff packet, operator activity audit timeline, operator compliance evidence binder, operator release-candidate runbook, operator release artifact manifest, operator go-live readiness index, operator launch blockers remediation plan, operator staged go-live rollout plan, operator owner launch dossier, operator provider setup checklist, operator go-live rehearsal checklist, operator rehearsal outcome report, operator supervised pilot launch plan, operator supervised pilot candidate readiness, launch-readiness, owner-handoff-packet, compliance-evidence-binder, release-candidate-runbook, release-artifact-manifest, go-live-readiness-index, launch-blockers-plan, staged-rollout-plan, owner-launch-dossier, provider-setup-checklist, go-live-rehearsal-checklist, rehearsal-outcome-report, supervised-pilot-plan, supervised-pilot-candidates, and supervised-pilot-go-no-go routes are read-only. CLI (`vyro-growth dashboard-summary`, `vyro-growth system-status`, `vyro-growth operator-command-center`, `vyro-growth action-readiness`, `vyro-growth compliance-evidence-binder`, `vyro-growth release-candidate-runbook`, `vyro-growth release-artifact-manifest`, `vyro-growth go-live-readiness-index`, `vyro-growth launch-blockers-plan`, `vyro-growth staged-rollout-plan`, `vyro-growth owner-launch-dossier`, `vyro-growth provider-setup-checklist`, `vyro-growth go-live-rehearsal-checklist`, `vyro-growth rehearsal-outcome-report`, `vyro-growth supervised-pilot-plan`, `vyro-growth supervised-pilot-candidates`, `vyro-growth supervised-pilot-go-no-go`) does not use the HTTP key and does not write pipeline state. The HTML dashboard and drilldowns are HTTP-only and do not change operator halt state.
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

## Settings change request UI integrity
- Phase 29 settings-change HTML pages are a sanitized operator drilldown over Phase 28 records. They never perform a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Decision forms may only call the existing record-only decision service. They must not apply settings, lift halt, enable outbound, execute requests, or set live `owner_approved`.
- Render request type, status, owner decision status, setting names, desired boolean/status, finding/next-action codes, timestamps, source, record-only/no-execution flags, and safe counts only.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.

## Settings execution preflight integrity
- Phase 30 settings-execution preflight is a dry-run simulator over recorded settings change requests and owner decisions. It never performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, or deploy.
- Do not call GitHub Actions, OpenAI, NPPES/search, Apollo, Smartlead, Google Calendar, Google Ads, Search Console, Analytics, SEO/search, deployment, or voice providers in CI/defaults.
- Print request IDs, request types, decision status, setting names, desired booleans/statuses, blocker/gate codes, missing credential names, timestamps, counts, and no-execution flags only.
- Do not print PHI, emails, phones, message bodies, full outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw error text, or invented real-world prospect facts.
- `execution_allowed=false` is not permission or machinery for going live. A future explicitly approved execution phase does not exist in this phase.

## Settings execution preflight UI integrity
- Phase 31 settings-execution preflight HTML is a sanitized read-only shell over the Phase 30 simulator. It never performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/deploy/campaign/booking/call/publish/spend controls. Filters are read-only query parameters only.
- Render overall status, request/decision counts, blocker/gate/approval codes, missing credential variable names, closed provider flag names, request IDs/types, decision status, desired booleans/statuses, timestamps, and no-execution flags only.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- This page is a read-only blocker view, not permission or machinery for going live.

## Owner go-live handoff packet integrity
- Phase 32 owner go-live handoff is a sanitized read-only export over existing launch-readiness, settings-change, settings-execution-preflight, approval-packet, and action-readiness summaries. It never performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, or deploy.
- Do not call GitHub Actions, OpenAI, NPPES/search, Apollo, Smartlead, Google Calendar, Google Ads, Search Console, Analytics, SEO/search, deployment, or voice providers in CI/defaults.
- Print statuses, counts, blocker/gate/approval codes, request IDs, packet IDs, candidate IDs, setting names, desired booleans/statuses, missing credential variable names, closed provider flag names, timestamps, and no-execution flags only.
- Do not print PHI, emails, phones, message bodies, full outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw error text, or invented real-world prospect facts.
- `execution_allowed=false` and `go_live_permitted=false` are not permission or machinery for going live. A future explicitly approved execution phase does not exist in this phase.

## Owner go-live handoff packet UI integrity
- Phase 33 owner go-live handoff HTML is a sanitized read-only shell over the Phase 32 packet. It never performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/deploy/campaign/booking/call/publish/spend controls, mutation forms, workers, or mutators.
- Render statuses, counts, blocker/gate/approval codes, request IDs, packet IDs, candidate IDs, setting names, desired booleans/statuses, missing credential variable names, closed provider flag names, timestamps, and no-execution flags only.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- The page must state `go_live_permitted=false` and `execution_allowed=false`. This is a read-only manual-review view, not permission or machinery for going live.

## Operator activity audit timeline UI integrity
- Phase 34 operator activity audit timeline HTML is a sanitized read-only view over existing activity, audit, and decision records. It never performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not create, mutate, approve, reject, apply, execute, publish, deploy, spend, enroll, call, book, or contact anyone.
- Do not add apply/execute/lift-halt/enable-outbound/provider/deploy/campaign/booking/call/publish/spend controls, mutation forms, workers, or mutators. Filters are read-only query parameters only.
- Render event type, sanitized actor/source labels, timestamps, status/decision, artifact/packet/request/candidate/run IDs, reason/code labels, and no-execution/read-only flags only.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- This page is a read-only history view, not permission or machinery for going live.

## Compliance evidence binder integrity
- Phase 35 compliance evidence binder is a sanitized read-only export over existing launch-readiness, settings-execution-preflight, owner-handoff, operator audit timeline, CI smoke/deploy-config, and documented guardrail evidence. It never performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, or deploy.
- Do not call GitHub Actions, OpenAI, NPPES/search, Apollo, Smartlead, Google Calendar, Google Ads, Search Console, Analytics, SEO/search, deployment, or voice providers in CI/defaults.
- Print statuses, counts, codes, no-execution flags, operator halt status, outbound/live-provider flag states, CI gate names, route/command names, sanitized timestamps, and missing credential variable names only.
- Do not print PHI, emails, phones, message bodies, full outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw error text, or invented real-world prospect facts.
- `execution_allowed=false`, `go_live_permitted=false`, and `binder_is_not_go_live=true` are not permission or machinery for going live. A future explicitly approved execution phase does not exist in this phase.

## Compliance evidence binder UI integrity
- Phase 36 compliance evidence binder HTML is a sanitized read-only view over the Phase 35 binder. It never performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/deploy/campaign/booking/call/publish/spend controls, mutation forms, workers, or mutators.
- Render statuses, counts, codes, no-execution flags, operator halt status, outbound/live-provider flag states, CI gate names, route/command names, sanitized timestamps, and missing credential variable names only.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- The page must state `go_live_permitted=false`, `execution_allowed=false`, and `binder_is_not_go_live=true`. This is a read-only owner-review view, not permission or machinery for going live.

## Release-candidate deployment runbook integrity
- Phase 37 release-candidate deployment runbook is a sanitized read-only planning export over existing launch-readiness, settings-execution-preflight, owner-handoff, compliance evidence binder, operator audit timeline, CI smoke/deploy-config, deployment safe defaults, and documented guardrail evidence. It never deploys or performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, or deploy.
- Do not call GitHub Actions, OpenAI, NPPES/search, Apollo, Smartlead, Google Calendar, Google Ads, Search Console, Analytics, SEO/search, deployment, or voice providers in CI/defaults.
- Print statuses, counts, codes, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text only.
- Do not print PHI, emails, phones, message bodies, full outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw error text, or invented real-world prospect facts.
- `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, and `runbook_is_not_deployment=true` are not permission or machinery for going live or deploying. This runbook is for future manual owner review only.

## Release-candidate deployment runbook UI integrity
- Phase 38 release-candidate runbook HTML is a sanitized read-only view over the Phase 37 runbook. It never deploys or performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/deploy/campaign/booking/call/publish/spend controls, mutation forms, workers, or mutators.
- Render statuses, counts, codes, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text only.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- The page must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, and `runbook_is_not_deployment=true`. This is a read-only owner-review view, not a deployment mechanism or permission to go live.

## Release artifact manifest integrity
- Phase 39 release artifact manifest is a sanitized read-only owner-review export over existing release-candidate runbook, compliance evidence binder, launch-readiness, settings-execution-preflight, owner-handoff, operator audit timeline, CI smoke/deploy-config, deployment safe defaults, and documented guardrail evidence. It never builds, publishes, deploys, or performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not call GitHub Actions, GitHub provider APIs, OpenAI, NPPES/search, Apollo, Smartlead, Google Calendar, Google Ads, Search Console, Analytics, SEO/search, deployment, or voice providers in CI/defaults.
- Print statuses, counts, codes, filenames, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text only.
- Do not print PHI, emails, phones, message bodies, full outreach draft copy, evidence snippets, API keys, tokens, provider secrets, environment secret values, unsafe raw error text, or invented real-world prospect facts.
- Local git metadata may include sanitized branch name and SHA from `.git` files only. Do not include remotes, commit messages, author emails, or secret values.
- `execution_allowed=false`, `go_live_permitted=false`, `deployment_allowed=false`, `build_allowed=false`, `artifact_publish_allowed=false`, `runbook_is_not_deployment=true`, and `manifest_is_not_a_build_or_deploy=true` are not permission or machinery for building, publishing, going live, or deploying. This manifest is for owner/operator review only.

## Release artifact manifest UI integrity
- Phase 40 release artifact manifest HTML is a sanitized read-only view over the Phase 39 manifest. It never builds, publishes, deploys, or performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, or mutators.
- Render statuses, counts, codes, filenames, command names, route names, flag names/states, missing credential variable names, sanitized timestamps, and checklist text only.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from `.git` files only. Do not include remotes, commit messages, author emails, or secret values.
- The page must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `build_allowed=false`, `artifact_publish_allowed=false`, `runbook_is_not_deployment=true`, and `manifest_is_not_a_build_or_deploy=true`. This is a read-only owner-review view, not a build, artifact publishing, deployment mechanism, or permission to go live.

## Go-live readiness index UI integrity
- Phase 41 go-live readiness index HTML is a sanitized read-only index of existing owner/operator readiness, evidence, runbook, manifest, and audit surfaces. It never executes, builds, publishes, deploys, or performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, or mutators.
- Render statuses, counts, codes, route names, command names, flag names/states, missing credential variable names, sanitized timestamps, and checklist labels only.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The page must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `build_allowed=false`, `artifact_publish_allowed=false`, `OUTBOUND_ENABLED=false`, and that this is an index/review view only, not permission to go live and not an execution surface.

## Go-live readiness index export integrity
- Phase 42 go-live readiness index CLI and JSON are a sanitized read-only export of the Phase 41 index. They never execute, build, publish, deploy, or perform a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, or mutators.
- Export statuses, counts, codes, route names, command names, flag names/states, missing credential variable names, sanitized timestamps, and checklist labels only.
- Do not export secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The export must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `build_allowed=false`, `artifact_publish_allowed=false`, `OUTBOUND_ENABLED=false`, and that this is a review export only, not permission to go live and not an execution surface.

## Launch blockers remediation plan export integrity
- Phase 43 launch blockers remediation plan CLI and JSON are a sanitized read-only planning export of existing Phase 42 go-live readiness index blockers. They never execute, build, publish, deploy, or perform a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, or mutators.
- Export blocker codes, surface keys/labels, statuses, recommended manual remediation steps, owner approval types, step kinds, route names, command names, config names, sanitized timestamps, and counts only.
- Do not export secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The export must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `OUTBOUND_ENABLED=false`, and that this is a remediation planning export only, not permission to go live and not an execution surface.

## Launch blockers remediation plan UI integrity
- Phase 44 launch blockers remediation plan HTML is a sanitized read-only shell of the existing Phase 43 plan. It never executes, builds, publishes, deploys, or performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, or mutators.
- Render blocker codes, surface keys/labels, statuses, recommended manual remediation steps, owner approval types, step kinds, route names, command names, config names, sanitized timestamps, and counts only.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The page must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `OUTBOUND_ENABLED=false`, and that this is a remediation planning view only, not permission to go live and not an execution surface.

## Staged go-live rollout plan export integrity
- Phase 45 staged go-live rollout plan CLI and JSON are a sanitized read-only planning export over existing readiness, blocker, binder, runbook, manifest, and launch-readiness surfaces. They never execute, build, publish, deploy, or perform a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, or mutators.
- Export stage keys/labels, statuses, blocker/gate codes, owner approval types, checklist labels, route names, command names, config names, sanitized timestamps, and counts only.
- Do not export secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The export must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `OUTBOUND_ENABLED=false`, `staged_rollout_plan_is_not_go_live=true`, and that this is a staged rollout planning export only, not permission to go live and not an execution surface.

## Staged go-live rollout plan UI integrity
- Phase 46 staged go-live rollout plan HTML is a sanitized read-only shell of the existing Phase 45 plan. It never executes, builds, publishes, deploys, or performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, or mutators.
- Render stage keys/labels, statuses, blocker/gate codes, owner approval types, checklist labels, route names, command names, config names, sanitized timestamps, and counts only.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The page must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `OUTBOUND_ENABLED=false`, `staged_rollout_plan_is_not_go_live=true`, and that this is a staged rollout planning view only, not permission to go live and not an execution surface.

## Owner launch dossier export integrity
- Phase 47 owner launch dossier CLI and JSON are a sanitized read-only review export over existing readiness, blocker, staged-rollout, handoff, binder, runbook, manifest, settings-preflight, and audit surfaces. They never execute, build, publish, deploy, or perform a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, or mutators.
- Export statuses, blocker/gate codes, missing credential variable names, route names, command names, config names, sanitized timestamps, counts, and safe local git metadata only.
- Do not export secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The export must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `OUTBOUND_ENABLED=false`, `owner_launch_dossier_is_not_go_live=true`, and that this is a review export only, not permission to go live and not an execution surface.

## Owner launch dossier UI integrity
- Phase 48 owner launch dossier HTML is a sanitized read-only shell of the existing Phase 47 dossier. It never executes, builds, publishes, deploys, or performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, or mutators.
- Render statuses, blocker/gate codes, missing credential variable names, route names, command names, config names, sanitized timestamps, counts, and safe local git metadata only.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The page must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `OUTBOUND_ENABLED=false`, `owner_launch_dossier_is_not_go_live=true`, and that this is a launch dossier review view only, not permission to go live and not an execution surface.

## Provider setup checklist export integrity
- Phase 49 provider setup checklist CLI and JSON are a sanitized read-only planning export over existing launch-readiness, go-live index, launch-blocker, staged-rollout, owner-launch-dossier, settings-preflight, and runbook surfaces. They never execute, build, publish, deploy, or perform a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, or mutators.
- Export category keys/labels, statuses, required owner approval types, missing credential variable names, closed provider/live flag names, blocker/gate codes, route names, command names, config names, sanitized timestamps, counts, and safe local git metadata only.
- Do not export secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The export must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `OUTBOUND_ENABLED=false`, `provider_setup_checklist_is_not_go_live=true`, and that this is a planning/export layer only, not permission to go live and not an execution surface.

## Provider setup checklist UI integrity
- Phase 50 provider setup checklist UI is a sanitized read-only HTML shell over the existing Phase 49 checklist. It never executes, builds, publishes, deploys, or performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, or mutators.
- Render statuses, blocker/gate codes, missing credential variable names, closed provider/live flag names, route names, command names, config names, sanitized timestamps, counts, and safe local git metadata only.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The page must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `OUTBOUND_ENABLED=false`, `provider_setup_checklist_is_not_go_live=true`, and that this is a provider setup review view only, not permission to go live and not an execution surface.

## Go-live rehearsal checklist export integrity
- Phase 51 go-live rehearsal checklist CLI and JSON are a sanitized read-only manual rehearsal export over existing launch-readiness, go-live index, launch-blocker, staged-rollout, owner-launch-dossier, provider-setup, runbook, manifest, and settings-preflight surfaces. They never execute commands, build, publish, deploy, or perform a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, mutators, or a script runner.
- Export rehearsal step instructions, expected safe assertions, required owner approval types, blocker/gate codes, missing credential variable names, closed provider/live flag names, route names, command names, config names, rollback/abort review text, sanitized timestamps, counts, and safe local git metadata only.
- Command names and routes are references only and must not be executed from this export.
- Do not export secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The export must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `OUTBOUND_ENABLED=false`, `go_live_rehearsal_checklist_is_not_go_live=true`, `rehearsal_is_not_a_script_runner=true`, and that this is a checklist/export only, not permission to go live and not an execution surface.

## Go-live rehearsal checklist UI integrity
- Phase 52 go-live rehearsal checklist UI is a sanitized read-only HTML shell over the existing Phase 51 checklist. It never executes commands, builds, publishes, deploys, or performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, mutators, or a script runner.
- Render rehearsal step instructions, expected safe assertions, required owner approval types, blocker/gate codes, missing credential variable names, closed provider/live flag names, route names, command names, config names, rollback/abort review text, sanitized timestamps, counts, and safe local git metadata only.
- Command names and routes are references only and must not be executed from this page.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The page must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `OUTBOUND_ENABLED=false`, `go_live_rehearsal_checklist_is_not_go_live=true`, `rehearsal_is_not_a_script_runner=true`, and that this is a manual rehearsal review view only, not permission to go live and not an execution surface.

## Rehearsal outcome report export integrity
- Phase 53 rehearsal outcome report CLI and JSON are a sanitized read-only compact summary of the existing Phase 51 go-live rehearsal checklist. They never execute commands, build, publish, deploy, or perform a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, mutators, or a script runner.
- Export rehearsal step counts, expected safe assertion passed/failed counts, failed assertion keys only, required owner approval type counts, blocker/gate codes, missing credential/config names, closed provider/live flag names, route names, command names, config names, sanitized timestamps, counts, a manual-only outcome summary, and safe local git metadata only.
- Do not export assertion expected/observed values, rehearsal step instructions, secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The export must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `OUTBOUND_ENABLED=false`, `rehearsal_outcome_report_is_not_go_live=true`, and that this is an outcome report/export only, not permission to go live and not an execution surface.

## Rehearsal outcome report UI integrity
- Phase 54 rehearsal outcome report UI is a sanitized read-only HTML shell over the existing Phase 53 report. It never executes commands, builds, publishes, deploys, or performs a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, mutators, or a script runner.
- Render rehearsal step counts, expected safe assertion passed/failed counts, failed assertion keys only, remaining owner approval types, blocker/gate codes, missing credential/config names, closed provider/live flag names, route names, command names, config names, sanitized timestamps, counts, a manual-only outcome summary, and safe local git metadata only.
- Command names and routes are references only and must not be executed from this page.
- Do not render secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, assertion expected/observed values, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The page must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `OUTBOUND_ENABLED=false`, `rehearsal_outcome_report_is_not_go_live=true`, `report_is_not_permission_to_go_live=true`, `report_is_not_execution=true`, and that this is an outcome report review view only, not permission to go live and not an execution surface.

## Supervised pilot launch plan export integrity
- Phase 55 supervised pilot launch plan CLI and JSON are a sanitized read-only small-pilot planning export over existing readiness, rehearsal, outcome, provider setup, and dossier surfaces. They never execute commands, build, publish, deploy, spend, or perform a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend controls, mutation forms, workers, mutators, or a script runner.
- Export count-only pilot scope limits, grouped prerequisite statuses, safety assertions, blocker/gate codes, missing credential/config names, closed provider/live flag names, route names, command names, config names, runbook steps with `runnable=false` and `executed=0`, abort/rollback review text, sanitized timestamps, counts, and safe local git metadata only.
- Command names and routes are references only and must not be executed from this export.
- Do not export secret values, environment values, API keys, tokens, provider secrets, message bodies, full outreach draft copy, real emails, real phones, evidence snippets, PHI, or unsafe raw error text.
- Local git metadata may include sanitized branch name and SHA from reused read-only builders only. Do not include remotes, commit messages, author emails, or secret values.
- The export must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `spend_allowed=false`, `OUTBOUND_ENABLED=false`, `supervised_pilot_plan_is_not_go_live=true`, and that this is a supervised pilot planning export only, not permission to go live and not an execution surface.

## Supervised pilot candidate readiness export integrity
- Phase 57 supervised pilot candidate readiness CLI and JSON are a sanitized read-only review export over existing discovery, enrichment, scoring, outreach, supervised pilot plan, provider setup, rehearsal outcome, launch readiness, and operator halt surfaces. They never execute commands, scrape, select candidates, build, publish, deploy, spend, send, or perform a live workflow.
- Do not change `OUTBOUND_ENABLED`, provider live flags, deployment settings, campaign live settings, scoring thresholds, or operator halt.
- Do not apply settings, execute settings requests, set live `owner_approved`, execute review items/approval packets, send email, enroll campaigns, generate sendable autonomous replies, place calls, book meetings, create Google Meet links, publish content, launch ads, spend money, build containers, publish artifacts, or deploy.
- Do not add apply/execute/lift-halt/enable-outbound/provider/build/publish/deploy/campaign/booking/call/spend/candidate-selection controls, mutation forms, workers, mutators, or a script runner.
- Export count-only candidate scope limits, generic readiness/status/stage/source/specialty/state buckets, scoring distribution counts, missing prerequisite/gate codes, suppression/kill-switch rollups, blocked-count reasons, route names, command names, sanitized timestamps, counts, and safe local git metadata only.
- Do not export practice names, provider names, NPI numbers, street addresses, emails, phones, websites, raw evidence snippets, message bodies, outreach drafts, PHI, patient data, secret values, environment values, API keys, tokens, provider secrets, or unsafe raw error text.
- The export must state `go_live_permitted=false`, `execution_allowed=false`, `deployment_allowed=false`, `settings_applied=false`, `halt_changed=false`, `owner_approved=false`, `spend_allowed=false`, `OUTBOUND_ENABLED=false`, `supervised_pilot_candidates_is_not_go_live=true`, and that this is a candidate readiness review export only, not permission to go live and not an execution surface.

## Enrichment integrity
- AI-generated prospect facts are not authoritative.
- Store source URLs and confidence/evidence for material enrichment claims.
- Do not use unverifiable claims in personalization.

## Least privilege
Each provider integration should receive only the scopes required for its job. Production service accounts should be separate from personal accounts when possible.

## Separation from billing operations
Future HIPAA/RCM systems must be separate services/data stores with their own controls, access policies, BAAs, and audit requirements. Do not extend this sales database into a patient billing database.
