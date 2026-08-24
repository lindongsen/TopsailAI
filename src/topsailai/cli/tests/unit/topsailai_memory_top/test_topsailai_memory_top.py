#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the top-memory CLI."""

import json
import sys
from collections import OrderedDict
from pathlib import Path
from unittest.mock import patch

import pytest

CLI_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CLI_DIR))

import topsailai_memory_top as cli


class TestArguments:
    """Validate command-line argument handling."""

    def test_defaults_use_environment_token_budget(self, monkeypatch):
        """Use the existing memory-load environment variable by default."""
        monkeypatch.setenv(cli.MAX_TOKENS_ENV, "321")
        args = cli.parse_args([])
        assert args.max_tokens == 321
        assert args.max_count == 0
        assert args.json is False

    def test_explicit_bounds_and_json(self):
        """Parse explicit token, count, and JSON options."""
        args = cli.parse_args(
            ["--max-tokens", "100", "--max-count", "2", "--json"]
        )
        assert args.max_tokens == 100
        assert args.max_count == 2
        assert args.json is True

    def test_negative_bound_is_rejected(self):
        """Reject negative token and count bounds."""
        for option in ("--max-tokens", "--max-count"):
            with pytest.raises(SystemExit) as exc_info:
                cli.parse_args([option, "-1"])
            assert exc_info.value.code == 2


class TestSelection:
    """Validate reuse of the established MRU loader."""

    def test_reuses_lru_loader_and_applies_count(self):
        """Delegate token selection and retain only the requested top count."""
        loaded = OrderedDict((("new", "N"), ("middle", "M"), ("old", "O")))
        with patch.object(
            cli.story_memory_tool, "_load_memories_lru", return_value=loaded
        ) as loader:
            result = cli.load_top_memories(90, 2)
        loader.assert_called_once_with(90)
        assert list(result.items()) == [("new", "N"), ("middle", "M")]

    def test_zero_count_keeps_all_loaded_memories(self):
        """Treat a zero count as unlimited."""
        loaded = OrderedDict((("new", "N"), ("old", "O")))
        with patch.object(
            cli.story_memory_tool, "_load_memories_lru", return_value=loaded
        ):
            assert cli.load_top_memories(0, 0) is loaded


class TestOutput:
    """Validate structured and human-readable output."""

    def test_build_result_preserves_order(self):
        """Represent memories as an ordered JSON-compatible list."""
        loaded = OrderedDict((("new", "N"), ("old", "O")))
        with patch.object(cli, "load_top_memories", return_value=loaded):
            result = cli.build_result(10, 2)
        assert [item["title"] for item in result["memories"]] == ["new", "old"]
        assert result["count"] == 2
        assert result["total"] == 2

    def test_format_text_is_markdown_with_frontmatter(self):
        """Place metadata, main title, and title summary before memory details."""
        result = {
            "max_tokens": 10,
            "max_count": 2,
            "sort": cli.SORT_DESCRIPTION,
            "count": 2,
            "total": 2,
            "memories": [
                {"title": "new", "content": "N"},
                {"title": "old", "content": "O"},
            ],
        }
        output = cli.format_text(result)
        assert output.startswith("---\ntotal: 2\nmax_tokens: 10\nmax_count: 2\n")
        assert "\n---\n\n# Top Memories\n" in output
        assert "\n## Titles\n\n1. new\n2. old\n" in output
        assert output.index("2. old") < output.index("### new")

    def test_main_prints_json(self, capsys):
        """Print valid JSON with a total for automation."""
        with patch.object(
            cli,
            "build_result",
            return_value={
                "max_tokens": 10,
                "max_count": 1,
                "sort": cli.SORT_DESCRIPTION,
                "count": 1,
                "total": 1,
                "memories": [{"title": "new", "content": "N"}],
            },
        ):
            rc = cli.main(["--max-tokens", "10", "--max-count", "1", "--json"])
        assert rc == 0
        result = json.loads(capsys.readouterr().out)
        assert result["total"] == 1
        assert result["memories"][0]["title"] == "new"

    def test_main_returns_one_on_failure(self, capsys):
        """Return one and report selection failures on stderr."""
        with patch.object(cli, "build_result", side_effect=RuntimeError("boom")):
            rc = cli.main([])
        assert rc == 1
        assert "Error: boom" in capsys.readouterr().err
