from enum import StrEnum


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


class ContactFactType(StrEnum):
    DECISION_MAKER_CONTACT = "decision_maker_contact"


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
