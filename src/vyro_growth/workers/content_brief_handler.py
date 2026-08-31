from __future__ import annotations

from sqlalchemy.orm import Session

from vyro_growth.config import Settings, get_settings
from vyro_growth.services.content_brief import ContentBriefService
from vyro_growth.workers.base import Job

GENERATE_CONTENT_BRIEFS_JOB = "generate_content_briefs"


class GenerateContentBriefsHandler:
    """Persist review-only content briefs. Never publishes or launches ads."""

    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        service: ContentBriefService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.service = service or ContentBriefService()

    def handle(self, job: Job) -> None:
        del job
        active_settings = self.settings or get_settings()
        self.service.generate(self.db, active_settings)
