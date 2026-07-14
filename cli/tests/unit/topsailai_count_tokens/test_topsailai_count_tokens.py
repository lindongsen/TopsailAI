#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for topsailai_count_tokens.py."""

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
        """Passing both --text and --text triggers argparse error."""
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
