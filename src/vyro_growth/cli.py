from __future__ import annotations

import argparse
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from uuid import UUID

from vyro_growth.api.discovery import NppesDiscoveryRequest, run_nppes_discovery
from vyro_growth.config import (
    RuntimeConfigError,
    get_settings,
    live_provider_flags,
    require_valid_runtime_settings,
    validate_runtime_settings,
)
from vyro_growth.database import SessionLocal
from vyro_growth.domain import (
    ContentBriefType,
    LaunchReadinessStatus,
    VoiceConsentChannel,
    VoiceConsentSource,
)
from vyro_growth.providers.calendar_booking import build_booking_calendar_provider
from vyro_growth.providers.decision_makers import build_decision_maker_provider
from vyro_growth.providers.email_verification import build_email_verification_provider
from vyro_growth.providers.nppes import NARROW_FILTER_ERROR, NppesSearchQuery
from vyro_growth.providers.personalization import build_personalization_provider
from vyro_growth.providers.reply_classification import build_reply_classifier
from vyro_growth.providers.smartlead import build_smartlead_provider
from vyro_growth.providers.voice_qualification import (
    build_voice_qualification_provider,
    parse_consent_timestamp,
)
from vyro_growth.providers.website import HeuristicWebsiteSearchProvider
from vyro_growth.providers.website_client import build_public_page_fetcher
from vyro_growth.services.action_readiness import (
    ActionReadinessFilters,
    ActionReadinessResult,
    ActionReadinessService,
)
from vyro_growth.services.approval_packets import (
    ApprovalPacketError,
    ApprovalPacketFilters,
    ApprovalPacketRunResult,
    ApprovalPacketService,
)
from vyro_growth.services.booking_plan import BookingPlanService
from vyro_growth.services.channel_planning import (
    ChannelPlanningService,
    ChannelPlanRunResult,
    ChannelPlanSeeds,
)
from vyro_growth.services.command_center import (
    CommandCenterSummary,
    OperatorCommandCenterService,
)
from vyro_growth.services.compliance_evidence_binder import (
    ComplianceEvidenceBinderService,
    format_compliance_evidence_binder,
)
from vyro_growth.services.contact_enrichment import ContactEnrichmentService
from vyro_growth.services.contact_enrichment_metrics import (
    ContactEnrichmentMetricsService,
    format_contact_enrichment_metrics,
)
from vyro_growth.services.contact_validation import (
    ContactValidationError,
    ContactValidationFilters,
    ContactValidationService,
    format_contact_validation_plan,
    format_contact_validation_report,
)
from vyro_growth.services.content_brief import (
    ContentBriefError,
    ContentBriefRunResult,
    ContentBriefSeed,
    ContentBriefService,
)
from vyro_growth.services.dashboard import DashboardAnalyticsService, DashboardSummary
from vyro_growth.services.email_verification import EmailVerificationService
from vyro_growth.services.email_verification_metrics import (
    EmailVerificationMetricsService,
    format_email_verification_metrics,
)
from vyro_growth.services.execution_planning import (
    ExecutionPlanFilters,
    ExecutionPlanningError,
    ExecutionPlanningService,
    ExecutionPlanRunResult,
)
from vyro_growth.services.go_live_readiness_index import (
    GoLiveReadinessIndexService,
    format_go_live_readiness_index,
)
from vyro_growth.services.go_live_rehearsal_checklist import (
    GoLiveRehearsalChecklistService,
    format_go_live_rehearsal_checklist,
)
from vyro_growth.services.growth_optimizer import GrowthOptimizerService, OptimizerRunResult
from vyro_growth.services.launch_blockers_plan import (
    LaunchBlockersPlanService,
    format_launch_blockers_plan,
)
from vyro_growth.services.launch_readiness import (
    LaunchReadinessService,
    format_launch_readiness,
)
from vyro_growth.services.lead_scoring import LeadScoringService
from vyro_growth.services.monitoring import MonitoringSnapshot, OperatorMonitoringService
from vyro_growth.services.outreach_enrollment import OutreachEnrollmentService
from vyro_growth.services.owner_handoff import (
    OwnerHandoffPacketService,
    format_owner_handoff,
)
from vyro_growth.services.owner_launch_dossier import (
    OwnerLaunchDossierService,
    format_owner_launch_dossier,
)
from vyro_growth.services.personalization import PersonalizationService
from vyro_growth.services.phone_verification import (
    PhoneVerificationError,
    PhoneVerificationOutcomeInput,
    PhoneVerificationService,
    format_phone_verification_queue,
    format_phone_verification_task,
)
from vyro_growth.services.provider_setup_checklist import (
    ProviderSetupChecklistService,
    format_provider_setup_checklist,
)
from vyro_growth.services.rehearsal_outcome_report import (
    RehearsalOutcomeReportService,
    format_rehearsal_outcome_report,
)
from vyro_growth.services.release_artifact_manifest import (
    ReleaseArtifactManifestService,
    format_release_artifact_manifest,
)
from vyro_growth.services.release_candidate_runbook import (
    ReleaseCandidateRunbookService,
    format_release_candidate_runbook,
)
from vyro_growth.services.reply_classification import ReplyClassificationService
from vyro_growth.services.review_queue import (
    ReviewDecisionResult,
    ReviewQueueError,
    ReviewQueueResult,
    ReviewQueueService,
)
from vyro_growth.services.settings_change_requests import (
    SettingsChangeRequestError,
    SettingsChangeRequestService,
    format_settings_change_list,
    format_settings_change_propose,
    format_settings_change_request,
)
from vyro_growth.services.settings_execution_preflight import (
    SettingsExecutionPreflightFilters,
    SettingsExecutionPreflightService,
    format_settings_execution_preflight,
)
from vyro_growth.services.smoke_dry_run import (
    SmokeDryRunRefused,
    format_smoke_summary,
    isolated_demo_session,
    run_smoke_dry_run,
)
from vyro_growth.services.staged_rollout_plan import (
    StagedRolloutPlanService,
    format_staged_rollout_plan,
)
from vyro_growth.services.supervised_pilot_candidates import (
    SupervisedPilotCandidateService,
    format_supervised_pilot_candidates,
)
from vyro_growth.services.supervised_pilot_first_send_preflight import (
    SupervisedPilotFirstSendPreflightService,
    format_supervised_pilot_first_send_preflight,
)
from vyro_growth.services.supervised_pilot_go_no_go import (
    SupervisedPilotGoNoGoService,
    format_supervised_pilot_go_no_go,
)
from vyro_growth.services.supervised_pilot_launch_rehearsal_control_map import (
    SupervisedPilotLaunchRehearsalControlMapService,
    format_supervised_pilot_launch_rehearsal_control_map,
)
from vyro_growth.services.supervised_pilot_plan import (
    SupervisedPilotPlanService,
    format_supervised_pilot_plan,
)
from vyro_growth.services.voice_qualification import (
    VoiceConsentInput,
    VoiceQualificationService,
)
from vyro_growth.services.website_enrichment import WebsiteEnrichmentService
from vyro_growth.smoke_ci_gate import (
    SmokeCiGateError,
    format_smoke_ci_gate_summary,
    validate_smoke_ci_output,
)
from vyro_growth.workers.catalog import DEPLOYABLE_JOBS, UNDEPLOYED_OUTBOUND_JOBS


def _add_contact_validation_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    command: str,
    help_text: str,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(command, help=help_text)
    parser.add_argument("--state", help="Limit the validation cohort to a two-letter state code")
    parser.add_argument("--city", help="Limit the validation cohort to a city")
    parser.add_argument(
        "--specialty",
        help="Limit the validation cohort to a specialty/taxonomy label",
    )
    parser.add_argument(
        "--taxonomy-description",
        help="Alias for --specialty using the NPPES taxonomy description filter",
    )
    parser.add_argument(
        "--max-cohort-size",
        type=int,
        default=200,
        help="Maximum organizations in the planned 200-practice validation cohort",
    )
    parser.add_argument("--json", action="store_true", help="Print sanitized JSON")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vyro-growth")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser(
        "discover-nppes",
        help="Run a bounded NPPES practice discovery job",
    )
    discover.add_argument("--state", help="Two-letter state code")
    discover.add_argument("--city", help="City name")
    discover.add_argument("--taxonomy-description", help="Taxonomy/specialty description")
    discover.add_argument("--organization-name", help="Organization name")
    discover.add_argument("--max-records", type=int, help="Maximum records to import")

    score = subparsers.add_parser(
        "score-leads",
        help="Score discovered organizations from stored public/business evidence only",
    )
    score.add_argument("--lead-id", help="Existing lead UUID")
    score.add_argument("--organization-id", help="Organization UUID")
    score.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum organizations to score when no id is provided",
    )

    enrich = subparsers.add_parser(
        "enrich-websites",
        help="Resolve official practice websites and extract public business facts",
    )
    enrich.add_argument("--organization-id", help="Organization UUID")
    enrich.add_argument("--candidate-url", help="Optional official-website candidate to verify")
    enrich.add_argument("--state", help="Limit batch enrichment to a two-letter state code")
    enrich.add_argument("--city", help="Limit batch enrichment to a city")
    enrich.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum organizations to enrich when no organization id is provided",
    )
    enrich.add_argument(
        "--reenrich",
        action="store_true",
        help="Re-check organizations that already have a verified website",
    )

    contacts = subparsers.add_parser(
        "enrich-contacts",
        help="Persist professional decision-maker contacts from the stub enrichment provider",
    )
    contacts.add_argument("--organization-id", help="Organization UUID")
    contacts.add_argument("--state", help="Limit batch enrichment to a two-letter state code")
    contacts.add_argument("--city", help="Limit batch enrichment to a city")
    contacts.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum organizations to enrich when no organization id is provided",
    )
    metrics = subparsers.add_parser(
        "contact-enrichment-metrics",
        help=(
            "Print sanitized contact-enrichment hit-rate counts "
            "(dry-run validation only; no outbound or live provider calls)"
        ),
    )
    metrics.add_argument("--json", action="store_true", help="Print sanitized JSON")

    verify_emails = subparsers.add_parser(
        "verify-emails",
        help=(
            "Dry-run email verification and same-domain pattern inference "
            "(no send, no SMTP, no live verifier by default)"
        ),
    )
    verify_emails.add_argument("--organization-id", help="Organization UUID")
    verify_emails.add_argument(
        "--state",
        help="Limit batch verification to a two-letter state code",
    )
    verify_emails.add_argument("--city", help="Limit batch verification to a city")
    verify_emails.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum organizations to verify when no organization id is provided",
    )
    email_metrics = subparsers.add_parser(
        "email-verification-metrics",
        help=(
            "Print sanitized email-verification funnel counts "
            "(dry-run validation only; no outbound or live verifier calls)"
        ),
    )
    email_metrics.add_argument("--json", action="store_true", help="Print sanitized JSON")

    _add_contact_validation_parser(
        subparsers,
        "contact-validation-plan",
        "Print a sanitized 200-practice contact-enrichment validation plan "
        "(dry-run measurement only; no outbound or live provider calls)",
    )
    _add_contact_validation_parser(
        subparsers,
        "contact-validation-report",
        "Print a sanitized 200-practice contact-enrichment validation report "
        "(aggregate counts only; no outbound or live provider calls)",
    )

    phone_queue = subparsers.add_parser(
        "queue-phone-verification",
        help=(
            "Queue human phone-verification tasks for organizations with "
            "NO_CONTACT_FOUND (does not place calls)"
        ),
    )
    phone_queue.add_argument("--organization-id", help="Organization UUID")
    phone_queue.add_argument(
        "--state",
        help="Limit batch queueing to a two-letter state code",
    )
    phone_queue.add_argument("--city", help="Limit batch queueing to a city")
    phone_queue.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum organizations to inspect when no organization id is provided",
    )
    phone_list = subparsers.add_parser(
        "list-phone-verification",
        help="List sanitized human phone-verification tasks (no call placement)",
    )
    phone_list.add_argument("--status", help="Limit to one task status")
    phone_list.add_argument(
        "--include-completed",
        action="store_true",
        help="Include tasks that already have a recorded outcome",
    )
    phone_list.add_argument("--json", action="store_true", help="Print sanitized JSON")
    phone_record = subparsers.add_parser(
        "record-phone-verification",
        help=(
            "Record a human phone-verification outcome without placing a call "
            "or routing through VoiceProvider"
        ),
    )
    phone_record.add_argument("--task-id", required=True, help="Phone verification task UUID")
    phone_record.add_argument(
        "--outcome",
        required=True,
        choices=(
            "completed",
            "no_answer",
            "refused",
            "wrong_number",
            "decision_maker_identified",
            "do_not_contact",
        ),
        help="Human-entered outcome to record",
    )
    phone_record.add_argument("--operator", help="Operator label (default: operator)")
    phone_record.add_argument("--notes", help="Optional sanitized operator notes")
    phone_record.add_argument("--full-name", help="Human-entered decision-maker name")
    phone_record.add_argument("--title", help="Human-entered title")
    phone_record.add_argument("--phone", help="Human-entered phone (stored, never printed)")
    phone_record.add_argument("--email", help="Human-entered email (stored, never printed)")
    phone_record.add_argument("--role-category", help="Optional stored role category")

    personalize = subparsers.add_parser(
        "personalize-leads",
        help=(
            "Generate evidence-grounded personalization drafts (dry-run, outbound-disabled)"
        ),
    )
    personalize.add_argument("--lead-id", help="Existing lead UUID")
    personalize.add_argument("--organization-id", help="Organization UUID")
    personalize.add_argument(
        "--state",
        help="Limit batch personalization to a two-letter state code",
    )
    personalize.add_argument("--city", help="Limit batch personalization to a city")
    personalize.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum organizations to personalize when no id is provided",
    )

    outreach = subparsers.add_parser(
        "plan-outreach",
        help="Create a dry-run Smartlead enrollment plan without sending email",
    )
    outreach.add_argument("--lead-id", help="Existing lead UUID")
    outreach.add_argument("--campaign-id", help="Existing campaign UUID")
    outreach.add_argument(
        "--campaign-name",
        help="Campaign name to reuse or create (default: phase-6-dry-run)",
    )
    outreach.add_argument("--state", help="Limit batch planning to a two-letter state code")
    outreach.add_argument("--city", help="Limit batch planning to a city")
    outreach.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum leads to plan when no lead id is provided",
    )

    classify = subparsers.add_parser(
        "classify-replies",
        help=(
            "Classify stored inbound replies and update CRM state (dry-run, no outbound)"
        ),
    )
    classify.add_argument("--message-id", help="Inbound outreach message UUID")
    classify.add_argument("--lead-id", help="Lead UUID with stored inbound messages")
    classify.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum unclassified inbound messages when no id is provided",
    )

    booking = subparsers.add_parser(
        "plan-booking",
        help="Create a dry-run booking plan without calendar events or Meet links",
    )
    booking.add_argument("--lead-id", help="Existing lead UUID")
    booking.add_argument("--classification-id", help="Stored meeting-request classification UUID")
    booking.add_argument(
        "--operator-request",
        action="store_true",
        help="Plan from an explicit operator booking request instead of a stored reply",
    )
    booking.add_argument(
        "--request-key",
        help="Idempotency key for an operator booking request (default: operator)",
    )
    booking.add_argument("--window-start", help="Optional requested window start (ISO-8601)")
    booking.add_argument("--window-end", help="Optional requested window end (ISO-8601)")
    booking.add_argument("--state", help="Limit batch planning to a two-letter state code")
    booking.add_argument("--city", help="Limit batch planning to a city")
    booking.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum meeting-request classifications to plan when no id is provided",
    )

    voice = subparsers.add_parser(
        "plan-voice-qualification",
        help="Create a dry-run consent-based voice qualification plan without placing calls",
    )
    voice.add_argument("--lead-id", help="Existing lead UUID")
    voice.add_argument("--message-id", help="Stored inbound reply UUID that requested a call")
    voice.add_argument("--meeting-id", help="Stored meeting UUID with permission to call")
    voice.add_argument("--booking-plan-id", help="Stored booking plan UUID with permission to call")
    voice.add_argument(
        "--operator-request",
        action="store_true",
        help="Plan from an explicit operator voice request with consent proof",
    )
    voice.add_argument(
        "--request-key",
        help="Idempotency key for an operator voice request (default: operator)",
    )
    voice.add_argument(
        "--consent-source",
        help="Consent source (inbound_reply/operator_request/meeting_permission)",
    )
    voice.add_argument(
        "--consent-channel",
        help="Consent channel (email/inbound_call/operator/booking)",
    )
    voice.add_argument("--consent-timestamp", help="Consent timestamp (ISO-8601)")
    voice.add_argument("--consent-evidence-id", help="Consent evidence or reference id")
    voice.add_argument("--permitted-phone", help="Permitted business phone for the consent proof")
    voice.add_argument("--state", help="Limit batch planning to a two-letter state code")
    voice.add_argument("--city", help="Limit batch planning to a city")
    voice.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum inbound call-request messages to plan when no id is provided",
    )

    subparsers.add_parser(
        "dashboard-summary",
        help="Print a read-only pipeline and safety summary (no outbound side effects)",
    )
    subparsers.add_parser(
        "system-status",
        help=(
            "Print a read-only operator monitoring snapshot: run health, sanitized "
            "failures, safety, readiness, and pending review counts"
        ),
    )
    subparsers.add_parser(
        "operator-command-center",
        help=(
            "Print a sanitized read-only command-center summary: pipeline counts, "
            "readiness, review/approval-packet counts, and next-action labels"
        ),
    )
    subparsers.add_parser(
        "recommend-growth",
        help=(
            "Generate dry-run growth optimizer recommendations for operator review "
            "(does not apply changes or send outreach)"
        ),
    )
    channels = subparsers.add_parser(
        "plan-acquisition-channels",
        help=(
            "Generate dry-run acquisition channel plans for operator review "
            "(does not launch campaigns, publish pages, or spend)"
        ),
    )
    channels.add_argument("--seed-specialty", help="Optional operator specialty seed")
    channels.add_argument("--seed-state", help="Optional operator geography/state seed")
    channels.add_argument(
        "--seed-keyword",
        action="append",
        dest="seed_keywords",
        help="Optional operator keyword seed (repeatable)",
    )
    channels.add_argument("--seed-partner-type", help="Optional operator partner-type seed")
    subparsers.add_parser(
        "list-channel-plans",
        help="List the latest dry-run acquisition channel plans (no launch or spend)",
    )
    review = subparsers.add_parser(
        "review-queue",
        help=(
            "List pending dry-run artifacts for operator review "
            "(records no execution and sends no outreach)"
        ),
    )
    review.add_argument(
        "--include-decided",
        action="store_true",
        help="Include artifacts that already have an operator decision",
    )
    review.add_argument(
        "--artifact-type",
        help="Limit the queue to one artifact type",
    )
    decide = subparsers.add_parser(
        "record-review",
        help=(
            "Record an approval, rejection, or needs-changes decision "
            "without executing the artifact"
        ),
    )
    decide.add_argument("--artifact-type", required=True, help="Review artifact type")
    decide.add_argument("--artifact-id", required=True, help="Review artifact UUID")
    decide.add_argument(
        "--decision",
        required=True,
        choices=("approved", "rejected", "needs_changes"),
        help="Operator decision to record",
    )
    decide.add_argument("--notes", help="Optional sanitized reviewer notes")
    decide.add_argument("--reviewer", help="Reviewer label (default: operator)")
    briefs = subparsers.add_parser(
        "draft-content-briefs",
        help=(
            "Generate review-only landing page and SEO content briefs "
            "(does not publish pages, launch ads, or spend money)"
        ),
    )
    briefs.add_argument("--specialty", help="Safe specialty seed when known")
    briefs.add_argument("--geography", help="Safe geography/state seed when known")
    briefs.add_argument(
        "--brief-type",
        help=(
            "Optional brief type: specialty_landing_page, geography_landing_page, "
            "google_ads_landing_page, seo_article, referral_partner_page"
        ),
    )
    briefs.add_argument("--topic", help="Safe operator topic seed (no unverifiable claims)")
    briefs.add_argument("--icp-label", help="Safe ICP label when known")
    briefs.add_argument("--channel-plan-id", help="Existing pending channel-plan UUID")
    subparsers.add_parser(
        "list-content-briefs",
        help="List the latest review-only content brief run (no publish side effects)",
    )
    execute = subparsers.add_parser(
        "plan-approved-execution",
        help=(
            "Generate dry-run execution plans for operator-approved review artifacts "
            "(does not send, enroll, book, call, publish, spend, or apply changes)"
        ),
    )
    execute.add_argument("--artifact-type", help="Limit planning to one approved artifact type")
    execute.add_argument("--artifact-id", help="Limit planning to one approved artifact UUID")
    subparsers.add_parser(
        "list-execution-plans",
        help="List the latest dry-run execution plans (no live action)",
    )
    packets = subparsers.add_parser(
        "generate-approval-packets",
        help=(
            "Generate live-readiness preflight and owner approval packets "
            "(does not send, enroll, book, call, publish, spend, or apply changes)"
        ),
    )
    packets.add_argument("--plan-type", help="Limit packets to one execution plan family")
    packets.add_argument("--execution-plan-id", help="Limit packets to one execution plan UUID")
    subparsers.add_parser(
        "list-approval-packets",
        help="List the latest owner approval packets (no live action)",
    )
    readiness = subparsers.add_parser(
        "action-readiness",
        help=(
            "List the read-only approved action readiness queue "
            "(does not execute approved items or packets)"
        ),
    )
    readiness.add_argument("--plan-family", help="Limit to one execution plan family")
    readiness.add_argument("--readiness-status", help="Limit to one readiness status")
    readiness.add_argument("--blocker-status", help="Limit to blocked or phase_safety_only")
    readiness.add_argument(
        "--decision-status",
        help="Limit to one review decision status (approved, rejected, needs_changes, missing)",
    )
    smoke = subparsers.add_parser(
        "smoke-dry-run",
        help=(
            "Run a local-only dry-run smoke harness against synthetic demo data "
            "(does not send, enroll, book, call, publish, spend, deploy, or execute)"
        ),
    )
    smoke.add_argument(
        "--local-only",
        action="store_true",
        help="Acknowledge this is a local demo/dry-run (required outside development)",
    )
    smoke.add_argument(
        "--dev-demo",
        action="store_true",
        help="Alias for --local-only",
    )
    smoke.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized summary as JSON",
    )
    check_smoke = subparsers.add_parser(
        "check-smoke-output",
        help=(
            "Validate sanitized smoke-dry-run JSON for the CI dry-run gate "
            "(no providers, no execution)"
        ),
    )
    check_smoke.add_argument(
        "--file",
        help="Path to sanitized JSON output. Reads stdin when omitted.",
    )
    launch_readiness = subparsers.add_parser(
        "launch-readiness",
        help=(
            "Print a sanitized launch readiness checklist and secret inventory "
            "(read-only; does not execute, call providers, or print secret values)"
        ),
    )
    launch_readiness.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized checklist as JSON",
    )
    settings_queue = subparsers.add_parser(
        "settings-change-requests",
        help=(
            "List record-only live settings change requests "
            "(does not apply settings, lift halt, or execute)"
        ),
    )
    settings_queue.add_argument("--json", action="store_true", help="Print sanitized JSON")
    settings_queue.add_argument("--status", help="Filter by request status")
    settings_queue.add_argument("--request-type", help="Filter by request type")
    settings_queue.add_argument(
        "--decision-status",
        help="Filter by owner decision status",
    )
    create_settings = subparsers.add_parser(
        "create-settings-change-request",
        help=(
            "Create a record-only live settings change request "
            "(does not apply the setting or execute)"
        ),
    )
    create_settings.add_argument("--request-type", required=True, help="Request type")
    create_settings.add_argument(
        "--setting-name",
        action="append",
        dest="setting_names",
        required=True,
        help="Requested setting name (repeatable). Names only, never secret values.",
    )
    create_settings.add_argument(
        "--desired-boolean",
        choices=("true", "false"),
        help="Proposed desired boolean. Not applied.",
    )
    create_settings.add_argument(
        "--desired-status",
        help="Proposed desired status such as disabled, enabled, halted, or configured",
    )
    create_settings.add_argument("--finding-code", help="Optional launch-readiness finding code")
    create_settings.add_argument(
        "--next-action-code",
        help="Optional launch-readiness next-action code",
    )
    create_settings.add_argument("--idempotency-key", help="Optional idempotency key")
    create_settings.add_argument("--notes", help="Optional sanitized operator notes")
    create_settings.add_argument("--json", action="store_true", help="Print sanitized JSON")
    settings_detail = subparsers.add_parser(
        "settings-change-request",
        help="Show one record-only live settings change request (no execution)",
    )
    settings_detail.add_argument("--id", required=True, help="Request UUID")
    settings_detail.add_argument("--json", action="store_true", help="Print sanitized JSON")
    record_settings = subparsers.add_parser(
        "record-settings-change-decision",
        help=(
            "Record an audit-only owner decision on a settings change request "
            "(does not apply settings, lift halt, or execute)"
        ),
    )
    record_settings.add_argument("--id", required=True, help="Request UUID")
    record_settings.add_argument(
        "--decision",
        required=True,
        choices=("approved", "rejected", "needs_changes"),
        help="Owner decision record. Approved does not apply the setting.",
    )
    record_settings.add_argument("--reviewer", help="Optional short owner/reviewer label")
    record_settings.add_argument("--notes", help="Optional sanitized notes")
    record_settings.add_argument("--json", action="store_true", help="Print sanitized JSON")
    propose_settings = subparsers.add_parser(
        "propose-settings-changes",
        help=(
            "Create record-only settings change requests from the launch-readiness "
            "checklist (does not apply settings or execute)"
        ),
    )
    propose_settings.add_argument("--json", action="store_true", help="Print sanitized JSON")
    settings_preflight = subparsers.add_parser(
        "settings-execution-preflight",
        help=(
            "Dry-run preflight for approved settings change requests "
            "(does not apply settings, lift halt, or execute; not permission to go live)"
        ),
    )
    settings_preflight.add_argument("--json", action="store_true", help="Print sanitized JSON")
    settings_preflight.add_argument("--request-type", help="Filter by request type")
    settings_preflight.add_argument(
        "--decision-status",
        help="Filter by owner decision status",
    )
    settings_preflight.add_argument(
        "--execution-status",
        help="Filter by simulated execution status",
    )
    owner_handoff = subparsers.add_parser(
        "owner-handoff-packet",
        help=(
            "Export a sanitized owner go-live handoff packet "
            "(read-only; does not execute, apply settings, or go live)"
        ),
    )
    owner_handoff.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized handoff packet as JSON",
    )
    binder = subparsers.add_parser(
        "compliance-evidence-binder",
        help=(
            "Export a sanitized compliance evidence binder "
            "(read-only; does not execute, apply settings, or go live)"
        ),
    )
    binder.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized compliance evidence binder as JSON",
    )
    runbook = subparsers.add_parser(
        "release-candidate-runbook",
        help=(
            "Export a sanitized release-candidate deployment runbook "
            "(read-only; does not deploy, apply settings, or go live)"
        ),
    )
    runbook.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized release-candidate runbook as JSON",
    )
    manifest = subparsers.add_parser(
        "release-artifact-manifest",
        help=(
            "Export a sanitized release artifact manifest "
            "(read-only; does not build, publish, deploy, or go live)"
        ),
    )
    manifest.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized release artifact manifest as JSON",
    )
    index = subparsers.add_parser(
        "go-live-readiness-index",
        help=(
            "Export a sanitized go-live readiness index "
            "(read-only; does not execute, apply settings, or go live)"
        ),
    )
    index.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized go-live readiness index as JSON",
    )
    plan = subparsers.add_parser(
        "launch-blockers-plan",
        help=(
            "Export a sanitized launch blockers remediation plan "
            "(read-only; does not execute, apply settings, or go live)"
        ),
    )
    plan.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized launch blockers remediation plan as JSON",
    )
    staged = subparsers.add_parser(
        "staged-rollout-plan",
        help=(
            "Export a sanitized staged go-live rollout plan "
            "(read-only; does not execute, deploy, apply settings, or go live)"
        ),
    )
    staged.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized staged go-live rollout plan as JSON",
    )
    dossier = subparsers.add_parser(
        "owner-launch-dossier",
        help=(
            "Export a sanitized owner launch dossier "
            "(read-only; does not execute, deploy, apply settings, or go live)"
        ),
    )
    dossier.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized owner launch dossier as JSON",
    )
    checklist = subparsers.add_parser(
        "provider-setup-checklist",
        help=(
            "Export a sanitized provider credential/setup checklist "
            "(read-only; does not execute, deploy, apply settings, or go live)"
        ),
    )
    checklist.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized provider setup checklist as JSON",
    )
    rehearsal = subparsers.add_parser(
        "go-live-rehearsal-checklist",
        help=(
            "Export a sanitized manual go-live rehearsal checklist "
            "(read-only; does not execute, deploy, apply settings, or go live)"
        ),
    )
    rehearsal.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized go-live rehearsal checklist as JSON",
    )
    outcome = subparsers.add_parser(
        "rehearsal-outcome-report",
        help=(
            "Export a sanitized rehearsal outcome report "
            "(read-only; does not execute, deploy, apply settings, or go live)"
        ),
    )
    outcome.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized rehearsal outcome report as JSON",
    )
    pilot = subparsers.add_parser(
        "supervised-pilot-plan",
        help=(
            "Export a sanitized supervised pilot launch plan "
            "(read-only; does not execute, deploy, apply settings, or go live)"
        ),
    )
    pilot.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized supervised pilot launch plan as JSON",
    )
    candidates = subparsers.add_parser(
        "supervised-pilot-candidates",
        help=(
            "Export a sanitized supervised pilot candidate readiness packet "
            "(read-only; does not execute, deploy, apply settings, or go live)"
        ),
    )
    candidates.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized supervised pilot candidate readiness packet as JSON",
    )
    go_no_go = subparsers.add_parser(
        "supervised-pilot-go-no-go",
        help=(
            "Export a sanitized supervised pilot go/no-go packet "
            "(read-only; does not execute, deploy, apply settings, or go live)"
        ),
    )
    go_no_go.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized supervised pilot go/no-go packet as JSON",
    )
    first_send = subparsers.add_parser(
        "supervised-pilot-first-send-preflight",
        help=(
            "Export a sanitized supervised pilot first-send preflight "
            "(read-only; does not execute, send, deploy, apply settings, or go live)"
        ),
    )
    first_send.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized supervised pilot first-send preflight as JSON",
    )
    control_map = subparsers.add_parser(
        "supervised-pilot-launch-rehearsal-control-map",
        help=(
            "Export a sanitized supervised pilot launch rehearsal control map "
            "(read-only; does not execute, send, deploy, apply settings, or go live)"
        ),
    )
    control_map.add_argument(
        "--json",
        action="store_true",
        help="Print the sanitized supervised pilot launch rehearsal control map as JSON",
    )
    subparsers.add_parser(
        "check-config",
        help="Validate runtime settings without connecting to live providers",
    )
    worker = subparsers.add_parser(
        "worker",
        help="Inspect the in-process worker catalog (no durable queue, no outbound)",
    )
    worker.add_argument(
        "--list",
        action="store_true",
        help="List deployable dry-run job names",
    )
    worker.add_argument(
        "--check",
        action="store_true",
        help="Validate runtime config and print the job catalog summary",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "discover-nppes":
        query = NppesSearchQuery(
            state=args.state,
            city=args.city,
            taxonomy_description=args.taxonomy_description,
            organization_name=args.organization_name,
        )
        if not query.has_narrow_filter():
            parser.error(NARROW_FILTER_ERROR)

        request = NppesDiscoveryRequest(
            state=args.state,
            city=args.city,
            taxonomy_description=args.taxonomy_description,
            organization_name=args.organization_name,
            max_records=args.max_records,
        )
        with SessionLocal() as db:
            result = run_nppes_discovery(db, request)
        print(
            "Discovery run completed:",
            f"id={result.discovery_run_id}",
            f"fetched={result.records_fetched}",
            f"upserted={result.records_upserted}",
            f"skipped={result.records_skipped}",
            f"status={result.status.value}",
        )
        return 0

    if args.command == "score-leads":
        return _run_score_leads(parser, args)

    if args.command == "enrich-websites":
        return _run_enrich_websites(parser, args)

    if args.command == "enrich-contacts":
        return _run_enrich_contacts(args)

    if args.command == "contact-enrichment-metrics":
        return _run_contact_enrichment_metrics(args)

    if args.command == "verify-emails":
        return _run_verify_emails(args)

    if args.command == "email-verification-metrics":
        return _run_email_verification_metrics(args)

    if args.command == "contact-validation-plan":
        return _run_contact_validation_plan(args)

    if args.command == "contact-validation-report":
        return _run_contact_validation_report(args)

    if args.command == "queue-phone-verification":
        return _run_queue_phone_verification(args)

    if args.command == "list-phone-verification":
        return _run_list_phone_verification(args)

    if args.command == "record-phone-verification":
        return _run_record_phone_verification(args)

    if args.command == "personalize-leads":
        return _run_personalize_leads(parser, args)

    if args.command == "plan-outreach":
        return _run_plan_outreach(args)

    if args.command == "classify-replies":
        return _run_classify_replies(parser, args)

    if args.command == "plan-booking":
        return _run_plan_booking(parser, args)

    if args.command == "plan-voice-qualification":
        return _run_plan_voice_qualification(parser, args)

    if args.command == "dashboard-summary":
        return _run_dashboard_summary()

    if args.command == "system-status":
        return _run_system_status()

    if args.command == "operator-command-center":
        return _run_operator_command_center()

    if args.command == "recommend-growth":
        return _run_recommend_growth()

    if args.command == "plan-acquisition-channels":
        return _run_plan_acquisition_channels(args)

    if args.command == "list-channel-plans":
        return _run_list_channel_plans()

    if args.command == "review-queue":
        return _run_review_queue(args)

    if args.command == "record-review":
        return _run_record_review(args)

    if args.command == "draft-content-briefs":
        return _run_draft_content_briefs(parser, args)

    if args.command == "list-content-briefs":
        return _run_list_content_briefs()

    if args.command == "plan-approved-execution":
        return _run_plan_approved_execution(args)

    if args.command == "list-execution-plans":
        return _run_list_execution_plans()

    if args.command == "generate-approval-packets":
        return _run_generate_approval_packets(args)

    if args.command == "list-approval-packets":
        return _run_list_approval_packets()

    if args.command == "action-readiness":
        return _run_action_readiness(args)

    if args.command == "smoke-dry-run":
        return _run_smoke_dry_run(args)

    if args.command == "check-smoke-output":
        return _run_check_smoke_output(args)

    if args.command == "launch-readiness":
        return _run_launch_readiness(args)

    if args.command == "settings-change-requests":
        return _run_settings_change_requests(args)

    if args.command == "create-settings-change-request":
        return _run_create_settings_change_request(args)

    if args.command == "settings-change-request":
        return _run_settings_change_request_detail(args)

    if args.command == "record-settings-change-decision":
        return _run_record_settings_change_decision(args)

    if args.command == "propose-settings-changes":
        return _run_propose_settings_changes(args)

    if args.command == "settings-execution-preflight":
        return _run_settings_execution_preflight(args)

    if args.command == "owner-handoff-packet":
        return _run_owner_handoff_packet(args)

    if args.command == "compliance-evidence-binder":
        return _run_compliance_evidence_binder(args)

    if args.command == "release-candidate-runbook":
        return _run_release_candidate_runbook(args)

    if args.command == "release-artifact-manifest":
        return _run_release_artifact_manifest(args)

    if args.command == "go-live-readiness-index":
        return _run_go_live_readiness_index(args)

    if args.command == "launch-blockers-plan":
        return _run_launch_blockers_plan(args)

    if args.command == "staged-rollout-plan":
        return _run_staged_rollout_plan(args)

    if args.command == "owner-launch-dossier":
        return _run_owner_launch_dossier(args)

    if args.command == "provider-setup-checklist":
        return _run_provider_setup_checklist(args)

    if args.command == "go-live-rehearsal-checklist":
        return _run_go_live_rehearsal_checklist(args)

    if args.command == "rehearsal-outcome-report":
        return _run_rehearsal_outcome_report(args)

    if args.command == "supervised-pilot-plan":
        return _run_supervised_pilot_plan(args)

    if args.command == "supervised-pilot-candidates":
        return _run_supervised_pilot_candidates(args)

    if args.command == "supervised-pilot-go-no-go":
        return _run_supervised_pilot_go_no_go(args)

    if args.command == "supervised-pilot-first-send-preflight":
        return _run_supervised_pilot_first_send_preflight(args)

    if args.command == "supervised-pilot-launch-rehearsal-control-map":
        return _run_supervised_pilot_launch_rehearsal_control_map(args)

    if args.command == "check-config":
        return _run_check_config()

    if args.command == "worker":
        return _run_worker(args)

    parser.error(f"Unsupported command: {args.command}")
    return 1


def _run_score_leads(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.lead_id and args.organization_id:
        parser.error("Provide --lead-id or --organization-id, not both")
    scoring_service = LeadScoringService()
    with SessionLocal() as db:
        if args.lead_id:
            score_results = [scoring_service.score_lead(db, UUID(args.lead_id))]
        elif args.organization_id:
            score_results = [scoring_service.score_organization(db, UUID(args.organization_id))]
        else:
            score_results = list(scoring_service.score_batch(db, limit=args.limit))
    for score_item in score_results:
        print(
            "Scored lead:",
            f"id={score_item.lead_id}",
            f"organization_id={score_item.organization_id}",
            f"score={score_item.scoring.total}",
            f"band={score_item.scoring.band.value}",
            f"model={score_item.scoring.model_version}",
        )
    print(f"scored={len(score_results)}")
    return 0


def _run_enrich_websites(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.candidate_url and not args.organization_id:
        parser.error("--candidate-url requires --organization-id")
    settings = get_settings()
    enrichment_service = WebsiteEnrichmentService(
        HeuristicWebsiteSearchProvider(),
        build_public_page_fetcher(
            timeout_seconds=settings.website_fetch_timeout_seconds,
            max_bytes=settings.website_fetch_max_bytes,
            max_redirects=settings.website_fetch_max_redirects,
            rate_limit_seconds=settings.website_rate_limit_seconds,
            user_agent=settings.website_user_agent,
        ),
        max_pages_per_org=settings.website_max_pages_per_org,
    )
    with SessionLocal() as db:
        if args.organization_id:
            enrichment_results = [
                enrichment_service.enrich_organization(
                    db,
                    UUID(args.organization_id),
                    candidate_url=args.candidate_url,
                    skip_verified=not args.reenrich and not args.candidate_url,
                )
            ]
        else:
            enrichment_results = list(
                enrichment_service.enrich_batch(
                    db,
                    limit=args.limit,
                    skip_verified=not args.reenrich,
                    state=args.state,
                    city=args.city,
                )
            )
    for enrichment_item in enrichment_results:
        print(
            "Website enrichment:",
            f"organization_id={enrichment_item.organization_id}",
            f"match={enrichment_item.match_status.value}",
            f"website={enrichment_item.official_website or '-'}",
            f"facts={enrichment_item.facts_extracted}",
            f"status={enrichment_item.status.value}",
        )
    print(f"enriched={len(enrichment_results)}")
    return 0


def _run_enrich_contacts(args: argparse.Namespace) -> int:
    service = ContactEnrichmentService(build_decision_maker_provider())
    with SessionLocal() as db:
        if args.organization_id:
            contact_results = [service.enrich_organization(db, UUID(args.organization_id))]
        else:
            contact_results = list(
                service.enrich_batch(
                    db,
                    limit=args.limit,
                    state=args.state,
                    city=args.city,
                )
            )
    for item in contact_results:
        print(
            "Contact enrichment:",
            f"organization_id={item.organization_id}",
            f"upserted={item.contacts_upserted}",
            f"skipped={item.contacts_skipped}",
            f"provider={item.provider_name}",
            f"status={item.status.value}",
            f"phone_verification_queued={item.phone_verification_queued}",
        )
    print(f"enriched={len(contact_results)}")
    return 0


def _run_contact_enrichment_metrics(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        metrics = ContactEnrichmentMetricsService().summarize(db, settings)
    print(format_contact_enrichment_metrics(metrics, as_json=args.json))
    return 0


def _run_verify_emails(args: argparse.Namespace) -> int:
    service = EmailVerificationService(build_email_verification_provider())
    with SessionLocal() as db:
        if args.organization_id:
            results = [service.verify_organization(db, UUID(args.organization_id))]
        else:
            results = list(
                service.verify_batch(
                    db,
                    limit=args.limit,
                    state=args.state,
                    city=args.city,
                )
            )
    for item in results:
        print(
            "Email verification:",
            f"organization_id={item.organization_id}",
            f"considered={item.contacts_considered}",
            f"verified={item.verified_count}",
            f"no_verified_email={item.no_verified_email_count}",
            f"inferred={item.inferred_count}",
            f"promoted={item.promoted_count}",
            f"provider={item.provider_name}",
            f"status={item.status.value}",
        )
    print(f"verified_runs={len(results)}")
    return 0


def _run_email_verification_metrics(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        metrics = EmailVerificationMetricsService().summarize(db, settings)
    print(format_email_verification_metrics(metrics, as_json=args.json))
    return 0


def _contact_validation_filters(args: argparse.Namespace) -> ContactValidationFilters:
    return ContactValidationFilters(
        state=args.state,
        city=args.city,
        specialty=args.specialty,
        taxonomy_description=args.taxonomy_description,
        max_cohort_size=args.max_cohort_size,
    )


def _run_contact_validation_plan(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        try:
            plan = ContactValidationService().build_plan(
                db,
                settings,
                _contact_validation_filters(args),
            )
        except ContactValidationError as exc:
            print(f"Contact validation error: {exc.message}")
            return 1
    print(format_contact_validation_plan(plan, as_json=args.json))
    return 0


def _run_contact_validation_report(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        try:
            report = ContactValidationService().build_report(
                db,
                settings,
                _contact_validation_filters(args),
            )
        except ContactValidationError as exc:
            print(f"Contact validation error: {exc.message}")
            return 1
    print(format_contact_validation_report(report, as_json=args.json))
    return 0


def _run_queue_phone_verification(args: argparse.Namespace) -> int:
    service = PhoneVerificationService()
    with SessionLocal() as db:
        try:
            results = service.queue_missing_contacts(
                db,
                organization_id=UUID(args.organization_id) if args.organization_id else None,
                limit=args.limit,
                state=args.state,
                city=args.city,
                source="cli",
            )
        except PhoneVerificationError as exc:
            print(f"Phone verification error: {exc.message}")
            return 1
        except ValueError:
            print("Phone verification error: organization id must be a UUID")
            return 1
    for item in results:
        print(format_phone_verification_task(item))
    print(f"queued={len(results)}")
    return 0


def _run_list_phone_verification(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        try:
            result = PhoneVerificationService(settings).list_tasks(
                db,
                settings,
                status=args.status,
                include_completed=args.include_completed,
            )
        except PhoneVerificationError as exc:
            print(f"Phone verification error: {exc.message}")
            return 1
    print(format_phone_verification_queue(result, as_json=args.json))
    return 0


def _run_record_phone_verification(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        try:
            result = PhoneVerificationService().record_outcome(
                db,
                UUID(args.task_id),
                PhoneVerificationOutcomeInput(
                    outcome=args.outcome,
                    operator=args.operator,
                    notes=args.notes,
                    full_name=args.full_name,
                    title=args.title,
                    phone=args.phone,
                    email=args.email,
                    role_category=args.role_category,
                ),
                source="cli",
            )
        except PhoneVerificationError as exc:
            print(f"Phone verification error: {exc.message}")
            return 1
        except ValueError:
            print("Phone verification error: task id must be a UUID")
            return 1
    print(format_phone_verification_task(result))
    return 0


def _run_personalize_leads(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.lead_id and args.organization_id:
        parser.error("Provide --lead-id or --organization-id, not both")
    service = PersonalizationService(build_personalization_provider())
    with SessionLocal() as db:
        if args.lead_id:
            results = [service.personalize_lead(db, UUID(args.lead_id))]
        elif args.organization_id:
            results = [service.personalize_organization(db, UUID(args.organization_id))]
        else:
            results = list(
                service.personalize_batch(
                    db,
                    limit=args.limit,
                    state=args.state,
                    city=args.city,
                )
            )
    for item in results:
        print(
            "Personalization:",
            f"lead_id={item.lead_id}",
            f"organization_id={item.organization_id}",
            f"draft_id={item.draft_id or '-'}",
            f"readiness={item.readiness_status.value if item.readiness_status else '-'}",
            f"provider={item.provider_name}",
            f"reused={item.reused_existing_draft}",
            f"outbound_attempted={item.outbound_attempted}",
            f"status={item.status.value}",
        )
    print(f"personalized={len(results)}")
    return 0


def _run_plan_outreach(args: argparse.Namespace) -> int:
    campaign_id = UUID(args.campaign_id) if args.campaign_id else None
    service = OutreachEnrollmentService(build_smartlead_provider())
    with SessionLocal() as db:
        if args.lead_id:
            result = service.plan_lead(
                db,
                UUID(args.lead_id),
                campaign_id=campaign_id,
                campaign_name=args.campaign_name,
            )
        else:
            result = service.plan_batch(
                db,
                limit=args.limit,
                state=args.state,
                city=args.city,
                campaign_id=campaign_id,
                campaign_name=args.campaign_name,
            )
    print(
        "Outreach plan:",
        f"id={result.outreach_plan_run_id}",
        f"campaign_id={result.campaign_id}",
        f"planned={result.planned_count}",
        f"skipped={result.skipped_count}",
        f"suppressed={result.suppressed_count}",
        f"blocked={result.blocked_count}",
        f"reused={result.reused_count}",
        f"status={result.status.value}",
    )
    return 0


def _run_classify_replies(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.message_id and args.lead_id:
        parser.error("Provide --message-id or --lead-id, not both")
    service = ReplyClassificationService(build_reply_classifier())
    with SessionLocal() as db:
        if args.message_id:
            results = [service.classify_message(db, UUID(args.message_id))]
        elif args.lead_id:
            results = list(service.classify_lead(db, UUID(args.lead_id)))
        else:
            results = list(service.classify_batch(db, limit=args.limit))
    for item in results:
        print(
            "Reply classification:",
            f"lead_id={item.lead_id}",
            f"message_id={item.message_id or '-'}",
            f"intent={item.intent.value if item.intent else '-'}",
            f"outcome={item.outcome.value}",
            f"provider={item.provider_name}",
            f"reused={item.reused_existing}",
            f"suppressed={item.suppressed}",
            f"stage={item.lead_stage_after}",
            f"outbound_attempted={item.outbound_attempted}",
        )
    print(f"classified={len(results)}")
    return 0


def _run_plan_booking(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.lead_id and args.classification_id and not args.operator_request:
        parser.error("Provide --lead-id or --classification-id, not both")
    if args.operator_request and not args.lead_id:
        parser.error("--operator-request requires --lead-id")
    requested_window = _requested_window(args.window_start, args.window_end)
    service = BookingPlanService(build_booking_calendar_provider())
    with SessionLocal() as db:
        if args.classification_id and not args.lead_id:
            result = service.plan_classification(db, UUID(args.classification_id))
        elif args.lead_id:
            result = service.plan_lead(
                db,
                UUID(args.lead_id),
                classification_id=(
                    UUID(args.classification_id) if args.classification_id else None
                ),
                operator_request=args.operator_request,
                request_key=args.request_key,
                requested_window=requested_window,
            )
        else:
            result = service.plan_batch(
                db,
                limit=args.limit,
                state=args.state,
                city=args.city,
            )
    print(
        "Booking plan:",
        f"id={result.booking_plan_run_id}",
        f"planned={result.planned_count}",
        f"skipped={result.skipped_count}",
        f"suppressed={result.suppressed_count}",
        f"blocked={result.blocked_count}",
        f"reused={result.reused_count}",
        f"status={result.status.value}",
    )
    return 0


def _requested_window(start: str | None, end: str | None) -> dict[str, object] | None:
    if not start and not end:
        return None
    window: dict[str, object] = {}
    if start:
        window["starts_at"] = start
    if end:
        window["ends_at"] = end
    return window


def _run_plan_voice_qualification(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    selected = [
        bool(args.lead_id),
        bool(args.message_id),
        bool(args.meeting_id),
        bool(args.booking_plan_id),
    ]
    if sum(1 for item in selected if item) > 1 and not args.lead_id:
        parser.error("Provide one of --lead-id, --message-id, --meeting-id, or --booking-plan-id")
    if args.operator_request and not args.lead_id:
        parser.error("--operator-request requires --lead-id")
    consent = _voice_consent_input(args)
    service = VoiceQualificationService(build_voice_qualification_provider())
    with SessionLocal() as db:
        if args.message_id and not args.lead_id:
            result = service.plan_message(db, UUID(args.message_id))
        elif args.meeting_id and not args.lead_id:
            result = service.plan_meeting(db, UUID(args.meeting_id), consent=consent)
        elif args.lead_id:
            result = service.plan_lead(
                db,
                UUID(args.lead_id),
                message_id=UUID(args.message_id) if args.message_id else None,
                meeting_id=UUID(args.meeting_id) if args.meeting_id else None,
                booking_plan_id=UUID(args.booking_plan_id) if args.booking_plan_id else None,
                operator_request=args.operator_request,
                request_key=args.request_key,
                consent=consent,
            )
        else:
            result = service.plan_batch(
                db,
                limit=args.limit,
                state=args.state,
                city=args.city,
            )
    print(
        "Voice qualification:",
        f"id={result.voice_qualification_run_id}",
        f"planned={result.planned_count}",
        f"skipped={result.skipped_count}",
        f"suppressed={result.suppressed_count}",
        f"blocked={result.blocked_count}",
        f"reused={result.reused_count}",
        f"status={result.status.value}",
    )
    return 0


def _voice_consent_input(args: argparse.Namespace) -> VoiceConsentInput | None:
    source = _voice_source(args.consent_source)
    channel = _voice_channel(args.consent_channel)
    consented_at = parse_consent_timestamp(args.consent_timestamp)
    permitted_phone = args.permitted_phone
    evidence_id = args.consent_evidence_id
    if (
        source is None
        and channel is None
        and consented_at is None
        and not permitted_phone
        and not evidence_id
    ):
        return None
    return VoiceConsentInput(
        source=source,
        channel=channel,
        consented_at=consented_at,
        permitted_phone=permitted_phone,
        evidence_reference_id=evidence_id,
    )


def _voice_source(value: str | None) -> VoiceConsentSource | None:
    if not value:
        return None
    try:
        return VoiceConsentSource(value)
    except ValueError:
        return None


def _voice_channel(value: str | None) -> VoiceConsentChannel | None:
    if not value:
        return None
    try:
        return VoiceConsentChannel(value)
    except ValueError:
        return None


def _run_dashboard_summary() -> int:
    settings = get_settings()
    with SessionLocal() as db:
        summary = DashboardAnalyticsService().summarize(db, settings)
    _print_dashboard_summary(summary)
    return 0


def _print_dashboard_summary(summary: DashboardSummary) -> None:
    safety = summary.safety
    print(
        "Dashboard safety:",
        f"outbound_enabled={safety.outbound_enabled}",
        f"operator_halt={safety.operator_halt_status}",
        f"planned={safety.planned_count}",
        f"skipped={safety.skipped_count}",
        f"suppressed={safety.suppressed_count}",
        f"blocked={safety.blocked_count}",
        f"live_calendar_events={safety.live_calendar_events}",
        f"live_meet_links={safety.live_meet_links}",
        f"live_phone_calls={safety.live_phone_calls}",
        f"phi_fields_present={safety.phi_fields_present}",
    )
    print(
        "Discovery:",
        f"organizations={summary.discovery.organizations}",
        f"leads={summary.discovery.leads}",
        f"runs={summary.discovery.discovery_runs}",
    )
    print(
        "Website enrichment:",
        f"runs={summary.website_enrichment.enrichment_runs}",
        f"match={summary.website_enrichment.by_match_status}",
    )
    print(
        "Decision-makers:",
        f"contacts={summary.decision_maker_enrichment.contacts}",
        f"runs={summary.decision_maker_enrichment.enrichment_runs}",
    )
    print(
        "Scoring:",
        f"latest={summary.scoring.latest_scores}",
        f"bands={summary.scoring.by_band}",
    )
    print(
        "Personalization:",
        f"drafts={summary.personalization.drafts}",
        f"readiness={summary.personalization.by_readiness}",
    )
    print(
        "Outreach plans:",
        f"planned={summary.outreach_plans.planned_count}",
        f"skipped={summary.outreach_plans.skipped_count}",
        f"suppressed={summary.outreach_plans.suppressed_count}",
        f"blocked={summary.outreach_plans.blocked_count}",
    )
    print(
        "Reply classifications:",
        f"total={summary.reply_classifications.classifications}",
        f"outcomes={summary.reply_classifications.by_outcome}",
    )
    print(
        "Booking plans:",
        f"planned={summary.booking_plans.planned_count}",
        f"events_created={summary.booking_plans.events_created}",
        f"meet_links_created={summary.booking_plans.meet_links_created}",
    )
    print(
        "Voice qualification plans:",
        f"planned={summary.voice_qualification_plans.planned_count}",
        f"calls_placed={summary.voice_qualification_plans.calls_placed}",
    )
    print(
        "Suppressions:",
        f"records={summary.suppressions.records}",
        f"reasons={summary.suppressions.by_reason}",
    )
    for run in summary.latest_runs:
        print(
            "Latest run:",
            f"phase={run.phase}",
            f"status={run.status}",
            f"run_id={run.run_id or '-'}",
        )


def _run_system_status() -> int:
    settings = get_settings()
    with SessionLocal() as db:
        snapshot = OperatorMonitoringService().snapshot(db, settings)
    _print_system_status(snapshot)
    return 0


def _print_system_status(snapshot: MonitoringSnapshot) -> None:
    safety = snapshot.safety
    readiness = snapshot.readiness
    pending = snapshot.pending_review
    print(
        "System status:",
        f"overall={snapshot.overall_severity.value}",
        f"read_only={snapshot.read_only}",
        f"ready_for_manual_rollout={readiness.ready_for_manual_rollout}",
    )
    print(
        "Safety:",
        f"outbound_enabled={safety.outbound_enabled}",
        f"operator_halt={safety.operator_halt_status}",
        f"live_providers_enabled={safety.live_providers_enabled}",
        f"live_calendar_events={safety.live_calendar_events}",
        f"live_meet_links={safety.live_meet_links}",
        f"live_phone_calls={safety.live_phone_calls}",
        f"phi_fields_present={safety.phi_fields_present}",
    )
    print(
        "Readiness:",
        f"status={readiness.status}",
        f"environment={readiness.environment}",
        f"database={readiness.database}",
        f"config_ok={readiness.config_ok}",
    )
    print(
        "Pending review:",
        f"drafts={pending.personalization_drafts}",
        f"enrollments={pending.enrollment_plans}",
        f"bookings={pending.booking_plans}",
        f"voice={pending.voice_plans}",
        f"optimizer={pending.optimizer_recommendations}",
        f"channel_plans={pending.channel_plans}",
        f"content_briefs={pending.content_briefs}",
        f"total={pending.total}",
    )
    for run in snapshot.latest_runs:
        print(
            "Latest run:",
            f"phase={run.phase}",
            f"job={run.job_name or '-'}",
            f"status={run.status}",
            f"run_id={run.run_id or '-'}",
        )
    for failure in snapshot.recent_failures:
        print(
            "Failure:",
            f"phase={failure.phase}",
            f"status={failure.status}",
            f"error={failure.error_message or '-'}",
        )
    for finding in snapshot.findings:
        print(
            "Finding:",
            f"severity={finding.severity.value}",
            f"code={finding.code.value}",
            f"message={finding.message}",
        )
    for item in snapshot.activity_summary:
        print("Activity:", f"action={item.action}", f"count={item.count}")


def _run_operator_command_center() -> int:
    settings = get_settings()
    with SessionLocal() as db:
        summary = OperatorCommandCenterService().summarize(db, settings)
    _print_command_center(summary)
    return 0


def _print_command_center(summary: CommandCenterSummary) -> None:
    safety = summary.safety
    readiness = summary.readiness
    review = summary.outstanding_review
    packets = summary.approval_packets
    pipeline = summary.pipeline
    findings = summary.finding_counts
    print(
        "Command center:",
        f"overall={summary.overall_severity.value}",
        f"read_only={summary.read_only}",
        f"ready_for_manual_rollout={readiness.ready_for_manual_rollout}",
        f"executed={summary.executed_count}",
        f"outbound_attempted={summary.outbound_attempted}",
    )
    print(
        "Safety:",
        f"outbound_enabled={safety.outbound_enabled}",
        f"operator_halt={safety.operator_halt_status}",
        f"live_providers_enabled={safety.live_providers_enabled}",
        f"live_calendar_events={safety.live_calendar_events}",
        f"live_meet_links={safety.live_meet_links}",
        f"live_phone_calls={safety.live_phone_calls}",
        f"phi_fields_present={safety.phi_fields_present}",
    )
    print(
        "Readiness:",
        f"status={readiness.status}",
        f"environment={readiness.environment}",
        f"database={readiness.database}",
        f"config_ok={readiness.config_ok}",
    )
    print(
        "Pipeline:",
        f"organizations={pipeline.organizations}",
        f"leads={pipeline.leads}",
        f"drafts={pipeline.personalization_drafts}",
        f"outreach_planned={pipeline.outreach_plans_planned}",
        f"replies={pipeline.reply_classifications}",
        f"bookings={pipeline.booking_plans}",
        f"voice={pipeline.voice_qualification_plans}",
        f"optimizer={pipeline.optimizer_recommendations}",
        f"channel_plans={pipeline.channel_plans}",
        f"content_briefs={pipeline.content_briefs}",
        f"execution_plans={pipeline.execution_plans}",
        f"approval_packets={pipeline.approval_packets}",
    )
    print(
        "Outstanding review:",
        f"pending={review.pending_count}",
        f"decided={review.decided_count}",
        f"approved={review.approved_count}",
        f"rejected={review.rejected_count}",
        f"needs_changes={review.needs_changes_count}",
        f"executed={review.executed_count}",
    )
    print(
        "Approval packets:",
        f"packets={packets.packets}",
        f"status={packets.latest_run_status}",
        f"owner_approved={packets.owner_approved}",
        f"executed={packets.executed}",
        f"preflight={packets.by_preflight_status}",
    )
    print(
        "Findings:",
        f"blocked={findings.blocked}",
        f"warning={findings.warning}",
        f"info={findings.info}",
        f"total={findings.total}",
    )
    for run in summary.latest_runs:
        print(
            "Latest run:",
            f"phase={run.phase}",
            f"job={run.job_name or '-'}",
            f"status={run.status}",
            f"run_id={run.run_id or '-'}",
        )
    for failure in summary.recent_failures:
        print(
            "Failure:",
            f"phase={failure.phase}",
            f"status={failure.status}",
            f"error={failure.error_message or '-'}",
        )
    for finding in summary.findings:
        print(
            "Finding:",
            f"severity={finding.severity.value}",
            f"code={finding.code.value}",
            f"message={finding.message}",
        )
    for action in summary.next_actions:
        print(
            "Next action:",
            f"severity={action.severity}",
            f"code={action.code}",
            f"label={action.label}",
        )


def _run_recommend_growth() -> int:
    settings = get_settings()
    with SessionLocal() as db:
        result = GrowthOptimizerService().recommend(db, settings)
    _print_optimizer_result(result)
    return 0


def _print_optimizer_result(result: OptimizerRunResult) -> None:
    print(
        "Optimizer run:",
        f"id={result.optimizer_run_id}",
        f"recommendations={result.recommendation_count}",
        f"reused={result.reused_existing}",
        f"applied={result.applied_count}",
        "approval=pending_operator_review",
        f"outbound_attempted={result.outbound_attempted}",
        f"status={result.status.value}",
    )
    for item in result.recommendations:
        print(
            "Recommendation:",
            f"key={item.recommendation_key}",
            f"category={item.category}",
            f"priority={item.priority}",
            f"confidence={item.confidence}",
            f"approval={item.approval_status}",
            f"applied={item.applied}",
        )


def _run_plan_acquisition_channels(args: argparse.Namespace) -> int:
    seeds = ChannelPlanSeeds(
        specialty=args.seed_specialty,
        geography=args.seed_state,
        keywords=tuple(args.seed_keywords or ()),
        partner_type=args.seed_partner_type,
    )
    with SessionLocal() as db:
        result = ChannelPlanningService().plan(db, seeds=seeds)
    _print_channel_plan_result(result)
    return 0


def _run_list_channel_plans() -> int:
    with SessionLocal() as db:
        result = ChannelPlanningService().latest(db)
    if result is None:
        print("Channel plans: status=not_started plans=0")
        return 0
    _print_channel_plan_result(result)
    return 0


def _print_channel_plan_result(result: ChannelPlanRunResult) -> None:
    print(
        "Channel plan run:",
        f"id={result.channel_plan_run_id}",
        f"plans={result.plan_count}",
        f"reused={result.reused_existing}",
        "approval=pending_operator_review",
        f"dry_run_only={result.dry_run_only}",
        f"no_spend={result.no_spend}",
        f"spend_attempted={result.spend_attempted}",
        f"campaign_launched={result.campaign_launched}",
        f"pages_published={result.pages_published}",
        f"outbound_attempted={result.outbound_attempted}",
        f"status={result.status.value}",
    )
    for item in result.plans:
        print(
            "Channel plan:",
            f"key={item.plan_key}",
            f"channel={item.channel}",
            f"type={item.plan_type}",
            f"priority={item.priority}",
            f"confidence={item.confidence}",
            f"approval={item.approval_status}",
            f"launched={item.launched}",
            f"spend_attempted={item.spend_attempted}",
        )


def _run_check_config() -> int:
    settings = get_settings()
    issues = validate_runtime_settings(settings)
    flags = live_provider_flags(settings)
    print(f"environment={settings.environment}")
    print(f"outbound_enabled={settings.outbound_enabled}")
    print(f"live_providers_enabled={any(flags.values())}")
    for name, enabled in flags.items():
        print(f"live_{name}={str(enabled).lower()}")
    if issues:
        for issue in issues:
            print(f"config_issue={issue}", file=sys.stderr)
        print("config_ok=false")
        return 1
    print("config_ok=true")
    return 0


def _run_worker(args: argparse.Namespace) -> int:
    if args.list:
        for job in DEPLOYABLE_JOBS:
            print(f"{job.name}\t{job.cli}\t{job.description}")
        print("undeployed_outbound=" + ",".join(UNDEPLOYED_OUTBOUND_JOBS))
        if not args.check:
            return 0
    settings = get_settings()
    try:
        require_valid_runtime_settings(settings)
    except RuntimeConfigError as exc:
        print(f"config_invalid={exc}", file=sys.stderr)
        return 1
    print("config_ok=true")
    print(f"environment={settings.environment}")
    print(f"outbound_enabled={settings.outbound_enabled}")
    print("queue=inline")
    print(f"jobs={len(DEPLOYABLE_JOBS)}")
    print("scheduler=operator_or_external_cron")
    return 0


def _run_review_queue(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        try:
            result = ReviewQueueService().list_queue(
                db,
                settings,
                include_decided=args.include_decided,
                artifact_type=args.artifact_type,
            )
        except ReviewQueueError as exc:
            print(f"Review queue error: {exc.message}")
            return 1
    _print_review_queue(result)
    return 0


def _print_review_queue(result: ReviewQueueResult) -> None:
    print(
        "Review queue:",
        f"pending={result.pending_count}",
        f"decided={result.decided_count}",
        f"shown={len(result.items)}",
        f"executed={result.executed_count}",
        f"outbound_attempted={result.outbound_attempted}",
        f"recommendation_applied={result.recommendation_applied}",
        f"operator_halt={result.operator_halt_status}",
    )
    for item in result.items:
        print(
            "Review item:",
            f"type={item.artifact_type}",
            f"id={item.artifact_id}",
            f"status={item.status}",
            f"executable_later={item.executable_later}",
            f"executed={item.executed}",
            f"title={item.title}",
        )


def _run_record_review(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        try:
            result = ReviewQueueService().record_decision(
                db,
                artifact_type=args.artifact_type,
                artifact_id=UUID(args.artifact_id),
                decision=args.decision,
                reviewer=args.reviewer,
                source="cli",
                reviewer_notes=args.notes,
            )
        except ReviewQueueError as exc:
            print(f"Review decision error: {exc.message}")
            return 1
        except ValueError:
            print("Review decision error: artifact id must be a UUID")
            return 1
    _print_review_decision(result)
    return 0


def _print_review_decision(result: ReviewDecisionResult) -> None:
    print(
        "Review decision:",
        f"id={result.decision_id}",
        f"type={result.artifact_type}",
        f"artifact_id={result.artifact_id}",
        f"decision={result.decision}",
        f"reviewer={result.reviewer}",
        f"source={result.source}",
        f"executed={result.executed}",
        f"outbound_attempted={result.outbound_attempted}",
        f"recommendation_applied={result.recommendation_applied}",
    )


def _run_draft_content_briefs(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    seed = _content_brief_seed(parser, args)
    settings = get_settings()
    with SessionLocal() as db:
        try:
            result = ContentBriefService().generate(
                db,
                settings,
                seeds=(seed,) if seed is not None else (),
            )
        except ContentBriefError as exc:
            print(f"Content brief error: {exc.message}")
            return 1
    _print_content_brief_result(result)
    return 0


def _content_brief_seed(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> ContentBriefSeed | None:
    brief_type = None
    if args.brief_type:
        try:
            brief_type = ContentBriefType(args.brief_type)
        except ValueError:
            parser.error("Unknown --brief-type")
    channel_plan_id = None
    if args.channel_plan_id:
        try:
            channel_plan_id = UUID(args.channel_plan_id)
        except ValueError:
            parser.error("--channel-plan-id must be a UUID")
    if (
        brief_type is None
        and not args.specialty
        and not args.geography
        and not args.topic
        and not args.icp_label
        and channel_plan_id is None
    ):
        return None
    return ContentBriefSeed(
        brief_type=brief_type,
        specialty=args.specialty,
        geography=args.geography,
        icp_label=args.icp_label,
        topic=args.topic,
        channel_plan_id=channel_plan_id,
    )


def _run_list_content_briefs() -> int:
    with SessionLocal() as db:
        result = ContentBriefService().latest(db)
    if result is None:
        print("Content briefs: status=not_started briefs=0 published=False")
        return 0
    _print_content_brief_result(result)
    return 0


def _print_content_brief_result(result: ContentBriefRunResult) -> None:
    print(
        "Content brief run:",
        f"id={result.content_brief_run_id}",
        f"briefs={result.brief_count}",
        f"reused={result.reused_existing}",
        f"published={result.published}",
        "approval=pending_operator_review",
        f"outbound_attempted={result.outbound_attempted}",
        f"ads_launched={result.ads_launched}",
        f"spend_attempted={result.spend_attempted}",
        f"status={result.status.value}",
    )
    for item in result.briefs:
        print(
            "Content brief:",
            f"key={item.brief_key}",
            f"type={item.brief_type}",
            f"priority={item.priority}",
            f"confidence={item.confidence}",
            f"approval={item.approval_status}",
            f"published={item.published}",
        )


def _run_plan_approved_execution(args: argparse.Namespace) -> int:
    settings = get_settings()
    artifact_id = None
    if args.artifact_id:
        try:
            artifact_id = UUID(args.artifact_id)
        except ValueError:
            print("Execution plan error: artifact id must be a UUID")
            return 1
    filters = ExecutionPlanFilters(
        artifact_type=args.artifact_type,
        artifact_id=artifact_id,
    )
    with SessionLocal() as db:
        try:
            result = ExecutionPlanningService().generate(db, settings, filters=filters)
        except ExecutionPlanningError as exc:
            print(f"Execution plan error: {exc.message}")
            return 1
    _print_execution_plan_result(result)
    return 0


def _run_list_execution_plans() -> int:
    with SessionLocal() as db:
        result = ExecutionPlanningService().latest(db)
    if result is None:
        print("Execution plans: status=not_started plans=0 executed=0")
        return 0
    _print_execution_plan_result(result)
    return 0


def _print_execution_plan_result(result: ExecutionPlanRunResult) -> None:
    print(
        "Execution plan run:",
        f"id={result.execution_plan_run_id}",
        f"plans={result.plan_count}",
        f"reused={result.reused_existing}",
        f"ignored_non_approved={result.ignored_non_approved_count}",
        f"executed={result.executed_count}",
        f"dry_run_only={result.dry_run_only}",
        f"no_execution={result.no_execution}",
        f"outbound_attempted={result.outbound_attempted}",
        f"recommendation_applied={result.recommendation_applied}",
        f"status={result.status.value}",
    )
    for item in result.plans:
        print(
            "Execution plan:",
            f"type={item.plan_type}",
            f"artifact_type={item.source_artifact_type}",
            f"artifact_id={item.source_artifact_id}",
            f"readiness={item.readiness_status}",
            f"executed={item.executed}",
            f"owner_approval_required={item.owner_approval_required}",
            f"action={item.proposed_action}",
        )


def _run_generate_approval_packets(args: argparse.Namespace) -> int:
    settings = get_settings()
    execution_plan_id = None
    if args.execution_plan_id:
        try:
            execution_plan_id = UUID(args.execution_plan_id)
        except ValueError:
            print("Approval packet error: execution plan id must be a UUID")
            return 1
    filters = ApprovalPacketFilters(
        plan_type=args.plan_type,
        execution_plan_id=execution_plan_id,
    )
    with SessionLocal() as db:
        try:
            result = ApprovalPacketService().generate(db, settings, filters=filters)
        except ApprovalPacketError as exc:
            print(f"Approval packet error: {exc.message}")
            return 1
    _print_approval_packet_result(result)
    return 0


def _run_list_approval_packets() -> int:
    with SessionLocal() as db:
        result = ApprovalPacketService().latest(db)
    if result is None:
        print("Approval packets: status=not_started packets=0 executed=0")
        return 0
    _print_approval_packet_result(result)
    return 0


def _print_approval_packet_result(result: ApprovalPacketRunResult) -> None:
    print(
        "Approval packet run:",
        f"id={result.approval_packet_run_id}",
        f"packets={result.packet_count}",
        f"reused={result.reused_existing}",
        f"executed={result.executed_count}",
        f"dry_run_only={result.dry_run_only}",
        f"no_execution={result.no_execution}",
        f"outbound_attempted={result.outbound_attempted}",
        f"recommendation_applied={result.recommendation_applied}",
        f"status={result.status.value}",
    )
    for item in result.packets:
        print(
            "Approval packet:",
            f"family={item.plan_family}",
            f"artifact_type={item.source_artifact_type}",
            f"artifact_id={item.source_artifact_id}",
            f"preflight={item.preflight_status}",
            f"executed={item.executed}",
            f"owner_approval_required={item.owner_approval_required}",
            f"action={item.proposed_action}",
        )


def _run_smoke_dry_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    local_only = bool(args.local_only or args.dev_demo)
    log_buffer = StringIO()
    try:
        with isolated_demo_session() as db:
            with redirect_stdout(log_buffer):
                result = run_smoke_dry_run(
                    db,
                    settings,
                    local_only=local_only,
                    isolated_demo_database=True,
                )
    except SmokeDryRunRefused as exc:
        print(exc.message, file=sys.stderr)
        return 1
    print(format_smoke_summary(result, as_json=args.json))
    return 0


def _run_check_smoke_output(args: argparse.Namespace) -> int:
    try:
        raw = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
        payload = validate_smoke_ci_output(raw)
    except OSError:
        print("CI smoke gate: failed reason=unreadable_input", file=sys.stderr)
        return 1
    except SmokeCiGateError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    print(format_smoke_ci_gate_summary(payload, passed=True))
    return 0


def _run_launch_readiness(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        checklist = LaunchReadinessService().assess(db, settings)
    print(format_launch_readiness(checklist, as_json=args.json))
    if checklist.overall_status == LaunchReadinessStatus.BLOCKED.value:
        return 1
    return 0


def _parse_desired_boolean(value: str | None) -> bool | None:
    if value is None:
        return None
    return value == "true"


def _run_settings_change_requests(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        try:
            result = SettingsChangeRequestService().list_requests(
                db,
                settings,
                status=args.status,
                request_type=args.request_type,
                owner_decision_status=args.decision_status,
            )
        except SettingsChangeRequestError as exc:
            print(f"Settings change request error: {exc.message}")
            return 1
    print(format_settings_change_list(result, as_json=args.json))
    return 0


def _run_create_settings_change_request(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        try:
            result = SettingsChangeRequestService().create(
                db,
                settings,
                request_type=args.request_type,
                requested_setting_names=args.setting_names,
                desired_boolean=_parse_desired_boolean(args.desired_boolean),
                desired_status=args.desired_status,
                finding_code=args.finding_code,
                next_action_code=args.next_action_code,
                idempotency_key=args.idempotency_key,
                source="cli",
                reviewer_notes=args.notes,
            )
        except SettingsChangeRequestError as exc:
            print(f"Settings change request error: {exc.message}")
            return 1
    print(format_settings_change_request(result, as_json=args.json))
    return 0


def _run_settings_change_request_detail(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        request_id = UUID(args.id)
    except ValueError:
        print("Settings change request error: id must be a UUID")
        return 1
    with SessionLocal() as db:
        result = SettingsChangeRequestService().get_request(db, settings, request_id)
    if result is None:
        print("Settings change request error: request was not found")
        return 1
    print(format_settings_change_request(result, as_json=args.json))
    return 0


def _run_record_settings_change_decision(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        request_id = UUID(args.id)
    except ValueError:
        print("Settings change request error: id must be a UUID")
        return 1
    with SessionLocal() as db:
        try:
            result = SettingsChangeRequestService().record_decision(
                db,
                settings,
                request_id=request_id,
                decision=args.decision,
                reviewer=args.reviewer,
                source="cli",
                reviewer_notes=args.notes,
            )
        except SettingsChangeRequestError as exc:
            print(f"Settings change request error: {exc.message}")
            return 1
    print(format_settings_change_request(result, as_json=args.json))
    return 0


def _run_propose_settings_changes(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        checklist = LaunchReadinessService().assess(db, settings)
        try:
            result = SettingsChangeRequestService().propose_from_seeds(
                db,
                settings,
                checklist.proposed_settings_change_requests,
                source="launch_readiness",
            )
        except SettingsChangeRequestError as exc:
            print(f"Settings change request error: {exc.message}")
            return 1
    print(format_settings_change_propose(result, as_json=args.json))
    return 0


def _run_settings_execution_preflight(args: argparse.Namespace) -> int:
    settings = get_settings()
    filters = SettingsExecutionPreflightFilters(
        request_type=args.request_type,
        decision_status=args.decision_status,
        execution_status=args.execution_status,
    )
    with SessionLocal() as db:
        result = SettingsExecutionPreflightService().simulate(db, settings, filters=filters)
    print(format_settings_execution_preflight(result, as_json=args.json))
    return 0


def _run_owner_handoff_packet(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        packet = OwnerHandoffPacketService().build(db, settings)
    print(format_owner_handoff(packet, as_json=args.json))
    return 0


def _run_compliance_evidence_binder(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        binder = ComplianceEvidenceBinderService().build(db, settings)
    print(format_compliance_evidence_binder(binder, as_json=args.json))
    return 0


def _run_release_candidate_runbook(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        runbook = ReleaseCandidateRunbookService().build(db, settings)
    print(format_release_candidate_runbook(runbook, as_json=args.json))
    return 0


def _run_release_artifact_manifest(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        manifest = ReleaseArtifactManifestService().build(db, settings)
    print(format_release_artifact_manifest(manifest, as_json=args.json))
    return 0


def _run_go_live_readiness_index(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        index = GoLiveReadinessIndexService().build(db, settings)
    print(format_go_live_readiness_index(index, as_json=args.json))
    return 0


def _run_launch_blockers_plan(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        plan = LaunchBlockersPlanService().build(db, settings)
    print(format_launch_blockers_plan(plan, as_json=args.json))
    return 0


def _run_staged_rollout_plan(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        plan = StagedRolloutPlanService().build(db, settings)
    print(format_staged_rollout_plan(plan, as_json=args.json))
    return 0


def _run_owner_launch_dossier(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        dossier = OwnerLaunchDossierService().build(db, settings)
    print(format_owner_launch_dossier(dossier, as_json=args.json))
    return 0


def _run_provider_setup_checklist(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        checklist = ProviderSetupChecklistService().build(db, settings)
    print(format_provider_setup_checklist(checklist, as_json=args.json))
    return 0


def _run_go_live_rehearsal_checklist(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        checklist = GoLiveRehearsalChecklistService().build(db, settings)
    print(format_go_live_rehearsal_checklist(checklist, as_json=args.json))
    return 0


def _run_rehearsal_outcome_report(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        report = RehearsalOutcomeReportService().build(db, settings)
    print(format_rehearsal_outcome_report(report, as_json=args.json))
    return 0


def _run_supervised_pilot_plan(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        plan = SupervisedPilotPlanService().build(db, settings)
    print(format_supervised_pilot_plan(plan, as_json=args.json))
    return 0


def _run_supervised_pilot_candidates(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        export = SupervisedPilotCandidateService().build(db, settings)
    print(format_supervised_pilot_candidates(export, as_json=args.json))
    return 0


def _run_supervised_pilot_go_no_go(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        packet = SupervisedPilotGoNoGoService().build(db, settings)
    print(format_supervised_pilot_go_no_go(packet, as_json=args.json))
    return 0


def _run_supervised_pilot_first_send_preflight(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        packet = SupervisedPilotFirstSendPreflightService().build(db, settings)
    print(format_supervised_pilot_first_send_preflight(packet, as_json=args.json))
    return 0


def _run_supervised_pilot_launch_rehearsal_control_map(args: argparse.Namespace) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        packet = SupervisedPilotLaunchRehearsalControlMapService().build(db, settings)
    print(format_supervised_pilot_launch_rehearsal_control_map(packet, as_json=args.json))
    return 0


def _run_action_readiness(args: argparse.Namespace) -> int:
    settings = get_settings()
    filters = ActionReadinessFilters(
        plan_family=args.plan_family,
        readiness_status=args.readiness_status,
        blocker_status=args.blocker_status,
        decision_status=args.decision_status,
    )
    with SessionLocal() as db:
        result = ActionReadinessService().list_queue(db, settings, filters=filters)
    _print_action_readiness(result)
    return 0


def _print_action_readiness(result: ActionReadinessResult) -> None:
    print(
        "Action readiness:",
        f"candidates={result.candidate_count}",
        f"executed={result.executed_count}",
        f"dry_run_only={result.dry_run_only}",
        f"no_execution={result.no_execution}",
        f"live_action={result.live_action}",
        f"read_only={result.read_only}",
        f"explicit_live_owner_action_required={result.explicit_live_owner_action_required}",
        f"outbound_attempted={result.outbound_attempted}",
        f"operator_halt={result.operator_halt_status}",
    )
    for item in result.candidates:
        print(
            "Readiness candidate:",
            f"id={item.candidate_id}",
            f"family={item.plan_family}",
            f"artifact_type={item.artifact_type}",
            f"artifact_id={item.artifact_id}",
            f"review={item.review_decision_status}",
            f"packet={item.packet_decision_status}",
            f"preflight={item.preflight_status}",
            f"readiness={item.readiness_status}",
            f"blockers={item.blocker_status}",
            f"executed={item.executed}",
            f"live_action={item.live_action}",
            f"owner_approved={item.owner_approved}",
            f"label={item.sanitized_label}",
        )


if __name__ == "__main__":
    sys.exit(main())
