#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the memory eviction preview CLI."""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

CLI_DIR = Path(__file__).resolve().parents[2] / "cli"
sys.path.insert(0, str(CLI_DIR))

import topsailai_memory_evict as cli


class TestArguments:
    """Validate command-line argument handling."""

    def test_max_count_defaults_to_100(self):
        """Use a safe default when max-count is omitted."""
        args = cli.parse_args([])
        assert args.max_count == 100

    def test_help_explains_preview_and_deletion_safety(self, capsys):
        """Explain candidate selection and that eviction never deletes files."""
        with pytest.raises(SystemExit) as exc_info:
            cli.parse_args(["--help"])
        help_text = " ".join(capsys.readouterr().out.split())
        assert exc_info.value.code == 0
        assert "never deletes files" in help_text
        assert "eviction candidates" in help_text
        assert "topsailai_memory_delete" in help_text

    def test_valid_options(self):
        """Parse a workspace, max-count, and json option."""
        args = cli.parse_args(["--workspace", "/mem", "--max-count", "5", "--json"])
        assert args.workspace == "/mem"
        assert args.max_count == 5
        assert args.json is True

    def test_json_flag_defaults_off(self):
        """Json flag is disabled by default."""
        args = cli.parse_args(["--max-count", "5"])
        assert args.json is False

    def test_non_positive_max_count_rejected(self):
        """Reject zero or negative max-count values."""
        for bad in ("0", "-1"):
            with pytest.raises(SystemExit) as exc_info:
                cli.parse_args(["--max-count", bad])
            assert exc_info.value.code == 2

    def test_non_integer_max_count_rejected(self):
        """Reject a non-integer max-count value."""
        with pytest.raises(SystemExit) as exc_info:
            cli.parse_args(["--max-count", "abc"])
        assert exc_info.value.code == 2


class TestWorkspaceResolution:
    """Validate workspace source and path resolution."""

    def test_default_uses_memory_workspace(self, monkeypatch):
        """Use the configured memory workspace when no option is supplied."""
        monkeypatch.setattr(cli.story_memory_tool, "WORKSPACE", "/configured/memory")
        assert cli.resolve_workspace(None) == "/configured/memory"

    def test_default_falls_back_to_folder_memory(self, monkeypatch):
        """Fall back to FOLDER_MEMORY when the tool workspace is empty."""
        monkeypatch.setattr(cli.story_memory_tool, "WORKSPACE", "")
        monkeypatch.setattr(cli, "FOLDER_MEMORY", "/fallback/memory")
        assert cli.resolve_workspace(None) == "/fallback/memory"

    def test_absolute_workspace_is_preserved(self, tmp_path):
        """Normalize an explicit absolute workspace path."""
        assert cli.resolve_workspace(str(tmp_path)) == str(tmp_path)

    def test_relative_workspace_uses_original_pwd(self, tmp_path, monkeypatch):
        """Resolve relative paths against TOPSAILAI_PWD."""
        monkeypatch.setenv("TOPSAILAI_PWD", str(tmp_path))
        assert cli.resolve_workspace("memory") == str(tmp_path / "memory")

    def test_relative_workspace_falls_back_to_current_directory(
        self, tmp_path, monkeypatch
    ):
        """Resolve relative paths against cwd when TOPSAILAI_PWD is absent."""
        monkeypatch.delenv("TOPSAILAI_PWD", raising=False)
        monkeypatch.chdir(tmp_path)
        assert cli.resolve_workspace("memory") == str(tmp_path / "memory")


class TestCollectVictims:
    """Validate victim metadata collection."""

    def test_collects_victim_metadata(self):
        """Build victim rows from the eviction selector and stat reader."""
        fake_stat = {
            "memory_id": "mem-1",
            "last_activity_at": "2026-01-01T00:00:00",
            "sync_state": "synced",
        }
        with (
            patch.object(
                cli.memory_evict,
                "select_eviction_victims",
                return_value=[("/m/a.md", "/m/.stats/x.json")],
            ),
            patch.object(
                cli.memory_stat,
                "read_memory_stat_file",
                return_value=fake_stat,
            ),
            patch.object(
                cli.memory_stat,
                "is_memory_synced",
                return_value=True,
            ),
        ):
            victims = cli.collect_victims("/m", 99)
        assert victims == [
            {
                "memory_id": "mem-1",
                "last_activity_at": "2026-01-01T00:00:00",
                "synced": True,
            }
        ]

    def test_empty_when_no_victims(self):
        """Return an empty list when the selector finds nothing."""
        with patch.object(
            cli.memory_evict, "select_eviction_victims", return_value=[]
        ):
            assert cli.collect_victims("/m", 42) == []


class TestBuildResultAndFormat:
    """Validate result construction and text formatting."""

    def test_build_result_shape(self):
        """Assemble the dry-run result payload."""
        with (
            patch.object(cli, "collect_victims", return_value=[]),
            patch.object(
                cli.memory_evict,
                "maybe_evict_memory_stats",
                return_value=Mock(to_dict=lambda: {"scanned": 2, "would_evict": 0}),
            ),
        ):
            result = cli.build_result("/m", 77)
        assert result["workspace"] == "/m"
        assert result["max_count"] == 77
        assert result["dry_run"] is True
        assert result["victims"] == []
        assert result["summary"]["scanned"] == 2

    def test_format_text_mentions_no_deletion(self):
        """Text output states that no files were deleted."""
        result = {
            "workspace": "/m",
            "max_count": 88,
            "sort": cli.SORT_DESCRIPTION,
            "victims": [],
            "summary": {
                "scanned": 1,
                "eligible": 0,
                "evicted": 0,
                "protected_unsynced": 1,
                "errors": 0,
            },
        }
        text = cli.format_text(result)
        assert "Workspace: /m" in text
        assert "No files were deleted." in text
        assert "scanned=1" in text


class TestMain:
    """Validate the main entry point."""

    def test_main_json_output(self, capsys):
        """Print valid JSON when --json is supplied."""
        with (
            patch.object(cli, "resolve_workspace", return_value="/m"),
            patch.object(
                cli,
                "build_result",
                return_value={
                    "workspace": "/m",
                    "max_count": 66,
                    "dry_run": True,
                    "sort": cli.SORT_DESCRIPTION,
                    "victims": [],
                    "summary": {},
                },
            ),
        ):
            rc = cli.main(["--max-count", "66", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        assert json.loads(out)["workspace"] == "/m"

    def test_main_text_output(self, capsys):
        """Print human-readable text by default."""
        with (
            patch.object(cli, "resolve_workspace", return_value="/m"),
            patch.object(
                cli,
                "build_result",
                return_value={
                    "workspace": "/m",
                    "max_count": 44,
                    "dry_run": True,
                    "sort": cli.SORT_DESCRIPTION,
                    "victims": [],
                    "summary": {
                        "scanned": 0,
                        "eligible": 0,
                        "evicted": 0,
                        "protected_unsynced": 0,
                        "errors": 0,
                    },
                },
            ),
        ):
            rc = cli.main(["--max-count", "44"])
        assert rc == 0
        assert "Memory eviction dry-run" in capsys.readouterr().out

    def test_main_error_returns_one(self, capsys):
        """Return exit code 1 and print an error on failure."""
        with (
            patch.object(cli, "resolve_workspace", return_value="/m"),
            patch.object(
                cli, "build_result", side_effect=RuntimeError("boom")
            ),
        ):
            rc = cli.main(["--max-count", "5"])
        assert rc == 1
        assert "Error: boom" in capsys.readouterr().err
