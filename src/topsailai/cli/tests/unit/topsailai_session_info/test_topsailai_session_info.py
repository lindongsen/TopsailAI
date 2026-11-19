"""Unit tests for topsailai_session_info.py."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

CLI_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_ROOT = os.path.abspath(os.path.join(CLI_ROOT, "..", "src"))
sys.path.insert(0, SRC_ROOT)
sys.path.insert(0, CLI_ROOT)

import topsailai_session_info as si
from cli_topsailai.agent_launch_process import _process_state
from cli_topsailai.session_metrics import METRIC_FIELDS
from topsailai.context.ctx_manager import get_session_manager
from topsailai.context.session_manager import SessionData


class TestParseArgs:
    def test_session_id_required(self):
        args = si._parse_args(["abc123"])
        assert args.session_id == "abc123"
        assert args.db_conn is None
        assert args.home is None
        assert args.no_color is False
        assert args.json is False

    def test_custom_db_conn(self):
        args = si._parse_args(["abc123", "--db-conn", "sqlite:///test.db"])
        assert args.session_id == "abc123"
        assert args.db_conn == "sqlite:///test.db"

    def test_custom_home(self):
        args = si._parse_args(["abc123", "--home", "/tmp/home"])
        assert args.home == "/tmp/home"

    def test_no_color(self):
        args = si._parse_args(["abc123", "--no-color"])
        assert args.no_color is True

    def test_json_flag(self):
        args = si._parse_args(["abc123", "--json"])
        assert args.json is True


class TestRelativeTime:
    def test_just_now(self):
        assert si._relative_time(datetime.now()) == "just now"

    def test_minutes_ago(self):
        past = datetime.now() - timedelta(minutes=5)
        assert si._relative_time(past) == "5 minutes ago"

    def test_none_create_time(self):
        assert si._relative_time(None) == ""


class TestParseSessionStdoutFilename:
    def test_regular_session(self):
        assert si._parse_session_stdout_filename("abc.123.session.stdout") == ("abc", 123)

    def test_temp_session(self):
        assert si._parse_session_stdout_filename("topsailai.123.session.stdout") == ("topsailai", 123)

    def test_session_id_with_dots(self):
        assert si._parse_session_stdout_filename("a.b.c.123.session.stdout") == ("a.b.c", 123)

    def test_non_session_file(self):
        assert si._parse_session_stdout_filename("abc.123.task.stdout") == (None, None)

    def test_invalid_pid(self):
        assert si._parse_session_stdout_filename("abc.xyz.session.stdout") == (None, None)


class TestIsSessionRunning:
    def test_running_session(self, tmp_path: Path):
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / f"s1.{os.getpid()}.session.stdout").write_text("")
        assert si._is_session_running(str(tmp_path), "s1") is True

    def test_idle_session(self, tmp_path: Path):
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / "s1.99999999.session.stdout").write_text("")
        assert si._is_session_running(str(tmp_path), "s1") is False

    def test_zombie_session_is_not_running(self, tmp_path: Path):
        """An unreaped zombie has exited, so the session must be idle."""
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        pid = os.fork()
        if pid == 0:  # pragma: no cover - child process
            os._exit(0)
        try:
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if _process_state(pid) == "Z":
                    break
                time.sleep(0.01)
            (task_dir / f"s1.{pid}.session.stdout").write_text("")
            assert si._is_session_running(str(tmp_path), "s1") is False
        finally:
            try:
                os.waitpid(pid, 0)
            except (ChildProcessError, OSError):
                pass

    def test_older_live_file_beats_newer_dead_file(self, tmp_path: Path):
        """A newer dead stdout file must not hide an older live process."""
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        live = task_dir / f"s1.{os.getpid()}.session.stdout"
        live.write_text("")
        os.utime(live, (1000, 1000))
        dead = task_dir / "s1.99999999.session.stdout"
        dead.write_text("")
        os.utime(dead, (2000, 2000))
        assert si._is_session_running(str(tmp_path), "s1") is True

    def test_negative_pid_is_not_running(self, tmp_path: Path):
        """A negative PID must never be probed as a live process."""
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / "s1.-1.session.stdout").write_text("")
        assert si._is_session_running(str(tmp_path), "s1") is False

    def test_zero_pid_is_not_running(self, tmp_path: Path):
        """PID 0 addresses the process group, so it is not a session."""
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / "s1.0.session.stdout").write_text("")
        assert si._is_session_running(str(tmp_path), "s1") is False


class TestSessionToDict:
    def test_idle_session_dict(self, tmp_path: Path):
        session = SessionData(
            session_id="abc123",
            task="Do something useful.",
            session_name="test-session",
            category="agent",
            project_workspace="/workspace/abc",
            pwd="/workspace/abc/src",
            topsailai_home="/home/user/.topsailai",
        )
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        data = si._session_to_dict(session, str(tmp_path))
        assert data["session_id"] == "abc123"
        assert data["session_name"] == "test-session"
        assert data["category"] == "agent"
        assert data["task"] == "Do something useful."
        assert data["project_workspace"] == "/workspace/abc"
        assert data["pwd"] == "/workspace/abc/src"
        assert data["topsailai_home"] == "/home/user/.topsailai"
        assert data["status"] == "Idle"
        assert data["is_running"] is False
        assert data["create_time"] == "2026-07-05 10:30:15"
        assert "total_tokens" not in data
        assert data["total_prompt_tokens"] == 0
        assert data["total_cached_tokens"] == 0

    def test_running_session_dict(self, tmp_path: Path):
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / f"run123.{os.getpid()}.session.stdout").write_text("")

        session = SessionData(session_id="run123", task="Running task.")
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        data = si._session_to_dict(session, str(tmp_path))
        assert data["status"] == "Running"
        assert data["is_running"] is True

    def test_session_dict_with_token_totals(self, tmp_path: Path):
        session = SessionData(
            session_id="token123",
            task="Token task.",
            session_name="token-session",
            total_tokens=1234,
            total_cached_tokens=567,
            total_completion_tokens=56,
        )
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        data = si._session_to_dict(session, str(tmp_path))
        assert "total_tokens" not in data
        assert data["total_prompt_tokens"] == 1234
        assert data["total_completion_tokens"] == 56
        assert data["total_usage_tokens"] == 1290
        assert data["total_cached_tokens"] == 567


class TestFormatSessionJson:
    def test_json_output_contains_all_session_fields(self, tmp_path: Path):
        session = SessionData(
            session_id="json1",
            task="JSON task.",
            session_name="json-session",
            project_workspace="/workspace/json",
            pwd="/workspace/json/src",
            topsailai_home="/home/json/.topsailai",
        )
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        output = si._format_session_json(session, str(tmp_path))
        parsed = json.loads(output)

        # Original SessionData fields
        assert parsed["session_id"] == "json1"
        assert parsed["session_name"] == "json-session"
        assert parsed["task"] == "JSON task."
        assert parsed["project_workspace"] == "/workspace/json"
        assert parsed["pwd"] == "/workspace/json/src"
        assert parsed["topsailai_home"] == "/home/json/.topsailai"
        assert parsed["create_time"] == "2026-07-05 10:30:15"

        # Computed metadata
        assert parsed["status"] == "Idle"
        assert parsed["is_running"] is False
        assert isinstance(parsed["create_time_relative"], str)

        # Token totals default to 0 when not provided
        assert "total_tokens" not in parsed
        assert parsed["total_prompt_tokens"] == 0
        assert parsed["total_cached_tokens"] == 0

    def test_json_output_includes_all_expected_keys(self, tmp_path: Path):
        session = SessionData(session_id="json2", task="Task two")
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        output = si._format_session_json(session, str(tmp_path))
        parsed = json.loads(output)

        # The metric block is merged in from the shared field list, so the
        # expectation is derived from that list instead of being restated here.
        # A new metric then appears in both the payload and this assertion at
        # once, and the two cannot drift apart.
        expected_keys = {
            "session_id",
            "session_name",
            "category",
            "task",
            "project_workspace",
            "pwd",
            "topsailai_home",
            "create_time",
            "status",
            "is_running",
            "create_time_relative",
            "total_prompt_tokens",
            "total_completion_tokens",
            "total_usage_tokens",
            "total_cached_tokens",
            # Optional runtime enrichment, always present so the record shape
            # never changes between invocations.
            "runtime",
        }
        expected_keys.update(name for name, _attribute, _default in METRIC_FIELDS)
        # Derived values computed by session_metrics() itself.
        expected_keys.update({"first_byte_avg_ms", "model_name"})
        assert set(parsed.keys()) == expected_keys

    def test_json_output_with_nonzero_token_totals(self, tmp_path: Path):
        session = SessionData(
            session_id="json3",
            task="Token task.",
            session_name="token-session",
            total_tokens=9999,
            total_cached_tokens=4444,
            total_completion_tokens=111,
        )
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        output = si._format_session_json(session, str(tmp_path))
        parsed = json.loads(output)

        assert "total_tokens" not in parsed
        assert parsed["total_prompt_tokens"] == 9999
        assert parsed["total_completion_tokens"] == 111
        assert parsed["total_usage_tokens"] == 10110
        assert parsed["total_cached_tokens"] == 4444


class TestFormatSession:
    @patch.object(si, "_supports_color", return_value=False)
    @patch("shutil.get_terminal_size", return_value=Mock(columns=80))
    def test_format_found_session_idle(self, _mock_size, _mock_color, tmp_path: Path):
        session = SessionData(
            session_id="abc123",
            task="Do something useful.",
            session_name="test-session",
            project_workspace="/workspace/abc",
            pwd="/workspace/abc/src",
            topsailai_home="/home/abc/.topsailai",
        )
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        output = si._format_session(session, str(tmp_path), False)
        assert "Session Information" in output
        assert "abc123" in output
        assert "test-session" in output
        assert "2026-07-05 10:30:15" in output
        assert "Idle" in output
        assert "Do something useful." in output
        assert "/workspace/abc" in output
        assert "/workspace/abc/src" in output
        assert "/home/abc/.topsailai" in output
        assert "Prompt Tokens" in output
        assert "Completion Tokens" in output
        assert "Total Usage Tokens" in output
        assert "Cached Prompt Tokens" in output
        assert "Total Tokens" not in output

    @patch.object(si, "_supports_color", return_value=False)
    @patch("shutil.get_terminal_size", return_value=Mock(columns=80))
    def test_format_session_with_nonzero_token_totals(self, _mock_size, _mock_color, tmp_path: Path):
        session = SessionData(
            session_id="token123",
            task="Token task.",
            session_name="token-session",
            total_tokens=1234,
            total_cached_tokens=567,
            total_completion_tokens=56,
        )
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        output = si._format_session(session, str(tmp_path), False)
        assert "Prompt Tokens" in output
        assert "Completion Tokens" in output
        assert "Total Usage Tokens" in output
        assert "Cached Prompt Tokens" in output
        assert "Total Tokens" not in output
        assert "1234" in output
        assert "56" in output
        assert "1290" in output
        assert "567" in output

    @patch.object(si, "_supports_color", return_value=False)
    @patch("shutil.get_terminal_size", return_value=Mock(columns=80))
    def test_format_unnamed_session(self, _mock_size, _mock_color, tmp_path: Path):
        session = SessionData(session_id="def456", task="Another task.")
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        output = si._format_session(session, str(tmp_path), False)
        assert "(unnamed)" in output

    @patch.object(si, "_supports_color", return_value=False)
    @patch("shutil.get_terminal_size", return_value=Mock(columns=80))
    def test_format_running_session(self, _mock_size, _mock_color, tmp_path: Path):
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / f"run123.{os.getpid()}.session.stdout").write_text("")

        session = SessionData(session_id="run123", task="Running task.")
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        output = si._format_session(session, str(tmp_path), False)
        assert "Running" in output


class TestMain:
    def test_main_session_found(self, tmp_path: Path, capsys):
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        db_conn = f"sqlite:///{db_path}"
        try:
            manager = get_session_manager(db_conn)
            manager.create_session(
                SessionData(session_id="s1", task="Task one", session_name="First")
            )

            code = si.main(["s1", "--db-conn", db_conn, "--home", str(tmp_path)])
            captured = capsys.readouterr()
            assert code == 0
            assert "s1" in captured.out
            assert "First" in captured.out
            assert "Task one" in captured.out
        finally:
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_main_session_found_json(self, tmp_path: Path, capsys):
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        db_conn = f"sqlite:///{db_path}"
        try:
            manager = get_session_manager(db_conn)
            manager.create_session(
                SessionData(session_id="s1", task="Task one", session_name="First")
            )

            code = si.main(["s1", "--db-conn", db_conn, "--home", str(tmp_path), "--json"])
            captured = capsys.readouterr()
            assert code == 0
            parsed = json.loads(captured.out)
            assert parsed["session_id"] == "s1"
            assert parsed["session_name"] == "First"
            assert parsed["task"] == "Task one"
            assert parsed["status"] == "Idle"
        finally:
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_main_session_not_found(self, tmp_path: Path, capsys):
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        db_conn = f"sqlite:///{db_path}"
        try:
            code = si.main(["missing", "--db-conn", db_conn, "--home", str(tmp_path)])
            captured = capsys.readouterr()
            assert code == 1
            assert "Session not found" in captured.out
            assert "missing" in captured.out
        finally:
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_main_session_not_found_json(self, tmp_path: Path, capsys):
        """A missing session must still produce one parseable JSON object."""
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        db_conn = f"sqlite:///{db_path}"
        try:
            code = si.main(["missing", "--db-conn", db_conn, "--home", str(tmp_path), "--json"])
            captured = capsys.readouterr()
            assert code == 1
            parsed = json.loads(captured.out)
            assert parsed["session_id"] == "missing"
            assert parsed["error_code"] == "session_not_found"
            assert "Session not found" in parsed["message"]
            assert "\x1b[" not in captured.out
        finally:
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_main_session_not_found_json_has_no_session_fields(self, tmp_path: Path, capsys):
        """A failure record must not be mistakable for an empty real session."""
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        db_conn = f"sqlite:///{db_path}"
        try:
            si.main(["missing", "--db-conn", db_conn, "--home", str(tmp_path), "--json"])
            parsed = json.loads(capsys.readouterr().out)
            assert set(parsed.keys()) == {"session_id", "error_code", "message"}
        finally:
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_main_invalid_db_conn_json(self, tmp_path: Path, capsys):
        """A storage failure must also stay parseable in JSON mode."""
        code = si.main(
            ["s1", "--db-conn", "invalid://bad", "--home", str(tmp_path), "--json"]
        )
        captured = capsys.readouterr()
        assert code == 1
        parsed = json.loads(captured.out)
        assert parsed["session_id"] == "s1"
        assert parsed["error_code"] == "lookup_failed"
        assert parsed["message"]
        assert "\x1b[" not in captured.out

    def test_main_invalid_db_conn(self, tmp_path: Path, capsys):
        code = si.main(["s1", "--db-conn", "invalid://bad", "--home", str(tmp_path)])
        captured = capsys.readouterr()
        assert code == 1
        assert "[ERROR]" in captured.out

    @patch.object(si, "_supports_color", return_value=False)
    @patch("shutil.get_terminal_size", return_value=Mock(columns=80))
    def test_format_missing_category_displays_none(self, _mock_size, _mock_color, tmp_path: Path):
        """Legacy session-like objects without category remain renderable."""
        class LegacySession:
            session_id = "legacy"
            session_name = None
            task = "legacy task"
            project_workspace = None
            pwd = None
            topsailai_home = None
            create_time = None
            total_tokens = 0
            total_completion_tokens = 0
            total_cached_tokens = 0

        output = si._format_session(LegacySession(), str(tmp_path), False)
        assert "Category:" in output
        assert "(none)" in output


    def test_main_real_db_category_json_and_text(self, tmp_path: Path, capsys):
        """The real detail entry point exposes the stored category in both modes."""
        db_path = tmp_path / "sessions.db"
        db_conn = f"sqlite:///{db_path}"
        manager = get_session_manager(db_conn)
        manager.create_session(SessionData(session_id="real-category", task="Task", category="agent"))

        assert si.main(["real-category", "--db-conn", db_conn, "--home", str(tmp_path), "--json"]) == 0
        parsed = json.loads(capsys.readouterr().out)
        assert parsed["category"] == "agent"

        assert si.main(["real-category", "--db-conn", db_conn, "--home", str(tmp_path), "--no-color"]) == 0
        text = capsys.readouterr().out
        assert "Category:" in text
        assert "agent" in text


class TestIncludeRuntime:
    """Pin the `--include-runtime` contract of the single-session command."""

    def test_flag_defaults_to_false(self):
        """Runtime collection is opt-in, so the default must not query anything."""
        assert si._parse_args(["abc123"]).include_runtime is False
        assert si._parse_args(["abc123", "--include-runtime"]).include_runtime is True

    def test_record_carries_runtime_null_when_not_requested(self, tmp_path: Path):
        """The key is always present so the record shape never changes."""
        session = SessionData(session_id="abc123", task="Task")

        data = si._session_to_dict(session, str(tmp_path))

        assert "runtime" in data
        assert data["runtime"] is None

    def test_record_carries_collected_runtime(self, tmp_path: Path):
        """A collected record is published verbatim under `runtime`."""
        session = SessionData(session_id="abc123", task="Task")
        collected = {"state": "ok", "error_code": None, "pid": 123, "data": {"ok": True}}

        data = si._session_to_dict(session, str(tmp_path), runtime=collected)

        assert data["runtime"] == collected

    def test_idle_session_is_never_queried(self, tmp_path: Path):
        """An idle session has no process, so nothing may be contacted."""
        session = SessionData(session_id="idle1", task="Task")

        with patch("cli_topsailai.process_liveness.live_session_pid") as probe, \
             patch("cli_topsailai.workspace_runtime.collect_session_runtime") as collect:
            assert si._collect_runtime(session, str(tmp_path), False) is None

        probe.assert_not_called()
        collect.assert_not_called()

    def test_running_session_without_a_live_pid_is_not_queried(self, tmp_path: Path):
        """A status without a resolvable owner PID must not invent a target."""
        session = SessionData(session_id="run1", task="Task")

        with patch("cli_topsailai.process_liveness.live_session_pid",
                   return_value=None) as probe, \
             patch("cli_topsailai.workspace_runtime.collect_session_runtime") as collect:
            assert si._collect_runtime(session, str(tmp_path), True) is None

        probe.assert_called_once()
        collect.assert_not_called()

    def test_running_session_queries_the_proving_pid(self, tmp_path: Path):
        """The queried PID must be the one that proved the session live."""
        session = SessionData(session_id="run1", task="Task")
        collected = {"state": "ok", "error_code": None, "pid": 4242, "data": {"ok": True}}

        with patch("cli_topsailai.process_liveness.live_session_pid",
                   return_value=4242), \
             patch("cli_topsailai.workspace_runtime.collect_session_runtime",
                   return_value=collected) as collect:
            result = si._collect_runtime(session, str(tmp_path), True)

        assert result == collected
        args = collect.call_args.args
        assert args[0] == "run1"
        assert args[1] == 4242
        assert args[2] == os.path.join(str(tmp_path), si.TASK_SUBDIR)

    def test_collection_failure_leaves_runtime_null(self, tmp_path: Path):
        """Runtime data is optional enrichment, so a failure must not raise."""
        session = SessionData(session_id="run1", task="Task")

        with patch("cli_topsailai.process_liveness.live_session_pid",
                   side_effect=RuntimeError("boom")):
            assert si._collect_runtime(session, str(tmp_path), True) is None

    def test_flag_alone_selects_json(self, tmp_path: Path, capsys):
        """Runtime data has no card representation, so the flag selects JSON."""
        db_conn = f"sqlite:///{tmp_path / 'sessions.db'}"
        get_session_manager(db_conn).create_session(
            SessionData(session_id="json-runtime", task="Task")
        )

        assert si.main([
            "json-runtime", "--db-conn", db_conn, "--home", str(tmp_path),
            "--include-runtime",
        ]) == 0
        parsed = json.loads(capsys.readouterr().out)

        assert parsed["session_id"] == "json-runtime"
        assert parsed["runtime"] is None
        assert parsed["is_running"] is False

    def test_flag_alone_selects_json_on_the_failure_path(self, tmp_path: Path, capsys):
        """A machine consumer must receive parseable JSON even when not found."""
        db_conn = f"sqlite:///{tmp_path / 'sessions.db'}"

        assert si.main([
            "missing", "--db-conn", db_conn, "--home", str(tmp_path),
            "--include-runtime",
        ]) == 1
        captured = capsys.readouterr()

        assert json.loads(captured.out)["error_code"] == "session_not_found"
        assert "\x1b[" not in captured.out

    def test_running_session_publishes_runtime_in_json(self, tmp_path: Path, capsys):
        """A running session's record carries the collected runtime object."""
        db_conn = f"sqlite:///{tmp_path / 'sessions.db'}"
        get_session_manager(db_conn).create_session(
            SessionData(session_id="live-runtime", task="Task")
        )
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / f"live-runtime.{os.getpid()}.session.stdout").write_text("")
        collected = {"state": "ok", "error_code": None, "pid": os.getpid(),
                     "data": {"ok": True, "model": {"name": "m"}}}

        with patch("cli_topsailai.workspace_runtime.collect_session_runtime",
                   return_value=collected):
            assert si.main([
                "live-runtime", "--db-conn", db_conn, "--home", str(tmp_path),
                "--include-runtime",
            ]) == 0
        parsed = json.loads(capsys.readouterr().out)

        assert parsed["is_running"] is True
        assert parsed["runtime"] == collected

    def test_text_mode_is_unchanged(self, tmp_path: Path, capsys):
        """Without the flag the card is printed exactly as before."""
        db_conn = f"sqlite:///{tmp_path / 'sessions.db'}"
        get_session_manager(db_conn).create_session(
            SessionData(session_id="card-only", task="Task")
        )

        assert si.main([
            "card-only", "--db-conn", db_conn, "--home", str(tmp_path), "--no-color",
        ]) == 0
        text = capsys.readouterr().out

        assert "Session Information" in text
        assert "runtime" not in text


if __name__ == "__main__":
    pytest.main([__file__, "--color=no"])
