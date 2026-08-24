"""Unit tests for the memory reconciliation CLI.

Author: DawsonLin
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

CLI_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = CLI_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(CLI_DIR))

import topsailai_memory_reconcile as cli


SUMMARY = {
    "scanned": 7,
    "healthy": 2,
    "rebuilt": 1,
    "purged_orphan": 1,
    "quarantined": 2,
    "errors": 1,
    "dry_run": True,
    "elapsed_ms": 12,
}


class TestParseArgs:
    """Verify safe dry-run argument defaults and overrides."""

    def test_default_enables_dry_run(self):
        """No arguments keep reconciliation in dry-run mode."""
        assert cli._parse_args([]).dry_run is True

    def test_help_explains_actions_and_safe_default(self, capsys):
        """Explain reconciliation actions and how to apply them."""
        with pytest.raises(SystemExit) as exc_info:
            cli._parse_args(["--help"])
        help_text = " ".join(capsys.readouterr().out.split())
        assert exc_info.value.code == 0
        assert "Missing stats may be rebuilt" in help_text
        assert "malformed stats quarantined" in help_text
        assert "--no-dry-run to apply" in help_text

    def test_explicit_dry_run_enables_dry_run(self):
        """The positive flag explicitly enables dry-run mode."""
        assert cli._parse_args(["--dry-run"]).dry_run is True

    def test_no_dry_run_disables_dry_run(self):
        """The negative flag explicitly enables filesystem changes."""
        assert cli._parse_args(["--no-dry-run"]).dry_run is False


class TestMain:
    """Verify facade forwarding, output, and exit codes."""

    @patch.object(cli.story_memory_tool, "reconcile_memories", return_value=SUMMARY)
    def test_default_forwards_dry_run_and_prints_summary(
        self, mock_reconcile, capsys
    ):
        """Default execution forwards dry-run and prints every summary field."""
        code = cli.main([])

        captured = capsys.readouterr()
        assert code == 0
        assert json.loads(captured.out) == SUMMARY
        assert captured.err == ""
        mock_reconcile.assert_called_once_with(dry_run=True)

    @patch.object(cli.story_memory_tool, "reconcile_memories")
    def test_no_dry_run_forwards_execute_mode(self, mock_reconcile, capsys):
        """The negative flag forwards live execution mode to the facade."""
        live_summary = dict(SUMMARY, dry_run=False)
        mock_reconcile.return_value = live_summary

        code = cli.main(["--no-dry-run"])

        captured = capsys.readouterr()
        assert code == 0
        assert json.loads(captured.out) == live_summary
        assert captured.err == ""
        mock_reconcile.assert_called_once_with(dry_run=False)

    @patch.object(
        cli.story_memory_tool,
        "reconcile_memories",
        side_effect=PermissionError("denied"),
    )
    def test_facade_error_returns_nonzero(self, mock_reconcile, capsys):
        """Facade failures produce stderr output and a non-zero exit code."""
        code = cli.main([])

        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert "memory reconciliation failed: denied" in captured.err
        mock_reconcile.assert_called_once_with(dry_run=True)


if __name__ == "__main__":
    pytest.main([__file__, "--color=no"])
