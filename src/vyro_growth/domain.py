from enum import StrEnum
from typing import Never


class DiscoveryRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EnrichmentRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WebsiteMatchStatus(StrEnum):
    VERIFIED = "verified"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"


class WebsiteFactType(StrEnum):
    WEBSITE_MATCH = "website_match"
    OFFICIAL_WEBSITE = "official_website"
    SPECIALTY_SERVICES = "specialty_services"
    LOCATION = "location"
    PRACTICE_SIZE_SIGNAL = "practice_size_signal"
    PROVIDER_COUNT = "provider_count"
    OWNERSHIP_SIGNAL = "ownership_signal"
    CONTACT_PAGE_URL = "contact_page_url"
    BUSINESS_PHONE = "business_phone"
    BUSINESS_EMAIL = "business_email"
    BILLING_SIGNAL = "billing_signal"
    STAFF_MEMBER = "staff_member"
    JOB_POSTING_SIGNAL = "job_posting_signal"


class JobIntentCode(StrEnum):
    BILLING_HIRING = "billing_hiring"
    CODING_HIRING = "coding_hiring"
    DENIALS_HIRING = "denials_hiring"
    RCM_HIRING = "rcm_hiring"
    AR_HIRING = "ar_hiring"
    NON_BILLING_HIRING = "non_billing_hiring"


class JobRoleCategory(StrEnum):
    BILLING_SPECIALIST = "billing_specialist"
    BILLING_MANAGER = "billing_manager"
    MEDICAL_CODER = "medical_coder"
    CODING_MANAGER = "coding_manager"
    DENIALS_SPECIALIST = "denials_specialist"
    RCM_MANAGER = "rcm_manager"
    AR_SPECIALIST = "ar_specialist"
    OTHER = "other"


class JobRecencyStatus(StrEnum):
    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class ContactRoleCategory(StrEnum):
    OWNER_PHYSICIAN_OWNER = "owner_physician_owner"
    PRACTICE_ADMINISTRATOR = "practice_administrator"
    PRACTICE_MANAGER = "practice_manager"
    OFFICE_MANAGER = "office_manager"
    EXECUTIVE_DIRECTOR = "executive_director"
    COO = "coo"
    CEO_INDEPENDENT = "ceo_independent"
    REVENUE_CYCLE_MANAGER = "revenue_cycle_manager"
    BILLING_MANAGER = "billing_manager"
    OPERATIONS_MANAGER = "operations_manager"


class ContactVerificationStatus(StrEnum):
    UNKNOWN = "unknown"
    UNVERIFIED = "unverified"
    PROVIDER_VERIFIED = "provider_verified"
    INFERRED = "inferred"
    VERIFIER_VALID = "verifier_valid"
    VERIFIER_INVALID = "verifier_invalid"
    VERIFIER_RISKY = "verifier_risky"


class EmailVerificationVerdict(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    CATCH_ALL = "catch_all"
    UNKNOWN = "unknown"
    RISKY = "risky"
    DISPOSABLE = "disposable"
    ROLE = "role"
    UNVERIFIED = "unverified"


class EmailCandidateOrigin(StrEnum):
    STORED = "stored"
    INFERRED = "inferred"


class EmailVerificationOutcome(StrEnum):
    VERIFIED = "verified"
    NO_VERIFIED_EMAIL = "no_verified_email"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class EmailPatternName(StrEnum):
    FIRST_DOT_LAST = "first.last"
    FIRST_UNDERSCORE_LAST = "first_last"
    FIRST_LAST = "firstlast"
    F_DOT_LAST = "f.last"
    F_LAST = "flast"
    FIRST_L = "firstl"
    FIRST = "first"
    LAST = "last"
    LAST_DOT_FIRST = "last.first"


class ContactFactType(StrEnum):
    DECISION_MAKER_CONTACT = "decision_maker_contact"
    EMAIL_VERIFICATION = "email_verification"
    EMAIL_PATTERN_INFERENCE = "email_pattern_inference"
    PHONE_VERIFICATION = "phone_verification"


class ContactDiscoveryCallStatus(StrEnum):
    QUEUED = "queued"
    COMPLETED = "completed"
    NO_ANSWER = "no_answer"
    REFUSED = "refused"
    WRONG_NUMBER = "wrong_number"
    DECISION_MAKER_IDENTIFIED = "decision_maker_identified"
    DO_NOT_CONTACT = "do_not_contact"


CONTACT_DISCOVERY_CALL_TERMINAL_STATUSES: frozenset[ContactDiscoveryCallStatus] = frozenset(
    {
        ContactDiscoveryCallStatus.COMPLETED,
        ContactDiscoveryCallStatus.NO_ANSWER,
        ContactDiscoveryCallStatus.REFUSED,
        ContactDiscoveryCallStatus.WRONG_NUMBER,
        ContactDiscoveryCallStatus.DECISION_MAKER_IDENTIFIED,
        ContactDiscoveryCallStatus.DO_NOT_CONTACT,
    }
)


class PersonalizationReadiness(StrEnum):
    READY = "ready"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    BLOCKED = "blocked"


class PersonalizationFactType(StrEnum):
    PERSONALIZATION_DRAFT = "personalization_draft"


class PersonalizationReferenceKind(StrEnum):
    SOURCE_EVIDENCE = "source_evidence"
    SCORING_FACTOR = "scoring_factor"
    ORGANIZATION_FIELD = "organization_field"


class OutreachPlanRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EnrollmentStatus(StrEnum):
    PLANNED = "planned"
    SKIPPED = "skipped"
    SUPPRESSED = "suppressed"
    BLOCKED = "blocked"


class EnrollmentSkipReason(StrEnum):
    INELIGIBLE_STAGE = "ineligible_stage"
    MISSING_LEAD_SCORE = "missing_lead_score"
    INELIGIBLE_SCORE = "ineligible_score"
    MISSING_CONTACT_EMAIL = "missing_contact_email"
    NO_VERIFIED_EMAIL = "no_verified_email"
    INFERRED_EMAIL_UNVERIFIED = "inferred_email_unverified"
    MISSING_PERSONALIZATION = "missing_personalization"
    PERSONALIZATION_NOT_READY = "personalization_not_ready"
    SUPPRESSED = "suppressed"
    SUPPRESSION_CHECK_UNAVAILABLE = "suppression_check_unavailable"
    MALFORMED_PROVIDER_OUTPUT = "malformed_provider_output"
    PROVIDER_RETRYABLE_ERROR = "provider_retryable_error"
    PROVIDER_NON_RETRYABLE_ERROR = "provider_non_retryable_error"
    PROVIDER_NOT_ACCEPTED = "provider_not_accepted"
    LIVE_SEND_REJECTED = "live_send_rejected"
    SMARTLEAD_LIVE_DISABLED = "smartlead_live_disabled"
    GLOBAL_OUTBOUND_DISABLED = "global_outbound_disabled"
    OPERATOR_GLOBAL_HALT = "operator_global_halt"
    OPERATOR_HALT_UNAVAILABLE = "operator_halt_unavailable"
    TARGET_UNIDENTIFIED = "target_unidentified"
    LIVE_SMARTLEAD_NOT_IMPLEMENTED = "live_smartlead_not_implemented"


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class ReplyIntent(StrEnum):
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    UNSUBSCRIBE = "unsubscribe"
    WRONG_PERSON = "wrong_person"
    OUT_OF_OFFICE = "out_of_office"
    REFERRAL = "referral"
    NEEDS_MORE_INFO = "needs_more_info"
    MEETING_REQUEST = "meeting_request"
    HOSTILE = "hostile"
    SPAM = "spam"
    UNKNOWN = "unknown"


class ReplyClassificationOutcome(StrEnum):
    CLASSIFIED = "classified"
    SKIPPED = "skipped"
    SUPPRESSED = "suppressed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"
    FAILED = "failed"


class ConversationStatus(StrEnum):
    OPEN = "open"
    REPLIED = "replied"
    INTERESTED = "interested"
    NEEDS_INFO = "needs_info"
    REFERRAL = "referral"
    OUT_OF_OFFICE = "out_of_office"
    MEETING_REQUESTED = "meeting_requested"
    CLOSED = "closed"
    SUPPRESSED = "suppressed"
    HOSTILE = "hostile"
    SPAM = "spam"


class LeadStage(StrEnum):
    DISCOVERED = "discovered"
    ENRICHING = "enriching"
    QUALIFIED = "qualified"
    READY_FOR_OUTREACH = "ready_for_outreach"
    CONTACTED = "contacted"
    REPLIED = "replied"
    INTERESTED = "interested"
    QUALIFICATION_PENDING = "qualification_pending"
    MEETING_READY = "meeting_ready"
    MEETING_BOOKED = "meeting_booked"
    WON = "won"
    LOST = "lost"
    SUPPRESSED = "suppressed"


ALLOWED_TRANSITIONS: dict[LeadStage, set[LeadStage]] = {
    LeadStage.DISCOVERED: {LeadStage.ENRICHING, LeadStage.SUPPRESSED},
    LeadStage.ENRICHING: {LeadStage.QUALIFIED, LeadStage.LOST, LeadStage.SUPPRESSED},
    LeadStage.QUALIFIED: {LeadStage.READY_FOR_OUTREACH, LeadStage.LOST, LeadStage.SUPPRESSED},
    LeadStage.READY_FOR_OUTREACH: {LeadStage.CONTACTED, LeadStage.SUPPRESSED},
    LeadStage.CONTACTED: {LeadStage.REPLIED, LeadStage.LOST, LeadStage.SUPPRESSED},
    LeadStage.REPLIED: {
        LeadStage.INTERESTED,
        LeadStage.LOST,
        LeadStage.SUPPRESSED,
    },
    LeadStage.INTERESTED: {
        LeadStage.QUALIFICATION_PENDING,
        LeadStage.MEETING_READY,
        LeadStage.LOST,
        LeadStage.SUPPRESSED,
    },
    LeadStage.QUALIFICATION_PENDING: {
        LeadStage.MEETING_READY,
        LeadStage.LOST,
        LeadStage.SUPPRESSED,
    },
    LeadStage.MEETING_READY: {LeadStage.MEETING_BOOKED, LeadStage.LOST, LeadStage.SUPPRESSED},
    LeadStage.MEETING_BOOKED: {LeadStage.WON, LeadStage.LOST},
    LeadStage.WON: set(),
    LeadStage.LOST: set(),
    LeadStage.SUPPRESSED: set(),
}


def can_transition(current: LeadStage, target: LeadStage) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


FORBIDDEN_REPLY_STAGES: frozenset[LeadStage] = frozenset(
    {
        LeadStage.CONTACTED,
        LeadStage.MEETING_READY,
        LeadStage.MEETING_BOOKED,
        LeadStage.WON,
    }
)


def _unreachable_intent(value: ReplyIntent) -> Never:
    raise RuntimeError(f"unhandled reply intent: {value!r}")


def desired_reply_stages(intent: ReplyIntent) -> tuple[LeadStage, ...]:
    """Conservative CRM targets for a classified inbound reply.

    Meeting requests stay at interested. This phase never books a meeting or
    claims outreach was sent.
    """

    match intent:
        case ReplyIntent.UNSUBSCRIBE:
            return (LeadStage.SUPPRESSED,)
        case ReplyIntent.NOT_INTERESTED | ReplyIntent.WRONG_PERSON | ReplyIntent.HOSTILE:
            return (LeadStage.LOST,)
        case ReplyIntent.INTERESTED | ReplyIntent.MEETING_REQUEST:
            return (LeadStage.REPLIED, LeadStage.INTERESTED)
        case ReplyIntent.NEEDS_MORE_INFO | ReplyIntent.REFERRAL | ReplyIntent.UNKNOWN:
            return (LeadStage.REPLIED,)
        case ReplyIntent.OUT_OF_OFFICE | ReplyIntent.SPAM:
            return ()
        case _:
            return _unreachable_intent(intent)


class BookingPlanRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BookingPlanStatus(StrEnum):
    PLANNED = "planned"
    SKIPPED = "skipped"
    SUPPRESSED = "suppressed"
    BLOCKED = "blocked"


class BookingRequestSource(StrEnum):
    MEETING_REQUEST_REPLY = "meeting_request_reply"
    OPERATOR_REQUEST = "operator_request"


class BookingSkipReason(StrEnum):
    INELIGIBLE_CONSENT = "ineligible_consent"
    MISSING_MEETING_REQUEST = "missing_meeting_request"
    MISSING_CONTACT = "missing_contact"
    SUPPRESSED = "suppressed"
    SUPPRESSION_CHECK_UNAVAILABLE = "suppression_check_unavailable"
    MALFORMED_PROVIDER_OUTPUT = "malformed_provider_output"
    PROVIDER_RETRYABLE_ERROR = "provider_retryable_error"
    PROVIDER_NON_RETRYABLE_ERROR = "provider_non_retryable_error"
    PROVIDER_NOT_ACCEPTED = "provider_not_accepted"
    LIVE_BOOKING_REJECTED = "live_booking_rejected"
    EVENT_CREATION_REJECTED = "event_creation_rejected"
    MEET_LINK_REJECTED = "meet_link_rejected"
    GOOGLE_CALENDAR_LIVE_DISABLED = "google_calendar_live_disabled"
    GLOBAL_OUTBOUND_DISABLED = "global_outbound_disabled"
    OPERATOR_GLOBAL_HALT = "operator_global_halt"
    OPERATOR_HALT_UNAVAILABLE = "operator_halt_unavailable"
    TARGET_UNIDENTIFIED = "target_unidentified"
    LIVE_GOOGLE_NOT_IMPLEMENTED = "live_google_not_implemented"


class VoiceQualificationRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class VoicePlanStatus(StrEnum):
    PLANNED = "planned"
    SKIPPED = "skipped"
    SUPPRESSED = "suppressed"
    BLOCKED = "blocked"


class VoiceConsentSource(StrEnum):
    INBOUND_REPLY = "inbound_reply"
    OPERATOR_REQUEST = "operator_request"
    MEETING_PERMISSION = "meeting_permission"


class VoiceConsentChannel(StrEnum):
    EMAIL = "email"
    INBOUND_CALL = "inbound_call"
    OPERATOR = "operator"
    BOOKING = "booking"


class VoiceSkipReason(StrEnum):
    MISSING_CONSENT_PROOF = "missing_consent_proof"
    INVALID_CONSENT_PROOF = "invalid_consent_proof"
    INELIGIBLE_CONSENT_CONTEXT = "ineligible_consent_context"
    MISSING_BUSINESS_PHONE = "missing_business_phone"
    SUSPECTED_PHI = "suspected_phi"
    SUPPRESSED = "suppressed"
    SUPPRESSION_CHECK_UNAVAILABLE = "suppression_check_unavailable"
    MALFORMED_PROVIDER_OUTPUT = "malformed_provider_output"
    PROVIDER_RETRYABLE_ERROR = "provider_retryable_error"
    PROVIDER_NON_RETRYABLE_ERROR = "provider_non_retryable_error"
    PROVIDER_NOT_ACCEPTED = "provider_not_accepted"
    LIVE_CALL_REJECTED = "live_call_rejected"
    VOICE_LIVE_DISABLED = "voice_live_disabled"
    GLOBAL_OUTBOUND_DISABLED = "global_outbound_disabled"
    OPERATOR_GLOBAL_HALT = "operator_global_halt"
    OPERATOR_HALT_UNAVAILABLE = "operator_halt_unavailable"
    TARGET_UNIDENTIFIED = "target_unidentified"
    LIVE_VOICE_NOT_IMPLEMENTED = "live_voice_not_implemented"
    COLD_CALL_FORBIDDEN = "cold_call_forbidden"


class OptimizerRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RecommendationCategory(StrEnum):
    ICP_SCORING_THRESHOLD = "icp_scoring_threshold"
    SPECIALTY_GEOGRAPHY_SIGNAL = "specialty_geography_signal"
    WEBSITE_ENRICHMENT_GAP = "website_enrichment_gap"
    DECISION_MAKER_COVERAGE_GAP = "decision_maker_coverage_gap"
    PERSONALIZATION_READINESS_GAP = "personalization_readiness_gap"
    OUTREACH_PLAN_PATTERN = "outreach_plan_pattern"
    REPLY_INTENT_TREND = "reply_intent_trend"
    BOOKING_PLAN_BOTTLENECK = "booking_plan_bottleneck"
    VOICE_PLAN_BOTTLENECK = "voice_plan_bottleneck"
    SAFETY_RISK = "safety_risk"


class RecommendationPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecommendationApprovalStatus(StrEnum):
    PENDING_OPERATOR_REVIEW = "pending_operator_review"


class ChannelPlanRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AcquisitionChannel(StrEnum):
    GOOGLE_SEARCH_ADS = "google_search_ads"
    SEO_CONTENT = "seo_content"
    REFERRAL_PARTNER = "referral_partner"
    SPECIALTY_GEOGRAPHY = "specialty_geography"


class ChannelPlanType(StrEnum):
    KEYWORD_GROUP = "keyword_group"
    LANDING_PAGE_TOPIC = "landing_page_topic"
    PARTNER_CAMPAIGN = "partner_campaign"
    POSITIONING = "positioning"


class FindingSeverity(StrEnum):
    BLOCKED = "blocked"
    WARNING = "warning"
    INFO = "info"


class FindingCode(StrEnum):
    OUTBOUND_ENABLED = "outbound_enabled"
    LIVE_PROVIDER_ENABLED = "live_provider_enabled"
    LIVE_OUTBOUND_ARTIFACT = "live_outbound_artifact"
    CONFIG_NOT_READY = "config_not_ready"
    DATABASE_UNAVAILABLE = "database_unavailable"
    OPERATOR_HALT_UNAVAILABLE = "operator_halt_unavailable"
    RECENT_FAILURES = "recent_failures"
    PENDING_OPERATOR_REVIEW = "pending_operator_review"
    OPERATOR_HALT_ACTIVE = "operator_halt_active"
    SAFE_DEFAULTS = "safe_defaults"
    EXECUTION_PLANS_DRY_RUN = "execution_plans_dry_run"
    APPROVAL_PACKETS_DRY_RUN = "approval_packets_dry_run"
    SMOKE_GATE_MISSING = "smoke_gate_missing"
    MISSING_REQUIRED_CREDENTIAL = "missing_required_credential"
    PENDING_OWNER_APPROVAL_PACKETS = "pending_owner_approval_packets"
    ACTION_READINESS_BLOCKED = "action_readiness_blocked"
    PENDING_SETTINGS_CHANGE_REQUESTS = "pending_settings_change_requests"


class NextActionCode(StrEnum):
    DISABLE_OUTBOUND = "disable_outbound"
    DISABLE_LIVE_PROVIDERS = "disable_live_providers"
    INVESTIGATE_LIVE_ARTIFACTS = "investigate_live_artifacts"
    RECORD_OPERATOR_HALT = "record_operator_halt"
    REVIEW_FAILED_RUNS = "review_failed_runs"
    CHECK_RUNTIME_CONFIG = "check_runtime_config"
    REVIEW_PENDING_ARTIFACTS = "review_pending_artifacts"
    PLAN_APPROVED_EXECUTION = "plan_approved_execution"
    GENERATE_APPROVAL_PACKETS = "generate_approval_packets"
    OWNER_REVIEW_APPROVAL_PACKETS = "owner_review_approval_packets"
    INSPECT_ACTION_READINESS = "inspect_action_readiness"
    RUN_DISCOVERY_WHEN_READY = "run_discovery_when_ready"
    KEEP_OUTBOUND_DISABLED = "keep_outbound_disabled"
    KEEP_LIVE_PROVIDERS_DISABLED = "keep_live_providers_disabled"
    KEEP_OPERATOR_HALT = "keep_operator_halt_until_owner_approves"
    RESTORE_CI_SMOKE_GATE = "restore_ci_smoke_gate"
    CONFIGURE_REQUIRED_CREDENTIALS = "configure_required_credentials"
    REVIEW_SETTINGS_CHANGE_REQUESTS = "review_settings_change_requests"
    INSPECT_SETTINGS_EXECUTION_PREFLIGHT = "inspect_settings_execution_preflight"
    INSPECT_OPERATOR_AUDIT_TIMELINE = "inspect_operator_audit_timeline"
    HANDOFF_IS_NOT_GO_LIVE = "handoff_is_not_permission_to_go_live"
    BINDER_IS_NOT_GO_LIVE = "binder_is_not_permission_to_go_live"
    RUNBOOK_IS_NOT_DEPLOYMENT = "runbook_is_not_a_deployment_mechanism"
    MANIFEST_IS_NOT_BUILD_OR_DEPLOY = "manifest_is_not_a_build_or_deploy"
    GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION = (
        "go_live_readiness_index_is_not_permission_to_go_live"
    )
    LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION = "launch_blockers_plan_is_not_permission_to_go_live"
    STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE = "staged_rollout_plan_is_not_permission_to_go_live"
    OWNER_LAUNCH_DOSSIER_IS_NOT_GO_LIVE = "owner_launch_dossier_is_not_permission_to_go_live"
    PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE = (
        "provider_setup_checklist_is_not_permission_to_go_live"
    )
    GO_LIVE_REHEARSAL_CHECKLIST_IS_NOT_GO_LIVE = (
        "go_live_rehearsal_checklist_is_not_permission_to_go_live"
    )
    REHEARSAL_OUTCOME_REPORT_IS_NOT_GO_LIVE = (
        "rehearsal_outcome_report_is_not_permission_to_go_live"
    )
    SUPERVISED_PILOT_PLAN_IS_NOT_GO_LIVE = "supervised_pilot_plan_is_not_permission_to_go_live"
    SUPERVISED_PILOT_CANDIDATES_IS_NOT_GO_LIVE = (
        "supervised_pilot_candidates_is_not_permission_to_go_live"
    )
    SUPERVISED_PILOT_GO_NO_GO_IS_NOT_GO_LIVE = (
        "supervised_pilot_go_no_go_is_not_permission_to_go_live"
    )
    SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_IS_NOT_GO_LIVE = (
        "supervised_pilot_first_send_preflight_is_not_permission_to_go_live"
    )
    SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_IS_NOT_GO_LIVE = (
        "supervised_pilot_launch_rehearsal_control_map_is_not_permission_to_go_live"
    )
    LIVE_PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE = (
        "live_provider_setup_checklist_is_not_permission_to_go_live"
    )


class ReviewArtifactType(StrEnum):
    PERSONALIZATION_DRAFT = "personalization_draft"
    OUTREACH_ENROLLMENT_PLAN = "outreach_enrollment_plan"
    REPLY_FOLLOW_UP_PLAN = "reply_follow_up_plan"
    BOOKING_PLAN = "booking_plan"
    VOICE_QUALIFICATION_PLAN = "voice_qualification_plan"
    OPTIMIZER_RECOMMENDATION = "optimizer_recommendation"
    ACQUISITION_CHANNEL_PLAN = "acquisition_channel_plan"
    CONTENT_BRIEF = "content_brief"
    CONTACT_DISCOVERY_CALL = "contact_discovery_call"


class ContentBriefRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ContentBriefType(StrEnum):
    SPECIALTY_LANDING_PAGE = "specialty_landing_page"
    GEOGRAPHY_LANDING_PAGE = "geography_landing_page"
    GOOGLE_ADS_LANDING_PAGE = "google_ads_landing_page"
    SEO_ARTICLE = "seo_article"
    REFERRAL_PARTNER_PAGE = "referral_partner_page"


class ContentBriefPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContentBriefApprovalStatus(StrEnum):
    PENDING_OPERATOR_REVIEW = "pending_operator_review"


class ReviewDecisionStatus(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


class ReviewItemStatus(StrEnum):
    PENDING_OPERATOR_REVIEW = "pending_operator_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


class ExecutionPlanRunStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionPlanType(StrEnum):
    PERSONALIZATION_DRAFT = "personalization_draft"
    OUTREACH_ENROLLMENT = "outreach_enrollment"
    REPLY_FOLLOW_UP = "reply_follow_up"
    BOOKING = "booking"
    VOICE_QUALIFICATION = "voice_qualification"
    OPTIMIZER_APPLY = "optimizer_apply"
    ACQUISITION_CHANNEL_LAUNCH = "acquisition_channel_launch"
    CONTENT_PUBLISH = "content_publish"


class ExecutionReadinessStatus(StrEnum):
    BLOCKED = "blocked"
    AWAITING_OWNER_APPROVAL = "awaiting_owner_approval"


class ApprovalPacketRunStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class PreflightStatus(StrEnum):
    BLOCKED = "blocked"
    AWAITING_OWNER_DECISION = "awaiting_owner_decision"


class ActionReadinessStatus(StrEnum):
    BLOCKED = "blocked"
    MISSING_REVIEW_DECISION = "missing_review_decision"
    MISSING_OWNER_PACKET_DECISION = "missing_owner_packet_decision"
    PREFLIGHT_BLOCKED = "preflight_blocked"
    APPROVED_BUT_HALTED = "approved_but_halted"
    READY_PENDING_EXPLICIT_LIVE_OWNER_ACTION = "ready_pending_explicit_live_owner_action"


class ActionReadinessBlockerStatus(StrEnum):
    BLOCKED = "blocked"
    PHASE_SAFETY_ONLY = "phase_safety_only"


class ActionDecisionStatus(StrEnum):
    MISSING = "missing"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


class LaunchReadinessStatus(StrEnum):
    BLOCKED = "blocked"
    WARNING = "warning"
    READY_FOR_OWNER_REVIEW = "ready_for_owner_review"


class SecretPresenceStatus(StrEnum):
    REDACTED = "redacted"
    MISSING = "missing"


class SecretName(StrEnum):
    DATABASE_URL = "DATABASE_URL"
    INTERNAL_API_KEY = "INTERNAL_API_KEY"
    OPENAI_API_KEY = "OPENAI_API_KEY"
    SMARTLEAD_API_KEY = "SMARTLEAD_API_KEY"
    GOOGLE_CALENDAR_API_KEY = "GOOGLE_CALENDAR_API_KEY"
    VOICE_API_KEY = "VOICE_API_KEY"
    DECISION_MAKER_API_KEY = "DECISION_MAKER_API_KEY"
    EMAIL_VERIFICATION_API_KEY = "EMAIL_VERIFICATION_API_KEY"


class SettingsChangeRequestType(StrEnum):
    KEEP_OUTBOUND_DISABLED = "keep_outbound_disabled"
    REQUEST_OUTBOUND_ENABLEMENT_REVIEW = "request_outbound_enablement_review"
    REQUEST_PROVIDER_LIVE_FLAG_REVIEW = "request_provider_live_flag_review"
    REQUEST_OPERATOR_HALT_REVIEW = "request_operator_halt_review"
    REQUEST_CREDENTIAL_CONFIGURATION_REVIEW = "request_credential_configuration_review"
    KEEP_SAFE_DEFAULT = "keep_safe_default"


class SettingsChangeRequestStatus(StrEnum):
    PENDING = "pending"
    DECISION_RECORDED = "decision_recorded"


class SettingsChangeDecisionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


class SettingsChangeDesiredStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    HALTED = "halted"
    CLEARED = "cleared"
    CONFIGURED = "configured"


class SettingsExecutionPreflightStatus(StrEnum):
    BLOCKED = "blocked"
    PENDING_DECISION = "pending_decision"
    DECISION_NOT_APPROVED = "decision_not_approved"
    MISSING_OWNER_PACKET_DECISION = "missing_owner_packet_decision"
    MISSING_EXPLICIT_OWNER_APPROVAL = "missing_explicit_owner_approval"
    EXECUTION_GATES_CLOSED = "execution_gates_closed"
    DRY_RUN_BLOCKED = "dry_run_blocked"


class SettingsExecutionBlockerCode(StrEnum):
    OPERATOR_HALT_ACTIVE = "operator_halt_active"
    OPERATOR_HALT_UNAVAILABLE = "operator_halt_unavailable"
    OUTBOUND_DISABLED = "outbound_disabled"
    PROVIDER_LIVE_FLAG_FALSE = "provider_live_flag_false"
    MISSING_CREDENTIAL = "missing_credential"
    PENDING_DECISION = "pending_decision"
    REJECTED_DECISION = "rejected_decision"
    NEEDS_CHANGES_DECISION = "needs_changes_decision"
    MISSING_OWNER_APPROVAL_PACKET_DECISION = "missing_owner_approval_packet_decision"
    MISSING_EXPLICIT_OWNER_APPROVAL = "missing_explicit_owner_approval"
    EXECUTION_DISABLED_IN_THIS_PHASE = "execution_disabled_in_this_phase"
    FUTURE_EXECUTION_PHASE_ABSENT = "future_execution_phase_absent"


class SettingsExecutionGateCode(StrEnum):
    OPERATOR_HALT_GATE = "operator_halt_gate"
    OUTBOUND_ENABLED_GATE = "outbound_enabled_gate"
    PROVIDER_LIVE_FLAG_GATE = "provider_live_flag_gate"
    CREDENTIAL_GATE = "credential_gate"
    OWNER_DECISION_GATE = "owner_decision_gate"
    APPROVAL_PACKET_DECISION_GATE = "approval_packet_decision_gate"
    EXPLICIT_OWNER_APPROVAL_GATE = "explicit_owner_approval_gate"
    EXECUTION_PHASE_GATE = "execution_phase_gate"


FORBIDDEN_BOOKING_STAGES: frozenset[LeadStage] = frozenset(
    {
        LeadStage.MEETING_BOOKED,
        LeadStage.WON,
        LeadStage.CONTACTED,
    }
)


def desired_booking_stage(current: LeadStage) -> LeadStage | None:
    """Conservative CRM target after a dry-run booking plan.

    Phase 8 may move interested or qualification-pending leads to meeting_ready.
    It never books a meeting.
    """

    if current is LeadStage.MEETING_READY:
        return LeadStage.MEETING_READY
    if current in {LeadStage.INTERESTED, LeadStage.QUALIFICATION_PENDING}:
        return LeadStage.MEETING_READY
    return None


def conversation_status_for(intent: ReplyIntent) -> ConversationStatus:
    match intent:
        case ReplyIntent.UNSUBSCRIBE:
            return ConversationStatus.SUPPRESSED
        case ReplyIntent.NOT_INTERESTED | ReplyIntent.WRONG_PERSON:
            return ConversationStatus.CLOSED
        case ReplyIntent.HOSTILE:
            return ConversationStatus.HOSTILE
        case ReplyIntent.SPAM:
            return ConversationStatus.SPAM
        case ReplyIntent.OUT_OF_OFFICE:
            return ConversationStatus.OUT_OF_OFFICE
        case ReplyIntent.REFERRAL:
            return ConversationStatus.REFERRAL
        case ReplyIntent.NEEDS_MORE_INFO:
            return ConversationStatus.NEEDS_INFO
        case ReplyIntent.INTERESTED:
            return ConversationStatus.INTERESTED
        case ReplyIntent.MEETING_REQUEST:
            return ConversationStatus.MEETING_REQUESTED
        case ReplyIntent.UNKNOWN:
            return ConversationStatus.REPLIED
        case _:
            return _unreachable_intent(intent)
