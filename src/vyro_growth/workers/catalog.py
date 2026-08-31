from __future__ import annotations

from dataclasses import dataclass

from vyro_growth.workers.approval_packet_handler import GENERATE_APPROVAL_PACKETS_JOB
from vyro_growth.workers.booking_plan_handler import PLAN_BOOKING_SLOTS_JOB
from vyro_growth.workers.channel_planning_handler import GENERATE_CHANNEL_PLANS_JOB
from vyro_growth.workers.contact_enrichment_handler import ENRICH_DECISION_MAKERS_JOB
from vyro_growth.workers.content_brief_handler import GENERATE_CONTENT_BRIEFS_JOB
from vyro_growth.workers.discovery_handler import DISCOVER_NPPES_PRACTICES_JOB
from vyro_growth.workers.execution_planning_handler import GENERATE_EXECUTION_PLANS_JOB
from vyro_growth.workers.growth_optimizer_handler import GENERATE_GROWTH_RECOMMENDATIONS_JOB
from vyro_growth.workers.outbound import (
    PLACE_CONSENT_CALLBACK_JOB,
    SCHEDULE_MEETING_JOB,
    SEND_EMAIL_JOB,
)
from vyro_growth.workers.outreach_enrollment_handler import PLAN_OUTREACH_ENROLLMENTS_JOB
from vyro_growth.workers.personalization_handler import PERSONALIZE_SCORED_LEADS_JOB
from vyro_growth.workers.reply_classification_handler import CLASSIFY_INBOUND_REPLIES_JOB
from vyro_growth.workers.scoring_handler import SCORE_DISCOVERED_LEADS_JOB
from vyro_growth.workers.voice_qualification_handler import PLAN_VOICE_QUALIFICATIONS_JOB
from vyro_growth.workers.website_enrichment_handler import ENRICH_ORGANIZATION_WEBSITES_JOB


@dataclass(frozen=True)
class WorkerJobSpec:
    name: str
    cli: str
    description: str


DEPLOYABLE_JOBS: tuple[WorkerJobSpec, ...] = (
    WorkerJobSpec(
        DISCOVER_NPPES_PRACTICES_JOB,
        "discover-nppes",
        "Bounded NPPES organization discovery",
    ),
    WorkerJobSpec(
        SCORE_DISCOVERED_LEADS_JOB,
        "score-leads",
        "Deterministic ICP scoring from stored evidence",
    ),
    WorkerJobSpec(
        ENRICH_ORGANIZATION_WEBSITES_JOB,
        "enrich-websites",
        "Official website resolution and public-business extraction",
    ),
    WorkerJobSpec(
        ENRICH_DECISION_MAKERS_JOB,
        "enrich-contacts",
        "Stub decision-maker contact enrichment",
    ),
    WorkerJobSpec(
        PERSONALIZE_SCORED_LEADS_JOB,
        "personalize-leads",
        "Evidence-grounded personalization drafts",
    ),
    WorkerJobSpec(
        PLAN_OUTREACH_ENROLLMENTS_JOB,
        "plan-outreach",
        "Dry-run campaign enrollment planning",
    ),
    WorkerJobSpec(
        CLASSIFY_INBOUND_REPLIES_JOB,
        "classify-replies",
        "Dry-run inbound reply classification",
    ),
    WorkerJobSpec(
        PLAN_BOOKING_SLOTS_JOB,
        "plan-booking",
        "Dry-run booking plans without calendar events",
    ),
    WorkerJobSpec(
        PLAN_VOICE_QUALIFICATIONS_JOB,
        "plan-voice-qualification",
        "Dry-run consent-based voice qualification plans",
    ),
    WorkerJobSpec(
        GENERATE_GROWTH_RECOMMENDATIONS_JOB,
        "recommend-growth",
        "Dry-run growth optimizer recommendations",
    ),
    WorkerJobSpec(
        GENERATE_CHANNEL_PLANS_JOB,
        "plan-acquisition-channels",
        "Dry-run acquisition channel plans without spend or launch",
    ),
    WorkerJobSpec(
        GENERATE_CONTENT_BRIEFS_JOB,
        "draft-content-briefs",
        "Review-only landing page and SEO content briefs",
    ),
    WorkerJobSpec(
        GENERATE_EXECUTION_PLANS_JOB,
        "plan-approved-execution",
        "Dry-run execution plans for approved review artifacts",
    ),
    WorkerJobSpec(
        GENERATE_APPROVAL_PACKETS_JOB,
        "generate-approval-packets",
        "Live-readiness preflight and owner approval packets",
    ),
)

UNDEPLOYED_OUTBOUND_JOBS: tuple[str, ...] = (
    SEND_EMAIL_JOB,
    SCHEDULE_MEETING_JOB,
    PLACE_CONSENT_CALLBACK_JOB,
)


def deployable_job_names() -> tuple[str, ...]:
    return tuple(job.name for job in DEPLOYABLE_JOBS)


def undeployed_outbound_job_names() -> tuple[str, ...]:
    return UNDEPLOYED_OUTBOUND_JOBS
