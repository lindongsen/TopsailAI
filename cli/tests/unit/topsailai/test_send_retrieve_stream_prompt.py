"""Unit tests for send/retrieve/stream/prompt/main functions in topsailai.py."""

import builtins
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import topsailai as cli


class TestResolveSessionIdFromArg(unittest.TestCase):
    def test_resolve_by_index(self):
        log_files = [
            {"session_id": "session-a"},
            {"session_id": "session-b"},
        ]
        self.assertEqual(
            cli._resolve_session_id_from_arg("1", "/tmp", log_files), "session-a"
        )
        self.assertEqual(
            cli._resolve_session_id_from_arg("2", "/tmp", log_files), "session-b"
        )

    def test_resolve_by_index_temp_skipped(self):
        log_files = [{"session_id": "(temp)"}]
        self.assertIsNone(
            cli._resolve_session_id_from_arg("1", "/tmp", log_files)
        )

    def test_resolve_by_index_temp_allowed(self):
        log_files = [{"session_id": "(temp)"}]
        self.assertEqual(
            cli._resolve_session_id_from_arg("1", "/tmp", log_files, allow_temp=True),
            "topsailai",
        )

    def test_resolve_literal_temp(self):
        log_files = []
        self.assertEqual(
            cli._resolve_session_id_from_arg("(temp)", "/tmp", log_files),
            "topsailai",
        )

    def test_resolve_by_index_out_of_range(self):
        log_files = [{"session_id": "session-a"}]
        self.assertIsNone(
            cli._resolve_session_id_from_arg("5", "/tmp", log_files)
        )

    def test_resolve_invalid_index(self):
        log_files = [{"session_id": "session-a"}]
        self.assertIsNone(
            cli._resolve_session_id_from_arg("0", "/tmp", log_files)
        )

    def test_resolve_by_session_id(self):
        log_files = [{"session_id": "session-a"}]
        self.assertEqual(
            cli._resolve_session_id_from_arg("session-a", "/tmp", log_files),
            "session-a",
        )

    def test_resolve_literal_id(self):
        log_files = []
        self.assertEqual(
            cli._resolve_session_id_from_arg("abc", "/tmp", log_files), "abc"
        )

    def test_resolve_empty(self):
        self.assertIsNone(cli._resolve_session_id_from_arg("", "/tmp", []))


class TestBuildPipePath(unittest.TestCase):
    def test_build_pipe_path(self):
        path = cli._build_pipe_path("/task", "session-1", 1234)
        self.assertEqual(path, os.path.join("/task", "session-1.1234.session.pipe"))

    def test_build_pipe_path_temp(self):
        path = cli._build_pipe_path("/task", "(temp)", 1234)
        self.assertEqual(path, os.path.join("/task", "topsailai.1234.session.pipe"))


class TestDisplaySessionId(unittest.TestCase):
    def test_temp_session(self):
        self.assertEqual(cli._display_session_id("topsailai"), "(temp)")

    def test_normal_session(self):
        self.assertEqual(cli._display_session_id("session-1"), "session-1")

    def test_none_session(self):
        self.assertEqual(cli._display_session_id(None), "-")

    def test_task_session(self):
        self.assertEqual(cli._display_session_id("session-1", is_task=True), "session-1 (task)")

    def test_temp_task_session(self):
        self.assertEqual(cli._display_session_id("topsailai", is_task=True), "(temp) (task)")


class TestFormatPipePayload(unittest.TestCase):
    def test_format_payload(self):
        payload = cli._format_pipe_payload("hello")
        self.assertEqual(payload, b"hello\nEOF\n")

    def test_format_payload_already_has_eof(self):
        payload = cli._format_pipe_payload("hello\nEOF\n")
        self.assertEqual(payload, b"hello\nEOF\n")

    def test_format_payload_preserves_leading_whitespace(self):
        payload = cli._format_pipe_payload("  hello")
        self.assertEqual(payload, b"  hello\nEOF\n")

    def test_format_payload_preserves_trailing_newline(self):
        payload = cli._format_pipe_payload("hello\n")
        self.assertEqual(payload, b"hello\nEOF\n")

    def test_format_payload_empty(self):
        payload = cli._format_pipe_payload("")
        self.assertEqual(payload, b"\nEOF\n")


class TestReadMultilineInputForSend(unittest.TestCase):
    def test_multiline_input(self):
        with patch("builtins.input", side_effect=["line1", "line2", "EOF"]):
            result = cli._read_multiline_input_for_send()
        self.assertEqual(result, "line1\nline2")

    def test_empty_input(self):
        with patch("builtins.input", side_effect=["EOF"]):
            result = cli._read_multiline_input_for_send()
        self.assertEqual(result, "")

    def test_eof_error(self):
        with patch("builtins.input", side_effect=["line1", EOFError()]):
            result = cli._read_multiline_input_for_send()
        self.assertEqual(result, "line1")

    def test_keyboard_interrupt(self):
        with patch("builtins.input", side_effect=[KeyboardInterrupt()]):
            with patch("builtins.print"):
                result = cli._read_multiline_input_for_send()
        self.assertIsNone(result)


class TestSendMessageToSession(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.task_dir = os.path.join(self.tmpdir, "task")
        os.makedirs(self.task_dir)
        self.stdout_path = os.path.join(self.task_dir, "session-1.1234.session.stdout")
        with open(self.stdout_path, "w") as f:
            f.write("log")
        self.pipe_path = os.path.join(self.task_dir, "session-1.1234.session.pipe")

    def tearDown(self):
        for root, dirs, files in os.walk(self.tmpdir, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(self.tmpdir)

    @patch("topsailai.get_file_pid", return_value=1234)
    def test_send_success(self, mock_get_pid):
        os.mkfifo(self.pipe_path)

        received = []

        def reader():
            with open(self.pipe_path, "rb") as f:
                received.append(f.read())

        import threading

        t = threading.Thread(target=reader)
        t.start()
        try:
            result = cli.send_message_to_session(
                "session-1", "hello", self.task_dir, timeout=2.0
            )
            self.assertTrue(result)
        finally:
            t.join(timeout=3)

        self.assertEqual(received, [b"hello\nEOF\n"])

    @patch("topsailai.get_file_pid", return_value=None)
    def test_send_no_pid(self, mock_get_pid):
        result = cli.send_message_to_session("session-1", "hello", self.task_dir)
        self.assertFalse(result)

    def test_send_no_stdout_file(self):
        os.remove(self.stdout_path)
        result = cli.send_message_to_session("session-1", "hello", self.task_dir)
        self.assertFalse(result)

    @patch("topsailai.get_file_pid", return_value=1234)
    def test_send_pipe_not_found(self, mock_get_pid):
        result = cli.send_message_to_session("session-1", "hello", self.task_dir)
        self.assertFalse(result)

    @patch("topsailai.get_file_pid", return_value=1234)
    def test_send_pipe_not_fifo(self, mock_get_pid):
        with open(self.pipe_path, "w") as f:
            f.write("not a fifo")
        result = cli.send_message_to_session("session-1", "hello", self.task_dir)
        self.assertFalse(result)

    @patch("topsailai.get_file_pid", return_value=1234)
    def test_send_open_timeout(self, mock_get_pid):
        # Pipe exists but no reader -> ENXIO loop until timeout
        os.mkfifo(self.pipe_path)
        result = cli.send_message_to_session(
            "session-1", "hello", self.task_dir, timeout=0.05
        )
        self.assertFalse(result)

class TestHandleStreamCommand(unittest.TestCase):
    def setUp(self):
        self.task_dir = "/task"
        self.log_files = [
            {
                "session_id": "session-a",
                "path": "/task/session-a.session.stdout",
            }
        ]

    @patch("topsailai.send_message_to_session")
    def test_stream_send_with_message(self, mock_send):
        cli._handle_stream_command(
            "/send hello world",
            self.task_dir,
            self.log_files,
            "session-a",
            "/task/session-a.session.stdout",
        )
        mock_send.assert_called_once_with(
            "session-a", "hello world", self.task_dir,
            stdout_path="/task/session-a.session.stdout",
        )

    @patch("topsailai.send_message_to_session")
    @patch("builtins.input", side_effect=["line1", "EOF"])
    def test_stream_send_multiline(self, mock_input, mock_send):
        cli._handle_stream_command(
            "/send",
            self.task_dir,
            self.log_files,
            "session-a",
            "/task/session-a.session.stdout",
        )
        mock_send.assert_called_once_with(
            "session-a", "line1", self.task_dir,
            stdout_path="/task/session-a.session.stdout",
        )

    @patch("topsailai.send_message_to_session")
    def test_stream_send_no_session(self, mock_send):
        with patch("builtins.print") as mock_print:
            cli._handle_stream_command(
                "/send hello",
                self.task_dir,
                self.log_files,
                None,
                None,
            )
        mock_send.assert_not_called()
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("No session" in str(p) for p in printed))

    @patch("topsailai.send_message_to_session")
    def test_stream_send_by_index(self, mock_send):
        cli._handle_stream_command(
            "/send 1 hello",
            self.task_dir,
            self.log_files,
            "session-a",
            "/task/session-a.session.stdout",
        )
        mock_send.assert_called_once_with(
            "session-a", "hello", self.task_dir,
            stdout_path="/task/session-a.session.stdout",
        )

    @patch("topsailai.send_message_to_session")
    def test_stream_send_unknown_target(self, mock_send):
        with patch("builtins.print"):
            cli._handle_stream_command(
                "/send 99 hello",
                self.task_dir,
                self.log_files,
                "session-a",
                "/task/session-a.session.stdout",
            )
        mock_send.assert_not_called()

    def test_stream_help(self):
        with patch("builtins.print") as mock_print:
            cli._handle_stream_command(
                "/help",
                self.task_dir,
                self.log_files,
                "session-a",
                "/task/session-a.session.stdout",
            )
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("Streaming commands" in str(p) for p in printed))

    def test_stream_unknown_command(self):
        with patch("builtins.print") as mock_print:
            cli._handle_stream_command(
                "/unknown",
                self.task_dir,
                self.log_files,
                "session-a",
                "/task/session-a.session.stdout",
            )
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("Unknown streaming command" in str(p) for p in printed))

    def test_stream_send_prefix_not_matched(self):
        """/sendfoo should be treated as unknown, not as /send."""
        with patch("builtins.print") as mock_print:
            cli._handle_stream_command(
                "/sendfoo",
                self.task_dir,
                self.log_files,
                "session-a",
                "/task/session-a.session.stdout",
            )
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("Unknown streaming command" in str(p) for p in printed))

    def test_stream_empty_command(self):
        with patch("builtins.print") as mock_print:
            cli._handle_stream_command(
                "",
                self.task_dir,
                self.log_files,
                "session-a",
                "/task/session-a.session.stdout",
            )
        mock_print.assert_not_called()


class TestHandleSendCommand(unittest.TestCase):
    def setUp(self):
        self.task_dir = "/task"
        self.log_files = [
            {
                "session_id": "session-a",
                "path": "/task/session-a.session.stdout",
            }
        ]

    @patch("topsailai.send_message_to_session")
    def test_send_workspace_with_message(self, mock_send):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.handle_send_command(
            "/send session-a hello world", self.task_dir, self.log_files
        )
        mock_send.assert_called_once_with(
            "session-a", "hello world", self.task_dir,
        )

    @patch("topsailai.send_message_to_session")
    def test_send_workspace_by_index(self, mock_send):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.handle_send_command("/send 1 hello", self.task_dir, self.log_files)
        mock_send.assert_called_once_with(
            "session-a", "hello", self.task_dir,
            stdout_path="/task/session-a.session.stdout",
        )

    @patch("topsailai.send_message_to_session")
    def test_send_workspace_by_index_temp(self, mock_send):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        log_files = [
            {
                "session_id": "(temp)",
                "path": "/task/topsailai.1234.session.stdout",
            }
        ]
        cli.handle_send_command("/send 1 hello", self.task_dir, log_files)
        mock_send.assert_called_once_with(
            "topsailai", "hello", self.task_dir,
            stdout_path="/task/topsailai.1234.session.stdout",
        )

    @patch("topsailai.send_message_to_session")
    def test_send_workspace_by_index_temp_distinct_paths(self, mock_send):
        """Selecting different temp rows must target distinct stdout files."""
        cli.current_scope = "workspace"
        cli.current_session_id = None
        log_files = [
            {
                "session_id": "(temp)",
                "path": "/task/topsailai.1111.session.stdout",
            },
            {
                "session_id": "(temp)",
                "path": "/task/topsailai.2222.session.stdout",
            },
        ]
        cli.handle_send_command("/send 1 hello", self.task_dir, log_files)
        mock_send.assert_called_once_with(
            "topsailai", "hello", self.task_dir,
            stdout_path="/task/topsailai.1111.session.stdout",
        )
        mock_send.reset_mock()
        cli.handle_send_command("/send 2 hello", self.task_dir, log_files)
        mock_send.assert_called_once_with(
            "topsailai", "hello", self.task_dir,
            stdout_path="/task/topsailai.2222.session.stdout",
        )

    @patch("topsailai.send_message_to_session")
    def test_send_session_scope(self, mock_send):
        cli.current_scope = "session"
        cli.current_session_id = "session-a"
        cli.handle_send_command("/send hello", self.task_dir, self.log_files)
        mock_send.assert_called_once_with("session-a", "hello", self.task_dir)

    @patch("topsailai.send_message_to_session")
    @patch("builtins.input", side_effect=["line1", "EOF"])
    def test_send_multiline(self, mock_input, mock_send):
        cli.current_scope = "session"
        cli.current_session_id = "session-a"
        cli.handle_send_command("/send", self.task_dir, self.log_files)
        mock_send.assert_called_once_with("session-a", "line1", self.task_dir)

    @patch("topsailai.send_message_to_session")
    def test_send_unresolved(self, mock_send):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        with patch("builtins.print"):
            cli.handle_send_command("/send 99 hello", self.task_dir, self.log_files)
        mock_send.assert_not_called()

    @patch("topsailai.send_message_to_session")
    def test_send_usage_error(self, mock_send):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        with patch("builtins.print"):
            cli.handle_send_command("/send", self.task_dir, self.log_files)
        mock_send.assert_not_called()

class TestStreamFile(unittest.TestCase):
    def tearDown(self):
        cli.running = True

    @patch("topsailai.subprocess.run")
    def test_stream_file(self, mock_run):
        cli.running = False
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("line1\nline2\n")
            path = f.name
        try:
            cli.stream_file(path)
        finally:
            os.remove(path)
        mock_run.assert_called_once_with(["tail", "-n", "20", path], check=False)

    @patch("topsailai.subprocess.run")
    def test_stream_file_not_found(self, mock_run):
        cli.running = False
        mock_run.side_effect = FileNotFoundError
        missing_path = "/tmp/this_file_definitely_does_not_exist_12345.stdout"
        with patch("builtins.print") as mock_print:
            cli.stream_file(missing_path)
        mock_run.assert_called_once_with(["tail", "-n", "20", missing_path], check=False)
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("not found" in str(p) for p in printed))

class TestRetrieveSession(unittest.TestCase):
    @patch("topsailai.subprocess.Popen")
    @patch("topsailai.unregister_process")
    @patch("topsailai.register_process")
    def test_retrieve_success(self, mock_register, mock_unregister, mock_popen):
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate.return_value = ("stdout content", "")
        proc.poll.return_value = 0
        mock_popen.return_value = proc

        with patch("builtins.print"):
            cli.retrieve_session("session-a")

        mock_popen.assert_called_once_with(
            ["topsailai_retrieve_messages", "session-a"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        proc.communicate.assert_called_once_with(timeout=30)

    @patch("topsailai.subprocess.Popen")
    def test_retrieve_failure(self, mock_popen):
        proc = MagicMock()
        proc.returncode = 1
        proc.communicate.return_value = ("", "error msg")
        proc.poll.return_value = 1
        mock_popen.return_value = proc

        with patch("builtins.print"):
            cli.retrieve_session("session-a")

        proc.communicate.assert_called_once_with(timeout=30)

    @patch("topsailai.subprocess.Popen", side_effect=FileNotFoundError())
    def test_retrieve_command_not_found(self, mock_popen):
        with patch("builtins.print"):
            cli.retrieve_session("session-a")

    @patch("topsailai.subprocess.Popen")
    def test_retrieve_timeout(self, mock_popen):
        proc = MagicMock()
        proc.communicate.side_effect = subprocess.TimeoutExpired("cmd", 30)
        proc.poll.return_value = None
        mock_popen.return_value = proc

        with patch("builtins.print"):
            cli.retrieve_session("session-a")

        proc.kill.assert_called()


class TestPromptSelection(unittest.TestCase):
    def setUp(self):
        self.task_dir = "/task"
        self.files = [
            {"filename": "a.stdout", "session_id": "session-a"},
            {"filename": "b.stdout", "session_id": "session-b"},
        ]
        cli.current_scope = "workspace"
        cli.current_session_id = None

    def test_quit(self):
        with patch("builtins.input", return_value="q"):
            action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "quit")
        self.assertIsNone(value)

    def test_refresh(self):
        with patch("builtins.input", return_value="/refresh"):
            action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "refresh")

    def test_help(self):
        with patch("builtins.input", return_value="/help"):
            action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "help")

    def test_clean(self):
        with patch("builtins.input", return_value="/clean"):
            action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "clean")

    def test_clean_numbers(self):
        with patch("builtins.input", return_value="/clean 1 2"):
            action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "clean_numbers")
        self.assertEqual(value, [0, 1])

    def test_clean_invalid_numbers(self):
        with patch("builtins.input", side_effect=["/clean a", "q"]):
            action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "quit")

    def test_send(self):
        with patch("builtins.input", return_value="/send 1 hello"):
            action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "send")
        self.assertEqual(value, "/send 1 hello")

    def test_session(self):
        with patch("builtins.input", return_value="/session 1"):
            action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "session")
        self.assertEqual(value, 0)

    def test_session_out_of_range(self):
        with patch("builtins.input", side_effect=["/session 99", "q"]):
            action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "quit")

    def test_watch(self):
        with patch("builtins.input", return_value="1"):
            action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "watch")
        self.assertEqual(value, 0)

    def test_watch_out_of_range(self):
        with patch("builtins.input", side_effect=["99", "q"]):
            action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "quit")

    def test_unknown_command(self):
        with patch("builtins.input", side_effect=["/unknown", "q"]):
            action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "quit")

    def test_empty_input(self):
        with patch("builtins.input", side_effect=["", "q"]):
            action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "quit")

    def test_eof_exit(self):
        with patch("builtins.input", side_effect=EOFError()):
            with patch("builtins.print"):
                action, value = cli.prompt_selection(self.files, self.task_dir)
        self.assertEqual(action, "quit")
class TestMain(unittest.TestCase):
    def setUp(self):
        cli.running = True
        cli.current_scope = "workspace"
        cli.current_session_id = None

    def _make_file(self, name, session_id):
        return {
            "filename": name,
            "path": os.path.join("/task", name),
            "session_id": session_id,
            "pid": 1234,
            "size": 100,
            "mtime": 1234567890,
        }


    @patch("topsailai.signal.signal")
    @patch("topsailai.load_yaml_commands", return_value=[])
    @patch("topsailai.get_topsailai_home", return_value="/home")
    @patch("topsailai.discover_log_files", return_value=[])
    @patch("topsailai.print_table")
    @patch("topsailai.prompt_selection", side_effect=[("quit", None)])
    @patch("topsailai.HistoryManager")
    def test_main_no_files(
        self,
        mock_history_cls,
        mock_prompt,
        mock_print_table,
        mock_discover,
        mock_home,
        mock_yaml,
        mock_signal,
    ):
        mock_history = MagicMock()
        mock_history_cls.return_value = mock_history
        with patch("builtins.print"):
            cli.main()
        mock_discover.assert_called_with("/home/workspace/task")
        mock_print_table.assert_not_called()

    @patch("topsailai.signal.signal")
    @patch("topsailai.load_yaml_commands", return_value=[])
    @patch("topsailai.get_topsailai_home", return_value="/home")
    @patch(
        "topsailai.discover_log_files",
        return_value=[
            {
                "filename": "a.session.stdout",
                "path": "/task/a.session.stdout",
                "session_id": "session-a",
                "pid": 1234,
                "size": 100,
                "mtime": 1234567890,
            }
        ],
    )
    @patch("topsailai.print_table")
    @patch("topsailai.stream_file")
    @patch(
        "topsailai.prompt_selection",
        side_effect=[("watch", 0), ("quit", None)],
    )
    @patch("topsailai.HistoryManager")
    def test_main_watch(
        self,
        mock_history_cls,
        mock_prompt,
        mock_stream,
        mock_print_table,
        mock_discover,
        mock_home,
        mock_yaml,
        mock_signal,
    ):
        mock_history = MagicMock()
        mock_history_cls.return_value = mock_history
        with patch("builtins.print"):
            cli.main()
        mock_stream.assert_called_once_with(
            "/task/a.session.stdout",
            task_dir="/home/workspace/task",
            log_files=[
                {
                    "filename": "a.session.stdout",
                    "path": "/task/a.session.stdout",
                    "session_id": "session-a",
                    "pid": 1234,
                    "size": 100,
                    "mtime": 1234567890,
                }
            ],
            default_session_id="session-a",
            default_stdout_path="/task/a.session.stdout",
        )

    @patch("topsailai.signal.signal")
    @patch("topsailai.load_yaml_commands", return_value=[])
    @patch("topsailai.get_topsailai_home", return_value="/home")
    @patch(
        "topsailai.discover_log_files",
        return_value=[
            {
                "filename": "a.session.stdout",
                "path": "/task/a.session.stdout",
                "session_id": "session-a",
                "pid": 1234,
                "size": 100,
                "mtime": 1234567890,
            }
        ],
    )
    @patch("topsailai.print_table")
    @patch("topsailai.retrieve_session")
    @patch(
        "topsailai.prompt_selection",
        side_effect=[("session", 0), ("quit", None)],
    )
    @patch("topsailai.HistoryManager")
    def test_main_session(
        self,
        mock_history_cls,
        mock_prompt,
        mock_retrieve,
        mock_print_table,
        mock_discover,
        mock_home,
        mock_yaml,
        mock_signal,
    ):
        mock_history = MagicMock()
        mock_history_cls.return_value = mock_history
        with patch("builtins.print"):
            cli.main()
        mock_retrieve.assert_called_once_with("session-a")

    @patch("topsailai.signal.signal")
    @patch("topsailai.load_yaml_commands", return_value=[])
    @patch("topsailai.get_topsailai_home", return_value="/home")
    @patch(
        "topsailai.discover_log_files",
        return_value=[
            {
                "filename": "a.session.stdout",
                "path": "/task/a.session.stdout",
                "session_id": "(temp)",
                "pid": 1234,
                "size": 100,
                "mtime": 1234567890,
            }
        ],
    )
    @patch("topsailai.print_table")
    @patch("topsailai.retrieve_session")
    @patch(
        "topsailai.prompt_selection",
        side_effect=[("session", 0), ("quit", None)],
    )
    @patch("topsailai.HistoryManager")
    def test_main_session_temp(
        self,
        mock_history_cls,
        mock_prompt,
        mock_retrieve,
        mock_print_table,
        mock_discover,
        mock_home,
        mock_yaml,
        mock_signal,
    ):
        mock_history = MagicMock()
        mock_history_cls.return_value = mock_history
        with patch("builtins.print"):
            cli.main()
        mock_retrieve.assert_not_called()

    @patch("topsailai.signal.signal")
    @patch("topsailai.load_yaml_commands", return_value=[])
    @patch("topsailai.get_topsailai_home", return_value="/home")
    @patch("topsailai.discover_log_files", return_value=[])
    @patch("topsailai.print_table")
    @patch("topsailai.clean_expired_files")
    @patch(
        "topsailai.prompt_selection",
        side_effect=[("clean", None), ("quit", None)],
    )
    @patch("topsailai.HistoryManager")
    def test_main_clean(
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
    @patch("topsailai.handle_send_command")
    @patch(
        "topsailai.prompt_selection",
        side_effect=[("send", "/send 1 hello"), ("quit", None)],
    )
    @patch("topsailai.HistoryManager")
    def test_main_send(
        self,
        mock_history_cls,
        mock_prompt,
        mock_send,
        mock_print_table,
        mock_discover,
        mock_home,
        mock_yaml,
        mock_signal,
    ):
        mock_history = MagicMock()
        mock_history_cls.return_value = mock_history
        with patch("builtins.print"):
            cli.main()
        mock_send.assert_called_once_with("/send 1 hello", "/home/workspace/task", [])


if __name__ == "__main__":
    unittest.main()
