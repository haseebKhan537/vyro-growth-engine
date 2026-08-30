"""External provider interfaces and adapters."""

from vyro_growth.providers.base import (
    CalendarProvider,
    CallResult,
    EmailProvider,
    EnrichmentProvider,
    SendResult,
    VoiceProvider,
)
from vyro_growth.providers.guarded import (
    GuardedCalendarProvider,
    GuardedEmailProvider,
    GuardedVoiceProvider,
)
from vyro_growth.providers.nppes import (
    NARROW_FILTER_ERROR,
    NPPES_MAX_SKIP,
    NormalizedNppesOrganization,
    NppesProvider,
    NppesQueryError,
    NppesSearchPage,
    NppesSearchQuery,
    clean_optional_text,
)
from vyro_growth.providers.nppes_client import HttpNppesProvider, build_nppes_provider
from vyro_growth.providers.stubs import (
    StubCalendarProvider,
    StubEmailProvider,
    StubEnrichmentProvider,
    StubVoiceProvider,
)

__all__ = [
    "CalendarProvider",
    "CallResult",
    "EmailProvider",
    "EnrichmentProvider",
    "GuardedCalendarProvider",
    "GuardedEmailProvider",
    "GuardedVoiceProvider",
    "HttpNppesProvider",
    "NARROW_FILTER_ERROR",
    "NPPES_MAX_SKIP",
    "NormalizedNppesOrganization",
    "NppesProvider",
    "NppesQueryError",
    "NppesSearchPage",
    "NppesSearchQuery",
    "SendResult",
    "StubCalendarProvider",
    "StubEmailProvider",
    "StubEnrichmentProvider",
    "StubVoiceProvider",
    "VoiceProvider",
    "build_nppes_provider",
    "clean_optional_text",
]
