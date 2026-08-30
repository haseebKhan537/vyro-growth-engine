from __future__ import annotations

from vyro_growth.providers.base import SendResult


class StubEmailProvider:
    """Phase 1 placeholder. Does not perform external sends."""

    def send_email(self, *, to: str, subject: str, body: str) -> SendResult:
        return SendResult(provider_message_id=f"stub-email:{to}", accepted=True)


class StubCalendarProvider:
    """Phase 1 placeholder. Does not create external calendar events."""

    def create_meeting(
        self,
        *,
        attendee_email: str,
        starts_at_iso: str,
        duration_minutes: int,
        title: str,
    ) -> str:
        return f"stub-event:{attendee_email}:{starts_at_iso}:{duration_minutes}:{title}"


class StubEnrichmentProvider:
    """Phase 1 placeholder. Does not call external enrichment APIs."""

    def enrich_organization(self, *, name: str, website: str | None) -> dict[str, object]:
        return {
            "name": name,
            "website": website,
            "provider": "stub",
            "evidence": [],
        }
