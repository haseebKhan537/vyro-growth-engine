# Operator health check before a manual rollout

Use this checklist before considering any staged outbound or live-provider rollout. Phase 13 is visibility only. It does not send email, enroll campaigns, create calendar events or Meet links, place calls, enable autonomous replies, or call paid providers.

Keep `OUTBOUND_ENABLED=false` and every live-provider flag disabled unless the owner later approves a change. Persistent operator halt stays halted.

## One-command status

After PostgreSQL is up and migrations are applied:

```bash
vyro-growth operator-command-center
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
curl http://localhost:8000/internal/monitoring/status \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

CLI does not use the HTTP key. `operator-command-center` is the cross-pipeline JSON summary; `GET /internal/operator-dashboard` is the same summary as an HTML shell; `GET /internal/operator-review-queue` and `GET /internal/operator-approval-packets` are HTML drilldowns; review-item detail pages can record a decision only via `POST /internal/operator-review-queue/{artifact_type}/{artifact_id}/decision`; approval-packet detail pages can record a decision only via `POST /internal/operator-approval-packets/{packet_id}/decision`; `system-status` remains the detailed monitoring snapshot. Decision recording does not execute artifacts or packets.

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
4. `vyro-growth operator-command-center`, open `GET /internal/operator-dashboard`, `GET /internal/operator-review-queue`, `GET /internal/operator-approval-packets`, and `vyro-growth system-status`
5. Review `blocked` and `warning` findings and next-action labels. Do not enable outbound to "clear" them.
6. Review pending drafts, enrollment plans, booking plans, voice plans, optimizer recommendations, acquisition channel plans, and content briefs on their existing dry-run surfaces. Approval does not publish pages or launch ads. `vyro-growth plan-approved-execution` records a dry-run plan only and does not execute. `vyro-growth generate-approval-packets` records a live-readiness packet only and does not execute.

Do not invent prospect facts. Do not ingest or expose PHI. Do not lift the operator halt from this command.
