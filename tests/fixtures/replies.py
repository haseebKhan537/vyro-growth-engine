from __future__ import annotations

from vyro_growth.domain import ReplyIntent

REPLY_BODIES: dict[ReplyIntent, str] = {
    ReplyIntent.INTERESTED: "Thanks for reaching out. We are interested in a billing review.",
    ReplyIntent.NOT_INTERESTED: "Thanks, but we are not interested at this time.",
    ReplyIntent.UNSUBSCRIBE: "Please unsubscribe me and do not email this address again.",
    ReplyIntent.WRONG_PERSON: (
        "I am the wrong person for billing decisions and no longer work there."
    ),
    ReplyIntent.OUT_OF_OFFICE: "Automatic reply: I am out of office until next Monday.",
    ReplyIntent.REFERRAL: "Please talk to our office manager about this.",
    ReplyIntent.NEEDS_MORE_INFO: "Can you send pricing and explain how does it work?",
    ReplyIntent.MEETING_REQUEST: "Let's meet next week if you can schedule a meeting.",
    ReplyIntent.HOSTILE: "This is harassment. We will take legal action.",
    ReplyIntent.SPAM: "This is spam. Mark as spam.",
    ReplyIntent.UNKNOWN: "Received your note. Will circle back after the holiday.",
}


def classified_payload(
    intent: ReplyIntent,
    *,
    confidence: float = 0.8,
    rationale: str | None = None,
    signals: list[str] | None = None,
    unsubscribe_explicit: bool | None = None,
) -> dict[str, object]:
    return {
        "intent": intent.value,
        "confidence": confidence,
        "rationale": rationale or f"Classified as {intent.value}.",
        "matched_signals": signals or [intent.value],
        "unsubscribe_explicit": (
            intent is ReplyIntent.UNSUBSCRIBE
            if unsubscribe_explicit is None
            else unsubscribe_explicit
        ),
    }


def invented_payload() -> dict[str, object]:
    return classified_payload(
        ReplyIntent.INTERESTED,
        rationale="Their denial rate and payer mix make this a guaranteed fit.",
    )
