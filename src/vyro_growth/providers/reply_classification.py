from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from vyro_growth.config import Settings, get_settings
from vyro_growth.domain import ReplyIntent
from vyro_growth.providers.decision_makers import clean_optional_text, clip_text

REPLY_CLASSIFICATION_SOURCE = "reply_classification"
STUB_PROVIDER_NAME = "stub"
PROMPT_VERSION = "reply-classification-v1"
SCHEMA_VERSION = "reply-classification-v1"
RATIONALE_MAX_LENGTH = 240
SIGNAL_MAX_LENGTH = 80
MAX_SIGNALS = 12
SUBJECT_MAX_LENGTH = 500
BODY_MAX_LENGTH = 4000
FINGERPRINT_LENGTH = 64
WHITESPACE_RE = re.compile(r"\s+")

INVENTED_BUSINESS_PHRASES = frozenset(
    {
        "denial rate",
        "denial rates",
        "accounts receivable",
        "a/r days",
        "payer mix",
        "billing software",
        "patient diagnosis",
        "patient portal login",
        "phi",
    }
)

PROMPT_SYSTEM = (
    "You classify inbound B2B email replies for Vyro Medical Billing. "
    "Return JSON only. Choose exactly one intent from the allowed enum. "
    "Use only the supplied subject and body. Do not invent practice facts, "
    "revenue, denial rates, A/R, payer mix, billing software, patient details, "
    "or medical conditions. Do not draft a reply to send. Honor explicit "
    "unsubscribe or opt-out language with intent=unsubscribe and "
    "unsubscribe_explicit=true. If the text is an automatic out-of-office "
    "notice, use out_of_office. If intent is unclear, use unknown."
)

REPLY_CLASSIFICATION_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "intent",
        "confidence",
        "rationale",
        "matched_signals",
        "unsubscribe_explicit",
    ],
    "properties": {
        "intent": {
            "type": "string",
            "enum": [intent.value for intent in ReplyIntent],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
        "matched_signals": {"type": "array", "items": {"type": "string"}},
        "unsubscribe_explicit": {"type": "boolean"},
    },
}

_RULES: tuple[tuple[ReplyIntent, tuple[str, ...]], ...] = (
    (
        ReplyIntent.UNSUBSCRIBE,
        (
            "unsubscribe",
            "opt out",
            "opt-out",
            "remove me from",
            "take me off",
            "stop emailing",
            "stop contacting",
            "do not contact",
            "don't contact",
            "do not email",
            "don't email",
        ),
    ),
    (
        ReplyIntent.HOSTILE,
        (
            "lawsuit",
            "legal action",
            "cease and desist",
            "harassment",
            "report you",
        ),
    ),
    (
        ReplyIntent.SPAM,
        (
            "this is spam",
            "mark as spam",
            "unsolicited",
        ),
    ),
    (
        ReplyIntent.OUT_OF_OFFICE,
        (
            "out of office",
            "automatic reply",
            "auto-reply",
            "autoreply",
            "away from the office",
            "on vacation",
            "on leave until",
        ),
    ),
    (
        ReplyIntent.WRONG_PERSON,
        (
            "wrong person",
            "wrong email",
            "no longer work",
            "not the right person",
            "i'm not the",
            "i am not the",
        ),
    ),
    (
        ReplyIntent.MEETING_REQUEST,
        (
            "schedule a meeting",
            "book a time",
            "set up a call",
            "available to meet",
            "calendar invite",
            "let's meet",
            "lets meet",
        ),
    ),
    (
        ReplyIntent.REFERRAL,
        (
            "talk to",
            "speak with",
            "reach out to",
            "contact our",
            "forward this",
            "you should speak",
        ),
    ),
    (
        ReplyIntent.NOT_INTERESTED,
        (
            "not interested",
            "no thank you",
            "no thanks",
            "please stop",
            "we're all set",
            "we are all set",
        ),
    ),
    (
        ReplyIntent.NEEDS_MORE_INFO,
        (
            "more information",
            "more info",
            "tell me more",
            "how does it work",
            "send pricing",
            "what do you charge",
            "can you explain",
        ),
    ),
    (
        ReplyIntent.INTERESTED,
        (
            "interested",
            "sounds good",
            "let's talk",
            "lets talk",
            "please call",
            "would like to learn",
            "keen to discuss",
        ),
    ),
)


class ReplyClassifierError(RuntimeError):
    """Base error for reply classification providers."""

    retryable: bool = False


class RetryableReplyClassifierError(ReplyClassifierError):
    retryable = True


class NonRetryableReplyClassifierError(ReplyClassifierError):
    retryable = False


class MalformedReplyClassificationOutput(NonRetryableReplyClassifierError):
    """Raised when provider JSON cannot be parsed or violates safety rules."""


@dataclass(frozen=True)
class ReplyClassificationRequest:
    lead_id: UUID
    subject: str | None
    body: str
    sender_email: str | None = None
    provider_message_id: str | None = None
    message_id: UUID | None = None
    prompt_version: str = PROMPT_VERSION
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class ReplyClassificationContent:
    intent: ReplyIntent
    confidence: float
    rationale: str
    matched_signals: tuple[str, ...]
    unsubscribe_explicit: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "matched_signals": list(self.matched_signals),
            "unsubscribe_explicit": self.unsubscribe_explicit,
        }


@dataclass(frozen=True)
class ReplyClassifierAudit:
    prompt_version: str
    schema_version: str
    prompt_hash: str
    provider_name: str
    model: str | None
    max_input_tokens: int
    max_output_tokens: int
    estimated_cost_usd_limit: float | None
    input_tokens: int | None
    output_tokens: int | None
    retry_attempts: int
    live_call_attempted: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "prompt_hash": self.prompt_hash,
            "provider_name": self.provider_name,
            "model": self.model,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "estimated_cost_usd_limit": self.estimated_cost_usd_limit,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "retry_attempts": self.retry_attempts,
            "live_call_attempted": self.live_call_attempted,
        }


@dataclass(frozen=True)
class ReplyClassifierResult:
    content: ReplyClassificationContent
    audit: ReplyClassifierAudit


class ReplyClassifierProvider(Protocol):
    def classify(self, request: ReplyClassificationRequest) -> ReplyClassifierResult: ...


def prompt_hash(prompt: str = PROMPT_SYSTEM) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def normalize_reply_text(value: str | None) -> str:
    if value is None:
        return ""
    return WHITESPACE_RE.sub(" ", value).strip().lower()


def reply_content_hash(
    *,
    subject: str | None,
    body: str,
    sender_email: str | None = None,
    provider_message_id: str | None = None,
) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "provider_message_id": clean_optional_text(provider_message_id),
        "sender_email": clean_optional_text(sender_email),
        "subject": normalize_reply_text(subject),
        "body": normalize_reply_text(body),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


def request_prompt_payload(request: ReplyClassificationRequest) -> dict[str, object]:
    return {
        "subject": clip_text(request.subject or "", SUBJECT_MAX_LENGTH),
        "body": clip_text(request.body, BODY_MAX_LENGTH),
        "has_sender_email": clean_optional_text(request.sender_email) is not None,
    }


def parse_reply_classification(raw: object) -> ReplyClassificationContent | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    intent_raw = raw.get("intent")
    if not isinstance(intent_raw, str):
        return None
    try:
        intent = ReplyIntent(intent_raw)
    except ValueError:
        return None
    confidence_raw = raw.get("confidence")
    if isinstance(confidence_raw, bool) or not isinstance(confidence_raw, int | float):
        return None
    confidence = float(confidence_raw)
    if confidence < 0 or confidence > 1:
        return None
    rationale_raw = raw.get("rationale")
    rationale = clean_optional_text(rationale_raw if isinstance(rationale_raw, str) else None)
    signals_raw = raw.get("matched_signals")
    if signals_raw is None:
        signals: list[str] = []
    elif not isinstance(signals_raw, list):
        return None
    else:
        signals = []
        for item in signals_raw[:MAX_SIGNALS]:
            if not isinstance(item, str):
                return None
            cleaned = clean_optional_text(item)
            if cleaned is not None:
                signals.append(clip_text(cleaned, SIGNAL_MAX_LENGTH))
    unsubscribe = raw.get("unsubscribe_explicit")
    if unsubscribe is None:
        unsubscribe_explicit = intent is ReplyIntent.UNSUBSCRIBE
    elif isinstance(unsubscribe, bool):
        unsubscribe_explicit = unsubscribe
    else:
        return None
    if intent is ReplyIntent.UNSUBSCRIBE:
        unsubscribe_explicit = True
    content = ReplyClassificationContent(
        intent=intent,
        confidence=confidence,
        rationale=clip_text(rationale or f"Classified as {intent.value}.", RATIONALE_MAX_LENGTH),
        matched_signals=tuple(signals),
        unsubscribe_explicit=unsubscribe_explicit,
    )
    return validate_reply_classification(content)


def validate_reply_classification(
    content: ReplyClassificationContent,
) -> ReplyClassificationContent:
    lowered = content.rationale.lower()
    for phrase in INVENTED_BUSINESS_PHRASES:
        if phrase in lowered:
            raise MalformedReplyClassificationOutput(
                f"reply classification rationale contained disallowed claim: {phrase}"
            )
    if content.intent is ReplyIntent.UNSUBSCRIBE and not content.unsubscribe_explicit:
        raise MalformedReplyClassificationOutput(
            "unsubscribe intent requires unsubscribe_explicit=true"
        )
    return content


def classify_reply_rules(request: ReplyClassificationRequest) -> ReplyClassificationContent:
    haystack = f"{normalize_reply_text(request.subject)} {normalize_reply_text(request.body)}"
    if not haystack.strip():
        return ReplyClassificationContent(
            intent=ReplyIntent.UNKNOWN,
            confidence=0.2,
            rationale="Empty inbound text; intent remains unknown.",
            matched_signals=(),
            unsubscribe_explicit=False,
        )
    for intent, phrases in _RULES:
        matched = tuple(phrase for phrase in phrases if phrase in haystack)
        if matched:
            return ReplyClassificationContent(
                intent=intent,
                confidence=0.86 if intent is ReplyIntent.UNSUBSCRIBE else 0.78,
                rationale=f"Rule-based match for {intent.value}.",
                matched_signals=matched[:MAX_SIGNALS],
                unsubscribe_explicit=intent is ReplyIntent.UNSUBSCRIBE,
            )
    return ReplyClassificationContent(
        intent=ReplyIntent.UNKNOWN,
        confidence=0.35,
        rationale="No conservative rule matched; intent remains unknown.",
        matched_signals=(),
        unsubscribe_explicit=False,
    )


def _stub_audit(*, live_call_attempted: bool = False) -> ReplyClassifierAudit:
    return ReplyClassifierAudit(
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        prompt_hash=prompt_hash(),
        provider_name=STUB_PROVIDER_NAME,
        model=None,
        max_input_tokens=0,
        max_output_tokens=0,
        estimated_cost_usd_limit=None,
        input_tokens=None,
        output_tokens=None,
        retry_attempts=0,
        live_call_attempted=live_call_attempted,
    )


class StubReplyClassifier:
    """Deterministic keyword classifier. Never calls a live provider."""

    def classify(self, request: ReplyClassificationRequest) -> ReplyClassifierResult:
        return ReplyClassifierResult(
            content=classify_reply_rules(request),
            audit=_stub_audit(),
        )


class StaticReplyClassifier:
    """Test double that returns a fixed payload or raises."""

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def classify(self, request: ReplyClassificationRequest) -> ReplyClassifierResult:
        if isinstance(self._payload, ReplyClassifierError):
            raise self._payload
        if isinstance(self._payload, ReplyClassificationContent):
            return ReplyClassifierResult(content=self._payload, audit=_stub_audit())
        parsed = parse_reply_classification(self._payload)
        if parsed is None:
            raise MalformedReplyClassificationOutput(
                "static reply classifier payload was not valid structured JSON"
            )
        return ReplyClassifierResult(content=parsed, audit=_stub_audit())


def build_reply_classifier(settings: Settings | None = None) -> ReplyClassifierProvider:
    """Return the rule stub unless live classification is explicitly enabled."""
    resolved = settings or get_settings()
    if resolved.openai_reply_classification_enabled and clean_optional_text(
        resolved.openai_api_key
    ):
        # Imported here to avoid a circular import with reply_classification_openai.
        from vyro_growth.providers.reply_classification_openai import OpenAIReplyClassifier

        return OpenAIReplyClassifier.from_settings(resolved)
    return StubReplyClassifier()
