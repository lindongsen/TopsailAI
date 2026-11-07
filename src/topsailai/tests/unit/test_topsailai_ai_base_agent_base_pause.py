"""
Unit tests for AgentRun pause-request checkpoints.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-07
Purpose: Verify pause marker consumption, depth guard, interrupt priority and
         fail-open behaviour of the agent-loop pause checkpoint
"""

import json
from unittest.mock import patch

import pytest

from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.exception import HardInterruptError


def _agent():
    """Build an AgentRun without running the heavy constructor."""
    return AgentRun.__new__(AgentRun)


def _patch_paths(tmp_path):
    """Patch session identity so marker paths resolve inside *tmp_path*."""
    return (
        patch(
            "topsailai.ai_base.agent_base.env_tool.get_session_id",
            return_value="session",
        ),
        patch("topsailai.ai_base.agent_base.os.getpid", return_value=123),
        patch(
            "topsailai.workspace.folder_constants.FOLDER_WORKSPACE_TASK",
            str(tmp_path),
        ),
    )


def _write_marker(tmp_path, payload):
    """Write a pause marker for the patched session identity."""
    marker = tmp_path / "session.123.session.agent2llm_pause.flag"
    marker.write_text(json.dumps(payload), encoding="utf-8")
    return marker


def test_check_pause_request_without_marker_is_noop(tmp_path):
    """No marker means the checkpoint never prompts."""
    agent = _agent()
    session_patch, pid_patch, folder_patch = _patch_paths(tmp_path)

    with session_patch, pid_patch, folder_patch, \
            patch(
                "topsailai.ai_base.agent_base.get_thread_var",
                return_value=1,
            ), \
            patch(
                "topsailai.utils.input_tool.input_yes_or_no_with_timeout",
            ) as prompt:
        assert agent._check_pause_request() is None
        prompt.assert_not_called()


def test_check_pause_request_consumes_marker_exactly_once(tmp_path):
    """The marker is deleted before prompting, so a repeat cannot re-prompt."""
    agent = _agent()
    marker = _write_marker(tmp_path, {"prompt": "Resume? "})
    session_patch, pid_patch, folder_patch = _patch_paths(tmp_path)

    with session_patch, pid_patch, folder_patch, \
            patch(
                "topsailai.ai_base.agent_base.get_thread_var",
                return_value=1,
            ), \
            patch(
                "topsailai.utils.thread_local_tool.get_agent_runtime_input_with_timeout",
                return_value=None,
            ), \
            patch(
                "topsailai.utils.input_tool.input_yes_or_no_with_timeout",
                return_value=True,
            ) as prompt:
        agent._check_pause_request()
        assert prompt.call_count == 1
        assert not marker.exists()

        agent._check_pause_request()
        assert prompt.call_count == 1


def test_check_pause_request_skips_nested_agents(tmp_path):
    """Only the outermost agent consumes the marker."""
    agent = _agent()
    marker = _write_marker(tmp_path, {})
    session_patch, pid_patch, folder_patch = _patch_paths(tmp_path)

    with session_patch, pid_patch, folder_patch, \
            patch(
                "topsailai.ai_base.agent_base.get_thread_var",
                return_value=2,
            ), \
            patch(
                "topsailai.utils.input_tool.input_yes_or_no_with_timeout",
            ) as prompt:
        agent._check_pause_request()
        prompt.assert_not_called()
        assert marker.exists()


def test_check_pause_request_answer_no_raises_hard_interrupt(tmp_path):
    """A no answer terminates the loop through the hard-interrupt path."""
    agent = _agent()
    marker = _write_marker(tmp_path, {})
    session_patch, pid_patch, folder_patch = _patch_paths(tmp_path)

    with session_patch, pid_patch, folder_patch, \
            patch(
                "topsailai.ai_base.agent_base.get_thread_var",
                return_value=1,
            ), \
            patch(
                "topsailai.utils.thread_local_tool.get_agent_runtime_input_with_timeout",
                return_value=None,
            ), \
            patch(
                "topsailai.utils.input_tool.input_yes_or_no_with_timeout",
                return_value=False,
            ):
        with pytest.raises(HardInterruptError):
            agent._check_pause_request()
        assert not marker.exists()


def test_check_pause_request_answer_yes_resumes(tmp_path):
    """A yes answer lets the loop continue without raising."""
    agent = _agent()
    _write_marker(tmp_path, {})
    session_patch, pid_patch, folder_patch = _patch_paths(tmp_path)

    with session_patch, pid_patch, folder_patch, \
            patch(
                "topsailai.ai_base.agent_base.get_thread_var",
                return_value=1,
            ), \
            patch(
                "topsailai.utils.thread_local_tool.get_agent_runtime_input_with_timeout",
                return_value=None,
            ), \
            patch(
                "topsailai.utils.input_tool.input_yes_or_no_with_timeout",
                return_value=True,
            ):
        assert agent._check_pause_request() is None


def test_check_pause_request_passes_payload_prompt_and_default(tmp_path):
    """Marker prompt, timeout and default reach the generic input helper."""
    agent = _agent()
    _write_marker(
        tmp_path,
        {"prompt": "Resume? ", "timeout_seconds": 30, "default": "interrupt"},
    )
    session_patch, pid_patch, folder_patch = _patch_paths(tmp_path)

    with session_patch, pid_patch, folder_patch, \
            patch(
                "topsailai.ai_base.agent_base.get_thread_var",
                return_value=1,
            ), \
            patch(
                "topsailai.utils.thread_local_tool.get_agent_runtime_input_with_timeout",
                return_value=None,
            ), \
            patch(
                "topsailai.utils.input_tool.input_yes_or_no_with_timeout",
                return_value=True,
            ) as prompt:
        agent._check_pause_request()

    args, kwargs = prompt.call_args
    assert args[0] == "Resume? "
    assert kwargs["timeout"] == 30
    assert kwargs["default"] == "no"
    assert kwargs["poll_interval"] == agent.PAUSE_POLL_INTERVAL_SECONDS
    assert kwargs["on_poll"] == agent._check_hard_interrupt


def test_check_pause_request_malformed_marker_uses_defaults(tmp_path):
    """An unreadable marker is still consumed and falls back to defaults."""
    agent = _agent()
    marker = tmp_path / "session.123.session.agent2llm_pause.flag"
    marker.write_text("{not json", encoding="utf-8")
    session_patch, pid_patch, folder_patch = _patch_paths(tmp_path)

    with session_patch, pid_patch, folder_patch, \
            patch(
                "topsailai.ai_base.agent_base.get_thread_var",
                return_value=1,
            ), \
            patch(
                "topsailai.utils.thread_local_tool.get_agent_runtime_input_with_timeout",
                return_value=None,
            ), \
            patch(
                "topsailai.utils.input_tool.input_yes_or_no_with_timeout",
                return_value=True,
            ) as prompt:
        agent._check_pause_request()

    args, kwargs = prompt.call_args
    assert args[0] == agent.DEFAULT_PAUSE_PROMPT
    assert kwargs["timeout"] == 0.0
    assert kwargs["default"] == "yes"
    assert not marker.exists()


def test_check_pause_request_invalid_timeout_type_falls_back_to_wait(tmp_path):
    """A boolean timeout is not a duration and means wait indefinitely."""
    agent = _agent()
    _write_marker(tmp_path, {"timeout_seconds": True})
    session_patch, pid_patch, folder_patch = _patch_paths(tmp_path)

    with session_patch, pid_patch, folder_patch, \
            patch(
                "topsailai.ai_base.agent_base.get_thread_var",
                return_value=1,
            ), \
            patch(
                "topsailai.utils.thread_local_tool.get_agent_runtime_input_with_timeout",
                return_value=None,
            ), \
            patch(
                "topsailai.utils.input_tool.input_yes_or_no_with_timeout",
                return_value=True,
            ) as prompt:
        agent._check_pause_request()

    assert prompt.call_args.kwargs["timeout"] == 0.0


def test_check_pause_request_fails_open_without_input_channel(tmp_path):
    """No TTY and no runtime input applies the default instead of hanging."""
    agent = _agent()
    marker = _write_marker(tmp_path, {})
    session_patch, pid_patch, folder_patch = _patch_paths(tmp_path)

    with session_patch, pid_patch, folder_patch, \
            patch(
                "topsailai.ai_base.agent_base.get_thread_var",
                return_value=1,
            ), \
            patch(
                "topsailai.utils.thread_local_tool.get_agent_runtime_input_with_timeout",
                return_value=None,
            ), \
            patch("topsailai.utils.input_tool._stdin_is_tty", return_value=False):
        assert agent._check_pause_request() is None
        assert not marker.exists()


def test_pause_wait_stays_interruptible_between_slices(tmp_path):
    """A hard interrupt raised between slices aborts the pause wait."""
    agent = _agent()
    _write_marker(tmp_path, {})
    interrupt_flag = tmp_path / "session.123.session.agent2llm_interrupt.flag"
    interrupt_flag.write_text("1", encoding="utf-8")
    session_patch, pid_patch, folder_patch = _patch_paths(tmp_path)

    def _fake_prompt(tips, timeout=None, default="yes", input_func=None,
                     poll_interval=1.0, on_poll=None):
        """Simulate one empty slice followed by the poll callback."""
        on_poll()
        return True

    with session_patch, pid_patch, folder_patch, \
            patch(
                "topsailai.ai_base.agent_base.get_thread_var",
                return_value=1,
            ), \
            patch(
                "topsailai.utils.thread_local_tool.get_agent_runtime_input_with_timeout",
                return_value=None,
            ), \
            patch(
                "topsailai.utils.input_tool.input_yes_or_no_with_timeout",
                side_effect=_fake_prompt,
            ):
        with pytest.raises(HardInterruptError):
            agent._check_pause_request()


def test_hard_interrupt_discards_unconsumed_pause_marker(tmp_path):
    """A hard interrupt wins and removes a pending pause request."""
    agent = _agent()
    pause_marker = _write_marker(tmp_path, {})
    interrupt_flag = tmp_path / "session.123.session.agent2llm_interrupt.flag"
    interrupt_flag.write_text("1", encoding="utf-8")
    session_patch, pid_patch, folder_patch = _patch_paths(tmp_path)

    with session_patch, pid_patch, folder_patch:
        with pytest.raises(HardInterruptError):
            agent._check_hard_interrupt()

    assert not interrupt_flag.exists()
    assert not pause_marker.exists()
