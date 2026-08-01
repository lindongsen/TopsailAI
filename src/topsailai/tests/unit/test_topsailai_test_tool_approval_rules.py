#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for topsailai_test_tool_approval_rules.py."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
CLI_DIR = Path(__file__).resolve().parents[2] / "cli"
SRC_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(CLI_DIR))

import topsailai_test_tool_approval_rules as cli_module


@pytest.fixture(autouse=True)
def _clear_rules_cache():
    """Clear the matcher rule cache before and after each test."""
    cli_module.clear_approval_rules_cache()
    yield
    cli_module.clear_approval_rules_cache()


@pytest.fixture
def rules_file(tmp_path):
    """Create a single valid rule file."""
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "require echo",
                    "match": "cmd_tool-exec_cmd",
                    "mode": "require",
                    "params": [
                        {"param": "cmd", "op": "contains", "value": "echo"}
                    ],
                    "priority": 1,
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


class TestRuleLoading:
    """Tests for rule loading via --rules and environment variables."""

    def test_single_file_path(self, rules_file, capsys):
        """A single --rules file is loaded and reported."""
        code = cli_module.main(["--rules", str(rules_file)])
        captured = capsys.readouterr()
        assert code == 0
        assert "Loaded 1 approval rule(s)" in captured.out
        assert str(rules_file) in captured.out
        assert "require echo" in captured.out

    def test_multiple_file_paths(self, tmp_path, capsys):
        """Multiple --rules files separated by ';' are merged."""
        file_a = tmp_path / "a.json"
        file_b = tmp_path / "b.json"
        file_a.write_text(
            json.dumps(
                [
                    {
                        "name": "rule a",
                        "match": "cmd_tool-exec_cmd",
                        "mode": "require",
                        "priority": 10,
                    }
                ]
            ),
            encoding="utf-8",
        )
        file_b.write_text(
            json.dumps(
                [
                    {
                        "name": "rule b",
                        "match": "file_tool-write_file",
                        "mode": "require",
                        "priority": 5,
                    }
                ]
            ),
            encoding="utf-8",
        )

        code = cli_module.main(["--rules", f"{file_a};{file_b}"])
        captured = capsys.readouterr()
        assert code == 0
        assert "Loaded 2 approval rule(s)" in captured.out
        assert "rule a" in captured.out
        assert "rule b" in captured.out

    def test_inline_json_rules(self, capsys):
        """An inline JSON array passed to --rules is parsed."""
        inline = json.dumps(
            [
                {
                    "name": "inline rule",
                    "match": "cmd_tool-exec_cmd",
                    "mode": "require",
                }
            ]
        )
        code = cli_module.main(["--rules", inline])
        captured = capsys.readouterr()
        assert code == 0
        assert "Loaded 1 approval rule(s)" in captured.out
        assert "inline rule" in captured.out

    def test_inline_json_with_semicolon(self, capsys):
        """An inline JSON value containing ';' is not split."""
        inline = json.dumps(
            [
                {
                    "name": "inline semicolon",
                    "match": "cmd_tool-exec_cmd",
                    "mode": "require",
                    "params": [
                        {"param": "cmd", "op": "contains", "value": "a;b"}
                    ],
                }
            ]
        )
        code = cli_module.main(["--rules", inline])
        captured = capsys.readouterr()
        assert code == 0
        assert "Loaded 1 approval rule(s)" in captured.out
        assert "inline semicolon" in captured.out

    def test_rules_from_environment_variable(self, rules_file, capsys):
        """When --rules is omitted, TOPSAILAI_TOOL_APPROVAL_RULES is used."""
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_RULES": str(rules_file)}, clear=True):
            code = cli_module.main([])
        captured = capsys.readouterr()
        assert code == 0
        assert "Loaded 1 approval rule(s)" in captured.out
        assert "require echo" in captured.out

    def test_rules_argument_overrides_environment(self, tmp_path, rules_file, capsys):
        """--rules takes precedence over the environment variable."""
        other = tmp_path / "other.json"
        other.write_text(
            json.dumps(
                [
                    {
                        "name": "other rule",
                        "match": "cmd_tool-exec_cmd",
                        "mode": "require",
                    }
                ]
            ),
            encoding="utf-8",
        )
        with patch.dict(
            os.environ, {"TOPSAILAI_TOOL_APPROVAL_RULES": str(other)}, clear=True
        ):
            code = cli_module.main(["--rules", str(rules_file)])
        captured = capsys.readouterr()
        assert code == 0
        assert "require echo" in captured.out
        assert "other rule" not in captured.out


class TestEvaluation:
    """Tests for tool call evaluation output."""

    def test_default_regression_suite_runs(self, rules_file, capsys):
        """The built-in regression suite executes without error."""
        code = cli_module.main(["--rules", str(rules_file)])
        captured = capsys.readouterr()
        assert code == 0
        assert "Case 1" in captured.out

    def test_positional_call_default_tool(self, rules_file, capsys):
        """A positional argument is evaluated against the default tool."""
        code = cli_module.main(["--rules", str(rules_file), "echo hello"])
        captured = capsys.readouterr()
        assert code == 0
        assert "Decision: ASK" in captured.out

    def test_positional_call_with_tool_prefix(self, rules_file, capsys):
        """A positional argument with tool_name:value prefix is routed correctly."""
        code = cli_module.main(
            ["--rules", str(rules_file), "cmd_tool-exec_cmd:echo hello"]
        )
        captured = capsys.readouterr()
        assert code == 0
        assert "Decision: ASK" in captured.out

    def test_json_output(self, rules_file, capsys):
        """--json emits valid JSON."""
        code = cli_module.main(["--rules", str(rules_file), "--json", "echo hello"])
        captured = capsys.readouterr()
        assert code == 0
        results = json.loads(captured.out)
        assert isinstance(results, list)
        assert results[0]["decision"] == "ask"


class TestErrorHandling:
    """Tests for fail-open behavior and error reporting."""

    def test_missing_rules_file_is_skipped_when_other_files_present(
        self, rules_file, tmp_path, capsys, caplog
    ):
        """A missing file in a multi-file list is skipped; valid files still load."""
        missing = tmp_path / "missing.json"
        code = cli_module.main(["--rules", f"{missing};{rules_file}"])
        captured = capsys.readouterr()
        assert code == 0
        assert "Loaded 1 approval rule(s)" in captured.out
        assert "Cannot read approval rules file" in caplog.text

    def test_all_missing_files_results_in_empty_rules(self, tmp_path, capsys, caplog):
        """When all rule sources fail, no rules are loaded but the script exits cleanly."""
        missing = tmp_path / "missing.json"
        code = cli_module.main(["--rules", str(missing)])
        captured = capsys.readouterr()
        assert code == 0
        assert "Loaded 0 approval rule(s)" in captured.out
        assert "Cannot read approval rules file" in caplog.text
