import pytest

from vyro_growth.domain import LeadStage, can_transition


def test_valid_transition() -> None:
    assert can_transition(LeadStage.DISCOVERED, LeadStage.ENRICHING)


def test_invalid_transition_skips_pipeline() -> None:
    assert not can_transition(LeadStage.DISCOVERED, LeadStage.MEETING_BOOKED)


@pytest.mark.parametrize("terminal", [LeadStage.WON, LeadStage.LOST, LeadStage.SUPPRESSED])
def test_terminal_states_do_not_transition(terminal: LeadStage) -> None:
    for target in LeadStage:
        assert not can_transition(terminal, target)
