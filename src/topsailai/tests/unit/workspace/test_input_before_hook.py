"""Generic complete-message before boundary regressions.

Author: DawsonLin
"""

import asyncio
from unittest.mock import Mock

import pytest

from topsailai.hooks.points.workspace import before_input_message as point
from topsailai.workspace import input_tool


@pytest.fixture
def entry(monkeypatch):
    """Replace only the public Hook Point, not input or command semantics."""
    call = Mock(return_value=())
    monkeypatch.setattr(point, "hook__workspace__before__input_message", call)
    monkeypatch.setattr(input_tool, "_append_input_history_jsonl", Mock())
    monkeypatch.setattr(input_tool.env_tool, "is_chat_multi_line", lambda: False)
    return call


@pytest.mark.parametrize("multiline", [False, True])
def test_mode_hook_reader_order(entry, monkeypatch, multiline):
    """Invoke the zero-argument point once between mode selection and input."""
    trace = []
    monkeypatch.setattr(input_tool.env_tool, "is_chat_multi_line",
                        lambda: trace.append("mode") or multiline)
    entry.side_effect = lambda: trace.append("hook")
    reader = Mock(side_effect=lambda *a: trace.append("read") or "original")
    monkeypatch.setattr(input_tool, "input_multi_line" if multiline else "input_one_line", reader)
    assert input_tool.input_message("prompt") == "original"
    assert trace == ["mode", "hook", "read"]
    entry.assert_called_once_with()
    reader.assert_called_once_with("prompt", None)


@pytest.mark.parametrize("multiline,lines", [
    (False, ["", "/help", "message"]),
    (True, ["EOF", "/help", "first", "second", "EOF"]),
])
def test_reader_loops_do_not_redispatch(entry, monkeypatch, multiline, lines):
    """Retries and command interception stay inside one input occurrence."""
    monkeypatch.setattr(input_tool.env_tool, "is_chat_multi_line", lambda: multiline)
    values = iter(lines)
    monkeypatch.setattr(input_tool, "_input", lambda *a: next(values))
    instruction = Mock()
    instruction.exist_hook.side_effect = lambda text: text.strip() == "/help"
    assert input_tool.input_message(hook=instruction) == ("first\nsecond" if multiline else "message")
    entry.assert_called_once_with()
    instruction.call_hook.assert_called_once_with("/help")


@pytest.mark.parametrize("command", ["exit", "quit", "/exit", "/quit"])
def test_exit_semantics(entry, monkeypatch, command):
    """Exit tokens retain their original SystemExit behavior."""
    monkeypatch.setattr(input_tool, "_input", lambda *a: command)
    with pytest.raises(SystemExit):
        input_tool.input_message()
    entry.assert_called_once_with()


def test_direct_read_excluded(entry, monkeypatch):
    """Direct readers and confirmation do not introduce a second point."""
    monkeypatch.setattr(input_tool, "_input", Mock(side_effect=["direct", "yes"]))
    assert input_tool.input_one_line() == "direct"
    assert input_tool.input_yes() is True
    entry.assert_not_called()


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(), asyncio.CancelledError()])
def test_hook_interrupt_not_input_interrupt(entry, monkeypatch, error):
    """Host interruption before input propagates without a quit prompt."""
    entry.side_effect = error
    confirmation = Mock()
    monkeypatch.setattr(input_tool, "input_yes", confirmation)
    with pytest.raises(type(error)) as caught:
        input_tool.input_message()
    assert caught.value is error
    confirmation.assert_not_called()


@pytest.mark.parametrize("answer", [False, True])
def test_reader_interrupt_confirmation(entry, monkeypatch, answer):
    """Only reader interruption enters legacy confirmation handling."""
    monkeypatch.setattr(input_tool, "input_one_line", Mock(side_effect=KeyboardInterrupt))
    confirmation = Mock(return_value=answer)
    monkeypatch.setattr(input_tool, "input_yes", confirmation)
    if answer:
        with pytest.raises(Exception, match="User Quit"):
            input_tool.input_message()
    else:
        assert input_tool.input_message() == ""
    confirmation.assert_called_once()


def test_no_executor_parameter():
    """Hook insertion leaves the native public input signature unchanged."""
    with pytest.raises(TypeError, match="hook_executor"):
        input_tool.input_message(hook_executor=Mock())
