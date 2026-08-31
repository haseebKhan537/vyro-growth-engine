"""Phase 26 CI helper for the Phase 25 local-only smoke JSON output.

Validates that sanitized smoke-dry-run output proves no live side effects and
does not expose forbidden sensitive values. This module does not call providers,
open DATABASE_URL, or execute approved items.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from vyro_growth.observability import SENSITIVE_KEYS, UNSAFE_CONTENT_KEYS, contains_phi_indicator
from vyro_growth.services.smoke_dry_run import (
    SMOKE_CONTACT_EMAIL,
    SMOKE_CONTACT_NAME,
    SMOKE_INBOUND_BODY,
    SMOKE_ORG_NAME,
    SMOKE_VOICE_PHONE,
)

REQUIRED_FALSE_FIELDS = (
    "live_action",
    "outbound_attempted",
    "owner_approved",
    "live_call_attempted",
    "recommendation_applied",
    "spend_attempted",
    "campaign_launched",
    "pages_published",
    "ads_launched",
    "outbound_enabled",
    "live_providers_enabled",
)
REQUIRED_TRUE_FIELDS = (
    "dry_run_only",
    "no_execution",
    "isolated_demo_database",
    "local_only",
)
REQUIRED_ZERO_FIELDS = ("executed",)
FALSE_EVERYWHERE_KEYS = frozenset(REQUIRED_FALSE_FIELDS)
ZERO_EVERYWHERE_KEYS = frozenset((*REQUIRED_ZERO_FIELDS, "executed_count"))
FORBIDDEN_CONTENT_KEYS = frozenset(key.lower() for key in (*UNSAFE_CONTENT_KEYS, *SENSITIVE_KEYS))
FORBIDDEN_LITERALS = (
    SMOKE_CONTACT_EMAIL,
    SMOKE_CONTACT_NAME,
    SMOKE_INBOUND_BODY,
    SMOKE_ORG_NAME,
    SMOKE_VOICE_PHONE,
    "sk-testsecret",
    "patient diagnosis",
    "Bearer secret",
    "BEGIN PRIVATE KEY",
)
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}|\d{10})(?!\d)"
)
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|secret|token|credential|bearer)\b\s*[:=]\s*\S+"
)
_KEY_LIKE_RE = re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_\-]{8,}\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+\S+")


class SmokeCiGateError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_smoke_ci_output(raw: str) -> dict[str, Any]:
    """Parse sanitized smoke JSON and fail closed on live or sensitive content."""

    payload = _parse_json_object(raw)
    _require_completed_status(payload)
    _require_top_level_signals(payload)
    _require_disabled_live_providers(payload)
    _walk_payload(payload)
    _scan_raw_text(raw)
    return payload


def format_smoke_ci_gate_summary(payload: Mapping[str, Any], *, passed: bool = True) -> str:
    status = "passed" if passed else "failed"
    return "\n".join(
        [
            f"CI smoke gate: {status}",
            f"executed={payload.get('executed', 'missing')}",
            f"live_action={_bool_text(payload.get('live_action'))}",
            f"outbound_attempted={_bool_text(payload.get('outbound_attempted'))}",
            f"owner_approved={_bool_text(payload.get('owner_approved'))}",
            f"dry_run_only={_bool_text(payload.get('dry_run_only'))}",
            f"no_execution={_bool_text(payload.get('no_execution'))}",
            f"isolated_demo_database={_bool_text(payload.get('isolated_demo_database'))}",
        ]
    )


def _parse_json_object(raw: str) -> dict[str, Any]:
    stripped = raw.strip()
    if not stripped:
        raise SmokeCiGateError("invalid_json", "CI smoke gate: failed reason=invalid_json")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise SmokeCiGateError(
            "invalid_json",
            "CI smoke gate: failed reason=invalid_json",
        ) from exc
    if not isinstance(payload, dict):
        raise SmokeCiGateError("invalid_json", "CI smoke gate: failed reason=invalid_json")
    return payload


def _require_completed_status(payload: Mapping[str, Any]) -> None:
    if payload.get("status") != "completed":
        raise SmokeCiGateError(
            "unexpected_refusal",
            "CI smoke gate: failed reason=unexpected_refusal",
        )


def _require_top_level_signals(payload: Mapping[str, Any]) -> None:
    for field in REQUIRED_ZERO_FIELDS:
        if payload.get(field) != 0:
            raise SmokeCiGateError(
                "unsafe_side_effect",
                f"CI smoke gate: failed reason=unsafe_side_effect field={field}",
            )
    for field in REQUIRED_FALSE_FIELDS:
        if payload.get(field) is not False:
            raise SmokeCiGateError(
                "unsafe_side_effect",
                f"CI smoke gate: failed reason=unsafe_side_effect field={field}",
            )
    for field in REQUIRED_TRUE_FIELDS:
        if payload.get(field) is not True:
            raise SmokeCiGateError(
                "missing_required_field",
                f"CI smoke gate: failed reason=missing_required_field field={field}",
            )


def _require_disabled_live_providers(payload: Mapping[str, Any]) -> None:
    flags = payload.get("live_providers")
    if not isinstance(flags, Mapping) or not flags:
        raise SmokeCiGateError(
            "missing_required_field",
            "CI smoke gate: failed reason=missing_required_field field=live_providers",
        )
    if any(enabled is not False for enabled in flags.values()):
        raise SmokeCiGateError(
            "live_provider_enabled",
            "CI smoke gate: failed reason=live_provider_enabled",
        )


def _walk_payload(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in FORBIDDEN_CONTENT_KEYS:
                raise SmokeCiGateError(
                    "forbidden_content_key",
                    "CI smoke gate: failed reason=forbidden_content_key",
                )
            if lowered in FALSE_EVERYWHERE_KEYS and item is not False:
                raise SmokeCiGateError(
                    "unsafe_side_effect",
                    f"CI smoke gate: failed reason=unsafe_side_effect field={lowered}",
                )
            if lowered in ZERO_EVERYWHERE_KEYS and item != 0:
                raise SmokeCiGateError(
                    "unsafe_side_effect",
                    f"CI smoke gate: failed reason=unsafe_side_effect field={lowered}",
                )
            if isinstance(item, str):
                _reject_sensitive_text(item)
            _walk_payload(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            if isinstance(item, str):
                _reject_sensitive_text(item)
            _walk_payload(item)


def _scan_raw_text(raw: str) -> None:
    if contains_phi_indicator(raw) or _EMAIL_RE.search(raw) or _secret_like(raw):
        raise SmokeCiGateError(
            "forbidden_sensitive_value",
            "CI smoke gate: failed reason=forbidden_sensitive_value",
        )
    for token in FORBIDDEN_LITERALS:
        if token and token in raw:
            raise SmokeCiGateError(
                "forbidden_sensitive_value",
                "CI smoke gate: failed reason=forbidden_sensitive_value",
            )


def _reject_sensitive_text(value: str) -> None:
    if (
        contains_phi_indicator(value)
        or _EMAIL_RE.search(value)
        or _PHONE_RE.search(value)
        or _secret_like(value)
    ):
        raise SmokeCiGateError(
            "forbidden_sensitive_value",
            "CI smoke gate: failed reason=forbidden_sensitive_value",
        )


def _secret_like(value: str) -> bool:
    return bool(
        _BEARER_RE.search(value) or _KEY_LIKE_RE.search(value) or _SECRET_ASSIGN_RE.search(value)
    )


def _bool_text(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "missing"
