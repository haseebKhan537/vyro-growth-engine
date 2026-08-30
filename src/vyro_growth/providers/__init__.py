"""External provider interfaces and adapters."""

from vyro_growth.providers.base import (
    CalendarProvider,
    EmailProvider,
    EnrichmentProvider,
    SendResult,
)
from vyro_growth.providers.guarded import GuardedEmailProvider
from vyro_growth.providers.nppes import (
    NARROW_FILTER_ERROR,
    NPPES_MAX_SKIP,
    NormalizedNppesOrganization,
    NppesProvider,
    NppesQueryError,
    NppesSearchPage,
    NppesSearchQuery,
)
from vyro_growth.providers.nppes_client import HttpNppesProvider, build_nppes_provider
from vyro_growth.providers.stubs import (
    StubCalendarProvider,
    StubEmailProvider,
    StubEnrichmentProvider,
)

__all__ = [
    "CalendarProvider",
    "EmailProvider",
    "EnrichmentProvider",
    "GuardedEmailProvider",
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
    "build_nppes_provider",
]
