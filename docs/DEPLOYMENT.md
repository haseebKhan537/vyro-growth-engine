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
7. Run `vyro-growth operator-command-center`, open `GET /internal/operator-dashboard`, `GET /internal/operator-review-queue`, `GET /internal/operator-approval-packets`, `GET /internal/operator-action-readiness`, `GET /internal/operator-settings-change-requests`, `GET /internal/operator-settings-execution-preflight`, and `GET /internal/operator-owner-handoff-packet`, and `vyro-growth launch-readiness`, `vyro-growth settings-change-requests`, `vyro-growth settings-execution-preflight`, `vyro-growth owner-handoff-packet`, and `vyro-growth system-status` and review findings before any manual rollout. Recording a review, approval-packet, or settings-change decision from these surfaces does not execute the artifact, packet, or setting. The readiness queue, settings-execution preflight, and owner handoff packet are dry-run/read-only only. See `docs/OPERATOR_HEALTH.md`.
8. Start worker checks or cron-invoked CLI jobs as needed.

Production start fails closed when `INTERNAL_API_KEY` or `DATABASE_URL` is missing, or when a live-provider flag is true without its key.

## What this phase does not do

- No live cloud deploy, DNS, TLS, or paid provider signup.
- No emails, campaign enrollment, calendar events, Meet links, or phone calls.
- No autonomous replies.
- No staged outbound traffic.
- No PHI ingestion.
