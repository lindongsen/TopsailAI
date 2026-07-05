"""Unit tests for topsailai_project_history.py."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import topsailai_project_history as ph
from cli_topsailai.colors import Colors


class TestParseArgs:
    def test_default_limit(self):
        args = ph._parse_args([])
        assert args.limit == ph.DEFAULT_LIMIT
        assert args.home is None

    def test_custom_limit(self):
        args = ph._parse_args(["--limit", "5"])
        assert args.limit == 5

    def test_custom_limit_short(self):
        args = ph._parse_args(["-n", "10"])
        assert args.limit == 10

    def test_custom_home(self):
        args = ph._parse_args(["--home", "/tmp/test-home"])
        assert args.home == "/tmp/test-home"


class TestNormalizeTimestamp:
    def test_none_returns_none(self):
        assert ph._normalize_timestamp(None) is None

    def test_bool_returns_none(self):
        assert ph._normalize_timestamp(True) is None

    def test_milliseconds(self):
        ts = 1709913600000  # 2024-03-09 00:00:00 UTC
        result = ph._normalize_timestamp(ts)
        assert result is not None
        assert result.startswith("2024-03-09")

    def test_seconds(self):
        ts = 1709913600  # 2024-03-09 00:00:00 UTC
        result = ph._normalize_timestamp(ts)
        assert result is not None
        assert result.startswith("2024-03-09")

    def test_iso_string(self):
        ts = "2024-03-09T12:00:00+00:00"
        result = ph._normalize_timestamp(ts)
        assert result is not None
        assert "2024-03-09" in result

    def test_numeric_string(self):
        ts = "1709913600000"  # 2024-03-09 00:00:00 UTC
        result = ph._normalize_timestamp(ts)
        assert result is not None
        assert result.startswith("2024-03-09")

    def test_invalid_string_returns_none(self):
        assert ph._normalize_timestamp("not-a-timestamp") is None


class TestReadLastLines:
    def test_empty_file(self, tmp_path: Path):
        filepath = tmp_path / "history.jsonl"
        filepath.write_text("")
        assert ph._read_last_lines(str(filepath), 10) == []

    def test_reads_last_n_lines(self, tmp_path: Path):
        filepath = tmp_path / "history.jsonl"
        lines = [f"line{i}" for i in range(1, 6)]
        filepath.write_text("\n".join(lines) + "\n")
        result = ph._read_last_lines(str(filepath), 3)
        assert result == ["line3", "line4", "line5"]

    def test_skips_empty_lines(self, tmp_path: Path):
        filepath = tmp_path / "history.jsonl"
        filepath.write_text("line1\n\nline2\n\nline3\n")
        result = ph._read_last_lines(str(filepath), 3)
        assert result == ["line1", "line2", "line3"]

    def test_limit_zero(self, tmp_path: Path):
        filepath = tmp_path / "history.jsonl"
        filepath.write_text("line1\nline2\n")
        assert ph._read_last_lines(str(filepath), 0) == []

    def test_missing_file(self, tmp_path: Path):
        filepath = tmp_path / "missing.jsonl"
        assert ph._read_last_lines(str(filepath), 10) == []


class TestLoadEntries:
    def test_loads_and_normalizes(self, tmp_path: Path):
        filepath = tmp_path / ph.HISTORY_FILENAME
        entries: List[Dict[str, Any]] = [
            {"ts": 1709913600000, "session_id": "s1", "project_workspace": "/w1", "pwd": "/w1/p1"},
            {"ts": "2024-03-10T12:00:00+00:00", "session_id": "s2", "project_workspace": "/w2", "pwd": "/w2/p2"},
        ]
        with open(filepath, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        result = ph._load_entries(str(tmp_path), 10)
        assert len(result) == 2
        assert result[0]["session_id"] == "s1"
        assert result[1]["session_id"] == "s2"
        assert result[0]["ts"].startswith("2024-03-09")

    def test_skips_invalid_json(self, tmp_path: Path):
        filepath = tmp_path / ph.HISTORY_FILENAME
        filepath.write_text('{"valid": 1}\nnot json\n{"valid": 2}\n')
        result = ph._load_entries(str(tmp_path), 10)
        assert len(result) == 2
        assert result[0]["valid"] == 1
        assert result[1]["valid"] == 2

    def test_skips_non_object_json(self, tmp_path: Path):
        filepath = tmp_path / ph.HISTORY_FILENAME
        filepath.write_text('{"valid": 1}\n[1, 2, 3]\n{"valid": 2}\n')
        result = ph._load_entries(str(tmp_path), 10)
        assert len(result) == 2

    def test_missing_file(self, tmp_path: Path):
        result = ph._load_entries(str(tmp_path), 10)
        assert result == []


class TestEllipsize:
    def test_short_text(self):
        assert ph._ellipsize("hello", 10) == "hello"

    def test_long_text(self):
        assert ph._ellipsize("hello world", 8) == "hello..."

    def test_tiny_width(self):
        assert ph._ellipsize("hello", 2) == "he"


class TestDisplaySessionId:
    def test_none(self):
        assert ph._display_session_id(None) == "-"

    def test_empty(self):
        assert ph._display_session_id("") == "-"

    def test_temporary_session(self):
        assert ph._display_session_id("topsailai") == "(temp)"

    def test_regular_session(self):
        assert ph._display_session_id("abc123") == "abc123"


class TestParseSessionStdoutFilename:
    def test_regular_session(self):
        assert ph._parse_session_stdout_filename("abc.123.session.stdout") == ("abc", 123)

    def test_temp_session(self):
        assert ph._parse_session_stdout_filename("topsailai.123.session.stdout") == ("topsailai", 123)

    def test_session_id_with_dots(self):
        assert ph._parse_session_stdout_filename("a.b.c.123.session.stdout") == ("a.b.c", 123)

    def test_non_session_file(self):
        assert ph._parse_session_stdout_filename("abc.123.task.stdout") == (None, None)

    def test_invalid_pid(self):
        assert ph._parse_session_stdout_filename("abc.xyz.session.stdout") == (None, None)


class TestIsPidAlive:
    def test_current_process_is_alive(self):
        assert ph._is_pid_alive(os.getpid()) is True

    def test_nonexistent_pid(self):
        assert ph._is_pid_alive(99999999) is False


class TestIsSessionRunning:
    def test_no_task_dir(self, tmp_path: Path):
        assert ph._is_session_running(str(tmp_path), "s1") is False

    def test_no_matching_session(self, tmp_path: Path):
        task_dir = tmp_path / ph.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / "other.123.session.stdout").write_text("")
        assert ph._is_session_running(str(tmp_path), "s1") is False

    def test_running_session(self, tmp_path: Path):
        task_dir = tmp_path / ph.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / f"s1.{os.getpid()}.session.stdout").write_text("")
        assert ph._is_session_running(str(tmp_path), "s1") is True

    def test_idle_session(self, tmp_path: Path):
        task_dir = tmp_path / ph.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / "s1.99999999.session.stdout").write_text("")
        assert ph._is_session_running(str(tmp_path), "s1") is False

    def test_uses_most_recent_file(self, tmp_path: Path):
        task_dir = tmp_path / ph.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        old_file = task_dir / f"s1.{os.getpid()}.session.stdout"
        old_file.write_text("")
        old_stat = old_file.stat()
        os.utime(old_file, (old_stat.st_atime - 100, old_stat.st_mtime - 100))

        new_file = task_dir / "s1.99999999.session.stdout"
        new_file.write_text("")
        assert ph._is_session_running(str(tmp_path), "s1") is False


class TestPrintTable:
    def test_empty_entries(self, capsys):
        ph._print_table([], str(Path("/tmp")))
        captured = capsys.readouterr()
        assert "No project history entries found" in captured.out

    def test_prints_entries(self, capsys):
        entries = [
            {"ts": "2024-03-09T12:00:00+0800", "session_id": "s1", "project_workspace": "/w1", "pwd": "/w1/p1"},
            {"ts": "2024-03-10T12:00:00+0800", "session_id": "topsailai", "project_workspace": "/w2", "pwd": "/w2/p2"},
        ]
        ph._print_table(entries, str(Path("/tmp")))
        captured = capsys.readouterr()
        assert "No" in captured.out
        assert "Timestamp" in captured.out
        assert "Session ID" in captured.out
        assert "Project Workspace" in captured.out
        assert "PWD" in captured.out
        assert "s1" in captured.out
        assert "(temp)" in captured.out
        assert "Total: 2 entries" in captured.out
        assert "Running" in captured.out
        assert "Idle" in captured.out

    def test_running_session_highlighted(self, tmp_path: Path, capsys):
        task_dir = tmp_path / ph.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / f"s1.{os.getpid()}.session.stdout").write_text("")

        entries = [
            {"ts": "2024-03-09T12:00:00+0800", "session_id": "s1", "project_workspace": "/w1", "pwd": "/w1/p1"},
        ]
        ph._print_table(entries, str(tmp_path))
        captured = capsys.readouterr()
        assert "s1" in captured.out
        assert Colors.GREEN in captured.out


class TestMain:
    def test_main_with_entries(self, tmp_path: Path, capsys):
        filepath = tmp_path / ph.HISTORY_FILENAME
        entry = {"ts": 1709913600000, "session_id": "s1", "project_workspace": "/w1", "pwd": "/w1/p1"}
        filepath.write_text(json.dumps(entry) + "\n")

        with patch.object(ph, "get_topsailai_home", return_value=str(tmp_path)):
            code = ph.main(["--limit", "5"])

        captured = capsys.readouterr()
        assert code == 0
        assert "s1" in captured.out

    def test_main_no_entries(self, tmp_path: Path, capsys):
        with patch.object(ph, "get_topsailai_home", return_value=str(tmp_path)):
            code = ph.main(["--limit", "5"])

        captured = capsys.readouterr()
        assert code == 0
        assert "No project history entries found" in captured.out

    def test_main_invalid_limit(self, capsys):
        code = ph.main(["--limit", "0"])
        captured = capsys.readouterr()
        assert code == 1
        assert "must be a positive integer" in captured.out

    def test_main_custom_home(self, tmp_path: Path, capsys):
        filepath = tmp_path / ph.HISTORY_FILENAME
        entry = {"ts": 1709913600000, "session_id": "s1", "project_workspace": "/w1", "pwd": "/w1/p1"}
        filepath.write_text(json.dumps(entry) + "\n")

        code = ph.main(["--home", str(tmp_path), "--limit", "1"])
        captured = capsys.readouterr()
        assert code == 0
        assert "s1" in captured.out
