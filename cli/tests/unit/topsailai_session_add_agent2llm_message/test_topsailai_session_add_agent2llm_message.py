"""Unit tests for topsailai_session_add_agent2llm_message.py CLI."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure cli/ is importable.
CLI_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CLI_DIR))

import topsailai_session_add_agent2llm_message as cli_module
from topsailai_session_add_agent2llm_message import (
    JSONL_SUFFIX,
    build_inject_path,
    discover_jsonl_files,
    parse_stdout_filename,
)
from topsailai.workspace.agent.runtime_message_sources.file import write_message


class TestParseStdoutFilename:
    def test_valid(self):
        assert parse_stdout_filename("abc-001.12345.session.stdout") == (
            "abc-001",
            "12345",
        )

    def test_no_session(self):
        assert parse_stdout_filename("topsailai.12345.session.stdout") == (
            "topsailai",
            "12345",
        )

    def test_invalid(self):
        assert parse_stdout_filename("something.else.txt") == (None, None)


class TestBuildInjectPath:
    def test_build(self):
        path = build_inject_path("abc", "123")
        assert path.endswith("abc.123.session.agent2llm_inject_messages.jsonl")


class TestDiscoverJsonlFiles:
    def test_specific_session_and_pid(self, tmp_path):
        (tmp_path / "abc.123.session.stdout").write_text("")
        jsonl = tmp_path / "abc.123.session.agent2llm_inject_messages.jsonl"
        jsonl.write_text("")

        result = discover_jsonl_files(
            str(tmp_path),
            session_id="abc",
            pid="123",
            jsonl_suffix=JSONL_SUFFIX,
        )
        assert result == [str(jsonl)]

    def test_all_sessions(self, tmp_path):
        (tmp_path / "abc.123.session.stdout").write_text("")
        (tmp_path / "abc.123.session.agent2llm_inject_messages.jsonl").write_text("")
        (tmp_path / "def.456.session.stdout").write_text("")
        (tmp_path / "def.456.session.agent2llm_inject_messages.jsonl").write_text("")

        result = discover_jsonl_files(
            str(tmp_path),
            session_id=None,
            pid=None,
            jsonl_suffix=JSONL_SUFFIX,
        )
        assert len(result) == 2

    def test_missing_jsonl(self, tmp_path):
        (tmp_path / "abc.123.session.stdout").write_text("")
        result = discover_jsonl_files(
            str(tmp_path),
            session_id=None,
            pid=None,
            jsonl_suffix=JSONL_SUFFIX,
        )
        assert len(result) == 1
        assert result[0].endswith("abc.123.session.agent2llm_inject_messages.jsonl")


class TestWriteMessage:
    def test_appends_simple_message(self, tmp_path):
        jsonl = tmp_path / "messages.jsonl"
        write_message(str(jsonl), "hello")
        lines = jsonl.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["content"]["raw_text"] == "hello"
        assert "ts" in record

    def test_appends_structured_message(self, tmp_path):
        jsonl = tmp_path / "messages.jsonl"
        write_message(str(jsonl), {"step_name": "observation", "raw_text": "hi"})
        lines = jsonl.read_text().strip().splitlines()
        record = json.loads(lines[0])
        assert record["content"]["step_name"] == "observation"
        assert record["content"]["raw_text"] == "hi"
        assert "ts" in record

    def test_ts_is_added_when_missing(self, tmp_path):
        jsonl = tmp_path / "messages.jsonl"
        before = datetime.now(timezone.utc)
        write_message(str(jsonl), "hello")
        after = datetime.now(timezone.utc)
        record = json.loads(jsonl.read_text().strip().splitlines()[0])
        ts = datetime.fromisoformat(record["ts"])
        assert before <= ts <= after


class TestMain:
    def _run_main(self, argv, tmp_path):
        """Run the CLI main with patched task folder and argv."""
        import importlib

        importlib.reload(cli_module)
        with patch.object(cli_module, "FOLDER_WORKSPACE_TASK", str(tmp_path)):
            with patch.object(sys, "argv", argv):
                return cli_module.main()

    def test_no_matches_exits_nonzero(self, tmp_path, capsys):
        code = self._run_main(
            ["script", "-s", "missing", "-p", "99999", "-m", "hello"],
            tmp_path,
        )
        assert code != 0
        captured = capsys.readouterr()
        assert "No matching" in captured.err

    def test_writes_to_discovered_file(self, tmp_path, capsys):
        (tmp_path / "abc.123.session.stdout").write_text("")
        jsonl = tmp_path / "abc.123.session.agent2llm_inject_messages.jsonl"
        jsonl.write_text("")

        code = self._run_main(
            ["script", "-s", "abc", "-p", "123", "-m", "hello"],
            tmp_path,
        )

        assert code == 0
        captured = capsys.readouterr()
        assert "Message written" in captured.out
        record = json.loads(jsonl.read_text().strip().splitlines()[0])
        assert record["content"]["raw_text"] == "hello"
        assert "ts" in record

    def test_multi_line_input(self, tmp_path, monkeypatch):
        (tmp_path / "abc.123.session.stdout").write_text("")
        jsonl = tmp_path / "abc.123.session.agent2llm_inject_messages.jsonl"
        jsonl.write_text("")

        inputs = iter(["line1", "line2", "EOF"])
        monkeypatch.setattr("builtins.input", lambda _="": next(inputs))

        code = self._run_main(
            ["script", "-s", "abc", "-p", "123"],
            tmp_path,
        )

        assert code == 0
        record = json.loads(jsonl.read_text().strip().splitlines()[0])
        assert record["content"]["raw_text"] == "line1\nline2"
