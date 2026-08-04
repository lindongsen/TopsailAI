"""
Unit tests for AgentChat outer-loop interrupt state.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-04
Purpose: Verify interrupt state clearing before a resumed turn
"""

from types import SimpleNamespace
from unittest.mock import patch

from topsailai.workspace.agent.agent_shell_base import AgentChat


def test_clear_interrupt_state_resets_state_and_removes_flag(tmp_path):
    """Resuming after an interrupt clears both memory and the marker file."""
    flag_path = tmp_path / "session.123.session.agent2llm_interrupt.flag"
    flag_path.write_text("1")
    chat = AgentChat.__new__(AgentChat)
    chat.interrupted = True
    chat.ctx_rt_aiagent = SimpleNamespace(ctx_runtime_data=SimpleNamespace(session_id="session"))

    with patch("topsailai.workspace.agent.agent_shell_base.os.getpid", return_value=123), \
            patch("topsailai.workspace.folder_constants.FOLDER_WORKSPACE_TASK", str(tmp_path)):
        chat._clear_interrupt_state()

    assert chat.interrupted is False
    assert not flag_path.exists()


def test_clear_interrupt_state_without_session_only_resets_memory():
    """Missing session identity does not prevent state reset."""
    chat = AgentChat.__new__(AgentChat)
    chat.interrupted = True
    chat.ctx_rt_aiagent = SimpleNamespace(ctx_runtime_data=SimpleNamespace(session_id=None))

    with patch("topsailai.workspace.agent.agent_shell_base.env_tool.get_session_id", return_value=None):
        chat._clear_interrupt_state()

    assert chat.interrupted is False
