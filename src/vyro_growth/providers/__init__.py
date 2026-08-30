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
from vyro_growth.providers.website import (
    HeuristicWebsiteSearchProvider,
    PublicPage,
    PublicPageFetcher,
    StaticPublicPageFetcher,
    StaticWebsiteSearchProvider,
    WebsiteCandidate,
    WebsiteFetchError,
    WebsiteSearchProvider,
    WebsiteSearchQuery,
)
from vyro_growth.providers.website_client import HttpPublicPageFetcher, build_public_page_fetcher

__all__ = [
    "CalendarProvider",
    "CallResult",
    "EmailProvider",
    "EnrichmentProvider",
    "GuardedCalendarProvider",
    "GuardedEmailProvider",
    "GuardedVoiceProvider",
    "HeuristicWebsiteSearchProvider",
    "HttpNppesProvider",
    "HttpPublicPageFetcher",
    "PublicPage",
    "PublicPageFetcher",
    "StaticPublicPageFetcher",
    "StaticWebsiteSearchProvider",
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
    "WebsiteCandidate",
    "WebsiteFetchError",
    "WebsiteSearchProvider",
    "WebsiteSearchQuery",
    "build_nppes_provider",
    "build_public_page_fetcher",
    "clean_optional_text",
]
