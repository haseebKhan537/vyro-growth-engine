from enum import StrEnum


class DiscoveryRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


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
