#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the ``docs list`` and ``docs read`` subcommands."""

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

CLI_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = CLI_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(CLI_DIR))

import cli_topsailai.core as cli_core


def _docs_args(**kwargs):
    """Build an argparse namespace for the docs handlers."""
    return argparse.Namespace(**kwargs)


DOC_RECORDS = [
    {
        "row_number": 1,
        "folder": "memo",
        "rel_path": "memo/design.md",
        "path": "/docs/memo/design.md",
        "title": "design",
        "size_bytes": 11,
        "created": "2026-01-01T00:00:00",
    },
    {
        "row_number": 2,
        "folder": "usage",
        "rel_path": "usage/topsailai.md",
        "path": "/docs/usage/topsailai.md",
        "title": "topsailai",
        "size_bytes": 9,
        "created": "2026-01-02T00:00:00",
    },
]


class TestDocsListSubcommand:
    """Tests for ``docs list`` output modes."""

    def test_json_emits_the_record_list(self, capsys):
        """``--json`` prints the same records the table renders."""
        with patch.object(cli_core, "build_doc_list", return_value=DOC_RECORDS):
            code = cli_core._handle_docs_list_subcommand(_docs_args(json_output=True))

        captured = capsys.readouterr()
        assert code == 0
        assert json.loads(captured.out) == DOC_RECORDS
        assert captured.err == ""

    def test_json_keeps_every_field(self, capsys):
        """The JSON form carries fields the human table does not show."""
        with patch.object(cli_core, "build_doc_list", return_value=DOC_RECORDS):
            cli_core._handle_docs_list_subcommand(_docs_args(json_output=True))

        captured = capsys.readouterr()
        first = json.loads(captured.out)[0]
        assert first["path"] == "/docs/memo/design.md"
        assert first["size_bytes"] == 11
        assert first["created"] == "2026-01-01T00:00:00"

    def test_json_empty_list(self, capsys):
        """An empty documentation folder emits an empty JSON array."""
        with patch.object(cli_core, "build_doc_list", return_value=[]):
            code = cli_core._handle_docs_list_subcommand(_docs_args(json_output=True))

        captured = capsys.readouterr()
        assert code == 0
        assert json.loads(captured.out) == []

    def test_plain_output_renders_the_table(self, capsys):
        """Without ``--json`` the human table is still printed."""
        with patch.object(cli_core, "build_doc_list", return_value=DOC_RECORDS):
            with patch.object(cli_core, "print_doc_table") as table:
                code = cli_core._handle_docs_list_subcommand(_docs_args())

        assert code == 0
        table.assert_called_once_with(DOC_RECORDS)
        assert capsys.readouterr().out == ""

    def test_missing_json_attribute_defaults_to_plain(self, capsys):
        """A namespace without ``json_output`` keeps the human output."""
        with patch.object(cli_core, "build_doc_list", return_value=DOC_RECORDS):
            with patch.object(cli_core, "print_doc_table") as table:
                code = cli_core._handle_docs_list_subcommand(_docs_args())

        assert code == 0
        table.assert_called_once_with(DOC_RECORDS)


class TestDocsReadSubcommand:
    """Tests for ``docs read`` output modes."""

    def test_json_ok_result(self, capsys):
        """A resolved document emits its structured result and exits zero."""
        result = {
            "status": "ok",
            "content": "# Title\n",
            "path": "/docs/usage/topsailai.md",
            "rel_path": "usage/topsailai.md",
            "options": None,
        }
        with patch.object(cli_core, "resolve_doc", return_value=result):
            code = cli_core._handle_docs_read_subcommand(
                _docs_args(name="topsailai", json_output=True)
            )

        captured = capsys.readouterr()
        assert code == 0
        assert json.loads(captured.out) == result
        assert captured.err == ""

    def test_json_not_found_exits_one(self, capsys):
        """A missing document is a structured result with a non-zero exit."""
        result = {
            "status": "not_found",
            "content": None,
            "path": None,
            "rel_path": None,
            "options": None,
        }
        with patch.object(cli_core, "resolve_doc", return_value=result):
            code = cli_core._handle_docs_read_subcommand(
                _docs_args(name="nope", json_output=True)
            )

        captured = capsys.readouterr()
        assert code == 1
        assert json.loads(captured.out)["status"] == "not_found"
        assert captured.err == ""

    def test_json_conflict_exits_one(self, capsys):
        """An ambiguous name is a structured result carrying the options."""
        result = {
            "status": "conflict",
            "content": None,
            "path": None,
            "rel_path": None,
            "options": ["memo/design.md", "usage/design.md"],
        }
        with patch.object(cli_core, "resolve_doc", return_value=result):
            code = cli_core._handle_docs_read_subcommand(
                _docs_args(name="design", json_output=True)
            )

        captured = capsys.readouterr()
        assert code == 1
        payload = json.loads(captured.out)
        assert payload["status"] == "conflict"
        assert payload["options"] == ["memo/design.md", "usage/design.md"]

    def test_plain_ok_prints_content(self, capsys):
        """Without ``--json`` the raw content is printed."""
        result = {
            "status": "ok",
            "content": "# Title\n",
            "path": "/docs/usage/topsailai.md",
            "rel_path": "usage/topsailai.md",
            "options": None,
        }
        with patch.object(cli_core, "resolve_doc", return_value=result):
            code = cli_core._handle_docs_read_subcommand(_docs_args(name="topsailai"))

        captured = capsys.readouterr()
        assert code == 0
        assert captured.out == "# Title\n\n"

    def test_plain_not_found_prints_message(self, capsys):
        """Without ``--json`` a missing document prints a human message."""
        result = {
            "status": "not_found",
            "content": None,
            "path": None,
            "rel_path": None,
            "options": None,
        }
        with patch.object(cli_core, "resolve_doc", return_value=result):
            code = cli_core._handle_docs_read_subcommand(_docs_args(name="nope"))

        captured = capsys.readouterr()
        assert code == 1
        assert "Doc not found: nope" in captured.out
