"""
Unit tests for the generic timeout-aware yes/no input helper.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-07
Purpose: Verify input_yes_or_no_with_timeout stays generic, sliced and bounded
"""

from unittest import mock

import pytest

from topsailai.utils.input_tool import (
    _normalize_poll_interval,
    _normalize_yes_no_default,
    input_yes_or_no_with_timeout,
)


def test_yes_returns_true():
    """A yes answer returns True without polling again."""
    reader = mock.Mock(return_value="yes")
    assert input_yes_or_no_with_timeout("p? ", input_func=reader) is True
    reader.assert_called_once()


def test_no_returns_false():
    """A no answer returns False."""
    reader = mock.Mock(return_value="no")
    assert input_yes_or_no_with_timeout("p? ", input_func=reader) is False


def test_short_answers_are_accepted():
    """Single-letter answers are accepted as their full form."""
    assert input_yes_or_no_with_timeout("p? ", input_func=mock.Mock(return_value="y")) is True
    assert input_yes_or_no_with_timeout("p? ", input_func=mock.Mock(return_value="N")) is False


def test_answer_is_stripped_and_case_insensitive():
    """Surrounding whitespace and letter case do not change the answer."""
    reader = mock.Mock(return_value="  YeS  ")
    assert input_yes_or_no_with_timeout("p? ", input_func=reader) is True


def test_invalid_answer_reprompts_then_accepts():
    """An unrecognized answer prints a hint and keeps waiting."""
    reader = mock.Mock(side_effect=["maybe", "no"])
    with mock.patch("builtins.print") as printed:
        assert input_yes_or_no_with_timeout("p? ", input_func=reader) is False
    assert reader.call_count == 2
    printed.assert_any_call("Please enter 'yes' or 'no'.")


def test_banner_is_printed_once_with_flush():
    """The banner is emitted through a plain flushed print, never print_info."""
    reader = mock.Mock(return_value="yes")
    with mock.patch("builtins.print") as printed:
        input_yes_or_no_with_timeout("Continue? ", input_func=reader)
    printed.assert_called_once_with("Continue? ", flush=True)


def test_empty_banner_is_not_printed():
    """An empty banner produces no output."""
    reader = mock.Mock(return_value="yes")
    with mock.patch("builtins.print") as printed:
        input_yes_or_no_with_timeout("", input_func=reader)
    printed.assert_not_called()


def test_timeout_expiry_applies_default():
    """An exhausted budget returns the configured default."""
    reader = mock.Mock(return_value=None)
    result = input_yes_or_no_with_timeout(
        "p? ", timeout=0.05, default="no", input_func=reader, poll_interval=0.01
    )
    assert result is False
    assert reader.call_count >= 1


def test_timeout_expiry_applies_yes_default():
    """The default is yes when configured as yes."""
    reader = mock.Mock(return_value=None)
    result = input_yes_or_no_with_timeout(
        "p? ", timeout=0.05, default="yes", input_func=reader, poll_interval=0.01
    )
    assert result is True


def test_zero_timeout_waits_until_answered():
    """A zero timeout means wait indefinitely rather than expire immediately."""
    reader = mock.Mock(side_effect=[None, None, "yes"])
    assert input_yes_or_no_with_timeout(
        "p? ", timeout=0, input_func=reader, poll_interval=0.01
    ) is True
    assert reader.call_count == 3


def test_reader_timeout_error_is_treated_as_no_answer():
    """A reader raising TimeoutError keeps the loop polling."""
    reader = mock.Mock(side_effect=[TimeoutError("slice"), "yes"])
    assert input_yes_or_no_with_timeout(
        "p? ", input_func=reader, poll_interval=0.01
    ) is True


def test_reader_eof_error_is_treated_as_no_answer():
    """A reader raising EOFError keeps the loop polling."""
    reader = mock.Mock(side_effect=[EOFError("eof"), "no"])
    assert input_yes_or_no_with_timeout(
        "p? ", input_func=reader, poll_interval=0.01
    ) is False


def test_on_poll_runs_between_slices():
    """The poll callback runs after every slice without an answer."""
    reader = mock.Mock(side_effect=[None, None, "yes"])
    on_poll = mock.Mock()
    assert input_yes_or_no_with_timeout(
        "p? ", input_func=reader, poll_interval=0.01, on_poll=on_poll
    ) is True
    assert on_poll.call_count == 2


def test_on_poll_exception_propagates():
    """An exception raised by the poll callback is not swallowed."""
    reader = mock.Mock(return_value=None)

    def raise_signal():
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        input_yes_or_no_with_timeout(
            "p? ", input_func=reader, poll_interval=0.01, on_poll=raise_signal
        )


def test_no_input_channel_applies_default_with_warning():
    """Without a TTY or a reader the helper degrades instead of hanging."""
    with mock.patch(
        "topsailai.utils.input_tool._stdin_is_tty", return_value=False
    ), mock.patch("topsailai.utils.input_tool.logger") as logger_mock:
        result = input_yes_or_no_with_timeout("p? ", default="no")
    assert result is False
    logger_mock.warning.assert_called_once()


def test_tty_without_reader_uses_terminal_path():
    """A TTY without an explicit reader falls back to input_with_timeout."""
    with mock.patch(
        "topsailai.utils.input_tool._stdin_is_tty", return_value=True
    ), mock.patch(
        "topsailai.utils.input_tool.input_with_timeout", return_value="yes"
    ) as terminal_read:
        assert input_yes_or_no_with_timeout("p? ", poll_interval=0.01) is True
    terminal_read.assert_called_once()


def test_slice_never_exceeds_remaining_budget():
    """The last slice is clamped to the remaining budget."""
    reader = mock.Mock(return_value=None)
    with mock.patch(
        "topsailai.utils.input_tool.time.monotonic",
        side_effect=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 10.0],
    ):
        input_yes_or_no_with_timeout(
            "p? ", timeout=0.5, input_func=reader, poll_interval=5.0
        )
    first_slice = reader.call_args_list[0][0][1]
    assert first_slice <= 0.5


def test_normalize_yes_no_default():
    """Only an explicit no selects False."""
    assert _normalize_yes_no_default("no") is False
    assert _normalize_yes_no_default(" NO ") is False
    assert _normalize_yes_no_default("yes") is True
    assert _normalize_yes_no_default("") is True
    assert _normalize_yes_no_default(None) is True
    assert _normalize_yes_no_default(0) is True


def test_normalize_poll_interval():
    """Invalid poll intervals fall back to one second."""
    assert _normalize_poll_interval(0.25) == 0.25
    assert _normalize_poll_interval(0) == 1.0
    assert _normalize_poll_interval(-1) == 1.0
    assert _normalize_poll_interval("bad") == 1.0
    assert _normalize_poll_interval(True) == 1.0
    assert _normalize_poll_interval(float("nan")) == 1.0
