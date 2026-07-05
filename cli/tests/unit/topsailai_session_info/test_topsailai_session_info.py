"""Unit tests for topsailai_session_info.py."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

CLI_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_ROOT = os.path.abspath(os.path.join(CLI_ROOT, "..", "src"))
sys.path.insert(0, SRC_ROOT)
sys.path.insert(0, CLI_ROOT)

import topsailai_session_info as si
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


class TestIsPidAlive:
    def test_current_process_is_alive(self):
        assert si._is_pid_alive(os.getpid()) is True

    def test_nonexistent_pid(self):
        assert si._is_pid_alive(99999999) is False


class TestFindSessionPid:
    def test_no_task_dir(self, tmp_path: Path):
        assert si._find_session_pid(str(tmp_path), "s1") is None

    def test_no_matching_session(self, tmp_path: Path):
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / "other.123.session.stdout").write_text("")
        assert si._find_session_pid(str(tmp_path), "s1") is None

    def test_finds_most_recent_pid(self, tmp_path: Path):
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        old_file = task_dir / "s1.100.session.stdout"
        old_file.write_text("")
        old_stat = old_file.stat()
        os.utime(old_file, (old_stat.st_atime - 100, old_stat.st_mtime - 100))

        new_file = task_dir / "s1.200.session.stdout"
        new_file.write_text("")
        assert si._find_session_pid(str(tmp_path), "s1") == 200


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


class TestSessionToDict:
    def test_idle_session_dict(self, tmp_path: Path):
        session = SessionData(
            session_id="abc123",
            task="Do something useful.",
            session_name="test-session",
        )
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        data = si._session_to_dict(session, str(tmp_path))
        assert data["session_id"] == "abc123"
        assert data["session_name"] == "test-session"
        assert data["task"] == "Do something useful."
        assert data["status"] == "Idle"
        assert data["is_running"] is False
        assert data["create_time"] == "2026-07-05 10:30:15"

    def test_running_session_dict(self, tmp_path: Path):
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / f"run123.{os.getpid()}.session.stdout").write_text("")

        session = SessionData(session_id="run123", task="Running task.")
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        data = si._session_to_dict(session, str(tmp_path))
        assert data["status"] == "Running"
        assert data["is_running"] is True


class TestFormatSessionJson:
    def test_json_output_is_valid(self, tmp_path: Path):
        session = SessionData(
            session_id="json1",
            task="JSON task.",
            session_name="json-session",
        )
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        output = si._format_session_json(session, str(tmp_path))
        parsed = json.loads(output)
        assert parsed["session_id"] == "json1"
        assert parsed["session_name"] == "json-session"
        assert parsed["task"] == "JSON task."
        assert parsed["status"] == "Idle"
        assert parsed["is_running"] is False


class TestFormatSession:
    @patch.object(si, "_supports_color", return_value=False)
    @patch("shutil.get_terminal_size", return_value=Mock(columns=80))
    def test_format_found_session_idle(self, _mock_size, _mock_color, tmp_path: Path):
        session = SessionData(
            session_id="abc123",
            task="Do something useful.",
            session_name="test-session",
        )
        session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        output = si._format_session(session, str(tmp_path), False)
        assert "Session Information" in output
        assert "abc123" in output
        assert "test-session" in output
        assert "2026-07-05 10:30:15" in output
        assert "Idle" in output
        assert "Do something useful." in output

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
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        db_conn = f"sqlite:///{db_path}"
        try:
            code = si.main(["missing", "--db-conn", db_conn, "--home", str(tmp_path), "--json"])
            captured = capsys.readouterr()
            assert code == 1
            assert "Session not found" in captured.out
        finally:
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_main_invalid_db_conn(self, tmp_path: Path, capsys):
        code = si.main(["s1", "--db-conn", "invalid://bad", "--home", str(tmp_path)])
        captured = capsys.readouterr()
        assert code == 1
        assert "[ERROR]" in captured.out


if __name__ == "__main__":
    pytest.main([__file__, "--color=no"])
