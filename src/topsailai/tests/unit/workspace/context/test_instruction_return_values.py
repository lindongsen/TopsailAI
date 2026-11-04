"""Verify context instructions return display content without direct output.

Author: DawsonLin
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from topsailai.utils.instruction_tool import HookInstruction
from topsailai.workspace.context.instruction import ContextRuntimeInstructions


def _instructions(messages=None):
    runtime = MagicMock()
    runtime.session_id = "session-1"
    runtime.messages = messages or []
    runtime.ai_agent = None
    return ContextRuntimeInstructions(runtime), runtime


def test_context_history_returns_formatted_content(capsys):
    """Return history text while leaving stdout ownership to the dispatcher."""
    instruction, runtime = _instructions([{"role": "user", "content": "hello"}])

    result = instruction.ctx_history()

    runtime.reset_messages.assert_called_once_with()
    assert "Show history messages session-1" in result
    assert "Role: USER" in result
    assert "hello" in result
    assert capsys.readouterr().out == ""


def test_context_raw_history_returns_formatted_content(monkeypatch, capsys):
    """Return raw persisted history without printing it directly."""
    instruction, _ = _instructions()
    raw = SimpleNamespace(
        msg_id="message-1",
        message='{"role":"assistant","content":"answer"}',
    )
    monkeypatch.setattr(
        "topsailai.workspace.context.instruction.ctx_manager.get_messages_by_session",
        lambda session_id, for_raw: [raw],
    )

    result = instruction.ctx_history2()

    assert "Show raw history messages session-1" in result
    assert "ID: message-1" in result
    assert "answer" in result
    assert capsys.readouterr().out == ""


def test_context_clear_returns_status(capsys):
    """Return mutation status without writing directly to stdout."""
    instruction, runtime = _instructions()
    runtime.session_id = None

    result = instruction.ctx_clear()

    runtime.clear_messages.assert_called_once_with()
    assert result == "Context already is clear"
    assert capsys.readouterr().out == ""


def test_interactive_context_result_is_printed_once(tmp_path, capsys):
    """Print returned context content exactly once through call_hook."""
    instruction, runtime = _instructions([{"role": "user", "content": "hello"}])
    hooks = HookInstruction(
        str(tmp_path / "completions.json"),
        {"/ctx.history": instruction.ctx_history},
    )

    hooks.call_hook("/ctx.history")

    runtime.reset_messages.assert_called_once_with()
    output = capsys.readouterr().out
    assert output.count("Show history messages session-1") == 1
    assert output.count("hello") == 1
