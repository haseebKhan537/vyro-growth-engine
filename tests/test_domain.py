import pytest

from vyro_growth.domain import (
    ConversationStatus,
    LeadStage,
    ReplyIntent,
    can_transition,
    conversation_status_for,
    desired_booking_stage,
    desired_reply_stages,
)


def test_valid_transition() -> None:
    assert can_transition(LeadStage.DISCOVERED, LeadStage.ENRICHING)


def test_invalid_transition_skips_pipeline() -> None:
    assert not can_transition(LeadStage.DISCOVERED, LeadStage.MEETING_BOOKED)


@pytest.mark.parametrize("terminal", [LeadStage.WON, LeadStage.LOST, LeadStage.SUPPRESSED])
def test_terminal_states_do_not_transition(terminal: LeadStage) -> None:
    for target in LeadStage:
        assert not can_transition(terminal, target)


def test_meeting_request_never_targets_booked_or_contacted() -> None:
    targets = desired_reply_stages(ReplyIntent.MEETING_REQUEST)
    assert LeadStage.MEETING_BOOKED not in targets
    assert LeadStage.MEETING_READY not in targets
    assert LeadStage.CONTACTED not in targets
    assert conversation_status_for(ReplyIntent.MEETING_REQUEST) is (
        ConversationStatus.MEETING_REQUESTED
    )


def test_booking_plan_targets_meeting_ready_never_booked() -> None:
    assert desired_booking_stage(LeadStage.INTERESTED) is LeadStage.MEETING_READY
    assert desired_booking_stage(LeadStage.QUALIFICATION_PENDING) is LeadStage.MEETING_READY
    assert desired_booking_stage(LeadStage.MEETING_READY) is LeadStage.MEETING_READY
    assert desired_booking_stage(LeadStage.CONTACTED) is None
    assert desired_booking_stage(LeadStage.DISCOVERED) is None


def test_unsubscribe_targets_suppressed() -> None:
    assert desired_reply_stages(ReplyIntent.UNSUBSCRIBE) == (LeadStage.SUPPRESSED,)
    assert conversation_status_for(ReplyIntent.UNSUBSCRIBE) is ConversationStatus.SUPPRESSED
