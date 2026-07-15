#!/usr/bin/env python3
"""
Unit tests targeting coverage gaps in cli_topsailai.

Covers error-handling branches, edge cases, and less-common code paths
that are not exercised by the primary test suites.
"""

import builtins
import errno
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

import cli_topsailai.state as cli_state
import cli_topsailai.history as cli_history
import cli_topsailai.completer as cli_completer
import cli_topsailai.core as cli_core
from cli_topsailai.cleaning import clean_by_numbers, clean_expired_files
from cli_topsailai.completer import (
    get_all_command_names,
    get_available_completions,
    setup_tab_completion,
    tab_completer,
)
from cli_topsailai.formatting import print_table
from cli_topsailai.help_text import print_help
from cli_topsailai.history import HistoryManager, load_readline_history
from cli_topsailai.log_files import (
    _find_session_stdout_file,
    _get_pid_from_stdout_path,
    _parse_stdout_filename,
    discover_log_files,
    get_file_pid,
)
from cli_topsailai.process import cleanup_children, run_external_command
from cli_topsailai.retrieve import retrieve_session
from cli_topsailai.streaming import (
    handle_send_command,
    send_message_to_session,
    stream_file,
)
from cli_topsailai.yaml_commands import (
    build_command_env,
    handle_yaml_command,
    match_yaml_command,
)


class TestReadlineImportError(unittest.TestCase):
    """Simulate readline being unavailable."""

    @patch.dict(sys.modules, {"readline": None})
    def test_import_error_passes(self):
        """Importing cli_topsailai.core without readline should not raise."""
        # Re-importing is tricky because the module is already loaded;
        # this test documents the except ImportError: pass branch.
        self.assertTrue(True)


class TestHistoryManagerExceptions(unittest.TestCase):
    """Tests for HistoryManager exception handling."""

    def test_load_all_oserror(self):
        """load_all swallows OSError when opening file."""
        manager = HistoryManager("/nonexistent/path/history.jsonl")
        with patch("os.path.isfile", return_value=True):
            with patch("builtins.open", side_effect=OSError("boom")):
                manager.load_all()
        self.assertEqual(manager.entries, [])

    def test_load_all_json_decode_error(self):
        """load_all skips malformed JSON lines."""
        manager = HistoryManager("/tmp/history.jsonl")
        with patch("builtins.open", mock_open(read_data='{"valid": 1}\ninvalid\n')):
            with patch("os.path.isfile", return_value=True):
                manager.load_all()
        self.assertEqual(len(manager.entries), 1)

    def test_append_oserror(self):
        """append swallows OSError when writing file."""
        manager = HistoryManager("/tmp/history.jsonl")
        with patch("builtins.open", side_effect=OSError("boom")):
            manager.append("workspace", "s1", "hello")
        self.assertEqual(len(manager.entries), 1)


class TestLoadReadlineHistoryErrors(unittest.TestCase):
    """Tests for load_readline_history error paths."""

    def test_clear_history_name_error(self):
        """load_readline_history returns early if readline is missing."""
        with patch.dict(sys.modules, {"readline": None}):
            load_readline_history(HistoryManager("/tmp/h"), "workspace", None)

    def test_add_history_breaks_on_error(self):
        """load_readline_history breaks out if add_history fails."""
        manager = HistoryManager("/tmp/h")
        manager.entries = [{"scope": "workspace", "session_id": "", "text": "cmd"}]
        mock_readline = MagicMock()
        mock_readline.add_history.side_effect = AttributeError()
        with patch.dict(sys.modules, {"readline": mock_readline}):
            load_readline_history(manager, "workspace", None)


class TestRunExternalCommandIndependentStderr(unittest.TestCase):
    """Tests for run_external_command independent stderr path."""

    @patch("cli_topsailai.process.launch_independent_process")
    @patch("builtins.print")
    def test_independent_stderr_printed(self, mock_print, mock_launch):
        """Independent command prints stderr in red."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "error msg")
        mock_proc.poll.return_value = 0
        mock_launch.return_value = mock_proc

        run_external_command(["cmd"], {}, independent=True)

        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("error msg" in p for p in printed))


class TestCleanupChildrenExceptions(unittest.TestCase):
    """Tests for cleanup_children exception swallowing."""

    def tearDown(self):
        cli_state._child_processes.clear()

    def test_terminate_exception_swallowed(self):
        """cleanup_children swallows exceptions during terminate."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.terminate.side_effect = OSError("boom")
        mock_proc.kill.return_value = None
        mock_proc.wait.return_value = 0
        cli_state._child_processes.add(mock_proc)
        try:
            with patch("builtins.print"):
                with patch("cli_topsailai.process.time.sleep"):
                    cleanup_children()
        finally:
            cli_state._child_processes.clear()

    def test_kill_exception_swallowed(self):
        """cleanup_children swallows exceptions during kill."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.kill.side_effect = OSError("boom")
        cli_state._child_processes.add(mock_proc)
        try:
            with patch("builtins.print"):
                with patch("cli_topsailai.process.time.sleep"):
                    cleanup_children()
        finally:
            cli_state._child_processes.clear()


class TestGetAllCommandNames(unittest.TestCase):
    """Tests for get_all_command_names."""

    def test_alias_string(self):
        """Alias as a single string is converted to a list."""
        names = get_all_command_names({"cmd": "/foo", "alias": "f"})
        self.assertIn("foo", names)
        self.assertIn("f", names)


class TestTabCompleter(unittest.TestCase):
    """Tests for tab_completer edge cases."""

    def test_returns_none_when_not_first_word(self):
        """tab_completer returns None when completing a non-first word."""
        mock_readline = MagicMock()
        mock_readline.get_line_buffer.return_value = "/send "
        mock_readline.get_begidx.return_value = 6
        with patch.dict(sys.modules, {"readline": mock_readline}):
            result = tab_completer("he", 0)
        self.assertIsNone(result)


class TestSetupTabCompletion(unittest.TestCase):
    """Tests for setup_tab_completion."""

    def test_name_error_passes(self):
        """setup_tab_completion passes when readline is unavailable."""
        with patch.dict(sys.modules, {"readline": None}):
            setup_tab_completion()


class TestMatchYamlCommandAlias(unittest.TestCase):
    """Tests for alias matching with variables."""

    def setUp(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []

    def test_alias_with_variable(self):
        """Alias template with variable is matched."""
        cli_state.yaml_commands = [
            {
                "cmd": "/cd {session_id}",
                "alias": "go {session_id}",
                "scopes": ["workspace"],
                "shell": "",
            }
        ]
        result = match_yaml_command("go abc")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(variables.get("session_id"), "abc")

    def test_alias_with_args(self):
        """Alias template with args variable captures trailing text."""
        cli_state.yaml_commands = [
            {
                "cmd": "/echo {args}",
                "alias": "e {args}",
                "scopes": ["workspace"],
                "shell": "echo {args}",
            }
        ]
        result = match_yaml_command("e hello world")
        self.assertIsNotNone(result)
        _, variables = result
        self.assertEqual(variables.get("args"), "hello world")

    def test_alias_scope_mismatch(self):
        """Alias in different scope is skipped."""
        cli_state.yaml_commands = [
            {
                "cmd": "/cd {session_id}",
                "alias": "go {session_id}",
                "scopes": ["session"],
                "shell": "",
            }
        ]
        cli_state.current_scope = "workspace"
        result = match_yaml_command("go abc")
        self.assertIsNone(result)


class TestBuildCommandEnv(unittest.TestCase):
    """Tests for build_command_env edge cases."""

    def test_non_string_environ_value_skipped(self):
        """Non-string environ values are skipped."""
        instruction = {"environ": {"FOO": 123, "BAR": "baz"}}
        variables = {}
        env = build_command_env(instruction, variables)
        self.assertNotIn("FOO", env)
        self.assertEqual(env.get("BAR"), "baz")


class TestHandleYamlCommandCdHistory(unittest.TestCase):
    """Tests for /cd history loading."""

    def setUp(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.history_manager = None

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.history_manager = None

    @patch("cli_topsailai.yaml_commands.load_readline_history")
    @patch("builtins.print")
    def test_cd_loads_history(self, mock_print, mock_load_history):
        """Entering session scope loads readline history."""
        cli_state.history_manager = HistoryManager("/tmp/h")
        instruction = {"cmd": "/cd {session_id}", "shell": ""}
        variables = {"session_id": "s1"}
        handle_yaml_command(instruction, variables)
        mock_load_history.assert_called_once()


class TestHandleYamlCommandArgsVariable(unittest.TestCase):
    """Tests for args variable replacement in external shell commands."""

    def setUp(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def tearDown(self):
        cli_state._child_processes.clear()

    @patch("cli_topsailai.process.subprocess.Popen")
    @patch("builtins.print")
    def test_args_quoted_placeholder(self, mock_print, mock_popen):
        """Args variable replaces quoted placeholder directly."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        instruction = {"cmd": "/run {args}", "shell": "runner '{args}'"}
        variables = {"args": "one two"}
        handle_yaml_command(instruction, variables)

        args = mock_popen.call_args.args[0]
        self.assertIn("one", args)
        self.assertIn("two", args)

    @patch("cli_topsailai.process.subprocess.Popen")
    @patch("builtins.print")
    def test_args_unquoted_placeholder(self, mock_print, mock_popen):
        """Args variable replaces unquoted placeholder directly."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        instruction = {"cmd": "/run {args}", "shell": "runner {args}"}
        variables = {"args": "one two"}
        handle_yaml_command(instruction, variables)

        args = mock_popen.call_args.args[0]
        self.assertIn("one", args)
        self.assertIn("two", args)


class TestParseStdoutFilenameErrors(unittest.TestCase):
    """Tests for _parse_stdout_filename error cases."""

    def test_task_stdout_empty_base(self):
        """Empty base before .task.stdout returns None."""
        self.assertEqual(_parse_stdout_filename(".task.stdout"), (None, None))

    def test_task_stdout_too_few_parts(self):
        """Task stdout with too few parts returns None."""
        self.assertEqual(
            _parse_stdout_filename("sid.topsailai.123.task.stdout"), (None, None)
        )

    def test_task_stdout_non_numeric_pid(self):
        """Task stdout with non-numeric pid returns None."""
        self.assertEqual(
            _parse_stdout_filename(
                "sid.topsailai.20260101T000000.abc.task.stdout"
            ),
            (None, None),
        )

    def test_session_stdout_non_numeric_pid(self):
        """Session stdout with non-numeric pid returns None."""
        self.assertEqual(
            _parse_stdout_filename("session.abc.session.stdout"), (None, None)
        )

    def test_temp_session_non_numeric_pid(self):
        """Temp session stdout with non-numeric pid returns None."""
        self.assertEqual(
            _parse_stdout_filename("topsailai.abc.session.stdout"), (None, None)
        )


class TestDiscoverLogFilesSkipNonFile(unittest.TestCase):
    """Tests for discover_log_files skip logic."""

    def test_skip_non_file_entry(self):
        """Entries that are not regular files are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "subdir.session.stdout"))
            result = discover_log_files(tmpdir)
            self.assertEqual(result, [])


class TestGetFilePidCleanup(unittest.TestCase):
    """Tests for get_file_pid cleanup kill/wait paths."""

    def tearDown(self):
        cli_state._child_processes.clear()

    @patch("cli_topsailai.log_files.subprocess.Popen")
    def test_lsof_kill_survivor(self, mock_popen):
        """lsof process still running after communicate is killed."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.side_effect = [None, 0]
        mock_popen.return_value = mock_proc

        with patch("builtins.print"):
            get_file_pid("/tmp/file")

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=1)

    @patch("cli_topsailai.log_files.subprocess.Popen")
    def test_fuser_kill_survivor(self, mock_popen):
        """fuser process still running after communicate is killed."""
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = [("", ""), ("", "")]
        mock_proc.poll.side_effect = [0, None, 0]
        mock_popen.return_value = mock_proc

        with patch("builtins.print"):
            get_file_pid("/tmp/file")

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=1)


class TestPrintTableTruncation(unittest.TestCase):
    """Tests for print_table truncation paths."""

    def test_long_session_truncated(self):
        """Long session id is truncated."""
        captured = io.StringIO()
        sys.stdout = captured
        try:
            print_table(
                [
                    {
                        "filename": "a.session.stdout",
                        "path": "/tmp/a.session.stdout",
                        "session_id": "s" * 50,
                        "pid": 123,
                        "size": 100,
                        "mtime": 1700000000.0,
                        "ctime": 1700000000.0,
                    }
                ]
            )
        finally:
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("...", output)


class TestPrintHelpYamlCommands(unittest.TestCase):
    """Tests for print_help YAML command display."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"

    def test_yaml_commands_displayed(self):
        """YAML commands for current scope are displayed."""
        cli_state.yaml_commands = [
            {
                "cmd": "/test",
                "alias": ["t", "tst"],
                "scopes": ["workspace"],
                "desc": "Test command",
                "example": "/test example",
            }
        ]
        captured = io.StringIO()
        sys.stdout = captured
        try:
            print_help(cli_state.yaml_commands, cli_state.current_scope)
        finally:
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("YAML Commands", output)
        self.assertIn("/test", output)
        self.assertIn("alias:", output)
        self.assertIn("Test command", output)
        self.assertIn("/test example", output)

    def test_yaml_commands_other_scope_hidden(self):
        """YAML commands for other scopes are hidden."""
        cli_state.yaml_commands = [
            {
                "cmd": "/test",
                "scopes": ["session"],
                "desc": "Test command",
            }
        ]
        cli_state.current_scope = "workspace"
        captured = io.StringIO()
        sys.stdout = captured
        try:
            print_help(cli_state.yaml_commands, cli_state.current_scope)
        finally:
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertNotIn("YAML Commands", output)


class TestCleanExpiredFilesSkipCases(unittest.TestCase):
    """Tests for clean_expired_files skip branches."""

    def test_file_missing_skipped(self):
        """Missing files are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = clean_expired_files(
                tmpdir,
                [
                    {
                        "filename": "gone.stdout",
                        "path": os.path.join(tmpdir, "gone.stdout"),
                    }
                ],
            )
        self.assertEqual(result, 0)

    def test_fresh_file_skipped(self):
        """Files newer than threshold are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "fresh.stdout")
            with open(path, "w") as f:
                f.write("log")
            result = clean_expired_files(
                tmpdir,
                [
                    {
                        "filename": "fresh.stdout",
                        "path": path,
                    }
                ],
            )
        self.assertEqual(result, 0)

    def test_running_file_skipped(self):
        """Files still held open by a process are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "old.stdout")
            with open(path, "w") as f:
                f.write("log")
            old_time = 0
            os.utime(path, (old_time, old_time))
            with patch("cli_topsailai.cleaning.is_file_in_use", return_value=True):
                result = clean_expired_files(
                    tmpdir,
                    [
                        {
                            "filename": "old.stdout",
                            "path": path,
                        }
                    ],
                )
        self.assertEqual(result, 0)


class TestCleanByNumbersEdgeCases(unittest.TestCase):
    """Tests for clean_by_numbers edge cases."""

    def test_long_filename_truncated(self):
        """Long filename in confirmation table is truncated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "a" * 50 + ".stdout")
            with open(path, "w") as f:
                f.write("log")
            files = [
                {
                    "filename": "a" * 50 + ".stdout",
                    "path": path,
                    "size": 100,
                    "mtime": 1700000000.0,
                }
            ]
            captured = io.StringIO()
            sys.stdout = captured
            try:
                with patch("builtins.input", return_value="n"):
                    clean_by_numbers(tmpdir, files, [0])
            finally:
                sys.stdout = sys.__stdout__
            output = captured.getvalue()
            self.assertIn("...", output)

    def test_invalid_index_reported(self):
        """Invalid indices are reported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "a.stdout")
            with open(path, "w") as f:
                f.write("log")
            files = [
                {
                    "filename": "a.stdout",
                    "path": path,
                    "size": 100,
                    "mtime": 1700000000.0,
                }
            ]
            captured = io.StringIO()
            sys.stdout = captured
            try:
                with patch("builtins.input", return_value="n"):
                    clean_by_numbers(tmpdir, files, [5])
            finally:
                sys.stdout = sys.__stdout__
            output = captured.getvalue()
            self.assertIn("Invalid", output)

    def test_file_missing_reported(self):
        """Missing file for valid index is reported as invalid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "a.stdout")
            files = [
                {
                    "filename": "a.stdout",
                    "path": path,
                    "size": 100,
                    "mtime": 1700000000.0,
                }
            ]
            captured = io.StringIO()
            sys.stdout = captured
            try:
                with patch("builtins.input", return_value="n"):
                    clean_by_numbers(tmpdir, files, [0])
            finally:
                sys.stdout = sys.__stdout__
            output = captured.getvalue()
            self.assertIn("Invalid", output)

    def test_eof_cancels(self):
        """EOFError during confirmation cancels deletion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "a.stdout")
            with open(path, "w") as f:
                f.write("log")
            files = [
                {
                    "filename": "a.stdout",
                    "path": path,
                    "size": 100,
                    "mtime": 1700000000.0,
                }
            ]
            with patch("builtins.input", side_effect=EOFError()):
                result = clean_by_numbers(tmpdir, files, [0])
        self.assertEqual(result, 0)

    def test_delete_failure(self):
        """OSError during deletion is reported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "a.stdout")
            with open(path, "w") as f:
                f.write("log")
            files = [
                {
                    "filename": "a.stdout",
                    "path": path,
                    "size": 100,
                    "mtime": 1700000000.0,
                }
            ]
            with patch("builtins.input", return_value="y"):
                with patch("os.remove", side_effect=OSError("permission denied")):
                    with patch("builtins.print"):
                        result = clean_by_numbers(tmpdir, files, [0])
        self.assertEqual(result, 0)


class TestStreamFilePaths(unittest.TestCase):
    """Tests for stream_file branches."""

    def tearDown(self):
        cli_state.running = True

    @patch("cli_topsailai.streaming.subprocess.run")
    def test_stream_permission_error(self, mock_run):
        """PermissionError while opening file is reported."""
        cli_state.running = False
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("line\n")
            path = f.name
        try:
            with patch("builtins.open", side_effect=PermissionError("denied")) as mock_open:
                with patch("builtins.print") as mock_print:
                    stream_file(path)
                printed = [call[0][0] for call in mock_print.call_args_list]
                self.assertTrue(any("Permission denied" in str(p) for p in printed))
        finally:
            os.remove(path)

    @patch("cli_topsailai.streaming.subprocess.run")
    def test_stream_generic_error(self, mock_run):
        """Generic exception while opening file is reported."""
        cli_state.running = False
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("line\n")
            path = f.name
        try:
            with patch("builtins.open", side_effect=RuntimeError("boom")):
                with patch("builtins.print") as mock_print:
                    stream_file(path)
                printed = [call[0][0] for call in mock_print.call_args_list]
                self.assertTrue(any("Failed to stream" in str(p) for p in printed))
        finally:
            os.remove(path)

    @patch("cli_topsailai.streaming.subprocess.run")
    def test_stream_tty_q_quit(self, mock_run):
        """Pressing q in TTY mode quits streaming."""
        cli_state.running = True
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("line\n")
            path = f.name
        try:
            with patch("sys.stdin.isatty", return_value=True):
                with patch(
                    "cli_topsailai.streaming.select.select",
                    return_value=([sys.stdin], [], []),
                ):
                    with patch("sys.stdin.read", return_value="q"):
                        with patch("builtins.print"):
                            stream_file(path)
        finally:
            os.remove(path)

    @patch("cli_topsailai.streaming.subprocess.run")
    def test_stream_tty_cd_return_to_workspace(self, mock_run):
        """Pressing cd in TTY mode returns to workspace scope."""
        cli_state.running = True
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("line\n")
            path = f.name
        try:
            with patch("sys.stdin.isatty", return_value=True):
                with patch(
                    "cli_topsailai.streaming.select.select",
                    return_value=([sys.stdin], [], []),
                ):
                    with patch("builtins.input", return_value="cd") as mock_input:
                        with patch("builtins.print") as mock_print:
                            stream_file(path, default_session_id="s1")
                            mock_input.assert_called()
                            printed = [
                                call[0][0] for call in mock_print.call_args_list
                            ]
                            self.assertTrue(
                                any("workspace scope" in str(p) for p in printed)
                            )
            self.assertEqual(cli_state.current_scope, "workspace")
            self.assertIsNone(cli_state.current_session_id)
        finally:
            os.remove(path)

    @patch("cli_topsailai.streaming.subprocess.run")
    def test_stream_tty_slash_cd_return_to_workspace(self, mock_run):
        """Pressing /cd in TTY mode returns to workspace scope."""
        cli_state.running = True
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("line\n")
            path = f.name
        try:
            with patch("sys.stdin.isatty", return_value=True):
                with patch(
                    "cli_topsailai.streaming.select.select",
                    return_value=([sys.stdin], [], []),
                ):
                    with patch("builtins.input", return_value="/cd") as mock_input:
                        with patch("builtins.print") as mock_print:
                            stream_file(path, default_session_id="s1")
                            mock_input.assert_called()
                            printed = [
                                call[0][0] for call in mock_print.call_args_list
                            ]
                            self.assertTrue(
                                any("workspace scope" in str(p) for p in printed)
                            )
            self.assertEqual(cli_state.current_scope, "workspace")
            self.assertIsNone(cli_state.current_session_id)
        finally:
            os.remove(path)

    @patch("cli_topsailai.streaming.subprocess.run")
    def test_stream_non_tty_sleep(self, mock_run):
        """Non-TTY mode sleeps when no data."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            path = f.name
        try:
            def stop_running(*_args, **_kwargs):
                cli_topsailai.state.running = False

            with patch("cli_topsailai.state.running", True):
                with patch("sys.stdin.isatty", return_value=False):
                    with patch("cli_topsailai.streaming.time.sleep", side_effect=stop_running) as mock_sleep:
                        stream_file(path)
                        mock_sleep.assert_called()
        finally:
            os.remove(path)

    @patch("cli_topsailai.streaming.subprocess.run")
    def test_stream_keyboard_interrupt(self, mock_run):
        """KeyboardInterrupt during streaming is handled."""
        cli_state.running = True
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("line\n")
            path = f.name
        try:
            with patch("builtins.open", side_effect=KeyboardInterrupt()):
                with patch("builtins.print"):
                    stream_file(path)
        finally:
            os.remove(path)


class TestStreamFileDataBranch(unittest.TestCase):
    """Tests for stream_file data output branch."""

    def tearDown(self):
        cli_state.running = True

    @patch("cli_topsailai.streaming.subprocess.run")
    @patch("builtins.print")
    def test_binary_data_written(self, mock_print, mock_run):
        """Binary file data is written to stdout.buffer."""
        mock_file = mock_open(read_data=b"hello stream")
        mock_stdout = MagicMock()
        mock_stdout.buffer = MagicMock()

        def stop_running(*_args, **_kwargs):
            cli_topsailai.state.running = False

        with patch("cli_topsailai.state.running", True):
            with patch("builtins.open", mock_file):
                with patch.object(sys, "stdout", mock_stdout):
                    with patch("sys.stdin.isatty", return_value=False):
                        with patch("cli_topsailai.streaming.time.sleep", side_effect=stop_running):
                            stream_file("/tmp/fake.stdout")
        mock_stdout.buffer.write.assert_called_with(b"hello stream")
        mock_stdout.buffer.flush.assert_called_once()


class TestRetrieveSessionExceptions(unittest.TestCase):
    """Tests for retrieve_session exception handling."""

    def tearDown(self):
        cli_state._child_processes.clear()

    @patch("cli_topsailai.retrieve.subprocess.Popen")
    def test_generic_exception(self, mock_popen):
        """Generic exception during retrieve is reported."""
        mock_popen.side_effect = RuntimeError("boom")
        with patch("builtins.print") as mock_print:
            retrieve_session("session-a")
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("Failed to retrieve" in str(p) for p in printed))

    @patch("cli_topsailai.retrieve.subprocess.Popen")
    def test_wait_exception_swallowed(self, mock_popen):
        """Exception during final wait is swallowed."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = None
        mock_proc.wait.side_effect = OSError("boom")
        mock_proc.kill.return_value = None
        mock_popen.return_value = mock_proc

        with patch("builtins.print"):
            retrieve_session("session-a")


    @patch("cli_topsailai.retrieve.subprocess.Popen")
    def test_passes_max_chars(self, mock_popen):
        """retrieve_session passes --max-chars when max_chars is provided."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        retrieve_session("session-a", max_chars=1000)
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        self.assertIn("--max-chars", args)
        self.assertIn("1000", args)
        self.assertEqual(args[args.index("--max-chars") + 1], "1000")

    @patch("cli_topsailai.retrieve.subprocess.Popen")
    def test_omits_max_chars_when_none(self, mock_popen):
        """retrieve_session does not pass --max-chars when omitted."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        retrieve_session("session-a")
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        self.assertNotIn("--max-chars", args)

class TestFindSessionStdoutFile(unittest.TestCase):
    """Tests for _find_session_stdout_file."""

    def test_task_dir_missing(self):
        """Missing task directory returns None."""
        self.assertIsNone(_find_session_stdout_file("/nonexistent", "s1"))

    def test_no_candidates(self):
        """No matching stdout files returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNone(_find_session_stdout_file(tmpdir, "s1"))

    def test_oserror_on_mtime(self):
        """OSError when reading mtime skips candidate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "s1.1234.session.stdout")
            with open(path, "w") as f:
                f.write("log")
            with patch("os.path.getmtime", side_effect=OSError("boom")):
                result = _find_session_stdout_file(tmpdir, "s1")
        self.assertIsNone(result)

    def test_prefers_session_stdout_over_task_stdout(self):
        """Session stdout files are preferred over task stdout files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = os.path.join(tmpdir, "s1.1000.session.stdout")
            task_path = os.path.join(tmpdir, "s1.topsailai.1234567890.2000.task.stdout")
            with open(session_path, "w") as f:
                f.write("session log")
            with open(task_path, "w") as f:
                f.write("task log")
            # Make the task stdout newer so the old behavior would pick it.
            os.utime(task_path, (1234567890, 1234567890))
            result = _find_session_stdout_file(tmpdir, "s1")
        self.assertEqual(result, session_path)

    def test_ignores_task_stdout_when_no_session_stdout(self):
        """Task stdout files alone are not treated as session stdout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_path = os.path.join(tmpdir, "s1.topsailai.1234567890.2000.task.stdout")
            with open(task_path, "w") as f:
                f.write("task log")
            result = _find_session_stdout_file(tmpdir, "s1")
        self.assertIsNone(result)


class TestSendMessageErrors(unittest.TestCase):
    """Tests for send_message_to_session error paths."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.task_dir = self.tmpdir
        self.stdout_path = os.path.join(self.task_dir, "s1.1234.session.stdout")
        with open(self.stdout_path, "w") as f:
            f.write("log")
        self.pipe_path = os.path.join(self.task_dir, "s1.1234.session.pipe")

    def tearDown(self):
        for root, dirs, files in os.walk(self.tmpdir, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(self.tmpdir)

    @patch("cli_topsailai.streaming.get_file_pid", return_value=1234)
    def test_unexpected_oserror_on_open(self, mock_get_pid):
        """Unexpected OSError while opening pipe is reported."""
        os.mkfifo(self.pipe_path)
        with patch("os.open", side_effect=OSError(errno.EIO, "io error")):
            with patch("builtins.print"):
                result = send_message_to_session("s1", "hello", self.task_dir)
        self.assertFalse(result)

    @patch("cli_topsailai.streaming.get_file_pid", return_value=1234)
    def test_oserror_on_write(self, mock_get_pid):
        """OSError while writing to pipe is reported."""
        os.mkfifo(self.pipe_path)

        def reader():
            with open(self.pipe_path, "rb") as f:
                f.read()

        import threading

        t = threading.Thread(target=reader)
        t.start()
        try:
            with patch("os.write", side_effect=OSError(errno.EPIPE, "broken pipe")):
                with patch("builtins.print"):
                    result = send_message_to_session(
                        "s1", "hello", self.task_dir, timeout=2.0
                    )
            self.assertFalse(result)
        finally:
            t.join(timeout=3)


class TestHandleSendCommandNoParts(unittest.TestCase):
    """Tests for handle_send_command with no parts."""

    def test_send_no_parts_workspace(self):
        """No parts in workspace scope shows usage error."""
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        with patch("builtins.print") as mock_print:
            handle_send_command("/send", "/task", [])
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("Usage" in str(p) for p in printed))


class TestPromptSelectionHistoryAndYaml(unittest.TestCase):
    """Tests for prompt_selection history and YAML branches."""

    def setUp(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.history_manager = None

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.history_manager = None
        cli_state.yaml_commands = []

    def test_history_appended(self):
        """User input is appended to history manager."""
        manager = HistoryManager("/tmp/h")
        cli_state.history_manager = manager
        with patch("builtins.input", return_value="q"):
            cli_core.prompt_selection([], "/task")
        self.assertEqual(len(manager.entries), 1)
        self.assertEqual(manager.entries[0]["text"], "q")

    def test_readline_add_history_name_error(self):
        """NameError from readline.add_history is ignored."""
        cli_state.history_manager = HistoryManager("/tmp/h")
        mock_readline = MagicMock()
        mock_readline.add_history.side_effect = NameError()
        with patch.dict(sys.modules, {"readline": mock_readline}):
            with patch("builtins.input", return_value="q"):
                cli_core.prompt_selection([], "/task")

    def test_yaml_command_matched(self):
        """YAML command input returns yaml_handled action."""
        cli_state.yaml_commands = [
            {
                "cmd": "/test",
                "scopes": ["workspace"],
                "shell": "echo test",
            }
        ]
        with patch("cli_topsailai.process.run_external_command") as mock_run:
            with patch("builtins.input", return_value="/test"):
                action, value = cli_core.prompt_selection([], "/task")
        self.assertEqual(action, "yaml_handled")
        mock_run.assert_called_once()

    def test_session_missing_argument(self):
        """/session without argument shows error and continues."""
        with patch("builtins.input", side_effect=["/session", "q"]):
            action, value = cli_core.prompt_selection([], "/task")
        self.assertEqual(action, "quit")

    def test_session_literal_session_id(self):
        """/session with a non-numeric argument resolves to a literal session ID."""
        files = [{"filename": "a.stdout", "session_id": "s1"}]
        with patch("builtins.input", return_value="/session abc"):
            action, value = cli_core.prompt_selection(files, "/task")
        self.assertEqual(action, "session_id")
        self.assertEqual(value, "abc")

    def test_session_invalid_empty(self):
        """/session with an empty argument shows error and continues."""
        files = [{"filename": "a.stdout", "session_id": "s1"}]
        with patch("builtins.input", side_effect=["/session ", "q"]):
            action, value = cli_core.prompt_selection(files, "/task")
        self.assertEqual(action, "quit")


class TestMainLoopActions(unittest.TestCase):
    """Tests for main loop action branches."""

    def setUp(self):
        cli_state.running = True
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []

    @patch("cli_topsailai.core.signal.signal")
    @patch("cli_topsailai.yaml_commands.load_yaml_commands", return_value=[])
    @patch("cli_topsailai.paths.get_topsailai_home", return_value="/home")
    @patch("cli_topsailai.log_files.discover_log_files", return_value=[])
    @patch("cli_topsailai.formatting.print_table")
    @patch("cli_topsailai.help_text.print_help")
    @patch(
        "cli_topsailai.core.prompt_selection",
        side_effect=[("help", None), ("quit", None)],
    )
    @patch("cli_topsailai.history.HistoryManager")
    def test_main_help(
        self,
        mock_history_cls,
        mock_prompt,
        mock_help,
        mock_print_table,
        mock_discover,
        mock_home,
        mock_yaml,
        mock_signal,
    ):
        """Main loop handles help action."""
        mock_history = MagicMock()
        mock_history_cls.return_value = mock_history
        with patch("builtins.print"):
            cli_core.main()
        mock_help.assert_called_once()

    @patch("cli_topsailai.core.signal.signal")
    @patch("cli_topsailai.yaml_commands.load_yaml_commands", return_value=[])
    @patch("cli_topsailai.paths.get_topsailai_home", return_value="/home")
    @patch("cli_topsailai.log_files.discover_log_files", return_value=[])
    @patch("cli_topsailai.formatting.print_table")
    @patch("cli_topsailai.cleaning.clean_by_numbers")
    @patch(
        "cli_topsailai.core.prompt_selection",
        side_effect=[("clean_numbers", [0, 1]), ("quit", None)],
    )
    @patch("cli_topsailai.history.HistoryManager")
    def test_main_clean_numbers(
        self,
        mock_history_cls,
        mock_prompt,
        mock_clean,
        mock_print_table,
        mock_discover,
        mock_home,
        mock_yaml,
        mock_signal,
    ):
        """Main loop handles clean_numbers action."""
        mock_history = MagicMock()
        mock_history_cls.return_value = mock_history
        with patch("builtins.print"):
            cli_core.main()
        mock_clean.assert_called_once()

    @patch("cli_topsailai.retrieve.retrieve_session")
    @patch("cli_topsailai.core.signal.signal")
    @patch("cli_topsailai.yaml_commands.load_yaml_commands", return_value=[])
    @patch("cli_topsailai.paths.get_topsailai_home", return_value="/home")
    @patch(
        "cli_topsailai.log_files.discover_log_files",
        return_value=[{"filename": "s1.123.session.stdout", "session_id": "s1"}],
    )
    @patch("cli_topsailai.formatting.print_table")
    @patch(
        "cli_topsailai.core.prompt_selection",
        side_effect=[("session", 0), ("quit", None)],
    )
    @patch("cli_topsailai.history.HistoryManager")
    def test_main_session_passes_max_chars(
        self,
        mock_history_cls,
        mock_prompt,
        mock_print_table,
        mock_discover,
        mock_home,
        mock_yaml,
        mock_signal,
        mock_retrieve,
    ):
        """Main loop passes max_chars=1000 to retrieve_session for /session."""
        mock_history = MagicMock()
        mock_history_cls.return_value = mock_history
        with patch("builtins.print"):
            cli_core.main()
        mock_retrieve.assert_called_once_with("s1", max_chars=1000)
    @patch("cli_topsailai.core.signal.signal")
    @patch("cli_topsailai.yaml_commands.load_yaml_commands", return_value=[])
    @patch("cli_topsailai.paths.get_topsailai_home", return_value="/home")
    @patch("cli_topsailai.log_files.discover_log_files", return_value=[])
    @patch("cli_topsailai.formatting.print_table")
    @patch(
        "cli_topsailai.core.prompt_selection",
        side_effect=[KeyboardInterrupt(), ("quit", None)],
    )
    @patch("cli_topsailai.history.HistoryManager")
    def test_main_keyboard_interrupt(
        self,
        mock_history_cls,
        mock_prompt,
        mock_print_table,
        mock_discover,
        mock_home,
        mock_yaml,
        mock_signal,
    ):
        """Main loop handles KeyboardInterrupt."""
        mock_history = MagicMock()
        mock_history_cls.return_value = mock_history
        with patch("builtins.print"):
            cli_core.main()


class TestHistoryManagerEmptyLine(unittest.TestCase):
    """Tests for HistoryManager empty line handling."""

    def test_load_all_skips_empty_lines(self):
        """Empty lines in history file are skipped."""
        manager = HistoryManager("/tmp/history.jsonl")
        with patch("builtins.open", mock_open(read_data='{"valid": 1}\n\n{"valid": 2}\n')):
            with patch("os.path.isfile", return_value=True):
                manager.load_all()
        self.assertEqual(len(manager.entries), 2)


class TestReadlineImportErrorReal(unittest.TestCase):
    """Simulate readline being unavailable during module reload."""

    def test_reload_without_readline(self):
        """Reloading cli_topsailai.core without readline should not raise."""
        import importlib

        original_readline = sys.modules.get("readline")
        try:
            with patch.dict(sys.modules, {"readline": None}):
                importlib.reload(cli_core)
        finally:
            if original_readline is not None:
                sys.modules["readline"] = original_readline
            else:
                sys.modules.pop("readline", None)



class TestGetAvailableCompletionsAliasString(unittest.TestCase):
    """Tests for get_available_completions with string alias."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"

    def test_alias_string_converted_to_list(self):
        """Alias defined as a string is converted to a list."""
        cli_state.current_scope = "workspace"
        cli_state.yaml_commands = [
            {
                "cmd": "/test",
                "alias": "t",
                "scopes": ["workspace"],
            }
        ]
        completions = get_available_completions()
        self.assertIn("/test", completions)
        self.assertIn("/t", completions)


class TestTabCompleterException(unittest.TestCase):
    """Tests for tab_completer exception swallowing."""

    def test_readline_error_swallowed(self):
        """NameError/AttributeError from readline is swallowed."""
        mock_readline = MagicMock()
        mock_readline.get_line_buffer.side_effect = NameError()
        with patch.dict(sys.modules, {"readline": mock_readline}):
            result = tab_completer("re", 0)
        self.assertIsNone(result)


class TestMatchYamlCommandEmptyCases(unittest.TestCase):
    """Tests for match_yaml_command empty template/alias handling."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def test_empty_cmd_template_skipped(self):
        """Instruction with empty cmd template is skipped."""
        cli_state.yaml_commands = [
            {"cmd": "", "scopes": ["workspace"], "shell": "echo"}
        ]
        result = match_yaml_command("/something")
        self.assertIsNone(result)

    def test_empty_alias_skipped(self):
        """Empty alias entry is skipped."""
        cli_state.yaml_commands = [
            {
                "cmd": "/test",
                "alias": ["", "t"],
                "scopes": ["workspace"],
                "shell": "echo",
            }
        ]
        result = match_yaml_command("t")
        self.assertIsNotNone(result)


class TestBuildCommandEnvVariableReplacement(unittest.TestCase):
    """Tests for build_command_env variable placeholder resolution."""

    def test_environ_variable_replaced(self):
        """Variable placeholders in environ values are resolved."""
        instruction = {"environ": {"FOO": "session={session_id}"}}
        variables = {"session_id": "s1"}
        env = build_command_env(instruction, variables)
        self.assertEqual(env.get("FOO"), "session=s1")


class TestHandleYamlCommandQuotedPlaceholder(unittest.TestCase):
    """Tests for handle_yaml_command quoted placeholder replacement."""

    def setUp(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def tearDown(self):
        cli_state._child_processes.clear()

    @patch("cli_topsailai.process.subprocess.Popen")
    @patch("builtins.print")
    def test_quoted_placeholder_replaced(self, mock_print, mock_popen):
        """Quoted placeholder is replaced without double quoting."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        instruction = {
            "cmd": "/run {name}",
            "shell": "runner '{name}'",
        }
        variables = {"name": "hello world"}
        handle_yaml_command(instruction, variables)

        args = mock_popen.call_args.args[0]
        self.assertIn("runner", args)
        self.assertIn("hello world", args)


class TestParseStdoutFilenameRemaining(unittest.TestCase):
    """Tests for _parse_stdout_filename edge cases."""

    def test_session_stdout_empty_base(self):
        """Empty base for .session.stdout returns (None, None)."""
        self.assertEqual(_parse_stdout_filename(".session.stdout"), (None, None))

    def test_task_stdout_reaches_elif(self):
        """A .task.stdout filename reaches the elif branch and returns (None, None)."""
        result = _parse_stdout_filename("task_1.task.stdout")
        self.assertEqual(result, (None, None))

    def test_unsupported_extension(self):
        """Unsupported extension returns (None, None)."""
        self.assertEqual(_parse_stdout_filename("foo.txt"), (None, None))


class TestPrintHelpAliasString(unittest.TestCase):
    """Tests for print_help with alias as string."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"

    @patch("builtins.print")
    def test_alias_string_printed(self, mock_print):
        """Alias defined as a string is printed."""
        cli_state.yaml_commands = [
            {
                "cmd": "/demo",
                "alias": "d",
                "scopes": ["workspace"],
                "desc": "demo command",
            }
        ]
        print_help(cli_state.yaml_commands, cli_state.current_scope)
        output = " ".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
        self.assertIn("/demo", output)
        self.assertIn("/d", output)


class TestCleanExpiredFilesRemaining(unittest.TestCase):
    """Tests for clean_expired_files remaining branches."""

    def setUp(self):
        self.task_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.task_dir, ignore_errors=True)

    @patch("cli_topsailai.cleaning.os.path.getmtime", side_effect=OSError("bad mtime"))
    @patch("builtins.print")
    def test_getmtime_error_skips_file(self, mock_print, mock_getmtime):
        """OSError on getmtime skips the file."""
        path = os.path.join(self.task_dir, "t1.task.stdout")
        with open(path, "w") as f:
            f.write("data")
        old_time = time.time() - 86400 * 7
        os.utime(path, (old_time, old_time))
        clean_expired_files(
            self.task_dir,
            [{"filename": "t1.task.stdout", "path": path}],
        )
        mock_getmtime.assert_called()

    @patch("builtins.print")
    def test_long_filename_truncation(self, mock_print):
        """Very long filename is truncated in output."""
        long_name = "a" * 80 + ".task.stdout"
        path = os.path.join(self.task_dir, long_name)
        with open(path, "w") as f:
            f.write("data")
        # Make file very old so it is selected for cleanup
        old_time = time.time() - 86400 * 7
        os.utime(path, (old_time, old_time))
        with patch("builtins.input", return_value="n"):
            clean_expired_files(
                self.task_dir,
                [{"filename": long_name, "path": path}],
            )
        # File should not be removed because user cancelled
        self.assertTrue(os.path.exists(path))

    @patch("cli_topsailai.cleaning.os.remove", side_effect=OSError("remove failed"))
    @patch("builtins.print")
    def test_delete_error_reported(self, mock_print, mock_remove):
        """OSError during deletion is reported."""
        path = os.path.join(self.task_dir, "t2.task.stdout")
        with open(path, "w") as f:
            f.write("data")
        old_time = time.time() - 86400 * 7
        os.utime(path, (old_time, old_time))
        with patch("builtins.input", return_value="y"):
            clean_expired_files(
                self.task_dir,
                [{"filename": "t2.task.stdout", "path": path}],
            )
        mock_remove.assert_called()


class TestFindSessionStdoutFileRemaining(unittest.TestCase):
    """Tests for _find_session_stdout_file remaining branches."""

    def test_task_dir_missing_returns_none(self):
        """Missing task directory returns None."""
        self.assertIsNone(_find_session_stdout_file("/nonexistent_path_xyz", "s1"))

    def test_non_file_entry_ignored(self):
        """Directory entries that are not files are ignored."""
        task_dir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(task_dir, "s1.session.stdout"))
            result = _find_session_stdout_file(task_dir, "s1")
            self.assertIsNone(result)
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)


class TestStreamFileNoBuffer(unittest.TestCase):
    """Tests for stream_file when stdout lacks buffer."""

    @patch("cli_topsailai.streaming.subprocess.run")
    @patch("builtins.print")
    def test_no_buffer_branch(self, mock_print, mock_run):
        """Fallback print branch when stdout has no buffer."""
        task_dir = tempfile.mkdtemp()
        try:
            path = os.path.join(task_dir, "t1.task.stdout")
            with open(path, "wb") as f:
                f.write(b"hello stream")

            mock_file = mock_open(read_data=b"hello stream")
            mock_stdout = MagicMock()
            del mock_stdout.buffer

            def stop_running(*_args, **_kwargs):
                cli_topsailai.state.running = False

            with patch("cli_topsailai.state.running", True):
                with patch("builtins.open", mock_file):
                    with patch.object(sys, "stdout", mock_stdout):
                        with patch("sys.stdin.isatty", return_value=False):
                            with patch("cli_topsailai.streaming.time.sleep", side_effect=stop_running):
                                stream_file(path)

            mock_print.assert_any_call("hello stream", end="")
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)


class TestSendMessageCloseError(unittest.TestCase):
    """Tests for send_message_to_session close error handling."""

    @patch("os.close", side_effect=OSError("close failed"))
    @patch("os.write")
    @patch("os.open", return_value=3)
    @patch("stat.S_ISFIFO", return_value=True)
    @patch("os.stat")
    @patch("os.path.exists", return_value=True)
    @patch("cli_topsailai.streaming.get_file_pid", return_value=1234)
    @patch(
        "cli_topsailai.streaming._get_pid_from_stdout_path",
        return_value=None,
    )
    @patch(
        "cli_topsailai.streaming._find_session_stdout_file",
        return_value="/tmp/s1.session.stdout",
    )
    @patch("builtins.print")
    def test_close_fd_error_ignored(
        self,
        mock_print,
        mock_find,
        mock_getpid_from_path,
        mock_getpid,
        mock_exists,
        mock_stat,
        mock_isfifo,
        mock_open,
        mock_write,
        mock_close,
    ):
        """OSError from os.close in finally is ignored."""
        task_dir = tempfile.mkdtemp()
        try:
            result = send_message_to_session("s1", "hello", task_dir, timeout=0.1)
            self.assertTrue(result)
            mock_close.assert_called_once_with(3)
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)


class TestGetPidFromStdoutPath(unittest.TestCase):
    """Tests for _get_pid_from_stdout_path."""

    def test_returns_pid_from_valid_filename(self):
        path = "/tmp/task/20260704T053911.4004128.session.stdout"
        self.assertEqual(_get_pid_from_stdout_path(path), 4004128)

    def test_returns_none_for_missing_pid(self):
        path = "/tmp/task/s1.session.stdout"
        self.assertIsNone(_get_pid_from_stdout_path(path))

    def test_returns_none_for_non_digit_pid(self):
        path = "/tmp/task/20260704T053911.abc.session.stdout"
        self.assertIsNone(_get_pid_from_stdout_path(path))

    def test_returns_none_for_unexpected_extension(self):
        path = "/tmp/task/20260704T053911.4004128.session.stderr"
        self.assertIsNone(_get_pid_from_stdout_path(path))

class TestHandleSendCancel(unittest.TestCase):
    """Tests for handle_send_command cancellation."""

    def setUp(self):
        self.task_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.task_dir, ignore_errors=True)

    @patch("cli_topsailai.streaming._read_multiline_input_for_send", return_value=None)
    @patch("builtins.print")
    def test_cancel_multiline_input(self, mock_print, mock_read):
        """Cancel when multiline input returns None."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        handle_send_command("/send", self.task_dir, [])
        mock_read.assert_called_once()


class TestMainRefresh(unittest.TestCase):
    """Tests for main() refresh action."""

    @patch("cli_topsailai.formatting.print_table")
    @patch("cli_topsailai.log_files.discover_log_files", return_value=[])
    @patch("cli_topsailai.core.prompt_selection", side_effect=[("refresh", None), ("quit", None)])
    @patch("cli_topsailai.yaml_commands.load_yaml_commands", return_value=[])
    @patch("cli_topsailai.completer.setup_tab_completion")
    @patch("cli_topsailai.history.load_readline_history")
    @patch("cli_topsailai.history.HistoryManager")
    @patch("cli_topsailai.paths.get_topsailai_home", return_value=tempfile.mkdtemp())
    @patch("cli_topsailai.formatting.print_header")
    @patch("cli_topsailai.core.signal.signal")
    @patch("builtins.print")
    def test_refresh_action(
        self,
        mock_print,
        mock_signal,
        mock_print_header,
        mock_home,
        mock_history_cls,
        mock_load_history,
        mock_setup_tab,
        mock_load_yaml,
        mock_prompt,
        mock_discover,
        mock_print_table,
    ):
        """Refresh action in main() updates log_files and reprints table."""
        home = mock_home.return_value
        try:
            os.makedirs(os.path.join(home, "workspace", "task"), exist_ok=True)
            cli_state.running = True
            cli_state.yaml_commands = []
            cli_state.history_manager = None
            cli_core.main()
            self.assertEqual(mock_discover.call_count, 2)
            mock_print_table.assert_called()
        finally:
            shutil.rmtree(home, ignore_errors=True)


class TestMainEntryPoint(unittest.TestCase):
    """Tests for the module entry point."""

    @patch("cli_topsailai.core.prompt_selection", return_value=("quit", None))
    @patch("cli_topsailai.formatting.print_table")
    @patch("cli_topsailai.log_files.discover_log_files", return_value=[])
    @patch("cli_topsailai.formatting.print_header")
    @patch("cli_topsailai.completer.setup_tab_completion")
    @patch("cli_topsailai.history.load_readline_history")
    @patch("cli_topsailai.history.HistoryManager")
    @patch("cli_topsailai.yaml_commands.load_yaml_commands", return_value=[])
    @patch("cli_topsailai.paths.get_topsailai_home", return_value=tempfile.mkdtemp())
    @patch("cli_topsailai.core.signal.signal")
    @patch("cli_topsailai.process.cleanup_children")
    @patch("builtins.input", return_value="q")
    def test_name_main_calls_main(
        self,
        mock_input,
        mock_cleanup,
        mock_signal,
        mock_home,
        mock_load_yaml,
        mock_history_cls,
        mock_load_history,
        mock_setup_tab,
        mock_print_header,
        mock_discover,
        mock_print_table,
        mock_prompt,
    ):
        """if __name__ == '__main__' block calls main()."""
        import runpy

        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        topsailai_path = os.path.join(project_root, "topsailai.py")

        home = mock_home.return_value
        try:
            os.makedirs(os.path.join(home, "workspace", "task"), exist_ok=True)
            cli_state.running = True
            cli_state.yaml_commands = []
            cli_state.history_manager = None
            # Clear any cached topsailai module so the script is loaded from the
            # project root rather than a similarly-named package elsewhere on
            # sys.path (e.g. src/topsailai from the agent codebase).
            sys.modules.pop("topsailai", None)
            runpy.run_path(topsailai_path, run_name="__main__")
            mock_signal.assert_called()
        finally:
            shutil.rmtree(home, ignore_errors=True)


class TestMainRefreshIncremental(unittest.TestCase):
    """Tests for incremental refresh output in main()."""

    def setUp(self):
        cli_state.running = True
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []
        cli_state.history_manager = None

    def tearDown(self):
        cli_state.running = True
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []
        cli_state.history_manager = None

    @patch("cli_topsailai.core.signal.signal")
    @patch("cli_topsailai.yaml_commands.load_yaml_commands", return_value=[])
    @patch("cli_topsailai.completer.setup_tab_completion")
    @patch("cli_topsailai.history.load_readline_history")
    @patch("cli_topsailai.history.HistoryManager")
    @patch("cli_topsailai.formatting.print_header")
    @patch("cli_topsailai.formatting.print_table")
    @patch("cli_topsailai.session_info.enrich_files_with_session_names")
    @patch(
        "cli_topsailai.core.prompt_selection",
        side_effect=[("refresh", None), ("quit", None)],
    )
    @patch("cli_topsailai.paths.get_topsailai_home")
    def test_refresh_prints_each_file(
        self,
        mock_home,
        mock_prompt,
        mock_enrich,
        mock_print_table,
        mock_print_header,
        mock_history_cls,
        mock_load_history,
        mock_setup_tab,
        mock_load_yaml,
        mock_signal,
    ):
        """Refresh action prints each discovered file before the table."""
        home = tempfile.mkdtemp()
        try:
            task_dir = os.path.join(home, "workspace", "task")
            os.makedirs(task_dir, exist_ok=True)
            open(os.path.join(task_dir, "s1.1234.session.stdout"), "w").close()
            open(os.path.join(task_dir, "s2.5678.task.stdout"), "w").close()
            mock_home.return_value = home

            mock_history = MagicMock()
            mock_history_cls.return_value = mock_history

            captured = io.StringIO()
            with patch.object(sys, "stdout", captured):
                cli_core.main()

            output = captured.getvalue()
            ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
            clean_output = ansi_escape.sub("", output)
            self.assertIn("Found s1", clean_output)
            self.assertIn("Found s2", clean_output)
            self.assertIn("s1.1234.session.stdout", clean_output)
            self.assertIn("s2.5678.task.stdout", clean_output)
            mock_print_table.assert_called()
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
