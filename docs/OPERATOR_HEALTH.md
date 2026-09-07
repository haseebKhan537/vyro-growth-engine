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
vyro-growth release-artifact-manifest
vyro-growth go-live-readiness-index
vyro-growth launch-blockers-plan
vyro-growth action-readiness
vyro-growth supervised-pilot-first-send-preflight
vyro-growth supervised-pilot-launch-rehearsal-control-map
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
curl http://localhost:8000/internal/operator-release-artifact-manifest \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-go-live-readiness-index \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-launch-blockers-plan \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-staged-rollout-plan \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-owner-launch-dossier \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-provider-setup-checklist \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-go-live-rehearsal-checklist \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-rehearsal-outcome-report \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-supervised-pilot-plan \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-supervised-pilot-candidates \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-supervised-pilot-go-no-go \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-supervised-pilot-first-send-preflight \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-supervised-pilot-launch-rehearsal-control-map \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/operator-contact-validation \
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
curl http://localhost:8000/internal/release-artifact-manifest \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/go-live-readiness-index \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/launch-blockers-plan \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/staged-rollout-plan \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/owner-launch-dossier \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/provider-setup-checklist \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/go-live-rehearsal-checklist \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/rehearsal-outcome-report \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/supervised-pilot-plan \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/supervised-pilot-candidates \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/supervised-pilot-go-no-go \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/supervised-pilot-first-send-preflight \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/supervised-pilot-launch-rehearsal-control-map \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
curl http://localhost:8000/internal/monitoring/status \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY"
```

CLI does not use the HTTP key. `vyro-growth launch-readiness` is the owner-facing sanitized launch checklist and secret inventory; `vyro-growth settings-change-requests` is the record-only live settings change queue; `vyro-growth settings-execution-preflight` is a dry-run simulator of remaining settings-execution blockers and is not permission to go live; `vyro-growth owner-handoff-packet` is a read-only owner-review export of those summaries and is not permission or machinery for going live; `vyro-growth compliance-evidence-binder` is a read-only owner-review export of existing safety evidence and is not permission or machinery for going live; `vyro-growth release-candidate-runbook` is a read-only planning export of future manual deployment steps and rollback checks and is not a deployment mechanism or permission to go live; `vyro-growth release-artifact-manifest` is a read-only owner-review export of expected source/provenance, artifacts, migrations, runtime commands, and safety gates and is not a build, artifact publishing, deployment mechanism, or permission to go live; `vyro-growth go-live-readiness-index` is a read-only owner-review export of the Phase 41 go-live readiness index and is not permission to go live and not an execution surface; `vyro-growth launch-blockers-plan` is a read-only remediation-planning export of those index blockers and is not permission to go live and not an execution surface; `vyro-growth staged-rollout-plan` is a read-only staged rollout planning export of existing readiness, blocker, binder, runbook, and manifest surfaces and is not permission to go live and not an execution surface; `vyro-growth owner-launch-dossier` is a read-only owner-review export of those surfaces plus handoff, settings-preflight, and audit summaries and is not permission to go live and not an execution surface; `vyro-growth provider-setup-checklist` is a read-only provider credential/setup checklist export of those surfaces and is not permission to go live and not an execution surface; `vyro-growth go-live-rehearsal-checklist` is a read-only manual go-live rehearsal checklist export of those surfaces and is not a script runner, not permission to go live, and not an execution surface; `vyro-growth rehearsal-outcome-report` is a read-only compact outcome report of that checklist and is not permission to go live and not an execution surface; `vyro-growth supervised-pilot-plan` is a read-only supervised small-pilot planning export of those surfaces and is not permission to go live and not an execution surface; `vyro-growth supervised-pilot-candidates` is a read-only supervised pilot candidate readiness export and is not permission to go live and not an execution surface; `vyro-growth supervised-pilot-go-no-go` is a read-only supervised pilot go/no-go packet and is not permission to go live and not an execution surface; `vyro-growth supervised-pilot-first-send-preflight` is a read-only supervised pilot first-send preflight and is not permission to send, not permission to go live, and not an execution surface; `vyro-growth supervised-pilot-launch-rehearsal-control-map` is a read-only supervised pilot launch rehearsal control map and is not a script runner, not permission to send, not permission to go live, and not an execution surface; `operator-command-center` is the cross-pipeline JSON summary; `GET /internal/operator-dashboard` is the same summary as an HTML shell; `GET /internal/operator-review-queue` and `GET /internal/operator-approval-packets` are HTML drilldowns; `GET /internal/operator-action-readiness` is the read-only approved action readiness queue; `GET /internal/operator-settings-change-requests` is the record-only settings change request UI; `GET /internal/operator-settings-execution-preflight` is the read-only settings-execution preflight HTML shell and is not permission to go live; `GET /internal/operator-owner-handoff-packet` is the read-only owner go-live handoff packet HTML shell and is not permission or machinery for going live; `GET /internal/operator-audit-timeline` is the read-only activity audit timeline and does not execute; `GET /internal/operator-compliance-evidence-binder` is the read-only compliance evidence binder HTML shell and is not permission or machinery for going live; `GET /internal/operator-release-candidate-runbook` is the read-only release-candidate deployment runbook HTML shell and is not a deployment mechanism or permission to go live; `GET /internal/operator-release-artifact-manifest` is the read-only release artifact manifest HTML shell and is not a build, artifact publishing, deployment mechanism, or permission to go live; `GET /internal/operator-go-live-readiness-index` is the read-only go-live readiness index HTML page and is not permission to go live and not an execution surface; `GET /internal/operator-launch-blockers-plan` is the read-only launch blockers remediation plan HTML shell and is not permission to go live and not an execution surface; `GET /internal/operator-staged-rollout-plan` is the read-only staged go-live rollout plan HTML shell and is not permission to go live and not an execution surface; `GET /internal/operator-owner-launch-dossier` is the read-only owner launch dossier HTML shell and is not permission to go live and not an execution surface; `GET /internal/operator-provider-setup-checklist` is the read-only provider setup checklist HTML shell and is not permission to go live and not an execution surface; `GET /internal/operator-go-live-rehearsal-checklist` is the read-only go-live rehearsal checklist HTML shell and is not a script runner, not permission to go live, and not an execution surface; `GET /internal/operator-rehearsal-outcome-report` is the read-only rehearsal outcome report HTML shell and is not permission to go live and not an execution surface; `GET /internal/operator-supervised-pilot-plan` is the read-only supervised pilot launch plan HTML shell and is not permission to go live and not an execution surface; `GET /internal/operator-supervised-pilot-candidates` is the read-only supervised pilot candidate readiness HTML shell and is not permission to go live and not an execution surface; `GET /internal/operator-supervised-pilot-go-no-go` is the read-only supervised pilot go/no-go HTML shell and is not permission to go live and not an execution surface; `GET /internal/operator-supervised-pilot-first-send-preflight` is the read-only supervised pilot first-send preflight HTML shell and is not permission to send, not permission to go live, and not an execution surface; `GET /internal/operator-supervised-pilot-launch-rehearsal-control-map` is the read-only supervised pilot launch rehearsal control map HTML shell and is not a script runner, not permission to send, not permission to go live, and not an execution surface; `GET /internal/operator-contact-validation` is the read-only contact-enrichment validation HTML shell and is not permission to run a supervised validation and not an execution surface; `GET /internal/go-live-readiness-index` is the read-only go-live readiness index JSON export and is also not permission to go live and not an execution surface; `GET /internal/launch-blockers-plan` is the read-only launch blockers remediation plan JSON export and is also not permission to go live and not an execution surface; `GET /internal/staged-rollout-plan` is the read-only staged go-live rollout plan JSON export and is also not permission to go live and not an execution surface; `GET /internal/owner-launch-dossier` is the read-only owner launch dossier JSON export and is also not permission to go live and not an execution surface; `GET /internal/provider-setup-checklist` is the read-only provider setup checklist JSON export and is also not permission to go live and not an execution surface; `GET /internal/go-live-rehearsal-checklist` is the read-only go-live rehearsal checklist JSON export and is also not a script runner, not permission to go live, and not an execution surface; `GET /internal/rehearsal-outcome-report` is the read-only rehearsal outcome report JSON export and is also not permission to go live and not an execution surface; `GET /internal/supervised-pilot-plan` is the read-only supervised pilot launch plan JSON export and is also not permission to go live and not an execution surface; `GET /internal/supervised-pilot-candidates` is the read-only supervised pilot candidate readiness JSON export and is also not permission to go live and not an execution surface; `GET /internal/supervised-pilot-go-no-go` is the read-only supervised pilot go/no-go JSON export and is also not permission to go live and not an execution surface; `GET /internal/supervised-pilot-first-send-preflight` is the read-only supervised pilot first-send preflight JSON export and is also not permission to send, not permission to go live, and not an execution surface; `GET /internal/supervised-pilot-launch-rehearsal-control-map` is the read-only supervised pilot launch rehearsal control map JSON export and is also not a script runner, not permission to send, not permission to go live, and not an execution surface; `GET /internal/release-candidate-runbook` is the read-only release-candidate deployment runbook JSON export and is not a deployment mechanism; `GET /internal/release-artifact-manifest` is the read-only release artifact manifest JSON export and is not a build or deploy; review-item detail pages can record a decision only via `POST /internal/operator-review-queue/{artifact_type}/{artifact_id}/decision`; approval-packet detail pages can record a decision only via `POST /internal/operator-approval-packets/{packet_id}/decision`; settings-change detail pages can record a decision only via `POST /internal/operator-settings-change-requests/{request_id}/decision`; `system-status` remains the detailed monitoring snapshot. Decision recording does not execute artifacts, packets, or settings requests. The readiness queue, launch checklist, settings-execution preflight, owner handoff packet, activity audit timeline, compliance evidence binder, release-candidate runbook, release artifact manifest, go-live readiness index, launch blockers remediation plan, staged go-live rollout plan, owner launch dossier, provider setup checklist, go-live rehearsal checklist, rehearsal outcome report, supervised pilot launch plan, supervised pilot candidate readiness, supervised pilot go/no-go packet, supervised pilot first-send preflight, and supervised pilot launch rehearsal control map do not execute.

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
4. `vyro-growth launch-readiness`, `vyro-growth settings-execution-preflight`, `vyro-growth owner-handoff-packet`, `vyro-growth compliance-evidence-binder`, `vyro-growth release-candidate-runbook`, `vyro-growth release-artifact-manifest`, `vyro-growth go-live-readiness-index`, `vyro-growth launch-blockers-plan`, `vyro-growth operator-command-center`, open `GET /internal/operator-dashboard`, `GET /internal/operator-review-queue`, `GET /internal/operator-approval-packets`, `GET /internal/operator-action-readiness`, `GET /internal/operator-settings-change-requests`, `GET /internal/operator-settings-execution-preflight`, `GET /internal/operator-owner-handoff-packet`, `GET /internal/operator-audit-timeline`, `GET /internal/operator-compliance-evidence-binder`, `GET /internal/operator-release-candidate-runbook`, `GET /internal/operator-release-artifact-manifest`, `GET /internal/operator-go-live-readiness-index`, `GET /internal/operator-launch-blockers-plan`, `GET /internal/operator-staged-rollout-plan`, `GET /internal/operator-owner-launch-dossier`, `GET /internal/operator-provider-setup-checklist`, `GET /internal/operator-go-live-rehearsal-checklist`, `GET /internal/operator-rehearsal-outcome-report`, `GET /internal/operator-supervised-pilot-plan`, `GET /internal/operator-supervised-pilot-candidates`, `GET /internal/operator-supervised-pilot-go-no-go`, `GET /internal/operator-supervised-pilot-first-send-preflight`, `GET /internal/operator-supervised-pilot-launch-rehearsal-control-map`, `GET /internal/operator-contact-validation`, `GET /internal/supervised-pilot-go-no-go`, `GET /internal/release-artifact-manifest`, `GET /internal/go-live-readiness-index`, `GET /internal/launch-blockers-plan`, `GET /internal/staged-rollout-plan`, `GET /internal/provider-setup-checklist`, `GET /internal/go-live-rehearsal-checklist`, `GET /internal/rehearsal-outcome-report`, `GET /internal/supervised-pilot-plan`, `vyro-growth provider-setup-checklist`, `vyro-growth go-live-rehearsal-checklist`, `vyro-growth rehearsal-outcome-report`, `vyro-growth supervised-pilot-plan`, `vyro-growth supervised-pilot-candidates`, `vyro-growth supervised-pilot-go-no-go`, and `vyro-growth system-status`
5. Review `blocked` and `warning` findings and next-action labels. Do not enable outbound to "clear" them.
6. Review pending drafts, enrollment plans, booking plans, voice plans, optimizer recommendations, acquisition channel plans, and content briefs on their existing dry-run surfaces. Approval does not publish pages or launch ads. `vyro-growth plan-approved-execution` records a dry-run plan only and does not execute. `vyro-growth generate-approval-packets` records a live-readiness packet only and does not execute.
7. Optionally run `vyro-growth smoke-dry-run --local-only` on a developer machine. It uses an isolated in-memory demo database and is not a production workflow. Pull-request CI already runs that command as job `smoke-dry-run` with live flags disabled and `vyro-growth check-smoke-output` as the sanitization gate.

Do not invent prospect facts. Do not ingest or expose PHI. Do not lift the operator halt from this command.
