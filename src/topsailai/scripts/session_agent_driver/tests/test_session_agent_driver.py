"""
Unit tests for the Session Agent Driver.

These tests exercise the pure logic of the driver (status checks, prompt
rendering, message formatting, plugin tool structure, exit flag, and the
inject_input failure mechanism) without starting a real agent or LLM.

Run with:
    python -m pytest tests/test_session_agent_driver.py --color=no
"""

import os
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import session_agent_driver as sad  # noqa: E402
from plugins.tools import exit_process  # noqa: E402
from plugins.tools.inject_input import inject_input  # noqa: E402
from ai_base.agent_types.exception import AgentEndProcess  # noqa: E402


def _record(session_id="s1", pid=100, ctime=1000.0, pipe_open=False):
    """Build a fake log-file record dict."""
    return {
        "filename": f"{session_id}.{pid}.session.stdout",
        "path": f"/tmp/task/{session_id}.{pid}.session.stdout",
        "session_id": session_id,
        "is_task": False,
        "pid": pid,
        "size": 10,
        "mtime": ctime,
        "ctime": ctime,
    }


# ---------------------------------------------------------------------------
# check_session_status
# ---------------------------------------------------------------------------

class TestCheckSessionStatus:
    def test_idle_when_no_records(self):
        with mock.patch.object(sad, "discover_log_files", return_value=[]):
            assert sad.check_session_status("s1") == "idle"

    def test_idle_when_pid_dead(self):
        records = [_record(pid=100)]
        with mock.patch.object(sad, "discover_log_files", return_value=records), \
                mock.patch.object(sad, "_is_pid_alive", return_value=False):
            assert sad.check_session_status("s1") == "idle"

    def test_running_when_pipe_closed(self):
        records = [_record(pid=100, pipe_open=False)]
        with mock.patch.object(sad, "discover_log_files", return_value=records), \
                mock.patch.object(sad, "_is_pid_alive", return_value=True), \
                mock.patch.object(sad, "is_session_pipe_open", return_value=False):
            assert sad.check_session_status("s1") == "running"

    def test_input_when_pipe_open(self):
        records = [_record(pid=100, pipe_open=True)]
        with mock.patch.object(sad, "discover_log_files", return_value=records), \
                mock.patch.object(sad, "_is_pid_alive", return_value=True), \
                mock.patch.object(sad, "is_session_pipe_open", return_value=True):
            assert sad.check_session_status("s1") == "input"

    def test_selects_newest_alive_pid(self):
        # Two records for the same session: old dead pid and new alive pid.
        records = [
            _record(pid=100, ctime=1000.0),
            _record(pid=200, ctime=2000.0),
        ]
        with mock.patch.object(sad, "discover_log_files", return_value=records), \
                mock.patch.object(sad, "_is_pid_alive", side_effect=lambda pid: pid == 200), \
                mock.patch.object(sad, "is_session_pipe_open", return_value=True):
            assert sad.check_session_status("s1") == "input"

    def test_observes_living_task_records(self):
        records = [_record(pid=100)]
        records[0]["is_task"] = True
        with mock.patch.object(sad, "discover_log_files", return_value=records), \
                mock.patch.object(sad, "_is_pid_alive", return_value=True), \
                mock.patch.object(sad, "is_session_pipe_open", return_value=False):
            assert sad.check_session_status("s1") == "running"


# ---------------------------------------------------------------------------
# _is_pid_alive
# ---------------------------------------------------------------------------

class TestIsPidAlive:
    def test_invalid_pid(self):
        assert sad._is_pid_alive(None) is False
        assert sad._is_pid_alive(0) is False
        assert sad._is_pid_alive(-1) is False

    def test_alive(self):
        with mock.patch("os.kill", return_value=None):
            assert sad._is_pid_alive(123) is True

    def test_dead(self):
        with mock.patch("os.kill", side_effect=ProcessLookupError):
            assert sad._is_pid_alive(123) is False

    def test_permission_denied_treated_alive(self):
        with mock.patch("os.kill", side_effect=PermissionError):
            assert sad._is_pid_alive(123) is True


# ---------------------------------------------------------------------------
# format_messages_summary
# ---------------------------------------------------------------------------

class TestFormatMessagesSummary:
    def test_empty(self):
        assert sad.format_messages_summary([]) == "(no messages)"

    def test_basic(self):
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        summary = sad.format_messages_summary(messages)
        assert "[user] hello" in summary
        assert "[assistant] hi" in summary

    def test_truncates_long_content(self):
        messages = [{"role": "user", "content": "x" * 1000}]
        summary = sad.format_messages_summary(messages)
        assert len(summary) < 600

    def test_limits_items(self):
        messages = [{"role": "user", "content": f"m{i}"} for i in range(100)]
        summary = sad.format_messages_summary(messages)
        assert summary.count("[user]") == sad.MESSAGES_SUMMARY_MAX_ITEMS


# ---------------------------------------------------------------------------
# render_analysis_prompt
# ---------------------------------------------------------------------------

class TestRenderAnalysisPrompt:
    def test_renders_placeholders(self):
        info = {
            "session_id": "s1", "pid": 123, "status": "input",
            "project_workspace": "/w", "created_at": "2026",
            "task_goal": "goal", "messages_summary": "msgs", "log_tail": "log",
        }
        prompt = sad.render_analysis_prompt(info)
        assert "s1" in prompt
        assert "123" in prompt
        assert "input" in prompt
        assert "goal" in prompt
        assert "msgs" in prompt
        assert "log" in prompt

    def test_missing_template_falls_back_to_default(self):
        info = {
            "session_id": "s1", "pid": 123, "status": "input",
            "project_workspace": "/w", "created_at": "2026",
            "task_goal": "goal", "messages_summary": "msgs", "log_tail": "log",
        }
        with mock.patch.object(sad, "PROMPT_TEMPLATE_FILE", Path("/nonexistent/prompt.md")):
            prompt = sad.render_analysis_prompt(info)
            assert "s1" in prompt
            assert "goal" in prompt
            assert "log" in prompt

    def test_safe_substitute_keeps_unknown_placeholder(self):
        info = {"session_id": "s1"}
        prompt = sad.render_analysis_prompt(info)
        # Unknown placeholders are kept as-is instead of raising.
        assert "$task_goal" in prompt or "task_goal" in prompt

    def test_prompt_states_core_goal(self):
        info = {
            "session_id": "s1", "pid": 123, "status": "input",
            "project_workspace": "/w", "created_at": "2026",
            "task_goal": "goal", "messages_summary": "msgs", "log_tail": "log",
        }
        prompt = sad.render_analysis_prompt(info)
        assert "Core Goal" in prompt
        assert "replace the human operator" in prompt
        assert '"correct" decision' in prompt

    def test_default_prompt_states_core_goal(self):
        assert "Core Goal" in sad.DEFAULT_PROMPT
        assert "replace the human operator" in sad.DEFAULT_PROMPT


# ---------------------------------------------------------------------------
# _read_int_env
# ---------------------------------------------------------------------------

class TestReadIntEnv:
    def test_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            assert sad._read_int_env("TOPSAILAI_SESSION_DRIVER_POLL_INTERVAL", 5) == 5

    def test_valid(self):
        with mock.patch.dict(os.environ, {"TOPSAILAI_SESSION_DRIVER_POLL_INTERVAL": "7"}, clear=False):
            assert sad._read_int_env("TOPSAILAI_SESSION_DRIVER_POLL_INTERVAL", 5) == 7

    def test_invalid(self):
        with mock.patch.dict(os.environ, {"TOPSAILAI_SESSION_DRIVER_POLL_INTERVAL": "abc"}, clear=False):
            assert sad._read_int_env("TOPSAILAI_SESSION_DRIVER_POLL_INTERVAL", 5) == 5


# ---------------------------------------------------------------------------
# get_session_info
# ---------------------------------------------------------------------------

class TestGetSessionInfo:
    def test_none_when_no_living_process(self):
        with mock.patch.object(sad, "_session_snapshot", return_value=([], "idle")):
            assert sad.get_session_info("s1") is None

    def test_returns_info(self):
        record = dict(_record(pid=100, ctime=1000.0), status="input")
        with mock.patch.object(sad, "_session_snapshot", return_value=([record], "input")), \
                mock.patch.object(sad, "check_session_status", return_value="input"), \
                mock.patch.object(sad, "resolve_log_target", return_value=mock.Mock()), \
                mock.patch.object(sad, "read_log_tail", return_value=mock.Mock(lines=("line1", "line2"))), \
                mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=mock.Mock(
                    retrieve_messages=mock.Mock(return_value=[{"role": "user", "content": "hi"}])
                )):
            info = sad.get_session_info("s1")
            assert info["session_id"] == "s1"
            assert info["pid"] == 100
            assert info["status"] == "input"
            assert "line1" in info["log_tail"]
            assert "[user] hi" in info["messages_summary"]

    def test_log_failure_does_not_break(self):
        record = dict(_record(pid=100), status="input")
        with mock.patch.object(sad, "_session_snapshot", return_value=([record], "input")), \
                mock.patch.object(sad, "check_session_status", return_value="input"), \
                mock.patch.object(sad, "resolve_log_target", side_effect=RuntimeError("boom")), \
                mock.patch.object(sad.ctx_manager, "get_session_manager", side_effect=RuntimeError("db down")):
            info = sad.get_session_info("s1")
            assert info is not None
            assert "unavailable" in info["log_tail"]
            assert "unavailable" in info["messages_summary"]


# ---------------------------------------------------------------------------
# Plugin tools structure
# ---------------------------------------------------------------------------

class TestPluginToolsStructure:
    def test_inject_input_tools(self):
        from plugins.tools import inject_input as mod
        assert "inject_input" in mod.TOOLS
        assert callable(mod.TOOLS["inject_input"])
        assert "inject_input" in mod.TOOLS_INFO
        info = mod.TOOLS_INFO["inject_input"]
        assert info["type"] == "function"
        assert info["function"]["name"] == "inject_input"
        assert "session_id" in info["function"]["parameters"]["properties"]
        assert "content" in info["function"]["parameters"]["properties"]
        assert info["function"]["parameters"]["required"] == ["session_id", "content"]

    def test_exit_process_tools(self):
        from plugins.tools import exit_process as mod
        assert "exit_process" in mod.TOOLS
        assert callable(mod.TOOLS["exit_process"])
        assert "exit_process" in mod.TOOLS_INFO
        info = mod.TOOLS_INFO["exit_process"]
        assert info["function"]["name"] == "exit_process"

    def test_tools_loaded_into_global_registry(self):
        from topsailai.tools.base.common import TOOLS, TOOLS_INFO
        assert "inject_input-inject_input" in TOOLS
        assert "exit_process-exit_process" in TOOLS
        assert "inject_input-inject_input" in TOOLS_INFO
        assert "exit_process-exit_process" in TOOLS_INFO


# ---------------------------------------------------------------------------
# inject_input failure mechanism (AgentEndProcess)
# ---------------------------------------------------------------------------

class TestInjectInputFailure:
    def test_raises_agent_end_process_on_failure(self):
        with mock.patch(
            "plugins.tools.inject_input.execute_runtime_request",
            return_value=mock.Mock(ok=False, error_code="target_not_found", message="no target"),
        ):
            with pytest.raises(AgentEndProcess):
                inject_input("s1", "hello")

    def test_raises_agent_end_process_on_exception(self):
        with mock.patch(
            "plugins.tools.inject_input.execute_runtime_request",
            side_effect=RuntimeError("transport down"),
        ):
            with pytest.raises(AgentEndProcess):
                inject_input("s1", "hello")

    def test_returns_confirmation_on_success(self):
        with mock.patch(
            "plugins.tools.inject_input.execute_runtime_request",
            return_value=mock.Mock(ok=True, error_code=None, message=""),
        ):
            result = inject_input("s1", "hello")
            assert "s1" in result

    def test_invalid_args_raise_agent_end_process(self):
        with pytest.raises(AgentEndProcess):
            inject_input("", "hello")
        with pytest.raises(AgentEndProcess):
            inject_input("s1", "   ")


# ---------------------------------------------------------------------------
# exit_process flag
# ---------------------------------------------------------------------------

class TestExitProcessFlag:
    def setup_method(self):
        exit_process.reset_exit_flag()

    def test_flag_lifecycle(self):
        assert exit_process.is_exit_requested() is False
        result = exit_process.exit_process()
        assert result == "exit requested"
        assert exit_process.is_exit_requested() is True
        exit_process.reset_exit_flag()
        assert exit_process.is_exit_requested() is False

    def test_flag_is_threading_event(self):
        assert isinstance(exit_process._EXIT_EVENT, threading.Event)


# ---------------------------------------------------------------------------
# main argument parsing
# ---------------------------------------------------------------------------

class TestMainArgs:
    def test_requires_session_id(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            # Remove any session env var for this test.
            saved = os.environ.pop("TOPSAILAI_SESSION_ID", None)
            try:
                assert sad.main([]) == 2
            finally:
                if saved is not None:
                    os.environ["TOPSAILAI_SESSION_ID"] = saved

    def test_session_from_env(self):
        with mock.patch.dict(os.environ, {"TOPSAILAI_SESSION_ID": "s1"}, clear=False), \
                mock.patch.object(sad, "check_session_status", return_value="idle"), \
                mock.patch.object(sad.exit_process, "reset_exit_flag"), \
                mock.patch.object(sad.exit_process, "is_exit_requested", return_value=False):
            assert sad.main([]) == 0
