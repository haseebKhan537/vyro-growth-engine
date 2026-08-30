from __future__ import annotations

from uuid import uuid4

import pytest

from tests.fixtures.replies import REPLY_BODIES, classified_payload, invented_payload
from vyro_growth.config import Settings
from vyro_growth.domain import ReplyIntent
from vyro_growth.providers.reply_classification import (
    MalformedReplyClassificationOutput,
    NonRetryableReplyClassifierError,
    ReplyClassificationRequest,
    RetryableReplyClassifierError,
    StaticReplyClassifier,
    StubReplyClassifier,
    build_reply_classifier,
    classify_reply_rules,
    parse_reply_classification,
)


def _request(body: str, subject: str | None = None) -> ReplyClassificationRequest:
    return ReplyClassificationRequest(
        lead_id=uuid4(),
        subject=subject,
        body=body,
        sender_email="owner@clinic.example",
    )


@pytest.mark.parametrize("intent", list(ReplyIntent))
def test_rule_stub_classifies_each_intent(intent: ReplyIntent) -> None:
    content = classify_reply_rules(_request(REPLY_BODIES[intent]))
    assert content.intent is intent
    if intent is ReplyIntent.UNSUBSCRIBE:
        assert content.unsubscribe_explicit is True


def test_unsubscribe_outranks_not_interested() -> None:
    content = classify_reply_rules(
        _request("Please unsubscribe. We are not interested in more emails.")
    )
    assert content.intent is ReplyIntent.UNSUBSCRIBE
    assert content.unsubscribe_explicit is True


def test_empty_body_is_unknown() -> None:
    content = classify_reply_rules(_request("   "))
    assert content.intent is ReplyIntent.UNKNOWN


def test_stub_provider_never_attempts_live_call() -> None:
    result = StubReplyClassifier().classify(_request(REPLY_BODIES[ReplyIntent.INTERESTED]))
    assert result.audit.live_call_attempted is False
    assert result.audit.provider_name == "stub"


def test_build_reply_classifier_defaults_to_stub() -> None:
    settings = Settings(openai_reply_classification_enabled=False, openai_api_key="")
    provider = build_reply_classifier(settings)
    assert isinstance(provider, StubReplyClassifier)


def test_static_provider_rejects_malformed_payload() -> None:
    provider = StaticReplyClassifier({"nope": True})
    with pytest.raises(MalformedReplyClassificationOutput):
        provider.classify(_request(REPLY_BODIES[ReplyIntent.UNKNOWN]))


def test_static_provider_rejects_invalid_intent() -> None:
    provider = StaticReplyClassifier(
        {
            "intent": "book_meeting_now",
            "confidence": 0.9,
            "rationale": "Book it.",
            "matched_signals": [],
            "unsubscribe_explicit": False,
        }
    )
    with pytest.raises(MalformedReplyClassificationOutput):
        provider.classify(_request(REPLY_BODIES[ReplyIntent.UNKNOWN]))


def test_invented_business_claims_are_rejected() -> None:
    with pytest.raises(MalformedReplyClassificationOutput, match="disallowed claim"):
        parse_reply_classification(invented_payload())


def test_retryable_and_non_retryable_static_errors() -> None:
    retryable = StaticReplyClassifier(RetryableReplyClassifierError("timeout"))
    with pytest.raises(RetryableReplyClassifierError):
        retryable.classify(_request("hello"))
    non_retryable = StaticReplyClassifier(NonRetryableReplyClassifierError("disabled"))
    with pytest.raises(NonRetryableReplyClassifierError):
        non_retryable.classify(_request("hello"))


def test_valid_static_payload_is_accepted() -> None:
    provider = StaticReplyClassifier(classified_payload(ReplyIntent.NEEDS_MORE_INFO))
    result = provider.classify(_request(REPLY_BODIES[ReplyIntent.NEEDS_MORE_INFO]))
    assert result.content.intent is ReplyIntent.NEEDS_MORE_INFO
