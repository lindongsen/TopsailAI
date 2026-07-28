"""Unit tests for topsailai_format_response.py."""

import io
import json
import sys
from unittest import mock

import _import_topsailai  # noqa: F401
import pytest

import topsailai_format_response as cli


class TestFormatResponseCli:
    """Tests for the format_response CLI."""

    def test_format_json_text(self):
        text = json.dumps({"step_name": "thought", "raw_text": "hello"})
        result = cli.format_response_text(text)
        parsed = json.loads(result)
        assert parsed == [{"step_name": "thought", "raw_text": "hello"}]

    def test_format_topsailai_text(self):
        text = "topsailai.thought\nhello\n\ntopsailai.action\ntool\narg"
        result = cli.format_response_text(text)
        parsed = json.loads(result)
        assert parsed[0]["step_name"] == "thought"
        assert parsed[0]["raw_text"] == "hello"
        assert parsed[1]["step_name"] == "action"

    def test_format_invalid_text_raises(self):
        with pytest.raises(Exception):
            cli.format_response_text("[think]hello[/think]")

    def test_read_from_file(self, tmp_path):
        path = tmp_path / "response.txt"
        path.write_text(json.dumps({"step_name": "thought", "raw_text": "file"}))
        assert cli.read_input(str(path)) == path.read_text()

    def test_read_from_stdin(self):
        with mock.patch("sys.stdin", io.StringIO("stdin text")):
            assert cli.read_input("-") == "stdin text"

    def test_main_text(self, capsys):
        cli.main(["--text", json.dumps({"step_name": "thought", "raw_text": "hi"})])
        captured = capsys.readouterr()
        assert '"raw_text": "hi"' in captured.out

    def test_main_file(self, tmp_path, capsys):
        path = tmp_path / "response.txt"
        path.write_text(json.dumps({"step_name": "thought", "raw_text": "file"}))
        cli.main(["--file", str(path)])
        captured = capsys.readouterr()
        assert '"raw_text": "file"' in captured.out

    def test_main_stdin(self, capsys):
        with mock.patch("sys.stdin", io.StringIO('{"step_name":"thought","raw_text":"stdin"}')):
            cli.main(["-"])
        captured = capsys.readouterr()
        assert '"raw_text": "stdin"' in captured.out

    def test_main_compact(self, capsys):
        cli.main(["--text", json.dumps({"step_name": "thought", "raw_text": "hi"}), "--compact"])
        captured = capsys.readouterr()
        assert captured.out.startswith('[{"step_name"')

    def test_main_no_input(self):
        assert cli.main([]) != 0

    def test_format_topsailai_text(self):
        text = json.dumps({"step_name": "thought", "raw_text": "hello"})
        result = cli.format_response_text(text, fmt="topsailai")
        assert "topsailai.thought" in result
        assert "hello" in result

    def test_format_topsailai_text_with_action(self):
        text = (
            "topsailai.thought\n"
            "hello\n\n"
            "topsailai.action\n"
            '{"tool_call": "tool", "tool_args": {}}\n'
        )
        result = cli.format_response_text(text, fmt="topsailai")
        assert "topsailai.thought" in result
        assert "hello" in result
        assert "topsailai.action" in result

    def test_main_text_topsailai_format(self, capsys):
        cli.main([
            "--text",
            json.dumps({"step_name": "thought", "raw_text": "hi"}),
            "--format",
            "topsailai",
        ])
        captured = capsys.readouterr()
        assert "topsailai.thought" in captured.out
        assert "hi" in captured.out

    def test_main_file_topsailai_format(self, tmp_path, capsys):
        path = tmp_path / "response.txt"
        path.write_text(json.dumps({"step_name": "thought", "raw_text": "file"}))
        cli.main(["--file", str(path), "--format", "topsailai"])
        captured = capsys.readouterr()
        assert "topsailai.thought" in captured.out
        assert "file" in captured.out

    def test_main_stdin_topsailai_format(self, capsys):
        with mock.patch(
            "sys.stdin", io.StringIO('{"step_name":"thought","raw_text":"stdin"}')
        ):
            cli.main(["-", "--format", "topsailai"])
        captured = capsys.readouterr()
        assert "topsailai.thought" in captured.out
        assert "stdin" in captured.out

    def test_main_default_format_is_json(self, capsys):
        cli.main(["--text", json.dumps({"step_name": "thought", "raw_text": "hi"})])
        captured = capsys.readouterr()
        assert '"raw_text": "hi"' in captured.out
