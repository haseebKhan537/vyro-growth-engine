import logging
from collections.abc import Mapping, MutableMapping
from typing import Any, cast

import structlog
from structlog.typing import EventDict, WrappedLogger

SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "openai_api_key",
    "smartlead_api_key",
    "google_calendar_api_key",
    "internal_api_key",
    "password",
    "secret",
    "token",
}
SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-internal-api-key",
    "x-auth-token",
    "proxy-authorization",
}


def _redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        if key.lower() in SENSITIVE_KEYS or key.lower() in SENSITIVE_HEADERS:
            redacted[key] = "[REDACTED]"
        elif isinstance(item, Mapping):
            redacted[key] = _redact_mapping(item)
        else:
            redacted[key] = item
    return redacted


def _redact(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    for key in list(event_dict):
        lowered = key.lower()
        if lowered in SENSITIVE_KEYS:
            event_dict[key] = "[REDACTED]"
        elif lowered == "headers" and isinstance(event_dict[key], Mapping):
            event_dict[key] = _redact_mapping(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(message)s")
    structlog.configure(
        processors=[
            _redact,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
    )


def redact_event(event: MutableMapping[str, Any]) -> dict[str, Any]:
    """Apply the same redaction rules used by structured logging."""
    return cast(dict[str, Any], _redact(structlog.get_logger(), "", dict(event)))
