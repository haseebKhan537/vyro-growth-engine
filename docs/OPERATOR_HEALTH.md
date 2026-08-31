# Operator health check before a manual rollout

Use this checklist before considering any staged outbound or live-provider rollout. Phase 13 is visibility only. It does not send email, enroll campaigns, create calendar events or Meet links, place calls, enable autonomous replies, or call paid providers.

Keep `OUTBOUND_ENABLED=false` and every live-provider flag disabled unless the owner later approves a change. Persistent operator halt stays halted.

## One-command status

After PostgreSQL is up and migrations are applied:

```bash
vyro-growth system-status
```

Internal HTTP equivalent (not a public API). Outside development it is fail-closed unless `INTERNAL_API_KEY` is set and the request sends a matching `X-Internal-Api-Key` header.

```bash
curl http://localhost:8000/internal/monitoring/status \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

CLI does not use the HTTP key. Both paths are read-only.

## What the snapshot includes

- Latest job/run status by phase, including the Phase 12 deployable job name
- Recent failed runs with sanitized error text
- Safety flags: `OUTBOUND_ENABLED`, persistent operator halt, live-provider flags, live artifact counts
- Phase 12 readiness/config state (`/ready` fields plus `ready_for_manual_rollout`)
- Pending operator-review counts: personalization drafts, planned enrollments, booking plans, voice plans, optimizer recommendations, content briefs
- Findings with severity `blocked`, `warning`, or `info`

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
4. `vyro-growth system-status`
5. Review `blocked` and `warning` findings. Do not enable outbound to "clear" them.
6. Review pending drafts, enrollment plans, booking plans, voice plans, optimizer recommendations, and content briefs on their existing dry-run surfaces. Approval does not publish pages or launch ads.

Do not invent prospect facts. Do not ingest or expose PHI. Do not lift the operator halt from this command.
