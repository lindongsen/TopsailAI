#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the memory deletion CLI."""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

CLI_DIR = Path(__file__).resolve().parents[2] / "cli"
sys.path.insert(0, str(CLI_DIR))

import topsailai_memory_delete as cli


class TestArguments:
    """Validate command-line argument handling."""

    def test_title_positional_is_required(self):
        """Reject invocation without a title argument."""
        with pytest.raises(SystemExit) as exc_info:
            cli.parse_args([])
        assert exc_info.value.code == 2

    def test_valid_options(self):
        """Parse a title, home, yes, and json options."""
        args = cli.parse_args(
            ["My_Memory", "--home", "/memory", "--yes", "--json"]
        )
        assert args.title == "My_Memory"
        assert args.home == "/memory"
        assert args.yes is True
        assert args.json is True

    def test_default_flags_off(self):
        """Default yes and json flags are disabled."""
        args = cli.parse_args(["My_Memory"])
        assert args.yes is False
        assert args.json is False


class TestHomeResolution:
    """Validate home source and memory-path resolution."""

    def test_default_uses_memory_home(self, monkeypatch):
        """Use the configured memory workspace when no option is supplied."""
        monkeypatch.setattr(
            cli.story_memory_tool, "WORKSPACE", "/configured/memory"
        )
        assert cli.resolve_home(None) == "/configured/memory"

    def test_absolute_home_appends_memory(self, tmp_path):
        """Append memory to an explicit TOPSAILAI_HOME path."""
        assert cli.resolve_home(str(tmp_path)) == str(tmp_path / "memory")

    def test_memory_root_with_story_is_preserved(self, tmp_path):
        """Keep an explicit home that already contains story/."""
        (tmp_path / "story").mkdir()
        assert cli.resolve_home(str(tmp_path)) == str(tmp_path)

    def test_relative_home_uses_original_pwd(self, tmp_path, monkeypatch):
        """Resolve relative paths against TOPSAILAI_PWD."""
        monkeypatch.setenv("TOPSAILAI_PWD", str(tmp_path))
        assert cli.resolve_home("memory") == str(tmp_path / "memory" / "memory")

    def test_relative_home_falls_back_to_current_directory(
        self, tmp_path, monkeypatch
    ):
        """Resolve relative paths against cwd when TOPSAILAI_PWD is absent."""
        monkeypatch.delenv("TOPSAILAI_PWD", raising=False)
        monkeypatch.chdir(tmp_path)
        assert cli.resolve_home("memory") == str(tmp_path / "memory" / "memory")


class TestMemoryResolution:
    """Validate memory file resolution."""

    def test_resolve_memory_file_delegates(self):
        """Delegate to the story file resolver with must_only_one."""
        with patch.object(
            cli.story_memory_tool.StoryFileInstance,
            "get_story_file",
            return_value="/memory/story/2026/Mem.md",
        ) as resolver:
            path = cli.resolve_memory_file("/memory", "Mem")
        resolver.assert_called_once_with("/memory", "Mem", must_only_one=True)
        assert path == "/memory/story/2026/Mem.md"

    def test_resolve_memory_file_not_found(self):
        """Return None when no memory file matches."""
        with patch.object(
            cli.story_memory_tool.StoryFileInstance,
            "get_story_file",
            return_value=None,
        ):
            assert cli.resolve_memory_file("/memory", "Missing") is None


class TestConfirmation:
    """Validate the confirmation prompt."""

    def test_non_tty_denies_confirmation(self, monkeypatch):
        """Non-interactive stdin denies deletion by default."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        assert cli.confirm_deletion("Mem", "/memory/story/Mem.md") is False

    def test_yes_answer_confirms(self, monkeypatch):
        """An affirmative answer confirms deletion."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda: "y")
        assert cli.confirm_deletion("Mem", "/memory/story/Mem.md") is True

    def test_eof_denies_confirmation(self, monkeypatch):
        """End-of-file input denies deletion."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", Mock(side_effect=EOFError))
        assert cli.confirm_deletion("Mem", "/memory/story/Mem.md") is False


class TestResultBuilding:
    """Validate result payload construction."""

    def test_build_result(self):
        """Assemble workspace, title, memory file, and deleted flag."""
        result = cli.build_result("/memory", "Mem", "/memory/story/Mem.md", True)
        assert result == {
            "workspace": "/memory",
            "title": "Mem",
            "memory_file": "/memory/story/Mem.md",
            "deleted": True,
        }


class TestMain:
    """Validate end-to-end CLI behavior."""

    def test_deletes_with_yes_flag(self, capsys):
        """Delete the memory when --yes is supplied."""
        with patch.object(
            cli, "resolve_memory_file", return_value="/memory/story/Mem.md"
        ), patch.object(
            cli.story_memory_tool, "delete_memory", return_value=True
        ) as deleter:
            code = cli.main(["--home", "/memory", "--yes", "Mem"])
        assert code == 0
        deleter.assert_called_once_with("Mem")
        assert "Deleted memory: Mem" in capsys.readouterr().out

    def test_aborts_when_unconfirmed(self, capsys):
        """Cancel deletion when confirmation is denied."""
        with patch.object(
            cli, "resolve_memory_file", return_value="/memory/story/Mem.md"
        ), patch.object(cli, "confirm_deletion", return_value=False), patch.object(
            cli.story_memory_tool, "delete_memory"
        ) as deleter:
            code = cli.main(["--home", "/memory", "Mem"])
        assert code == 0
        deleter.assert_not_called()
        assert "Aborted: deletion cancelled." in capsys.readouterr().out

    def test_not_found_returns_error(self, capsys):
        """Return a non-zero code when the memory does not exist."""
        with patch.object(cli, "resolve_memory_file", return_value=None):
            code = cli.main(["--home", "/memory", "--yes", "Missing"])
        captured = capsys.readouterr()
        assert code == 1
        assert "No memory found" in captured.err

    def test_json_output(self, capsys):
        """Print a structured payload with --json."""
        with patch.object(
            cli, "resolve_memory_file", return_value="/memory/story/Mem.md"
        ), patch.object(
            cli.story_memory_tool, "delete_memory", return_value=True
        ):
            code = cli.main(
                ["--home", "/memory", "--yes", "--json", "Mem"]
            )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["deleted"] is True
        assert payload["title"] == "Mem"

    def test_reports_delete_error(self, capsys):
        """Return a non-zero code when deletion fails."""
        with patch.object(
            cli, "resolve_memory_file", return_value="/memory/story/Mem.md"
        ), patch.object(
            cli.story_memory_tool, "delete_memory", side_effect=OSError("locked")
        ):
            code = cli.main(["--home", "/memory", "--yes", "Mem"])
        captured = capsys.readouterr()
        assert code == 1
        assert "Error: locked" in captured.err
