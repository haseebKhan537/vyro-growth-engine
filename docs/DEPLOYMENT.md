# Production deployment runbook

This document is the Phase 12 operator guide for configuring and running Vyro Growth Engine without enabling live outreach.

It does **not** deploy to a public cloud, store production secrets in git, or call Smartlead, Apollo, OpenAI, Google Calendar, voice providers, or other paid/external services. Those remain owner-approved later work.

## Safety defaults

Keep these values unless the owner later approves a staged outbound rollout:

| Setting | Required default |
|---|---|
| `OUTBOUND_ENABLED` | `false` |
| `OPENAI_PERSONALIZATION_ENABLED` | `false` |
| `SMARTLEAD_LIVE_ENABLED` | `false` |
| `OPENAI_REPLY_CLASSIFICATION_ENABLED` | `false` |
| `GOOGLE_CALENDAR_LIVE_ENABLED` | `false` |
| `VOICE_LIVE_ENABLED` | `false` |

Persistent operator halt stays seeded **halted**. Enabling `OUTBOUND_ENABLED` is not enough to send mail, enroll campaigns, create calendar events/Meet links, or place calls.

Do not ingest or expose PHI. Do not invent prospect facts.

## Required environment variables

Copy `.env.example` and inject secrets from a deployment secret store. Never commit `.env`.

### Always required

- `DATABASE_URL` — PostgreSQL/Supabase-compatible SQLAlchemy URL (`postgresql+psycopg://...`)
- `ENVIRONMENT` — `development` for local Compose. Any other value is treated as deployed.

### Required outside development

- `INTERNAL_API_KEY` — shared secret for `/internal/*` HTTP routes. Process start and `vyro-growth check-config` fail closed when this is missing outside `development`.

### Safety flags (keep false)

- `OUTBOUND_ENABLED`
- `OUTBOUND_HALTED` (settings-backed halt; persistent DB halt is separate)
- `OPENAI_PERSONALIZATION_ENABLED`
- `SMARTLEAD_LIVE_ENABLED`
- `OPENAI_REPLY_CLASSIFICATION_ENABLED`
- `GOOGLE_CALENDAR_LIVE_ENABLED`
- `VOICE_LIVE_ENABLED`

Live provider keys (`OPENAI_API_KEY`, `SMARTLEAD_API_KEY`, `GOOGLE_CALENDAR_API_KEY`, `VOICE_API_KEY`) may stay empty. If a live flag is flipped true without its key, startup and `check-config` fail closed. Flipping a live flag still does not send email or open a default provider HTTP session.

### Optional local/runtime

- `APP_NAME`, `LOG_LEVEL`
- NPPES and website-fetch bounds (see `.env.example`)

Validate without calling providers:

```bash
vyro-growth check-config
```

## Database migration order

Apply forward migrations before starting API or worker processes that read the schema:

```bash
alembic upgrade head
```

Compose equivalent (does not enable outbound):

```bash
docker compose --profile ops run --rm migrate
```

Current revision chain (do not skip):

1. `001_initial_schema`
2. `002_discovery_runs`
3. `003_operator_halt_and_phone_suppression`
4. `004_website_enrichment`
5. `005_decision_maker_contacts`
6. `006_personalization_drafts`
7. `007_outreach_enrollment`
8. `008_reply_classifications`
9. `009_booking_plans`
10. `010_voice_qualification`
11. `011_optimizer_recommendations`
12. `012_operator_review_decisions`
13. `013_channel_plans`
14. `014_content_briefs`
15. `015_execution_plans`
16. `016_approval_packets`
17. `017_approval_packet_decisions`
18. `018_live_settings_change_requests`
19. `019_email_verification`
20. `020_contact_discovery_calls`

Check status:

```bash
alembic current
alembic history
```

## Health checks

| Endpoint | Purpose | Dependencies |
|---|---|---|
| `GET /health` | Liveness. Process is up. | None. Does not query the database or providers. |
| `GET /ready` | Readiness. Safe to receive traffic. | `DATABASE_URL` connectivity plus runtime config validation. |

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

`/health` includes `"outbound_enabled": false` and `"live_providers_enabled": false` with the default configuration.

`/ready` returns HTTP 200 only when the database answers `SELECT 1` and required security settings are present. Otherwise it returns HTTP 503 with `config_issues` and `database` status. It does not call live providers.

The API image and Compose `api` service also define container `HEALTHCHECK` probes against `/health`.

## Worker process startup

There is no durable queue in this phase. Jobs are one-shot CLI invocations using the in-process (`inline`) runner.

Inspect the catalog and fail closed on missing production settings:

```bash
vyro-growth worker --check
vyro-growth worker --list
```

Compose check (safe, no job execution):

```bash
docker compose --profile ops run --rm worker
```

Run a dry-run job after migrations, using the existing CLI commands. Examples:

```bash
vyro-growth score-leads --limit 25
vyro-growth plan-outreach --limit 25
vyro-growth recommend-growth
```

`vyro-growth smoke-dry-run --local-only` is a developer demo only. It uses an isolated in-memory database, refuses production/live settings unless `--local-only`/`--dev-demo` is passed, and is not a deployable worker job. CI job `smoke-dry-run` runs `vyro-growth smoke-dry-run --local-only --json` with `OUTBOUND_ENABLED=false` and live-provider flags disabled, then `vyro-growth check-smoke-output` to fail the build on live side effects or unsanitized output. CI unsets `DATABASE_URL` and provider credentials for that job.

`vyro-growth launch-readiness` is a read-only owner-facing checklist. It does not execute, call providers, print secret values, or change operator halt / live settings. Use it to see remaining blockers before any live acquisition activity is approved. `ready_for_owner_review` is not permission to enable outbound.

`vyro-growth settings-execution-preflight` is a dry-run simulator over recorded settings change requests. It does not apply settings, lift halt, enable outbound, or execute anything. `execution_allowed=false` is not permission or machinery for going live.

`vyro-growth owner-handoff-packet` is a read-only owner-review export of launch readiness, settings change requests, settings execution preflight, owner approval packets, and approved action readiness. It does not apply settings, lift halt, enable outbound, or execute anything. `go_live_permitted=false` is not permission or machinery for going live. `GET /internal/operator-owner-handoff-packet` is the same packet as a sanitized HTML shell and is also not permission to go live.

`vyro-growth compliance-evidence-binder` is a read-only owner-review export of existing safety evidence. It does not apply settings, lift halt, enable outbound, or execute anything. `go_live_permitted=false` and `binder_is_not_go_live=true` are not permission or machinery for going live. `GET /internal/operator-compliance-evidence-binder` is the same binder as a sanitized HTML shell and is also not permission to go live.

`vyro-growth release-candidate-runbook` is a read-only planning export of future manual deployment steps, CI gates, rollback checks, and remaining blockers. It does not deploy, apply settings, lift halt, enable outbound, or execute anything. `deployment_allowed=false` and `runbook_is_not_deployment=true` are not a deployment mechanism or permission to go live. `GET /internal/release-candidate-runbook` is the same packet as sanitized JSON and is also not a deploy. `GET /internal/operator-release-candidate-runbook` is the same packet as a sanitized HTML shell and is also not a deployment mechanism or permission to go live.

`vyro-growth release-artifact-manifest` is a read-only owner-review export of expected source/provenance, artifact paths, migration revision filenames/ids, runtime commands, and safety gates. It does not build containers, publish artifacts, deploy, apply settings, lift halt, enable outbound, or execute anything. `build_allowed=false`, `artifact_publish_allowed=false`, `deployment_allowed=false`, and `manifest_is_not_a_build_or_deploy=true` are not a build, publishing, or deployment mechanism or permission to go live. `GET /internal/release-artifact-manifest` is the same packet as sanitized JSON and is also not a build or deploy. `GET /internal/operator-release-artifact-manifest` is the same packet as a sanitized HTML shell and is also not a build, artifact publishing, deployment mechanism, or permission to go live.

`GET /internal/operator-go-live-readiness-index` is a read-only owner/operator index of existing readiness, evidence, runbook, manifest, and audit surfaces. It does not execute, apply settings, lift halt, enable outbound, build, publish, or deploy. It is an index/review view only, not permission to go live and not an execution surface.

`vyro-growth go-live-readiness-index` is a read-only owner-review export of that same index. It does not execute, apply settings, lift halt, enable outbound, build, publish, or deploy. `GET /internal/go-live-readiness-index` is the same packet as sanitized JSON and is also not permission to go live and not an execution surface.

`vyro-growth launch-blockers-plan` is a read-only remediation-planning export of existing go-live readiness index blockers. It does not execute, apply settings, lift halt, enable outbound, build, publish, or deploy. `GET /internal/launch-blockers-plan` is the same packet as sanitized JSON and is also not permission to go live and not an execution surface.

`GET /internal/operator-launch-blockers-plan` is a read-only owner/operator HTML shell of that same remediation plan. It does not execute, apply settings, lift halt, enable outbound, build, publish, or deploy. It is a remediation planning view only, not permission to go live and not an execution surface.

`vyro-growth staged-rollout-plan` is a read-only staged-rollout-planning export of existing readiness, blocker, binder, runbook, and manifest surfaces. It does not execute, apply settings, lift halt, enable outbound, build, publish, or deploy. `GET /internal/staged-rollout-plan` is the same packet as sanitized JSON and is also not permission to go live and not an execution surface.

`GET /internal/operator-staged-rollout-plan` is a read-only owner/operator HTML shell of that same staged rollout plan. It does not execute, apply settings, lift halt, enable outbound, build, publish, or deploy. It is a staged rollout planning view only, not permission to go live and not an execution surface.

`vyro-growth owner-launch-dossier` is a read-only owner-review export of existing readiness, blocker, staged-rollout, handoff, binder, runbook, manifest, settings-preflight, and audit surfaces. It does not execute, apply settings, lift halt, enable outbound, build, publish, or deploy. `GET /internal/owner-launch-dossier` is the same packet as sanitized JSON and is also not permission to go live and not an execution surface.

`GET /internal/operator-owner-launch-dossier` is a read-only owner/operator HTML shell of that same owner launch dossier. It does not execute, apply settings, lift halt, enable outbound, build, publish, or deploy. It is a launch dossier review view only, not permission to go live and not an execution surface.

`vyro-growth provider-setup-checklist` is a read-only provider credential/setup checklist export of existing launch-readiness, go-live index, launch-blocker, staged-rollout, owner-launch-dossier, settings-preflight, and runbook surfaces. It does not execute, apply settings, lift halt, enable outbound, build, publish, or deploy. `GET /internal/provider-setup-checklist` is the same packet as sanitized JSON and is also not permission to go live and not an execution surface.

`GET /internal/operator-provider-setup-checklist` is a read-only owner/operator HTML shell of that same provider setup checklist. It does not execute, apply settings, lift halt, enable outbound, build, publish, or deploy. It is a provider setup review view only, not permission to go live and not an execution surface.

`vyro-growth go-live-rehearsal-checklist` is a read-only manual go-live rehearsal checklist export of existing launch-readiness, go-live index, launch-blocker, staged-rollout, owner-launch-dossier, provider-setup, runbook, manifest, and settings-preflight surfaces. It does not execute commands, apply settings, lift halt, enable outbound, build, publish, or deploy. `GET /internal/go-live-rehearsal-checklist` is the same packet as sanitized JSON and is also not a script runner, not permission to go live, and not an execution surface.

`vyro-growth rehearsal-outcome-report` is a read-only compact outcome report of the current Phase 51 go-live rehearsal checklist. It does not execute commands, apply settings, lift halt, enable outbound, build, publish, or deploy. `GET /internal/rehearsal-outcome-report` is the same packet as sanitized JSON and is also not permission to go live and not an execution surface.

`GET /internal/operator-rehearsal-outcome-report` is a read-only owner/operator HTML shell of that same rehearsal outcome report. It does not execute, apply settings, lift halt, enable outbound, build, publish, or deploy. It is an outcome report review view only, not permission to go live and not an execution surface.

`vyro-growth supervised-pilot-plan` is a read-only supervised small-pilot planning export of existing readiness, rehearsal, outcome, provider setup, and dossier surfaces. It does not execute commands, apply settings, lift halt, enable outbound, build, publish, spend, or deploy. `GET /internal/supervised-pilot-plan` is the same packet as sanitized JSON and is also not permission to go live and not an execution surface.

`GET /internal/operator-supervised-pilot-plan` is a read-only owner/operator HTML shell of that same supervised pilot launch plan. It does not execute, apply settings, lift halt, enable outbound, build, publish, spend, or deploy. It is a supervised pilot planning review view only, not permission to go live and not an execution surface.

`vyro-growth supervised-pilot-candidates` is a read-only supervised pilot candidate readiness export over existing discovery, enrichment, scoring, outreach, pilot-plan, provider-setup, rehearsal-outcome, launch-readiness, and operator-halt surfaces. It does not execute commands, apply settings, lift halt, enable outbound, scrape, select candidates, send, spend, build, publish, or deploy. `GET /internal/supervised-pilot-candidates` is the same packet as sanitized JSON and is also not permission to go live and not an execution surface.

`GET /internal/operator-supervised-pilot-candidates` is a read-only owner/operator HTML shell of that same supervised pilot candidate readiness export. It does not execute, apply settings, lift halt, enable outbound, scrape, select candidates, send, spend, build, publish, or deploy. It is a candidate readiness review view only, not permission to go live and not an execution surface.

`vyro-growth supervised-pilot-go-no-go` is a read-only supervised pilot go/no-go packet over existing pilot-plan, candidate-readiness, provider-setup, rehearsal-outcome, launch-readiness, review/action-readiness, owner-approval, settings-request, and operator-halt surfaces. It does not execute commands, apply settings, lift halt, enable outbound, scrape, select candidates, send, spend, build, publish, or deploy. `GET /internal/supervised-pilot-go-no-go` is the same packet as sanitized JSON and is also not permission to go live and not an execution surface.

`GET /internal/operator-supervised-pilot-go-no-go` is a read-only owner/operator HTML shell of that same supervised pilot go/no-go packet. It does not execute, apply settings, lift halt, enable outbound, scrape, select candidates, send, spend, build, publish, or deploy. It is a go/no-go review view only, not permission to go live and not an execution surface.

`vyro-growth supervised-pilot-first-send-preflight` is a read-only supervised pilot first-send preflight over existing go/no-go, pilot-plan, candidate-readiness, provider-setup, rehearsal-outcome, launch-readiness, review/action-readiness, owner-approval, settings-request, and operator-halt surfaces. It does not execute commands, apply settings, lift halt, enable outbound, scrape, select candidates, send, spend, build, publish, or deploy. `GET /internal/supervised-pilot-first-send-preflight` is the same packet as sanitized JSON and is also not permission to send, not permission to go live, and not an execution surface.

`GET /internal/operator-supervised-pilot-first-send-preflight` is a read-only owner/operator HTML shell of that same supervised pilot first-send preflight packet. It does not execute, apply settings, lift halt, enable outbound, scrape, select candidates, send, spend, build, publish, or deploy. It is a first-send preflight review view only, not permission to send, not permission to go live, and not an execution surface.

`vyro-growth supervised-pilot-launch-rehearsal-control-map` is a read-only supervised-pilot launch rehearsal control map over existing halt, outbound, supervised-pilot, approval, settings, launch-readiness, rehearsal, provider-setup, compliance, and release surfaces. It does not execute commands, apply settings, lift halt, enable outbound, scrape, select candidates, send, spend, build, publish, or deploy. `GET /internal/supervised-pilot-launch-rehearsal-control-map` is the same packet as sanitized JSON and is also not a script runner, not permission to send, not permission to go live, and not an execution surface.

`GET /internal/operator-supervised-pilot-launch-rehearsal-control-map` is a read-only owner/operator HTML shell of that same supervised pilot launch rehearsal control map. It does not execute, apply settings, lift halt, enable outbound, scrape, select candidates, send, spend, build, publish, or deploy. It is a control-map review view only, not a script runner, not permission to send, not permission to go live, and not an execution surface.

`GET /internal/operator-contact-validation` is a read-only owner/operator HTML shell of the Phase 71 contact-enrichment validation plan and report. It does not execute validation stages, call providers, select or contact prospects, send, enroll, call, book, spend, publish, deploy, apply settings, or lift halt. It is an aggregate-only review view, not permission to run a supervised validation, and not an execution surface.

`vyro-growth supervised-validation-run-packet` is a read-only owner approval/run packet over those same Phase 71 plan/report payloads and Phase 72 UI route names. It does not execute the validation run, grant approval, call providers, send, enroll, call, book, spend, publish, deploy, apply settings, or lift halt. `GET /internal/supervised-validation-run-packet` is the same packet as sanitized JSON and is also not permission to run a supervised validation and not an execution surface.

`GET /internal/operator-supervised-validation-run-packet` is a read-only owner/operator HTML shell of that same supervised validation owner approval/run packet. It does not execute the validation run, grant approval, call providers, select or contact prospects, send, enroll, call, book, spend, publish, deploy, apply settings, or lift halt. It is an aggregate-only review view, not permission to run a supervised validation, and not an execution surface.

`vyro-growth final-safety-audit` is a read-only repository and safety audit over existing launch-readiness, contact-validation, provider-setup, manifest, runbook, and dossier surfaces. It does not execute validation, grant approval, call providers, send, enroll, call, book, spend, publish, deploy, apply settings, or lift halt. `GET /internal/final-safety-audit` is the same packet as sanitized JSON and is also not permission to run real-world validation and not an execution surface.

`GET /internal/operator-go-live-rehearsal-checklist` is a read-only owner/operator HTML shell of that same manual rehearsal checklist. It does not execute, apply settings, lift halt, enable outbound, build, publish, or deploy. It is a manual rehearsal review view only, not a script runner, not permission to go live, and not an execution surface.

Do not schedule `send_email`, `schedule_meeting`, or `place_consent_callback`. Those names exist only as fail-closed outbound guards and are not deployable jobs.

## Scheduler and queue assumptions

- Queue backend: in-process `InlineJobQueue` / `InlineWorkerRunner`. Not Redis, SQS, or Celery.
- Scheduling: operator or an external cron/systemd timer invokes `vyro-growth <command>`. The container `worker` service only checks configuration.
- No autonomous outbound loop. No process polls a mailbox, Smartlead, Google Calendar, or a voice provider.
- HTTP `/internal/*` routes stay off public ingress. Prefer CLI or the worker catalog in deployed environments.
- Job handlers are expected to be idempotent. Re-running a dry-run command should reuse existing plan/draft rows where those layers already do so.

## Backup and restore

Use the managed PostgreSQL/Supabase backup feature when that database is provisioned, or take logical dumps:

```bash
pg_dump --format=custom --file vyro_growth.dump "$BACKUP_DATABASE_URL"
```

Restore onto a new empty database, then confirm `alembic current` matches the dumped revision:

```bash
pg_restore --clean --if-exists --dbname "$RESTORE_DATABASE_URL" vyro_growth.dump
alembic current
```

Backup scope is sales/prospecting data only. Do not copy this dump into a HIPAA billing environment. Do not include `.env` or provider credentials in backup archives.

This repository does not enable cloud snapshot automation or off-site replication by default.

## Rollback

1. Halt traffic to the API/worker processes. Leave `OUTBOUND_ENABLED=false`.
2. Restore the previous application image or git revision.
3. If a migration must be reversed and the revision is backward-compatible, `alembic downgrade -1` one step at a time. Prefer restore-from-backup when a revision is not safely reversible.
4. Confirm `/health`, `/ready`, `vyro-growth check-config`, and `vyro-growth system-status`.
5. Persistent operator halt should remain halted unless the owner explicitly lifts it.

Do not roll forward by enabling live providers.

## Suggested startup order

1. Provision PostgreSQL/Supabase and inject `DATABASE_URL` plus `INTERNAL_API_KEY` from a secret store.
2. Confirm `.env` / runtime env keeps every live-provider flag false.
3. `vyro-growth check-config`
4. `alembic upgrade head`
5. Start the API (`uvicorn vyro_growth.main:app --host 0.0.0.0 --port 8000` or `docker compose up --build api`).
6. Probe `/health` and `/ready`.
7. Run `vyro-growth operator-command-center`, open `GET /internal/operator-dashboard`, `GET /internal/operator-review-queue`, `GET /internal/operator-approval-packets`, `GET /internal/operator-action-readiness`, `GET /internal/operator-settings-change-requests`, `GET /internal/operator-settings-execution-preflight`, `GET /internal/operator-owner-handoff-packet`, `GET /internal/operator-audit-timeline`, `GET /internal/operator-compliance-evidence-binder`, `GET /internal/operator-release-candidate-runbook`, and `GET /internal/operator-release-artifact-manifest`, `GET /internal/operator-go-live-readiness-index`, `GET /internal/operator-launch-blockers-plan`, `GET /internal/operator-staged-rollout-plan`, `GET /internal/operator-owner-launch-dossier`, `GET /internal/operator-provider-setup-checklist`, `GET /internal/operator-go-live-rehearsal-checklist`, `GET /internal/operator-rehearsal-outcome-report`, `GET /internal/operator-supervised-pilot-plan`, `GET /internal/operator-supervised-pilot-candidates`, `GET /internal/operator-supervised-pilot-go-no-go`, `GET /internal/operator-supervised-pilot-first-send-preflight`, `GET /internal/operator-supervised-pilot-launch-rehearsal-control-map`, `GET /internal/operator-contact-validation`, `GET /internal/operator-supervised-validation-run-packet`, `GET /internal/supervised-validation-run-packet`, `GET /internal/final-safety-audit`, `GET /internal/supervised-pilot-go-no-go`, `GET /internal/staged-rollout-plan`, `GET /internal/owner-launch-dossier`, `GET /internal/provider-setup-checklist`, `GET /internal/go-live-rehearsal-checklist`, `GET /internal/rehearsal-outcome-report`, `GET /internal/supervised-pilot-plan`, and `vyro-growth launch-readiness`, `vyro-growth settings-change-requests`, `vyro-growth settings-execution-preflight`, `vyro-growth owner-handoff-packet`, `vyro-growth compliance-evidence-binder`, `vyro-growth release-candidate-runbook`, `vyro-growth release-artifact-manifest`, `vyro-growth go-live-readiness-index`, `vyro-growth launch-blockers-plan`, `vyro-growth staged-rollout-plan`, `vyro-growth owner-launch-dossier`, `vyro-growth provider-setup-checklist`, `vyro-growth go-live-rehearsal-checklist`, `vyro-growth rehearsal-outcome-report`, `vyro-growth supervised-pilot-plan`, `vyro-growth supervised-pilot-candidates`, `vyro-growth supervised-pilot-go-no-go`, and `vyro-growth final-safety-audit`, and `vyro-growth system-status` and review findings before any manual rollout. Recording a review, approval-packet, or settings-change decision from these surfaces does not execute the artifact, packet, or setting. The readiness queue, settings-execution preflight, owner handoff packet, activity audit timeline, compliance evidence binder, release-candidate runbook, release artifact manifest, go-live readiness index, launch blockers remediation plan, staged go-live rollout plan, owner launch dossier, provider setup checklist, go-live rehearsal checklist, rehearsal outcome report, supervised pilot launch plan, supervised pilot candidate readiness, supervised pilot go/no-go packet and UI, and supervised pilot first-send preflight packet and UI, and supervised pilot launch rehearsal control map packet and UI, and operator contact-validation UI, and operator supervised validation run packet UI, and supervised validation owner run packet, and final safety audit packet are dry-run/read-only only. See `docs/OPERATOR_HEALTH.md`.
8. Start worker checks or cron-invoked CLI jobs as needed.

Production start fails closed when `INTERNAL_API_KEY` or `DATABASE_URL` is missing, or when a live-provider flag is true without its key.

## What this phase does not do

- No live cloud deploy, DNS, TLS, or paid provider signup.
- No emails, campaign enrollment, calendar events, Meet links, or phone calls.
- No autonomous replies.
- No staged outbound traffic.
- No PHI ingestion.
