from __future__ import annotations

from sqlalchemy.orm import Session

from vyro_growth.services.channel_planning import ChannelPlanningService, ChannelPlanSeeds
from vyro_growth.workers.base import Job

GENERATE_CHANNEL_PLANS_JOB = "generate_channel_plans"


class GenerateChannelPlansHandler:
    """Persist dry-run acquisition channel plans. Never launches or spends."""

    def __init__(
        self,
        db: Session,
        service: ChannelPlanningService | None = None,
    ) -> None:
        self.db = db
        self.service = service or ChannelPlanningService()

    def handle(self, job: Job) -> None:
        self.service.plan(self.db, seeds=_seeds_from_payload(job.payload))


def _seeds_from_payload(payload: dict[str, object]) -> ChannelPlanSeeds:
    specialty = payload.get("seed_specialty")
    geography = payload.get("seed_state")
    partner_type = payload.get("seed_partner_type")
    raw_keywords = payload.get("seed_keywords")
    keywords: tuple[str, ...] = ()
    if isinstance(raw_keywords, list):
        keywords = tuple(item for item in raw_keywords if isinstance(item, str))
    elif isinstance(raw_keywords, str):
        keywords = (raw_keywords,)
    return ChannelPlanSeeds(
        specialty=specialty if isinstance(specialty, str) else None,
        geography=geography if isinstance(geography, str) else None,
        keywords=keywords,
        partner_type=partner_type if isinstance(partner_type, str) else None,
    )
