"""
Unit tests for AgentRun hard-interrupt checkpoints.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-04
Purpose: Verify interrupt flag detection and streaming throttling
"""

from unittest.mock import patch

import pytest

from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.exception import HardInterruptError


def test_check_hard_interrupt_raises_and_removes_flag(tmp_path):
    """A hard-interrupt flag stops execution and is consumed."""
    flag_path = tmp_path / "session.123.session.agent2llm_interrupt.flag"
    flag_path.write_text("1")
    agent = AgentRun.__new__(AgentRun)

    with patch("topsailai.ai_base.agent_base.env_tool.get_session_id", return_value="session"), \
            patch("topsailai.ai_base.agent_base.os.getpid", return_value=123), \
            patch("topsailai.workspace.folder_constants.FOLDER_WORKSPACE_TASK", str(tmp_path)):
        with pytest.raises(HardInterruptError):
            agent._check_hard_interrupt()

    assert not flag_path.exists()


def test_check_hard_interrupt_without_flag_is_noop(tmp_path):
    """No flag leaves execution unchanged."""
    agent = AgentRun.__new__(AgentRun)

    with patch("topsailai.ai_base.agent_base.env_tool.get_session_id", return_value="session"), \
            patch("topsailai.ai_base.agent_base.os.getpid", return_value=123), \
            patch("topsailai.workspace.folder_constants.FOLDER_WORKSPACE_TASK", str(tmp_path)):
        assert agent._check_hard_interrupt() is None


def test_stream_interrupt_check_is_throttled(tmp_path):
    """Streaming checks inspect the flag only at the configured interval."""
    agent = AgentRun.__new__(AgentRun)
    agent._stream_chunk_counter = 0
    agent.STREAM_INTERRUPT_CHECK_INTERVAL = 2

    with patch.object(agent, "_get_interrupt_flag_path", return_value=str(tmp_path / "missing.flag")) as get_path:
        agent._check_hard_interrupt(throttle_stream=True)
        get_path.assert_not_called()
        agent._check_hard_interrupt(throttle_stream=True)
        get_path.assert_called_once_with()
