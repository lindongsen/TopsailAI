#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the memory eviction dry-run CLI."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

CLI_DIR = Path(__file__).resolve().parents[2] / "cli"
sys.path.insert(0, str(CLI_DIR))

import topsailai_memory_evict as cli


class TestArguments:
    """Validate command-line argument handling."""

    @pytest.mark.parametrize("value", ["0", "-1", "invalid"])
    def test_max_count_requires_positive_integer(self, value):
        """Reject zero, negative, and non-integer max-count values."""
        with pytest.raises(SystemExit) as exc_info:
            cli.parse_args(["--max-count", value])
        assert exc_info.value.code == 2

    def test_max_count_is_required(self):
        """Reject invocation without an explicit max-count."""
        with pytest.raises(SystemExit) as exc_info:
            cli.parse_args([])
        assert exc_info.value.code == 2

    def test_valid_options(self):
        """Parse explicit workspace, max-count, and JSON options."""
        args = cli.parse_args(
            ["--workspace", "/memory", "--max-count", "3", "--json"]
        )
        assert args.workspace == "/memory"
        assert args.max_count == 3
        assert args.json is True


class TestWorkspaceResolution:
    """Validate workspace source and path resolution."""

    def test_default_uses_topsailai_home(self, monkeypatch):
        """Use the folder-constant TOPSAILAI_HOME when no option is supplied."""
        monkeypatch.setattr(cli, "TOPSAILAI_HOME", "/configured/home")
        assert cli.resolve_workspace(None) == "/configured/home"

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


class TestResultBuilding:
    """Validate victim metadata and dry-run engine invocation."""

    def test_collect_victims_returns_ordered_metadata(self):
        """Read victim stats in the deterministic order selected by the engine."""
        selected = [("/story/b.md", "/stats/b.json"), ("/story/a.md", "/stats/a.json")]
        stats = {
            "/stats/b.json": {
                "memory_id": "b",
                "last_activity_at": "2026-01-01T00:00:00",
                "synced": True,
            },
            "/stats/a.json": {
                "memory_id": "a",
                "last_activity_at": "2026-01-01T00:00:01",
                "synced": True,
            },
        }
        with patch.object(
            cli.memory_evict, "select_eviction_victims", return_value=selected
        ), patch.object(
            cli.memory_stat, "read_memory_stat_file", side_effect=lambda path: stats[path]
        ):
            victims = cli.collect_victims("/memory", 1)
        assert [victim["memory_id"] for victim in victims] == ["b", "a"]
        assert all(victim["synced"] is True for victim in victims)

    def test_build_result_forces_dry_run(self):
        """Always call the eviction engine with dry_run=True."""
        summary = SimpleNamespace(
            to_dict=lambda: {
                "scanned": 2,
                "eligible": 1,
                "evicted": 1,
                "protected_unsynced": 1,
                "errors": 0,
                "dry_run": True,
                "elapsed_ms": 1,
            }
        )
        with patch.object(cli, "collect_victims", return_value=[{"memory_id": "a"}]), patch.object(
            cli.memory_evict, "maybe_evict_memory_stats", return_value=summary
        ) as evict:
            result = cli.build_result("/memory", 1)
        evict.assert_called_once_with("/memory", 1, dry_run=True)
        assert result["dry_run"] is True
        assert result["victims"] == [{"memory_id": "a"}]
        assert result["summary"]["evicted"] == 1


class TestOutput:
    """Validate human-readable and JSON CLI output."""

    @staticmethod
    def result():
        """Return a representative dry-run result."""
        return {
            "workspace": "/memory",
            "max_count": 1,
            "dry_run": True,
            "sort": cli.SORT_DESCRIPTION,
            "victims": [
                {
                    "memory_id": "memory-a",
                    "last_activity_at": "2026-01-01T00:00:00",
                    "synced": True,
                }
            ],
            "summary": {
                "scanned": 2,
                "eligible": 1,
                "evicted": 1,
                "protected_unsynced": 1,
                "errors": 0,
                "dry_run": True,
                "elapsed_ms": 1,
            },
        }

    def test_human_readable_output(self):
        """Show victim metadata, sorting, summary, and no-delete assurance."""
        output = cli.format_text(self.result())
        assert "memory_id=memory-a" in output
        assert "last_activity_at=2026-01-01T00:00:00" in output
        assert "synced=True" in output
        assert cli.SORT_DESCRIPTION in output
        assert "would_evict=1" in output
        assert "No files were deleted" in output

    def test_main_prints_text(self, capsys):
        """Print human-readable output by default."""
        with patch.object(cli, "build_result", return_value=self.result()) as build:
            code = cli.main(["--workspace", "/memory", "--max-count", "1"])
        assert code == 0
        build.assert_called_once_with("/memory", 1)
        assert "Memory eviction dry-run" in capsys.readouterr().out

    def test_main_prints_json(self, capsys):
        """Print a structured victims and summary payload with --json."""
        with patch.object(cli, "build_result", return_value=self.result()):
            code = cli.main(
                ["--workspace", "/memory", "--max-count", "1", "--json"]
            )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert payload["victims"][0]["memory_id"] == "memory-a"
        assert payload["summary"]["evicted"] == 1

    def test_main_reports_engine_error(self, capsys):
        """Return a non-zero code when preview generation fails."""
        with patch.object(cli, "build_result", side_effect=OSError("unavailable")):
            code = cli.main(["--max-count", "1"])
        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert "Error: unavailable" in captured.err
