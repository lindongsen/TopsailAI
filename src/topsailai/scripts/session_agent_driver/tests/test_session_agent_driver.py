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



class TestAnalysisSessionId:
    """Analysis sessions use the driver's short, filename-safe identifier."""

    def test_format(self):
        analysis_session_id = sad.ANALYSIS_SESSION_PREFIX + sad.uuid.uuid4().hex[:12]
        assert sad.ANALYSIS_SESSION_PREFIX == "sad-"
        assert len(analysis_session_id) == 16
        assert analysis_session_id.startswith("sad-")
        assert all(character in "0123456789abcdef" for character in analysis_session_id[4:])

    def test_generated_ids_are_distinct(self):
        first = sad.ANALYSIS_SESSION_PREFIX + sad.uuid.uuid4().hex[:12]
        second = sad.ANALYSIS_SESSION_PREFIX + sad.uuid.uuid4().hex[:12]
        assert first != second

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


@pytest.mark.parametrize(
    "content, expected",
    [("first\nsecond", "first;second"), ("first\r\nsecond", "first;second"), ("first\rsecond", "first;second")],
)
def test_inject_input_normalizes_newlines(monkeypatch, content, expected):
    """Runtime-request delivery receives semicolon-separated input."""
    transport = mock.Mock(return_value=mock.Mock(ok=True, error_code=None, message=""))
    monkeypatch.setattr("plugins.tools.inject_input.execute_runtime_request", transport)
    assert "s1" in inject_input("s1", content)
    request = transport.call_args.args[0]
    assert request.message == expected


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

    def test_main_applies_session_workspace_at_startup(self):
        """The driver process must carry the target workspace from startup."""
        manager = mock.Mock()
        manager.list_sessions.return_value = [mock.Mock(project_workspace="/project/real")]
        with mock.patch.dict(os.environ, {"TOPSAILAI_SESSION_ID": "s1"}, clear=False), \
                mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=manager), \
                mock.patch.object(sad, "check_session_status", return_value="idle"), \
                mock.patch.object(sad.exit_process, "reset_exit_flag"), \
                mock.patch.object(sad.exit_process, "is_exit_requested", return_value=False), \
                mock.patch("topsailai.tools.skill_tool.reload"):
            os.environ.pop(sad.PROJECT_WORKSPACE_ENV, None)
            assert sad.main([]) == 0
            # The startup value is restored on exit, so the process is clean.
            assert sad.PROJECT_WORKSPACE_ENV not in os.environ


# ---------------------------------------------------------------------------
# project workspace resolution and analysis session cleanup
# ---------------------------------------------------------------------------

class TestResolveProjectWorkspace:
    """The target session's stored workspace takes precedence over the environment."""

    def test_stored_workspace_wins(self):
        stored = mock.Mock(project_workspace="/project/real")
        manager = mock.Mock()
        manager.list_sessions.return_value = [stored]
        with mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=manager), \
                mock.patch.dict(os.environ, {"TOPSAILAI_PROJECT_WORKSPACE": "/driver/cwd"}):
            assert sad.resolve_project_workspace("s1") == "/project/real"
        manager.list_sessions.assert_called_once_with(sessions=["s1"], limit=1)

    def test_environment_fallback_when_record_missing(self):
        manager = mock.Mock()
        manager.list_sessions.return_value = []
        with mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=manager), \
                mock.patch.dict(os.environ, {"TOPSAILAI_PROJECT_WORKSPACE": "/driver/cwd"}):
            assert sad.resolve_project_workspace("s1") == "/driver/cwd"

    def test_environment_fallback_when_stored_value_empty(self):
        stored = mock.Mock(project_workspace=None)
        manager = mock.Mock()
        manager.list_sessions.return_value = [stored]
        with mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=manager), \
                mock.patch.dict(os.environ, {"TOPSAILAI_PROJECT_WORKSPACE": "/driver/cwd"}):
            assert sad.resolve_project_workspace("s1") == "/driver/cwd"

    def test_environment_fallback_when_store_raises(self):
        manager = mock.Mock()
        manager.list_sessions.side_effect = RuntimeError("store unavailable")
        with mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=manager), \
                mock.patch.dict(os.environ, {"TOPSAILAI_PROJECT_WORKSPACE": "/driver/cwd"}):
            assert sad.resolve_project_workspace("s1") == "/driver/cwd"

    def test_empty_string_when_no_authority(self):
        with mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=None), \
                mock.patch.dict(os.environ, {}, clear=False):
            saved = os.environ.pop("TOPSAILAI_PROJECT_WORKSPACE", None)
            try:
                assert sad.resolve_project_workspace("s1") == ""
            finally:
                if saved is not None:
                    os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = saved


class TestApplyProjectWorkspace:
    """The analysis agent must run in the target session's project workspace."""

    @staticmethod
    def _manager(workspace):
        """Build a session manager returning one stored workspace."""
        manager = mock.Mock()
        manager.list_sessions.return_value = [mock.Mock(project_workspace=workspace)]
        return manager

    def test_stored_workspace_is_exported(self):
        """Export the stored workspace and its alias to the process environment."""
        with mock.patch.object(sad.ctx_manager, "get_session_manager",
                               return_value=self._manager("/project/real")), \
                mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch("topsailai.tools.skill_tool.reload") as reload:
            os.environ.pop(sad.PROJECT_WORKSPACE_ENV, None)
            os.environ.pop(sad.PROJECT_FOLDER_ENV, None)
            previous = sad.apply_project_workspace("s1")
            assert os.environ[sad.PROJECT_WORKSPACE_ENV] == "/project/real"
            assert os.environ[sad.PROJECT_FOLDER_ENV] == "/project/real"
            reload.assert_called_once_with()
            assert previous == {sad.PROJECT_WORKSPACE_ENV: None, sad.PROJECT_FOLDER_ENV: None}

    def test_empty_stored_workspace_falls_back_to_pwd(self):
        """An empty stored value falls back to the framework startup directory."""
        with mock.patch.object(sad.ctx_manager, "get_session_manager",
                               return_value=self._manager(None)), \
                mock.patch.dict(os.environ, {sad.PWD_ENV: "/startup/dir"}, clear=False), \
                mock.patch("topsailai.tools.skill_tool.reload"):
            os.environ.pop(sad.PROJECT_WORKSPACE_ENV, None)
            sad.apply_project_workspace("s1")
            assert os.environ[sad.PROJECT_WORKSPACE_ENV] == "/startup/dir"

    def test_missing_pwd_falls_back_to_cwd(self):
        """Without a stored value or TOPSAILAI_PWD the current directory is used."""
        with mock.patch.object(sad.ctx_manager, "get_session_manager",
                               return_value=self._manager("")), \
                mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch("topsailai.tools.skill_tool.reload"):
            os.environ.pop(sad.PWD_ENV, None)
            os.environ.pop(sad.PROJECT_WORKSPACE_ENV, None)
            sad.apply_project_workspace("s1")
            assert os.environ[sad.PROJECT_WORKSPACE_ENV] == os.getcwd()

    def test_reload_is_skipped_when_value_is_unchanged(self):
        """An unchanged workspace must not rescan the skill folders."""
        with mock.patch.object(sad.ctx_manager, "get_session_manager",
                               return_value=self._manager("/project/real")), \
                mock.patch.dict(os.environ, {sad.PROJECT_WORKSPACE_ENV: "/project/real"},
                                clear=False), \
                mock.patch("topsailai.tools.skill_tool.reload") as reload:
            sad.apply_project_workspace("s1")
            reload.assert_not_called()

    def test_reload_failure_does_not_abort_the_run(self):
        """A broken skill reload only warns; the workspace stays applied."""
        with mock.patch.object(sad.ctx_manager, "get_session_manager",
                               return_value=self._manager("/project/real")), \
                mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch("topsailai.tools.skill_tool.reload",
                           side_effect=RuntimeError("scan failed")), \
                mock.patch.object(sad.logger, "warning") as warning:
            os.environ.pop(sad.PROJECT_WORKSPACE_ENV, None)
            sad.apply_project_workspace("s1")
            assert os.environ[sad.PROJECT_WORKSPACE_ENV] == "/project/real"
            assert "failed to reload skill prompt" in warning.call_args[0][0]

    def test_restore_removes_variables_that_were_unset(self):
        """Restoring must not leave a workspace behind for the next run."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(sad.PROJECT_WORKSPACE_ENV, None)
            os.environ.pop(sad.PROJECT_FOLDER_ENV, None)
            sad.restore_project_workspace({sad.PROJECT_WORKSPACE_ENV: None,
                                           sad.PROJECT_FOLDER_ENV: None})
            assert sad.PROJECT_WORKSPACE_ENV not in os.environ
            assert sad.PROJECT_FOLDER_ENV not in os.environ

    def test_restore_returns_previous_values(self):
        """Restoring must put back the values captured before the run."""
        with mock.patch.dict(os.environ, {sad.PROJECT_WORKSPACE_ENV: "/before"},
                             clear=False):
            sad.restore_project_workspace({sad.PROJECT_WORKSPACE_ENV: "/before"})
            assert os.environ[sad.PROJECT_WORKSPACE_ENV] == "/before"


class TestAnalysisRunAppliesWorkspace:
    """The analysis lifecycle exports the workspace and always restores it."""

    @pytest.mark.parametrize("failure", [None, "factory", "run"])
    def test_workspace_is_applied_and_restored(self, failure):
        """Apply before the agent is built and restore on every exit path."""
        observed = {}

        def run(**kwargs):
            """Record the workspace visible to the running agent."""
            observed["run"] = os.environ.get(sad.PROJECT_WORKSPACE_ENV)
            if failure == "run":
                raise RuntimeError("run failed")

        def factory(**kwargs):
            """Record the workspace visible when the agent is constructed."""
            observed["factory"] = os.environ.get(sad.PROJECT_WORKSPACE_ENV)
            if failure == "factory":
                raise RuntimeError("factory failed")
            return mock.Mock(run=run)

        manager = mock.Mock()
        manager.list_sessions.return_value = [mock.Mock(project_workspace="/project/real")]
        with mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=manager), \
                mock.patch.object(sad, "check_session_status", return_value="input"), \
                mock.patch.object(sad, "get_session_info", return_value={"status": "input"}), \
                mock.patch.object(sad, "render_analysis_prompt", return_value="prompt"), \
                mock.patch.object(sad, "get_agent_chat", side_effect=factory), \
                mock.patch.object(sad, "cleanup_analysis_session"), \
                mock.patch("topsailai.tools.skill_tool.reload"), \
                mock.patch.dict(os.environ, {sad.PROJECT_WORKSPACE_ENV: "/before"}, clear=False), \
                mock.patch.object(sad.signal, "signal"), \
                mock.patch.object(sad.signal, "alarm"):
            sad.run_analysis_agent("target")
            assert os.environ[sad.PROJECT_WORKSPACE_ENV] == "/before"
        assert observed.get("factory") == "/project/real"
        if failure != "factory":
            assert observed.get("run") == "/project/real"


class TestCleanupAnalysisSession:
    """Cleanup reports the real outcome instead of assuming success."""

    def test_reports_success_only_when_deleted(self):
        manager = mock.Mock()
        manager.exists_session.return_value = True
        manager.delete_session.return_value = True
        with mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=manager), \
                mock.patch.object(sad.logger, "info") as info:
            sad.cleanup_analysis_session("s1")
        manager.delete_session.assert_called_once_with("s1")
        assert info.call_args[0][0] == "cleaned analysis session %s"
        assert info.call_args[0][1] == "s1"

    def test_warns_when_deletion_not_authorized(self):
        manager = mock.Mock()
        manager.exists_session.return_value = True
        manager.delete_session.return_value = False
        with mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=manager), \
                mock.patch.object(sad.logger, "warning") as warning, \
                mock.patch.object(sad.logger, "info") as info:
            sad.cleanup_analysis_session("s1")
        assert not any("cleaned analysis session" in call[0][0] for call in info.call_args_list)
        assert "retained" in warning.call_args[0][0]


    def test_distinguishes_unavailable_manager_from_absent_session(self):
        with mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=None), \
                mock.patch.object(sad.logger, "warning") as warning:
            sad.cleanup_analysis_session("s1")
        warning_message = warning.call_args[0][0]
        assert "session manager unavailable" in warning_message
        assert "already absent" not in warning_message

        manager = mock.Mock()
        manager.exists_session.return_value = False
        with mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=manager), \
                mock.patch.object(sad.logger, "info") as info:
            sad.cleanup_analysis_session("s1")
        info_message = info.call_args[0][0]
        assert info_message == "analysis session %s already absent"
        assert "already absent" in info_message
        manager.delete_session.assert_not_called()

    def test_absent_session_is_not_deleted(self):
        manager = mock.Mock()
        manager.exists_session.return_value = False
        with mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=manager), \
                mock.patch.object(sad.logger, "info"):
            sad.cleanup_analysis_session("s1")
        manager.delete_session.assert_not_called()

    def test_store_failure_is_logged_not_raised(self):
        manager = mock.Mock()
        manager.exists_session.side_effect = RuntimeError("store unavailable")
        with mock.patch.object(sad.ctx_manager, "get_session_manager", return_value=manager), \
                mock.patch.object(sad.logger, "warning") as warning:
            sad.cleanup_analysis_session("s1")
        assert "failed to clean analysis session" in warning.call_args[0][0]
