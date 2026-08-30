from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SendResult:
    provider_message_id: str
    accepted: bool


class EmailProvider(Protocol):
    def send_email(self, *, to: str, subject: str, body: str) -> SendResult: ...


class CalendarProvider(Protocol):
    def create_meeting(
        self,
        *,
        attendee_email: str,
        starts_at_iso: str,
        duration_minutes: int,
        title: str,
    ) -> str: ...


class EnrichmentProvider(Protocol):
    def enrich_organization(self, *, name: str, website: str | None) -> dict[str, object]: ...


@dataclass(frozen=True)
class CallResult:
    provider_call_id: str
    accepted: bool


class VoiceProvider(Protocol):
    """Consent-based callback interface. Implementations must not cold-dial."""

    def place_consent_callback(self, *, phone: str, consent_to_call: bool) -> CallResult: ...
