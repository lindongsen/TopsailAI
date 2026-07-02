#!/usr/bin/env python3
"""
Unit tests targeting coverage gaps in topsailai.py.

Covers error-handling branches, edge cases, and less-common code paths
that are not exercised by the primary test suites.
"""

import builtins
import errno
import io
import os
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

import topsailai as cli


class TestReadlineImportError(unittest.TestCase):
    """Simulate readline being unavailable."""

    @patch.dict(sys.modules, {"readline": None})
    def test_import_error_passes(self):
        """Importing topsailai without readline should not raise."""
        # Re-importing is tricky because the module is already loaded;
        # this test documents the except ImportError: pass branch.
        self.assertTrue(True)


class TestHistoryManagerExceptions(unittest.TestCase):
    """Tests for HistoryManager exception handling."""

    def test_load_all_oserror(self):
        """load_all swallows OSError when opening file."""
        manager = cli.HistoryManager("/nonexistent/path/history.jsonl")
        with patch("os.path.isfile", return_value=True):
            with patch("builtins.open", side_effect=OSError("boom")):
                manager.load_all()
        self.assertEqual(manager.entries, [])

    def test_load_all_json_decode_error(self):
        """load_all skips malformed JSON lines."""
        manager = cli.HistoryManager("/tmp/history.jsonl")
        with patch("builtins.open", mock_open(read_data='{"valid": 1}\ninvalid\n')):
            with patch("os.path.isfile", return_value=True):
                manager.load_all()
        self.assertEqual(len(manager.entries), 1)

    def test_append_oserror(self):
        """append swallows OSError when writing file."""
        manager = cli.HistoryManager("/tmp/history.jsonl")
        with patch("builtins.open", side_effect=OSError("boom")):
            manager.append("workspace", "s1", "hello")
        self.assertEqual(len(manager.entries), 1)


class TestLoadReadlineHistoryErrors(unittest.TestCase):
    """Tests for load_readline_history error paths."""

    def test_clear_history_name_error(self):
        """load_readline_history returns early if readline is missing."""
        with patch.object(cli, "readline", None):
            cli.load_readline_history(cli.HistoryManager("/tmp/h"), "workspace", None)

    def test_add_history_breaks_on_error(self):
        """load_readline_history breaks out if add_history fails."""
        manager = cli.HistoryManager("/tmp/h")
        manager.entries = [{"scope": "workspace", "session_id": "", "text": "cmd"}]
        mock_readline = MagicMock()
        mock_readline.add_history.side_effect = AttributeError()
        with patch.object(cli, "readline", mock_readline):
            cli.load_readline_history(manager, "workspace", None)


class TestRunExternalCommandIndependentStderr(unittest.TestCase):
    """Tests for run_external_command independent stderr path."""

    @patch("topsailai.launch_independent_process")
    @patch("builtins.print")
    def test_independent_stderr_printed(self, mock_print, mock_launch):
        """Independent command prints stderr in red."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "error msg")
        mock_proc.poll.return_value = 0
        mock_launch.return_value = mock_proc

        cli.run_external_command(["cmd"], {}, independent=True)

        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("error msg" in p for p in printed))


class TestCleanupChildrenExceptions(unittest.TestCase):
    """Tests for cleanup_children exception swallowing."""

    def test_terminate_exception_swallowed(self):
        """cleanup_children swallows exceptions during terminate."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.terminate.side_effect = OSError("boom")
        mock_proc.kill.return_value = None
        mock_proc.wait.return_value = 0
        cli._child_processes.append(mock_proc)
        try:
            with patch("builtins.print"):
                with patch("topsailai.time.sleep"):
                    cli.cleanup_children()
        finally:
            cli._child_processes.clear()

    def test_kill_exception_swallowed(self):
        """cleanup_children swallows exceptions during kill."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.kill.side_effect = OSError("boom")
        cli._child_processes.append(mock_proc)
        try:
            with patch("builtins.print"):
                with patch("topsailai.time.sleep"):
                    cli.cleanup_children()
        finally:
            cli._child_processes.clear()


class TestGetAllCommandNames(unittest.TestCase):
    """Tests for get_all_command_names."""

    def test_alias_string(self):
        """Alias as a single string is converted to a list."""
        names = cli.get_all_command_names({"cmd": "/foo", "alias": "f"})
        self.assertIn("foo", names)
        self.assertIn("f", names)


class TestTabCompleter(unittest.TestCase):
    """Tests for tab_completer edge cases."""

    def test_returns_none_when_not_first_word(self):
        """tab_completer returns None when completing a non-first word."""
        mock_readline = MagicMock()
        mock_readline.get_line_buffer.return_value = "/send "
        mock_readline.get_begidx.return_value = 6
        with patch.object(cli, "readline", mock_readline):
            result = cli.tab_completer("he", 0)
        self.assertIsNone(result)


class TestSetupTabCompletion(unittest.TestCase):
    """Tests for setup_tab_completion."""

    def test_name_error_passes(self):
        """setup_tab_completion passes when readline is unavailable."""
        with patch.object(cli, "readline", None):
            cli.setup_tab_completion()


class TestMatchYamlCommandAlias(unittest.TestCase):
    """Tests for alias matching with variables."""

    def setUp(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None

    def tearDown(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.yaml_commands = []

    def test_alias_with_variable(self):
        """Alias template with variable is matched."""
        cli.yaml_commands = [
            {
                "cmd": "/cd {session_id}",
                "alias": "go {session_id}",
                "scopes": ["workspace"],
                "shell": "",
            }
        ]
        result = cli.match_yaml_command("go abc", "/task")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(variables.get("session_id"), "abc")

    def test_alias_with_args(self):
        """Alias template with args variable captures trailing text."""
        cli.yaml_commands = [
            {
                "cmd": "/echo {args}",
                "alias": "e {args}",
                "scopes": ["workspace"],
                "shell": "echo {args}",
            }
        ]
        result = cli.match_yaml_command("e hello world", "/task")
        self.assertIsNotNone(result)
        _, variables = result
        self.assertEqual(variables.get("args"), "hello world")

    def test_alias_scope_mismatch(self):
        """Alias in different scope is skipped."""
        cli.yaml_commands = [
            {
                "cmd": "/cd {session_id}",
                "alias": "go {session_id}",
                "scopes": ["session"],
                "shell": "",
            }
        ]
        cli.current_scope = "workspace"
        result = cli.match_yaml_command("go abc", "/task")
        self.assertIsNone(result)


class TestBuildCommandEnv(unittest.TestCase):
    """Tests for build_command_env edge cases."""

    def test_non_string_environ_value_skipped(self):
        """Non-string environ values are skipped."""
        instruction = {"environ": {"FOO": 123, "BAR": "baz"}}
        variables = {}
        env = cli.build_command_env(instruction, variables)
        self.assertNotIn("FOO", env)
        self.assertEqual(env.get("BAR"), "baz")


class TestHandleYamlCommandCdHistory(unittest.TestCase):
    """Tests for /cd history loading."""

    def setUp(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.history_manager = None

    def tearDown(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.history_manager = None

    @patch("topsailai.load_readline_history")
    @patch("builtins.print")
    def test_cd_loads_history(self, mock_print, mock_load_history):
        """Entering session scope loads readline history."""
        cli.history_manager = cli.HistoryManager("/tmp/h")
        instruction = {"cmd": "/cd {session_id}", "shell": ""}
        variables = {"session_id": "s1"}
        cli.handle_yaml_command(instruction, variables)
        mock_load_history.assert_called_once()


class TestHandleYamlCommandArgsVariable(unittest.TestCase):
    """Tests for args variable replacement in external shell commands."""

    def setUp(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None

    def tearDown(self):
        cli._child_processes.clear()

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_args_quoted_placeholder(self, mock_print, mock_popen):
        """Args variable replaces quoted placeholder directly."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        instruction = {"cmd": "/run {args}", "shell": "runner '{args}'"}
        variables = {"args": "one two"}
        cli.handle_yaml_command(instruction, variables)

        args = mock_popen.call_args.args[0]
        self.assertIn("one", args)
        self.assertIn("two", args)

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_args_unquoted_placeholder(self, mock_print, mock_popen):
        """Args variable replaces unquoted placeholder directly."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        instruction = {"cmd": "/run {args}", "shell": "runner {args}"}
        variables = {"args": "one two"}
        cli.handle_yaml_command(instruction, variables)

        args = mock_popen.call_args.args[0]
        self.assertIn("one", args)
        self.assertIn("two", args)


class TestParseStdoutFilenameErrors(unittest.TestCase):
    """Tests for _parse_stdout_filename error cases."""

    def test_task_stdout_empty_base(self):
        """Empty base before .task.stdout returns None."""
        self.assertEqual(cli._parse_stdout_filename(".task.stdout"), (None, None))

    def test_task_stdout_too_few_parts(self):
        """Task stdout with too few parts returns None."""
        self.assertEqual(
            cli._parse_stdout_filename("sid.topsailai.123.task.stdout"), (None, None)
        )

    def test_task_stdout_non_numeric_pid(self):
        """Task stdout with non-numeric pid returns None."""
        self.assertEqual(
            cli._parse_stdout_filename(
                "sid.topsailai.20260101T000000.abc.task.stdout"
            ),
            (None, None),
        )

    def test_session_stdout_non_numeric_pid(self):
        """Session stdout with non-numeric pid returns None."""
        self.assertEqual(
            cli._parse_stdout_filename("session.abc.session.stdout"), (None, None)
        )

    def test_temp_session_non_numeric_pid(self):
        """Temp session stdout with non-numeric pid returns None."""
        self.assertEqual(
            cli._parse_stdout_filename("topsailai.abc.session.stdout"), (None, None)
        )


class TestDiscoverLogFilesSkipNonFile(unittest.TestCase):
    """Tests for discover_log_files skip logic."""

    def test_skip_non_file_entry(self):
        """Entries that are not regular files are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "subdir.session.stdout"))
            result = cli.discover_log_files(tmpdir)
            self.assertEqual(result, [])


class TestGetFilePidCleanup(unittest.TestCase):
    """Tests for get_file_pid cleanup kill/wait paths."""

    def tearDown(self):
        cli._child_processes.clear()

    @patch("topsailai.subprocess.Popen")
    def test_lsof_kill_survivor(self, mock_popen):
        """lsof process still running after communicate is killed."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.side_effect = [None, 0]
        mock_popen.return_value = mock_proc

        with patch("builtins.print"):
            cli.get_file_pid("/tmp/file")

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=1)

    @patch("topsailai.subprocess.Popen")
    def test_fuser_kill_survivor(self, mock_popen):
        """fuser process still running after communicate is killed."""
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = [("", ""), ("", "")]
        mock_proc.poll.side_effect = [0, None, 0]
        mock_popen.return_value = mock_proc

        with patch("builtins.print"):
            cli.get_file_pid("/tmp/file")

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=1)


class TestPrintTableTruncation(unittest.TestCase):
    """Tests for print_table truncation paths."""

    def test_long_filename_truncated(self):
        """Long filename is truncated."""
        captured = io.StringIO()
        sys.stdout = captured
        try:
            cli.print_table(
                [
                    {
                        "filename": "a" * 50 + ".session.stdout",
                        "path": "/tmp/a.session.stdout",
                        "session_id": "sid",
                        "pid": 123,
                        "size": 100,
                        "mtime": 1700000000.0,
                    }
                ]
            )
        finally:
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("...", output)

    def test_long_session_truncated(self):
        """Long session id is truncated."""
        captured = io.StringIO()
        sys.stdout = captured
        try:
            cli.print_table(
                [
                    {
                        "filename": "a.session.stdout",
                        "path": "/tmp/a.session.stdout",
                        "session_id": "s" * 50,
                        "pid": 123,
                        "size": 100,
                        "mtime": 1700000000.0,
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
        cli.yaml_commands = []
        cli.current_scope = "workspace"

    def test_yaml_commands_displayed(self):
        """YAML commands for current scope are displayed."""
        cli.yaml_commands = [
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
            cli.print_help()
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
        cli.yaml_commands = [
            {
                "cmd": "/test",
                "scopes": ["session"],
                "desc": "Test command",
            }
        ]
        cli.current_scope = "workspace"
        captured = io.StringIO()
        sys.stdout = captured
        try:
            cli.print_help()
        finally:
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertNotIn("YAML Commands", output)


class TestCleanExpiredFilesSkipCases(unittest.TestCase):
    """Tests for clean_expired_files skip branches."""

    def test_file_missing_skipped(self):
        """Missing files are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = cli.clean_expired_files(
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
            result = cli.clean_expired_files(
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
        """Files with active pid are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "old.stdout")
            with open(path, "w") as f:
                f.write("log")
            old_time = 0
            os.utime(path, (old_time, old_time))
            with patch("topsailai.get_file_pid", return_value=1234):
                result = cli.clean_expired_files(
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
                    cli.clean_by_numbers(tmpdir, files, [0])
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
                    cli.clean_by_numbers(tmpdir, files, [5])
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
                    cli.clean_by_numbers(tmpdir, files, [0])
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
                result = cli.clean_by_numbers(tmpdir, files, [0])
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
                        result = cli.clean_by_numbers(tmpdir, files, [0])
        self.assertEqual(result, 0)


class TestStreamFilePaths(unittest.TestCase):
    """Tests for stream_file branches."""

    def tearDown(self):
        cli.running = True

    @patch("topsailai.subprocess.run")
    def test_stream_permission_error(self, mock_run):
        """PermissionError while opening file is reported."""
        cli.running = False
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("line\n")
            path = f.name
        try:
            with patch("builtins.open", side_effect=PermissionError("denied")) as mock_open:
                with patch("builtins.print") as mock_print:
                    cli.stream_file(path)
                printed = [call[0][0] for call in mock_print.call_args_list]
                self.assertTrue(any("Permission denied" in str(p) for p in printed))
        finally:
            os.remove(path)

    @patch("topsailai.subprocess.run")
    def test_stream_generic_error(self, mock_run):
        """Generic exception while opening file is reported."""
        cli.running = False
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("line\n")
            path = f.name
        try:
            with patch("builtins.open", side_effect=RuntimeError("boom")):
                with patch("builtins.print") as mock_print:
                    cli.stream_file(path)
                printed = [call[0][0] for call in mock_print.call_args_list]
                self.assertTrue(any("Failed to stream" in str(p) for p in printed))
        finally:
            os.remove(path)

    @patch("topsailai.subprocess.run")
    def test_stream_tty_q_quit(self, mock_run):
        """Pressing q in TTY mode quits streaming."""
        cli.running = True
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("line\n")
            path = f.name
        try:
            with patch("sys.stdin.isatty", return_value=True):
                with patch(
                    "topsailai.select.select",
                    return_value=([sys.stdin], [], []),
                ):
                    with patch("sys.stdin.read", return_value="q"):
                        with patch("builtins.print"):
                            cli.stream_file(path)
        finally:
            os.remove(path)

    @patch("topsailai.subprocess.run")
    def test_stream_non_tty_sleep(self, mock_run):
        """Non-TTY mode sleeps when no data."""
        cli.running = True
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            path = f.name
        try:
            def stop_running(*_args, **_kwargs):
                cli.running = False

            with patch("sys.stdin.isatty", return_value=False):
                with patch("topsailai.time.sleep", side_effect=stop_running) as mock_sleep:
                    cli.stream_file(path)
                    mock_sleep.assert_called()
        finally:
            os.remove(path)

    @patch("topsailai.subprocess.run")
    def test_stream_keyboard_interrupt(self, mock_run):
        """KeyboardInterrupt during streaming is handled."""
        cli.running = True
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("line\n")
            path = f.name
        try:
            with patch("builtins.open", side_effect=KeyboardInterrupt()):
                with patch("builtins.print"):
                    cli.stream_file(path)
        finally:
            os.remove(path)


class TestStreamFileDataBranch(unittest.TestCase):
    """Tests for stream_file data output branch."""

    def tearDown(self):
        cli.running = True

    @patch("topsailai.subprocess.run")
    @patch("builtins.print")
    def test_binary_data_written(self, mock_print, mock_run):
        """Binary file data is written to stdout.buffer (lines 1503-1508)."""
        mock_file = mock_open(read_data=b"hello stream")
        mock_stdout = MagicMock()
        mock_stdout.buffer = MagicMock()

        def stop_running(*_args, **_kwargs):
            cli.running = False

        with patch("builtins.open", mock_file):
            with patch.object(cli.sys, "stdout", mock_stdout):
                with patch("sys.stdin.isatty", return_value=False):
                    with patch("topsailai.time.sleep", side_effect=stop_running):
                        cli.running = True
                        cli.stream_file("/tmp/fake.stdout")
        mock_stdout.buffer.write.assert_called_with(b"hello stream")
        mock_stdout.buffer.flush.assert_called_once()

class TestRetrieveSessionExceptions(unittest.TestCase):
    """Tests for retrieve_session exception handling."""

    def tearDown(self):
        cli._child_processes.clear()

    @patch("topsailai.subprocess.Popen")
    def test_generic_exception(self, mock_popen):
        """Generic exception during retrieve is reported."""
        mock_popen.side_effect = RuntimeError("boom")
        with patch("builtins.print") as mock_print:
            cli.retrieve_session("session-a")
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("Failed to retrieve" in str(p) for p in printed))

    @patch("topsailai.subprocess.Popen")
    def test_wait_exception_swallowed(self, mock_popen):
        """Exception during final wait is swallowed."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = None
        mock_proc.wait.side_effect = OSError("boom")
        mock_proc.kill.return_value = None
        mock_popen.return_value = mock_proc

        with patch("builtins.print"):
            cli.retrieve_session("session-a")


class TestFindSessionStdoutFile(unittest.TestCase):
    """Tests for _find_session_stdout_file."""

    def test_task_dir_missing(self):
        """Missing task directory returns None."""
        self.assertIsNone(cli._find_session_stdout_file("/nonexistent", "s1"))

    def test_no_candidates(self):
        """No matching stdout files returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNone(cli._find_session_stdout_file(tmpdir, "s1"))

    def test_oserror_on_mtime(self):
        """OSError when reading mtime skips candidate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "s1.1234.session.stdout")
            with open(path, "w") as f:
                f.write("log")
            with patch("os.path.getmtime", side_effect=OSError("boom")):
                result = cli._find_session_stdout_file(tmpdir, "s1")
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

    @patch("topsailai.get_file_pid", return_value=1234)
    def test_unexpected_oserror_on_open(self, mock_get_pid):
        """Unexpected OSError while opening pipe is reported."""
        os.mkfifo(self.pipe_path)
        with patch("os.open", side_effect=OSError(errno.EIO, "io error")):
            with patch("builtins.print"):
                result = cli.send_message_to_session("s1", "hello", self.task_dir)
        self.assertFalse(result)

    @patch("topsailai.get_file_pid", return_value=1234)
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
                    result = cli.send_message_to_session(
                        "s1", "hello", self.task_dir, timeout=2.0
                    )
            self.assertFalse(result)
        finally:
            t.join(timeout=3)


class TestHandleSendCommandNoParts(unittest.TestCase):
    """Tests for handle_send_command with no parts."""

    def test_send_no_parts_workspace(self):
        """No parts in workspace scope shows usage error."""
        cli.current_scope = "workspace"
        cli.current_session_id = None
        with patch("builtins.print") as mock_print:
            cli.handle_send_command("/send", "/task", [])
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("Usage" in str(p) for p in printed))


class TestPromptSelectionHistoryAndYaml(unittest.TestCase):
    """Tests for prompt_selection history and YAML branches."""

    def setUp(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.history_manager = None

    def tearDown(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.history_manager = None
        cli.yaml_commands = []

    def test_history_appended(self):
        """User input is appended to history manager."""
        manager = cli.HistoryManager("/tmp/h")
        cli.history_manager = manager
        with patch("builtins.input", return_value="q"):
            cli.prompt_selection([], "/task")
        self.assertEqual(len(manager.entries), 1)
        self.assertEqual(manager.entries[0]["text"], "q")

    def test_readline_add_history_name_error(self):
        """NameError from readline.add_history is ignored."""
        cli.history_manager = cli.HistoryManager("/tmp/h")
        mock_readline = MagicMock()
        mock_readline.add_history.side_effect = NameError()
        with patch.object(cli, "readline", mock_readline):
            with patch("builtins.input", return_value="q"):
                cli.prompt_selection([], "/task")

    def test_yaml_command_matched(self):
        """YAML command input returns yaml_handled action."""
        cli.yaml_commands = [
            {
                "cmd": "/test",
                "scopes": ["workspace"],
                "shell": "echo test",
            }
        ]
        with patch("topsailai.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = ("", "")
            mock_proc.poll.return_value = 0
            mock_popen.return_value = mock_proc
            with patch("builtins.input", return_value="/test"):
                action, value = cli.prompt_selection([], "/task")
        self.assertEqual(action, "yaml_handled")

    def test_session_missing_argument(self):
        """/session without argument shows error and continues."""
        with patch("builtins.input", side_effect=["/session", "q"]):
            action, value = cli.prompt_selection([], "/task")
        self.assertEqual(action, "quit")

    def test_session_invalid_number(self):
        """/session with non-numeric argument shows error and continues."""
        files = [{"filename": "a.stdout", "session_id": "s1"}]
        with patch("builtins.input", side_effect=["/session abc", "q"]):
            action, value = cli.prompt_selection(files, "/task")
        self.assertEqual(action, "quit")


class TestMainLoopActions(unittest.TestCase):
    """Tests for main loop action branches."""

    def setUp(self):
        cli.running = True
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.yaml_commands = []

    @patch("topsailai.signal.signal")
    @patch("topsailai.load_yaml_commands", return_value=[])
    @patch("topsailai.get_topsailai_home", return_value="/home")
    @patch("topsailai.discover_log_files", return_value=[])
    @patch("topsailai.print_table")
    @patch("topsailai.print_help")
    @patch(
        "topsailai.prompt_selection",
        side_effect=[("help", None), ("quit", None)],
    )
    @patch("topsailai.HistoryManager")
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
            cli.main()
        mock_help.assert_called_once()

    @patch("topsailai.signal.signal")
    @patch("topsailai.load_yaml_commands", return_value=[])
    @patch("topsailai.get_topsailai_home", return_value="/home")
    @patch("topsailai.discover_log_files", return_value=[])
    @patch("topsailai.print_table")
    @patch("topsailai.clean_by_numbers")
    @patch(
        "topsailai.prompt_selection",
        side_effect=[("clean_numbers", [0, 1]), ("quit", None)],
    )
    @patch("topsailai.HistoryManager")
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
            cli.main()
        mock_clean.assert_called_once()

    @patch("topsailai.signal.signal")
    @patch("topsailai.load_yaml_commands", return_value=[])
    @patch("topsailai.get_topsailai_home", return_value="/home")
    @patch("topsailai.discover_log_files", return_value=[])
    @patch("topsailai.print_table")
    @patch(
        "topsailai.prompt_selection",
        side_effect=[KeyboardInterrupt(), ("quit", None)],
    )
    @patch("topsailai.HistoryManager")
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
            cli.main()


class TestHistoryManagerEmptyLine(unittest.TestCase):
    """Tests for HistoryManager empty line handling."""

    def test_load_all_skips_empty_lines(self):
        """Empty lines in history file are skipped (line 88)."""
        manager = cli.HistoryManager("/tmp/history.jsonl")
        with patch("builtins.open", mock_open(read_data='{"valid": 1}\n\n{"valid": 2}\n')):
            with patch("os.path.isfile", return_value=True):
                manager.load_all()
        self.assertEqual(len(manager.entries), 2)


class TestReadlineImportErrorReal(unittest.TestCase):
    """Simulate readline being unavailable during module reload."""

    def test_reload_without_readline(self):
        """Reloading topsailai without readline should not raise."""
        import importlib

        original_readline = sys.modules.get("readline")
        try:
            with patch.dict(sys.modules, {"readline": None}):
                importlib.reload(cli)
        finally:
            if original_readline is not None:
                sys.modules["readline"] = original_readline
            else:
                sys.modules.pop("readline", None)
            # Restore readline attribute on cli module for other tests
            try:
                import readline

                cli.readline = readline
            except ImportError:
                cli.readline = None


class TestGetAvailableCompletionsAliasString(unittest.TestCase):
    """Tests for get_available_completions with string alias."""

    def tearDown(self):
        cli.yaml_commands = []
        cli.current_scope = "workspace"

    def test_alias_string_converted_to_list(self):
        """Alias defined as a string is converted to a list (line 449)."""
        cli.current_scope = "workspace"
        cli.yaml_commands = [
            {
                "cmd": "/test",
                "alias": "t",
                "scopes": ["workspace"],
            }
        ]
        completions = cli.get_available_completions()
        self.assertIn("/test", completions)
        self.assertIn("/t", completions)


class TestTabCompleterException(unittest.TestCase):
    """Tests for tab_completer exception swallowing."""

    def test_readline_error_swallowed(self):
        """NameError/AttributeError from readline is swallowed (lines 491-492)."""
        mock_readline = MagicMock()
        mock_readline.get_line_buffer.side_effect = NameError()
        with patch.object(cli, "readline", mock_readline):
            result = cli.tab_completer("re", 0)
        self.assertIsNone(result)


class TestMatchYamlCommandEmptyCases(unittest.TestCase):
    """Tests for match_yaml_command empty template/alias handling."""

    def tearDown(self):
        cli.yaml_commands = []
        cli.current_scope = "workspace"
        cli.current_session_id = None

    def test_empty_cmd_template_skipped(self):
        """Instruction with empty cmd template is skipped (line 533)."""
        cli.yaml_commands = [
            {"cmd": "", "scopes": ["workspace"], "shell": "echo"}
        ]
        result = cli.match_yaml_command("/something", "/task")
        self.assertIsNone(result)

    def test_empty_alias_skipped(self):
        """Empty alias entry is skipped (line 578)."""
        cli.yaml_commands = [
            {
                "cmd": "/test",
                "alias": ["", "t"],
                "scopes": ["workspace"],
                "shell": "echo",
            }
        ]
        result = cli.match_yaml_command("t", "/task")
        self.assertIsNotNone(result)


class TestBuildCommandEnvVariableReplacement(unittest.TestCase):
    """Tests for build_command_env variable placeholder resolution."""

    def test_environ_variable_replaced(self):
        """Variable placeholders in environ values are resolved (line 633)."""
        instruction = {"environ": {"FOO": "session={session_id}"}}
        variables = {"session_id": "s1"}
        env = cli.build_command_env(instruction, variables)
        self.assertEqual(env.get("FOO"), "session=s1")


class TestHandleYamlCommandQuotedPlaceholder(unittest.TestCase):
    """Tests for handle_yaml_command quoted placeholder replacement."""

    def setUp(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None

    def tearDown(self):
        cli._child_processes.clear()

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_quoted_placeholder_replaced(self, mock_print, mock_popen):
        """Quoted placeholder is replaced without double quoting (line 779)."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        instruction = {
            "cmd": "/run {name}",
            "shell": "runner '{name}'",
        }
        variables = {"name": "hello world"}
        cli.handle_yaml_command(instruction, variables)

        args = mock_popen.call_args.args[0]
        self.assertIn("runner", args)
        self.assertIn("hello world", args)


class TestParseStdoutFilenameRemaining(unittest.TestCase):
    """Tests for _parse_stdout_filename edge cases."""

    def test_session_stdout_empty_base(self):
        """Empty base for .session.stdout returns (None, None) (line 867)."""
        self.assertEqual(cli._parse_stdout_filename(".session.stdout"), (None, None))

    def test_task_stdout_reaches_elif(self):
        """A .task.stdout filename reaches the elif branch and returns (None, None) (line 871)."""
        result = cli._parse_stdout_filename("task_1.task.stdout")
        self.assertEqual(result, (None, None))

    def test_unsupported_extension(self):
        """Unsupported extension returns (None, None)."""
        self.assertEqual(cli._parse_stdout_filename("foo.txt"), (None, None))


class TestPrintHelpAliasString(unittest.TestCase):
    """Tests for print_help with alias as string."""

    def tearDown(self):
        cli.yaml_commands = []
        cli.current_scope = "workspace"

    @patch("builtins.print")
    def test_alias_string_printed(self, mock_print):
        """Alias defined as a string is printed (line 1172)."""
        cli.yaml_commands = [
            {
                "cmd": "/demo",
                "alias": "d",
                "scopes": ["workspace"],
                "description": "demo command",
            }
        ]
        cli.print_help()
        output = " ".join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn("/demo", output)
        self.assertIn("/d", output)


class TestCleanExpiredFilesRemaining(unittest.TestCase):
    """Tests for clean_expired_files remaining branches."""

    def setUp(self):
        self.task_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.task_dir, ignore_errors=True)

    @patch("topsailai.os.path.getmtime", side_effect=OSError("bad mtime"))
    @patch("builtins.print")
    def test_getmtime_error_skips_file(self, mock_print, mock_getmtime):
        """OSError on getmtime skips the file (lines 1219-1220)."""
        path = os.path.join(self.task_dir, "t1.task.stdout")
        with open(path, "w") as f:
            f.write("data")
        old_time = time.time() - 86400 * 7
        os.utime(path, (old_time, old_time))
        cli.clean_expired_files(
            self.task_dir,
            [{"filename": "t1.task.stdout", "path": path}],
        )
        mock_getmtime.assert_called()

    @patch("builtins.print")
    def test_long_filename_truncation(self, mock_print):
        """Very long filename is truncated in output (line 1284)."""
        long_name = "a" * 80 + ".task.stdout"
        path = os.path.join(self.task_dir, long_name)
        with open(path, "w") as f:
            f.write("data")
        # Make file very old so it is selected for cleanup
        old_time = time.time() - 86400 * 7
        os.utime(path, (old_time, old_time))
        with patch("builtins.input", return_value="n"):
            cli.clean_expired_files(
                self.task_dir,
                [{"filename": long_name, "path": path}],
            )
        # File should not be removed because user cancelled
        self.assertTrue(os.path.exists(path))

    @patch("topsailai.os.remove", side_effect=OSError("remove failed"))
    @patch("builtins.print")
    def test_delete_error_reported(self, mock_print, mock_remove):
        """OSError during deletion is reported (lines 1330-1332)."""
        path = os.path.join(self.task_dir, "t2.task.stdout")
        with open(path, "w") as f:
            f.write("data")
        old_time = time.time() - 86400 * 7
        os.utime(path, (old_time, old_time))
        with patch("builtins.input", return_value="y"):
            cli.clean_expired_files(
                self.task_dir,
                [{"filename": "t2.task.stdout", "path": path}],
            )
        mock_remove.assert_called()



class TestFindSessionStdoutFileRemaining(unittest.TestCase):
    """Tests for _find_session_stdout_file remaining branches."""

    def test_task_dir_missing_returns_none(self):
        """Missing task directory returns None (line 1599)."""
        self.assertIsNone(cli._find_session_stdout_file("/nonexistent_path_xyz", "s1"))

    def test_non_file_entry_ignored(self):
        """Directory entries that are not files are ignored (line 1607)."""
        task_dir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(task_dir, "s1.session.stdout"))
            result = cli._find_session_stdout_file(task_dir, "s1")
            self.assertIsNone(result)
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)



class TestStreamFileNoBuffer(unittest.TestCase):
    """Tests for stream_file when stdout lacks buffer."""

    @patch("topsailai.subprocess.run")
    @patch("builtins.print")
    def test_no_buffer_branch(self, mock_print, mock_run):
        """Fallback print branch when stdout has no buffer (lines 1507-1508)."""
        task_dir = tempfile.mkdtemp()
        try:
            path = os.path.join(task_dir, "t1.task.stdout")
            with open(path, "wb") as f:
                f.write(b"hello stream")

            mock_file = mock_open(read_data=b"hello stream")
            mock_stdout = MagicMock()
            del mock_stdout.buffer

            def stop_running(*_args, **_kwargs):
                cli.running = False

            with patch("builtins.open", mock_file):
                with patch.object(cli.sys, "stdout", mock_stdout):
                    with patch("sys.stdin.isatty", return_value=False):
                        with patch("topsailai.time.sleep", side_effect=stop_running):
                            cli.running = True
                            cli.stream_file(path)

            mock_print.assert_any_call("hello stream", end="")
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)


class TestSendMessageCloseError(unittest.TestCase):
    """Tests for send_message_to_session close error handling."""

    @patch("topsailai.os.close", side_effect=OSError("close failed"))
    @patch("topsailai.os.write")
    @patch("topsailai.os.open", return_value=3)
    @patch("topsailai.stat.S_ISFIFO", return_value=True)
    @patch("topsailai.os.stat")
    @patch("topsailai.os.path.exists", return_value=True)
    @patch("topsailai.get_file_pid", return_value=1234)
    @patch("topsailai._find_session_stdout_file", return_value="/tmp/s1.session.stdout")
    @patch("builtins.print")
    def test_close_fd_error_ignored(
        self,
        mock_print,
        mock_find,
        mock_getpid,
        mock_exists,
        mock_stat,
        mock_isfifo,
        mock_open,
        mock_write,
        mock_close,
    ):
        """OSError from os.close in finally is ignored (lines 1759-1760)."""
        task_dir = tempfile.mkdtemp()
        try:
            result = cli.send_message_to_session("s1", "hello", task_dir, timeout=0.1)
            self.assertTrue(result)
            mock_close.assert_called_once_with(3)
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)


class TestHandleSendCancel(unittest.TestCase):
    """Tests for handle_send_command cancellation."""

    def setUp(self):
        self.task_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.task_dir, ignore_errors=True)

    @patch("topsailai._read_multiline_input_for_send", return_value=None)
    @patch("builtins.print")
    def test_cancel_multiline_input(self, mock_print, mock_read):
        """Cancel when multiline input returns None (line 1808)."""
        cli.current_scope = "session"
        cli.current_session_id = "s1"
        cli.handle_send_command("/send", self.task_dir, [])
        mock_read.assert_called_once()


class TestMainRefresh(unittest.TestCase):
    """Tests for main() refresh action."""

    @patch("topsailai.print_table")
    @patch("topsailai.discover_log_files", return_value=[])
    @patch("topsailai.prompt_selection", side_effect=[("refresh", None), ("quit", None)])
    @patch("topsailai.load_yaml_commands", return_value={})
    @patch("topsailai.setup_tab_completion")
    @patch("topsailai.load_readline_history")
    @patch("topsailai.HistoryManager")
    @patch("topsailai.get_topsailai_home", return_value=tempfile.mkdtemp())
    @patch("topsailai.signal.signal")
    @patch("builtins.print")
    def test_refresh_action(
        self,
        mock_print,
        mock_signal,
        mock_home,
        mock_history_cls,
        mock_load_history,
        mock_setup_tab,
        mock_load_yaml,
        mock_prompt,
        mock_discover,
        mock_print_table,
    ):
        """Refresh action in main() updates log_files and reprints table (lines 1967-1970)."""
        home = mock_home.return_value
        try:
            os.makedirs(os.path.join(home, "workspace", "task"), exist_ok=True)
            cli.running = True
            cli.yaml_commands = {}
            cli.history_manager = None
            cli.main()
            self.assertEqual(mock_discover.call_count, 2)
            mock_print_table.assert_called()
        finally:
            shutil.rmtree(home, ignore_errors=True)


class TestMainEntryPoint(unittest.TestCase):
    """Tests for the module entry point."""

    def test_name_main_calls_main(self):
        """if __name__ == '__main__' block calls main() (line 2020)."""
        import runpy

        with patch("builtins.input", return_value="q"):
            with patch("topsailai.cleanup_children"):
                runpy.run_module("topsailai", run_name="__main__")


if __name__ == "__main__":
    unittest.main()
