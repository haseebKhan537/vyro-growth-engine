# Operator health check before a manual rollout

Use this checklist before considering any staged outbound or live-provider rollout. Phase 13 is visibility only. It does not send email, enroll campaigns, create calendar events or Meet links, place calls, enable autonomous replies, or call paid providers.

Keep `OUTBOUND_ENABLED=false` and every live-provider flag disabled unless the owner later approves a change. Persistent operator halt stays halted.

## One-command status

After PostgreSQL is up and migrations are applied:

```bash
vyro-growth operator-command-center
vyro-growth launch-readiness
vyro-growth settings-change-requests
vyro-growth settings-execution-preflight
vyro-growth owner-handoff-packet
vyro-growth compliance-evidence-binder
vyro-growth release-candidate-runbook
vyro-growth action-readiness
vyro-growth system-status
```

Internal HTTP equivalents (not a public API). Outside development they are fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/operator-command-center \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-dashboard \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-review-queue \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-approval-packets \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-action-readiness \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-settings-change-requests \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-settings-execution-preflight \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-owner-handoff-packet \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-audit-timeline \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-compliance-evidence-binder \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-release-candidate-runbook \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/launch-readiness \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/settings-change-requests \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/settings-execution-preflight \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/owner-handoff-packet \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/compliance-evidence-binder \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/release-candidate-runbook \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/monitoring/status \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

CLI does not use the HTTP key. `vyro-growth launch-readiness` is the owner-facing sanitized launch checklist and secret inventory; `vyro-growth settings-change-requests` is the record-only live settings change queue; `vyro-growth settings-execution-preflight` is a dry-run simulator of remaining settings-execution blockers and is not permission to go live; `vyro-growth owner-handoff-packet` is a read-only owner-review export of those summaries and is not permission or machinery for going live; `vyro-growth compliance-evidence-binder` is a read-only owner-review export of existing safety evidence and is not permission or machinery for going live; `vyro-growth release-candidate-runbook` is a read-only planning export of future manual deployment steps and rollback checks and is not a deployment mechanism or permission to go live; `operator-command-center` is the cross-pipeline JSON summary; `GET /internal/operator-dashboard` is the same summary as an HTML shell; `GET /internal/operator-review-queue` and `GET /internal/operator-approval-packets` are HTML drilldowns; `GET /internal/operator-action-readiness` is the read-only approved action readiness queue; `GET /internal/operator-settings-change-requests` is the record-only settings change request UI; `GET /internal/operator-settings-execution-preflight` is the read-only settings-execution preflight HTML shell and is not permission to go live; `GET /internal/operator-owner-handoff-packet` is the read-only owner go-live handoff packet HTML shell and is not permission or machinery for going live; `GET /internal/operator-audit-timeline` is the read-only activity audit timeline and does not execute; `GET /internal/operator-compliance-evidence-binder` is the read-only compliance evidence binder HTML shell and is not permission or machinery for going live; `GET /internal/operator-release-candidate-runbook` is the read-only release-candidate deployment runbook HTML shell and is not a deployment mechanism or permission to go live; `GET /internal/release-candidate-runbook` is the read-only release-candidate deployment runbook JSON export and is not a deployment mechanism; review-item detail pages can record a decision only via `POST /internal/operator-review-queue/{artifact_type}/{artifact_id}/decision`; approval-packet detail pages can record a decision only via `POST /internal/operator-approval-packets/{packet_id}/decision`; settings-change detail pages can record a decision only via `POST /internal/operator-settings-change-requests/{request_id}/decision`; `system-status` remains the detailed monitoring snapshot. Decision recording does not execute artifacts, packets, or settings requests. The readiness queue, launch checklist, settings-execution preflight, owner handoff packet, activity audit timeline, compliance evidence binder, and release-candidate runbook do not execute.

## What the snapshot includes

- Latest job/run status by phase, including the Phase 12 deployable job name
- Recent failed runs with sanitized error text
- Safety flags: `OUTBOUND_ENABLED`, persistent operator halt, live-provider flags, live artifact counts
- Phase 12 readiness/config state (`/ready` fields plus `ready_for_manual_rollout`)
- Pending operator-review counts: personalization drafts, planned enrollments, booking plans, voice plans, optimizer recommendations, acquisition channel plans, content briefs
- Findings with severity `blocked`, `warning`, or `info`, including an info finding when dry-run execution plans or owner approval packets exist and none were executed
- Command-center next-action labels for owner review (no execution)

Output is counts, statuses, timestamps, and sanitized messages only. It does not include message bodies, draft copy, emails, phones, evidence snippets, API keys, or PHI.

## How to read findings

| Severity | Meaning |
|---|---|
| `blocked` | Unsafe for a manual rollout. Outbound is on, a live-provider flag is on, live artifacts exist, or the database is unavailable. |
| `warning` | Needs operator attention before any rollout. Recent failed runs, missing operator-halt row, or Phase 12 config is not ready. |
| `info` | Expected dry-run posture. Halt is active and live flags remain off. Pending review items are listed for human follow-up. |

`ready_for_manual_rollout=true` means the process is ready, outbound and live-provider flags are off, and no stored live calendar/Meet/send/call artifacts were found. It is **not** permission to enable outbound.

## Suggested pre-rollout order

1. Confirm `.env` / runtime env still has `OUTBOUND_ENABLED=false` and every live-provider flag false. See `docs/DEPLOYMENT.md`.
2. `vyro-growth check-config`
3. Probe `/health` and `/ready`
4. `vyro-growth launch-readiness`, `vyro-growth settings-execution-preflight`, `vyro-growth owner-handoff-packet`, `vyro-growth compliance-evidence-binder`, `vyro-growth release-candidate-runbook`, `vyro-growth operator-command-center`, open `GET /internal/operator-dashboard`, `GET /internal/operator-review-queue`, `GET /internal/operator-approval-packets`, `GET /internal/operator-action-readiness`, `GET /internal/operator-settings-change-requests`, `GET /internal/operator-settings-execution-preflight`, `GET /internal/operator-owner-handoff-packet`, `GET /internal/operator-audit-timeline`, `GET /internal/operator-compliance-evidence-binder`, `GET /internal/operator-release-candidate-runbook`, and `vyro-growth system-status`
5. Review `blocked` and `warning` findings and next-action labels. Do not enable outbound to "clear" them.
6. Review pending drafts, enrollment plans, booking plans, voice plans, optimizer recommendations, acquisition channel plans, and content briefs on their existing dry-run surfaces. Approval does not publish pages or launch ads. `vyro-growth plan-approved-execution` records a dry-run plan only and does not execute. `vyro-growth generate-approval-packets` records a live-readiness packet only and does not execute.
7. Optionally run `vyro-growth smoke-dry-run --local-only` on a developer machine. It uses an isolated in-memory demo database and is not a production workflow. Pull-request CI already runs that command as job `smoke-dry-run` with live flags disabled and `vyro-growth check-smoke-output` as the sanitization gate.

Do not invent prospect facts. Do not ingest or expose PHI. Do not lift the operator halt from this command.
