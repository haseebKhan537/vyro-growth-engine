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
- Email, domain, and phone suppressions are checked immediately before every outbound action.
- Future email, calendar, and consent-based phone adapters/workers must call `OutboundGuard.require_allowed` (or use the guarded wrappers / `SafetyCheckedWorkerRunner`) before sending, scheduling, or dialing.
- Permanent unsubscribe records must be durable and honored across campaigns.
- Every external action must create an audit/activity record.

## Voice
Do not implement indiscriminate cold AI robocalling. Voice automation is restricted to inbound leads, requested callbacks, or prospects with documented permission/consent.

## Secrets
- Never commit API keys, passwords, OAuth refresh tokens, SMTP credentials, or private keys.
- Use environment variables or deployment secret stores.
- `.env` is gitignored.
- Loggers must redact credentials and authorization headers.

## Enrichment integrity
- AI-generated prospect facts are not authoritative.
- Store source URLs and confidence/evidence for material enrichment claims.
- Do not use unverifiable claims in personalization.

## Least privilege
Each provider integration should receive only the scopes required for its job. Production service accounts should be separate from personal accounts when possible.

## Separation from billing operations
Future HIPAA/RCM systems must be separate services/data stores with their own controls, access policies, BAAs, and audit requirements. Do not extend this sales database into a patient billing database.
