#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for topsailai_count_tokens.py."""

import io
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

CLI_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = CLI_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(CLI_DIR))

import topsailai_count_tokens


class TestCountTokensCLI:
    """Tests for the token counting CLI."""

    def test_count_text(self, capsys):
        """Token count is printed for raw text input."""
        with patch.object(sys, "argv", ["topsailai_count_tokens", "--text", "hello world"]):
            code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 0
        assert captured.out.strip() == "2"
        assert captured.err == ""

    def test_count_file(self, tmp_path, capsys):
        """Token count is printed for file content input."""
        file_path = tmp_path / "sample.txt"
        file_path.write_text("hello world", encoding="utf-8")

        with patch.object(
            sys, "argv", ["topsailai_count_tokens", "--file", str(file_path)]
        ):
            code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 0
        assert captured.out.strip() == "2"
        assert captured.err == ""

    def test_missing_file(self, capsys):
        """A missing file path returns a non-zero exit code and an error."""
        with patch.object(
            sys, "argv", ["topsailai_count_tokens", "--file", "/tmp/does_not_exist.txt"]
        ):
            code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 1
        assert "file not found" in captured.err
        assert captured.out == ""

    def test_text_and_file_mutually_exclusive(self, capsys):
        """Passing both --text and --file triggers argparse error."""
        with patch.object(
            sys,
            "argv",
            [
                "topsailai_count_tokens",
                "--text",
                "hello",
                "--file",
                "/tmp/sample.txt",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                topsailai_count_tokens.main()

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "not allowed with argument" in captured.err

    def test_encoding_option(self, capsys):
        """A custom encoding name is forwarded to count_tokens."""
        with patch(
            "topsailai_count_tokens.count_tokens", return_value=42
        ) as mock_count:
            with patch.object(
                sys,
                "argv",
                [
                    "topsailai_count_tokens",
                    "--text",
                    "hello world",
                    "--encoding",
                    "p50k_base",
                ],
            ):
                code = topsailai_count_tokens.main()

        assert code == 0
        mock_count.assert_called_once_with("hello world", encoding_name="p50k_base")
        captured = capsys.readouterr()
        assert captured.out.strip() == "42"

    def test_empty_text(self, capsys):
        """Empty text input should produce a token count of zero."""
        with patch.object(sys, "argv", ["topsailai_count_tokens", "--text", ""]):
            code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 0
        assert captured.out.strip() == "0"

    def test_count_multiple_files(self, tmp_path, capsys):
        """Token counts are printed with paths for multiple positional files."""
        file1 = tmp_path / "first.txt"
        file2 = tmp_path / "second.txt"
        file1.write_text("hello world", encoding="utf-8")
        file2.write_text("another sample file content", encoding="utf-8")

        with patch.object(
            sys,
            "argv",
            [
                "topsailai_count_tokens",
                str(file1),
                str(file2),
            ],
        ):
            code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 0
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == f"2 {file1}"
        assert lines[1] == f"4 {file2}"
        assert captured.err == ""

    def test_count_multiple_files_with_missing_file(self, tmp_path, capsys):
        """Missing positional files are reported and the exit code is non-zero."""
        existing = tmp_path / "existing.txt"
        existing.write_text("hello world", encoding="utf-8")
        missing = tmp_path / "missing.txt"

        with patch.object(
            sys,
            "argv",
            [
                "topsailai_count_tokens",
                str(existing),
                str(missing),
            ],
        ):
            code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 1
        assert f"2 {existing}" in captured.out
        assert "file not found" in captured.err
        assert str(missing) in captured.err

    def test_no_arguments(self, capsys):
        """Running without any arguments reports a usage error."""
        with patch.object(sys, "argv", ["topsailai_count_tokens"]):
            code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 2
        assert "provide --text, --file, or one or more file paths" in captured.err
        assert captured.out == ""

    def test_text_with_positional_files(self, capsys):
        """--text combined with positional files is rejected."""
        with patch.object(
            sys,
            "argv",
            [
                "topsailai_count_tokens",
                "--text",
                "hello",
                "/tmp/sample.txt",
            ],
        ):
            code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 2
        assert "--text cannot be used with positional file arguments" in captured.err
        assert captured.out == ""

    def test_file_option_with_positional_files(self, capsys):
        """--file combined with positional files is rejected."""
        with patch.object(
            sys,
            "argv",
            [
                "topsailai_count_tokens",
                "--file",
                "/tmp/sample.txt",
                "/tmp/other.txt",
            ],
        ):
            code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 2
        assert "--file cannot be used with positional file arguments" in captured.err
        assert captured.out == ""

    def test_relative_path_with_topsailai_pwd(self, tmp_path, capsys, monkeypatch):
        """Relative paths are resolved against TOPSAILAI_PWD when set."""
        file_path = tmp_path / "relative.txt"
        file_path.write_text("hello world", encoding="utf-8")
        monkeypatch.setenv("TOPSAILAI_PWD", str(tmp_path))

        with patch.object(
            sys,
            "argv",
            [
                "topsailai_count_tokens",
                "relative.txt",
            ],
        ):
            code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 0
        assert captured.out.strip() == "2 relative.txt"
        assert captured.err == ""

    def test_relative_path_with_file_option(self, tmp_path, capsys, monkeypatch):
        """Relative paths passed via --file are resolved against TOPSAILAI_PWD."""
        file_path = tmp_path / "relative.txt"
        file_path.write_text("hello world", encoding="utf-8")
        monkeypatch.setenv("TOPSAILAI_PWD", str(tmp_path))

        with patch.object(
            sys,
            "argv",
            [
                "topsailai_count_tokens",
                "--file",
                "relative.txt",
            ],
        ):
            code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 0
        assert captured.out.strip() == "2"
        assert captured.err == ""

    def test_count_from_stdin(self, capsys):
        """Passing '-' as a positional argument reads from stdin."""
        stdin = io.StringIO("hello world")
        with patch.object(sys, "stdin", stdin):
            with patch.object(
                sys, "argv", ["topsailai_count_tokens", "-"]
            ):
                code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 0
        assert captured.out.strip() == "2 -"
        assert captured.err == ""

    def test_count_stdin_mixed_with_files(self, tmp_path, capsys):
        """'-' can be combined with regular file arguments."""
        file_path = tmp_path / "sample.txt"
        file_path.write_text("another sample", encoding="utf-8")
        stdin = io.StringIO("hello world")

        with patch.object(sys, "stdin", stdin):
            with patch.object(
                sys,
                "argv",
                [
                    "topsailai_count_tokens",
                    "-",
                    str(file_path),
                ],
            ):
                code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 0
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "2 -"
        assert lines[1] == f"2 {file_path}"
        assert captured.err == ""

    def test_count_empty_stdin(self, capsys):
        """Empty stdin input produces a token count of zero."""
        stdin = io.StringIO("")
        with patch.object(sys, "stdin", stdin):
            with patch.object(
                sys, "argv", ["topsailai_count_tokens", "-"]
            ):
                code = topsailai_count_tokens.main()

        captured = capsys.readouterr()
        assert code == 0
        assert captured.out.strip() == "0 -"
        assert captured.err == ""
