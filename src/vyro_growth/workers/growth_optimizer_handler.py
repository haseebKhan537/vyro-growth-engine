from __future__ import annotations

from sqlalchemy.orm import Session

from vyro_growth.config import Settings, get_settings
from vyro_growth.services.growth_optimizer import GrowthOptimizerService
from vyro_growth.workers.base import Job

GENERATE_GROWTH_RECOMMENDATIONS_JOB = "generate_growth_recommendations"


class GenerateGrowthRecommendationsHandler:
    """Persist dry-run optimizer recommendations. Never auto-applies them."""

    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        service: GrowthOptimizerService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.service = service or GrowthOptimizerService()

    def handle(self, job: Job) -> None:
        del job
        active_settings = self.settings or get_settings()
        self.service.recommend(self.db, active_settings)
