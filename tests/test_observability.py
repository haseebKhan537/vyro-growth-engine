from __future__ import annotations

from vyro_growth.observability import (
    REDACTED,
    REDACTED_UNSAFE_ERROR,
    redact_event,
    sanitize_error_message,
    sanitize_mapping,
    sanitize_operator_text,
)


def test_redacts_sensitive_top_level_keys() -> None:
    event = redact_event(
        {
            "authorization": "Bearer secret",
            "internal_api_key": "internal-secret",
            "openai_api_key": "placeholder-key",
            "smartlead_api_key": "placeholder-smartlead-key",
            "voice_api_key": "placeholder-voice-key",
            "message": "ok",
        }
    )

    assert event["authorization"] == "[REDACTED]"
    assert event["internal_api_key"] == "[REDACTED]"
    assert event["openai_api_key"] == "[REDACTED]"
    assert event["smartlead_api_key"] == "[REDACTED]"
    assert event["voice_api_key"] == "[REDACTED]"
    assert event["message"] == "ok"


def test_redacts_sensitive_headers() -> None:
    event = redact_event(
        {
            "headers": {
                "Authorization": "Bearer secret",
                "Content-Type": "application/json",
                "X-Api-Key": "abc123",
                "X-Internal-Api-Key": "internal-secret",
                "X-Website-Intake-Key": "website-secret",
            }
        }
    )

    headers = event["headers"]
    assert headers["Authorization"] == "[REDACTED]"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Api-Key"] == "[REDACTED]"
    assert headers["X-Internal-Api-Key"] == "[REDACTED]"
    assert headers["X-Website-Intake-Key"] == "[REDACTED]"


def test_sanitize_operator_text_redacts_contacts_and_secrets() -> None:
    text = sanitize_operator_text(
        "Failed for jordan.blake@austinfamily.example phone=5551112222 "
        "token=sk-abcdefghijklmnop Authorization: Bearer secret-token"
    )

    assert text is not None
    assert "jordan.blake@austinfamily.example" not in text
    assert "5551112222" not in text
    assert "sk-abcdefghijklmnop" not in text
    assert "secret-token" not in text
    assert REDACTED in text


def test_sanitize_error_message_redacts_phi() -> None:
    assert (
        sanitize_error_message("The patient has a diagnosis of diabetes.")
        == REDACTED_UNSAFE_ERROR
    )


def test_sanitize_mapping_redacts_unsafe_content_keys() -> None:
    sanitized = sanitize_mapping(
        {
            "openai_api_key": "placeholder-key",
            "practice_summary": "Clinic summary must not leak.",
            "status": "failed",
        }
    )

    assert sanitized["openai_api_key"] == REDACTED
    assert sanitized["practice_summary"] == REDACTED
    assert sanitized["status"] == "failed"
