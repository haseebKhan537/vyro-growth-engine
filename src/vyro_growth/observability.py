import logging
import re
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
    "voice_api_key",
    "decision_maker_api_key",
    "email_verification_api_key",
    "internal_api_key",
    "password",
    "secret",
    "token",
    "credential",
    "access_token",
    "refresh_token",
}
UNSAFE_CONTENT_KEYS = {
    "body",
    "subject",
    "message",
    "draft",
    "copy",
    "content",
    "practice_summary",
    "why_vyro_relevant",
    "opening_line",
    "outreach_angle",
    "suggested_offer",
    "evidence_snippet",
    "extracted_value",
    "snippet",
    "email",
    "sender_email",
    "phone",
    "permitted_phone",
    "meeting_url",
    "facts_json",
    "consent_json",
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

REDACTED = "[REDACTED]"
REDACTED_UNSAFE_ERROR = "[REDACTED_UNSAFE_ERROR]"
MAX_SANITIZED_TEXT = 240

_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]*)\d{3}[-.\s]*\d{4}")
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|secret|token|credential|bearer)\b\s*[:=]\s*\S+"
)
_KEY_LIKE_RE = re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_\-]{8,}\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+\S+")
_PHI_TOKEN_RE = re.compile(
    r"(?i)\b(patient|diagnosis|diabetes|phi|ssn|hipaa|medical[\s_-]?record|mrn)\b"
)


def _redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        if key.lower() in SENSITIVE_KEYS or key.lower() in SENSITIVE_HEADERS:
            redacted[key] = REDACTED
        elif isinstance(item, Mapping):
            redacted[key] = _redact_mapping(item)
        else:
            redacted[key] = item
    return redacted


def _redact(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    for key in list(event_dict):
        lowered = key.lower()
        if lowered in SENSITIVE_KEYS:
            event_dict[key] = REDACTED
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


def contains_phi_indicator(value: str) -> bool:
    return bool(_PHI_TOKEN_RE.search(value))


def sanitize_operator_text(
    value: str | None, *, max_length: int = MAX_SANITIZED_TEXT
) -> str | None:
    """Redact secrets, contact fields, and PHI-like text for operator-visible output."""

    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return ""
    redacted = _EMAIL_RE.sub(REDACTED, stripped)
    redacted = _PHONE_RE.sub(REDACTED, redacted)
    redacted = _BEARER_RE.sub(REDACTED, redacted)
    redacted = _KEY_LIKE_RE.sub(REDACTED, redacted)
    redacted = _SECRET_ASSIGN_RE.sub(REDACTED, redacted)
    if contains_phi_indicator(redacted):
        return REDACTED_UNSAFE_ERROR
    if len(redacted) > max_length:
        return redacted[: max_length - 3].rstrip() + "..."
    return redacted


def sanitize_error_message(value: str | None) -> str | None:
    """Sanitize a stored run error for operator monitoring. Never returns raw PHI or secrets."""

    return sanitize_operator_text(value)


def sanitize_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Redact secrets and unsafe content keys from a mapping used in operator output."""

    redacted: dict[str, Any] = {}
    for key, item in value.items():
        lowered = key.lower()
        if (
            lowered in SENSITIVE_KEYS
            or lowered in SENSITIVE_HEADERS
            or lowered in UNSAFE_CONTENT_KEYS
        ):
            redacted[key] = REDACTED
        elif isinstance(item, Mapping):
            redacted[key] = sanitize_mapping(item)
        elif isinstance(item, str):
            sanitized = sanitize_operator_text(item)
            redacted[key] = sanitized if sanitized is not None else REDACTED
        else:
            redacted[key] = item
    return redacted
