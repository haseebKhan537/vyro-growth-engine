from __future__ import annotations

from vyro_growth.observability import redact_event


def test_redacts_sensitive_top_level_keys() -> None:
    event = redact_event({"authorization": "Bearer secret", "message": "ok"})

    assert event["authorization"] == "[REDACTED]"
    assert event["message"] == "ok"


def test_redacts_sensitive_headers() -> None:
    event = redact_event(
        {
            "headers": {
                "Authorization": "Bearer secret",
                "Content-Type": "application/json",
                "X-Api-Key": "abc123",
            }
        }
    )

    headers = event["headers"]
    assert headers["Authorization"] == "[REDACTED]"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Api-Key"] == "[REDACTED]"
