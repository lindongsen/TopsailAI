"""Generic yes/no confirmation before boundary regressions.

Author: DawsonLin
"""

from unittest.mock import Mock

import pytest

from topsailai.hooks.points.workspace import before_input_yes as point
from topsailai.workspace import input_tool


@pytest.fixture
def entry(monkeypatch):
    """Replace only the public Hook Point, not confirmation semantics."""
    call = Mock(return_value=())
    monkeypatch.setattr(point, "hook__workspace__before__input_yes", call)
    return call


@pytest.mark.parametrize("answer,expected", [("yes", True), ("no", False)])
def test_hook_reader_order(entry, monkeypatch, answer, expected):
    """Invoke the point once with the prompt text before the reader runs."""
    trace = []
    entry.side_effect = lambda **kwargs: trace.append("hook")
    reader = Mock(side_effect=lambda *a: trace.append("read") or answer)
    monkeypatch.setattr(input_tool, "input_one_line", reader)
    assert input_tool.input_yes("Proceed with deletion? ") is expected
    assert trace == ["hook", "read"]
    entry.assert_called_once_with(tips="Proceed with deletion? ")


def test_default_tips_reach_the_point(entry, monkeypatch):
    """The declared default prompt is forwarded unchanged."""
    monkeypatch.setattr(input_tool, "input_one_line", lambda *a: "no")
    assert input_tool.input_yes() is False
    entry.assert_called_once_with(tips="Continue [yes/no] ")


def test_retry_loop_does_not_redispatch(entry, monkeypatch):
    """Invalid answers retry inside one confirmation without a second point."""
    values = iter(["maybe", "yes"])
    monkeypatch.setattr(input_tool, "input_one_line", lambda *a: next(values))
    assert input_tool.input_yes("Continue? ") is True
    entry.assert_called_once_with(tips="Continue? ")


def test_eof_returns_false_without_redispatch(entry, monkeypatch):
    """A closed channel answers no and never re-runs the point."""
    monkeypatch.setattr(input_tool, "input_one_line", Mock(side_effect=EOFError))
    assert input_tool.input_yes("Continue? ") is False
    entry.assert_called_once_with(tips="Continue? ")


def test_message_checkpoint_is_not_dispatched(entry, monkeypatch):
    """Confirmation does not dispatch the complete-message checkpoint."""
    message_point = Mock()
    monkeypatch.setattr(
        "topsailai.hooks.points.workspace.before_input_message."
        "hook__workspace__before__input_message", message_point)
    monkeypatch.setattr(input_tool, "input_one_line", lambda *a: "yes")
    assert input_tool.input_yes("Continue? ") is True
    message_point.assert_not_called()


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_hook_interrupt_propagates(entry, monkeypatch, error):
    """Host interruption before confirmation propagates unchanged."""
    entry.side_effect = error
    reader = Mock()
    monkeypatch.setattr(input_tool, "input_one_line", reader)
    with pytest.raises(type(error)) as caught:
        input_tool.input_yes("Continue? ")
    assert caught.value is error
    reader.assert_not_called()


def test_direct_reader_excluded(entry, monkeypatch):
    """A direct single-line read does not introduce a confirmation point."""
    monkeypatch.setattr(input_tool, "_input", lambda *a: "direct")
    assert input_tool.input_one_line() == "direct"
    entry.assert_not_called()
