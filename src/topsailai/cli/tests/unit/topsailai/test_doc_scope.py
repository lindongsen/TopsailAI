#!/usr/bin/env python3
"""
Unit tests for the doc scope module and CLI integration.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

import cli_topsailai.state as cli_state
from cli_topsailai.core import main, prompt_selection
from cli_topsailai.doc_scope import (
    build_doc_list,
    get_usage_docs_dir,
    print_doc_table,
    read_doc_file,
)


class TestGetUsageDocsDir(unittest.TestCase):
    """Tests for portable usage docs directory resolution."""

    def test_returns_absolute_path(self):
        docs_dir = get_usage_docs_dir()
        self.assertTrue(os.path.isabs(docs_dir))
        self.assertTrue(docs_dir.endswith(os.path.join("docs", "usage")))

    def test_points_to_existing_directory(self):
        docs_dir = get_usage_docs_dir()
        self.assertTrue(os.path.isdir(docs_dir))


class TestBuildDocList(unittest.TestCase):
    """Tests for usage documentation discovery."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.docs_dir = self._tmp_dir.name

    def tearDown(self):
        self._tmp_dir.cleanup()

    def _patch_docs_dir(self):
        return patch(
            "cli_topsailai.doc_scope.get_usage_docs_dir",
            return_value=self.docs_dir,
        )

    def test_empty_directory_returns_empty_list(self):
        with self._patch_docs_dir():
            self.assertEqual(build_doc_list(), [])

    def test_ignores_non_markdown_files(self):
        with open(
            os.path.join(self.docs_dir, "readme.txt"), "w", encoding="utf-8"
        ) as fh:
            fh.write("not markdown")
        with self._patch_docs_dir():
            self.assertEqual(build_doc_list(), [])

    @patch("cli_topsailai.doc_scope.os.stat")
    def test_discovers_markdown_files_sorted_by_creation_time(self, mock_stat):
        files = [
            ("second.md", "# Second\n"),
            ("first.md", "# First\n"),
            ("third.md", "# Third\n"),
        ]
        ctime_map = {
            "second.md": 300.0,
            "first.md": 100.0,
            "third.md": 200.0,
        }

        class FakeStat:
            def __init__(self, ctime, size, mode):
                self.st_ctime = ctime
                self.st_size = size
                self.st_mode = mode

        for name, content in files:
            path = os.path.join(self.docs_dir, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)

        def fake_stat(path):
            filename = os.path.basename(path)
            if path == self.docs_dir:
                return FakeStat(0.0, 0, 0o40755)
            content = ctime_map.get(filename, "")
            size = len(content.encode("utf-8")) if isinstance(content, str) else 0
            return FakeStat(ctime_map.get(filename, 0.0), size, 0o100644)

        mock_stat.side_effect = fake_stat

        with self._patch_docs_dir():
            docs = build_doc_list()

        self.assertEqual(len(docs), 3)
        self.assertEqual(
            [d["filename"] for d in docs], ["first.md", "third.md", "second.md"]
        )
        self.assertEqual([d["row_number"] for d in docs], [1, 2, 3])

    def test_extracts_first_heading_as_title(self):
        path = os.path.join(self.docs_dir, "with_title.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# My Title\n\nSome body.\n")
        with self._patch_docs_dir():
            docs = build_doc_list()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["title"], "My Title")

    def test_uses_filename_when_no_heading(self):
        path = os.path.join(self.docs_dir, "no_title.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("Just body text.\n")
        with self._patch_docs_dir():
            docs = build_doc_list()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["title"], "no_title.md")


class TestReadDocFile(unittest.TestCase):
    """Tests for reading usage documentation files."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.docs_dir = self._tmp_dir.name

    def tearDown(self):
        self._tmp_dir.cleanup()

    def _patch_docs_dir(self):
        return patch(
            "cli_topsailai.doc_scope.get_usage_docs_dir",
            return_value=self.docs_dir,
        )

    def test_reads_existing_file(self):
        with open(
            os.path.join(self.docs_dir, "sample.md"), "w", encoding="utf-8"
        ) as fh:
            fh.write("# Sample\nContent.\n")
        with self._patch_docs_dir():
            content = read_doc_file("sample.md")
        self.assertEqual(content, "# Sample\nContent.\n")

    def test_returns_none_for_missing_file(self):
        with self._patch_docs_dir():
            self.assertIsNone(read_doc_file("missing.md"))

    def test_blocks_path_traversal(self):
        with self._patch_docs_dir():
            self.assertIsNone(read_doc_file("../secret.md"))
            self.assertIsNone(read_doc_file("/etc/passwd"))


class TestPrintDocTable(unittest.TestCase):
    """Tests for doc table rendering."""

    @patch("builtins.print")
    def test_prints_table_for_docs(self, mock_print):
        docs = [
            {
                "row_number": 1,
                "filename": "a.md",
                "title": "A Title",
                "size_bytes": 2048,
            }
        ]
        print_doc_table(docs)
        output = "\n".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("a.md", output)
        self.assertIn("A Title", output)
        self.assertIn("2.0K", output)

    @patch("builtins.print")
    def test_prints_warning_when_empty(self, mock_print):
        print_doc_table([])
        output = "\n".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("No usage documentation", output)


class TestDocScopePromptSelection(unittest.TestCase):
    """Tests for prompt_selection in doc scope."""

    def setUp(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.current_doc_filename = None
        cli_state.yaml_commands = []
        cli_state.history_manager = None

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.current_doc_filename = None
        cli_state.yaml_commands = []
        cli_state.history_manager = None
        cli_state._child_processes.clear()

    @patch("cli_topsailai.core.input")
    def test_cd_doc_enters_doc_scope(self, mock_input):
        mock_input.return_value = "cd doc"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "enter_doc")

    @patch("cli_topsailai.core.input")
    def test_cd_docs_enters_doc_scope(self, mock_input):
        mock_input.return_value = "cd docs"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "enter_doc")

    @patch("cli_topsailai.core.input")
    def test_cd_usage_enters_doc_scope(self, mock_input):
        mock_input.return_value = "cd usage"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "enter_doc")

    @patch("cli_topsailai.core.input")
    def test_numeric_selection_in_doc_scope_reads_doc(self, mock_input):
        cli_state.current_scope = "doc"
        docs = [
            {"filename": "a.md", "title": "A"},
            {"filename": "b.md", "title": "B"},
        ]
        mock_input.return_value = "2"
        action, value = prompt_selection(docs, "/task")
        self.assertEqual(action, "read_doc")
        self.assertEqual(value, 1)

    @patch("cli_topsailai.core.input")
    def test_q_in_doc_scope_returns_to_workspace(self, mock_input):
        cli_state.current_scope = "doc"
        mock_input.return_value = "q"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "leave_scope")

    @patch("cli_topsailai.core.input")
    def test_quit_in_doc_scope_returns_to_workspace(self, mock_input):
        cli_state.current_scope = "doc"
        mock_input.return_value = "quit"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "leave_scope")

    @patch("cli_topsailai.core.input")
    def test_bare_cd_in_doc_scope_returns_to_workspace(self, mock_input):
        cli_state.current_scope = "doc"
        mock_input.return_value = "cd"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "leave_scope")

    @patch("cli_topsailai.core.input")
    def test_refresh_in_doc_scope(self, mock_input):
        cli_state.current_scope = "doc"
        mock_input.return_value = "/refresh"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "refresh")

    @patch("builtins.print")
    @patch("cli_topsailai.core.input")
    def test_invalid_number_in_doc_scope(self, mock_input, mock_print):
        cli_state.current_scope = "doc"
        docs = [{"filename": "a.md", "title": "A"}]
        mock_input.side_effect = ["5", "q"]
        action, value = prompt_selection(docs, "/task")
        self.assertEqual(action, "leave_scope")
        self.assertTrue(
            any("Invalid number" in str(call) for call in mock_print.call_args_list)
        )


class TestDocScopeMainFlags(unittest.TestCase):
    """Tests for --list-docs and --read-doc CLI flags."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.docs_dir = self._tmp_dir.name
        with open(
            os.path.join(self.docs_dir, "hello.md"), "w", encoding="utf-8"
        ) as fh:
            fh.write("# Hello\nWorld\n")

    def tearDown(self):
        self._tmp_dir.cleanup()

    @patch("cli_topsailai.doc_scope.get_usage_docs_dir")
    @patch("sys.exit")
    @patch("builtins.print")
    def test_list_docs_flag(self, mock_print, mock_exit, mock_get_dir):
        mock_get_dir.return_value = self.docs_dir
        mock_exit.side_effect = SystemExit(0)
        with self.assertRaises(SystemExit):
            main(["--list-docs"])
        output = "\n".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("hello.md", output)
        self.assertIn("Hello", output)

    @patch("cli_topsailai.doc_scope.get_usage_docs_dir")
    @patch("sys.exit")
    @patch("builtins.print")
    def test_read_doc_flag(self, mock_print, mock_exit, mock_get_dir):
        mock_get_dir.return_value = self.docs_dir
        mock_exit.side_effect = SystemExit(0)
        with self.assertRaises(SystemExit):
            main(["--read-doc", "hello.md"])
        output = "\n".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("# Hello", output)
        self.assertIn("World", output)

    @patch("cli_topsailai.doc_scope.get_usage_docs_dir")
    @patch("sys.exit")
    @patch("builtins.print")
    def test_read_doc_missing_file_exits_with_error(
        self, mock_print, mock_exit, mock_get_dir
    ):
        mock_get_dir.return_value = self.docs_dir
        mock_exit.side_effect = SystemExit(1)
        with self.assertRaises(SystemExit):
            main(["--read-doc", "missing.md"])
        output = "\n".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("Usage doc not found", output)


class TestDocScopeMainLoop(unittest.TestCase):
    """Tests for doc scope integration in the main loop."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.docs_dir = self._tmp_dir.name
        with open(
            os.path.join(self.docs_dir, "hello.md"), "w", encoding="utf-8"
        ) as fh:
            fh.write("# Hello\nWorld\n")

        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.current_doc_filename = None
        cli_state.yaml_commands = []
        cli_state.history_manager = None

    def tearDown(self):
        self._tmp_dir.cleanup()
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.current_doc_filename = None
        cli_state.yaml_commands = []
        cli_state.history_manager = None
        cli_state._child_processes.clear()

    @patch("cli_topsailai.doc_scope.get_usage_docs_dir")
    @patch("cli_topsailai.core.prompt_selection")
    @patch("cli_topsailai.log_files.discover_log_files")
    @patch("cli_topsailai.session_info.enrich_files_with_session_names")
    @patch("cli_topsailai.formatting.print_table")
    @patch("cli_topsailai.formatting.print_header")
    @patch("cli_topsailai.history.HistoryManager")
    @patch("cli_topsailai.history.load_readline_history")
    @patch("cli_topsailai.completer.setup_tab_completion")
    def test_enter_doc_scope_lists_docs(
        self,
        _mock_setup_tab: MagicMock,
        _mock_load_history: MagicMock,
        _mock_history: MagicMock,
        _mock_header: MagicMock,
        _mock_table: MagicMock,
        _mock_enrich: MagicMock,
        mock_discover: MagicMock,
        mock_prompt: MagicMock,
        mock_get_dir: MagicMock,
    ) -> None:
        """Entering doc scope refreshes and prints the doc table."""
        mock_get_dir.return_value = self.docs_dir
        mock_discover.return_value = []
        mock_prompt.side_effect = [
            ("enter_doc", None),
            ("leave_scope", None),
            ("quit", None),
        ]

        main([])

        # prompt_selection should be called with the discovered docs.
        self.assertEqual(mock_prompt.call_count, 3)
        second_call_args = mock_prompt.call_args_list[1][0]
        self.assertEqual(len(second_call_args[0]), 1)
        self.assertEqual(second_call_args[0][0]["filename"], "hello.md")


if __name__ == "__main__":
    unittest.main()
