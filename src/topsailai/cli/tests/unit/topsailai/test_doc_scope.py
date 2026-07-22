"""Tests for cli_topsailai.doc_scope module."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli_topsailai import doc_scope


class TestGetDocsDir(unittest.TestCase):
    """Tests for get_docs_dir and get_usage_docs_dir helpers."""

    def test_get_docs_dir_returns_absolute_docs_path(self):
        docs_dir = doc_scope.get_docs_dir()
        self.assertTrue(os.path.isabs(docs_dir))
        self.assertTrue(docs_dir.endswith(os.path.join("topsailai", "cli", "docs")))

    def test_get_usage_docs_dir_returns_usage_subfolder(self):
        usage_dir = doc_scope.get_usage_docs_dir()
        self.assertTrue(os.path.isabs(usage_dir))
        self.assertTrue(usage_dir.endswith(os.path.join("docs", "usage")))


class TestBuildDocList(unittest.TestCase):
    """Tests for build_doc_list with folder grouping."""

    def _make_docs(self, tmp):
        docs_dir = Path(tmp) / "docs"
        usage_dir = docs_dir / "usage"
        memo_dir = docs_dir / "memo"
        usage_dir.mkdir(parents=True)
        memo_dir.mkdir(parents=True)
        (usage_dir / "topsailai.md").write_text("usage doc")
        (usage_dir / "launch.md").write_text("launch doc")
        (memo_dir / "design.md").write_text("design doc")
        return docs_dir

    def test_lists_docs_grouped_by_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_docs(tmp)
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                entries = doc_scope.build_doc_list()
        self.assertEqual(len(entries), 3)
        folders = [e["folder"] for e in entries]
        # Folders are sorted alphabetically: memo, usage.
        self.assertEqual(folders, ["memo", "usage", "usage"])
        self.assertEqual(entries[0]["rel_path"], "memo/design.md")
        self.assertEqual(entries[1]["rel_path"], "usage/launch.md")
        self.assertEqual(entries[2]["rel_path"], "usage/topsailai.md")

    def test_row_numbers_are_global(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_docs(tmp)
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                entries = doc_scope.build_doc_list()
        self.assertEqual([e["row_number"] for e in entries], [1, 2, 3])

    def test_ignores_non_md_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs_dir = Path(tmp) / "docs" / "usage"
            docs_dir.mkdir(parents=True)
            (docs_dir / "readme.md").write_text("ok")
            (docs_dir / "notes.txt").write_text("ignored")
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                entries = doc_scope.build_doc_list()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["filename"], "readme.md")

    def test_follows_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs_dir = Path(tmp) / "docs" / "usage"
            docs_dir.mkdir(parents=True)
            real_file = Path(tmp) / "real.md"
            real_file.write_text("real")
            (docs_dir / "linked.md").symlink_to(real_file)
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                entries = doc_scope.build_doc_list()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["filename"], "linked.md")

    def test_empty_when_no_docs_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                entries = doc_scope.build_doc_list()
        self.assertEqual(entries, [])


class TestResolveDoc(unittest.TestCase):
    """Tests for resolve_doc with exact, bare, conflict, and not-found cases."""

    def _make_docs(self, tmp):
        docs_dir = Path(tmp) / "docs"
        usage_dir = docs_dir / "usage"
        memo_dir = docs_dir / "memo"
        usage_dir.mkdir(parents=True)
        memo_dir.mkdir(parents=True)
        (usage_dir / "topsailai.md").write_text("usage content")
        (memo_dir / "topsailai.md").write_text("memo content")
        (usage_dir / "launch.md").write_text("launch content")
        return docs_dir

    def test_exact_folder_document_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_docs(tmp)
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                result = doc_scope.resolve_doc("usage/topsailai.md")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["content"], "usage content")
        self.assertEqual(result["rel_path"], "usage/topsailai.md")

    def test_bare_unique_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_docs(tmp)
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                result = doc_scope.resolve_doc("launch")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["content"], "launch content")

    def test_bare_unique_name_with_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_docs(tmp)
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                result = doc_scope.resolve_doc("launch.md")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["content"], "launch content")

    def test_conflict_prompts_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_docs(tmp)
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                result = doc_scope.resolve_doc("topsailai")
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(
            sorted(result["options"]), ["memo/topsailai.md", "usage/topsailai.md"]
        )

    def test_conflict_with_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_docs(tmp)
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                result = doc_scope.resolve_doc("topsailai.md")
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(
            sorted(result["options"]), ["memo/topsailai.md", "usage/topsailai.md"]
        )

    def test_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_docs(tmp)
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                result = doc_scope.resolve_doc("missing")
        self.assertEqual(result["status"], "not_found")

    def test_not_found_exact_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_docs(tmp)
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                result = doc_scope.resolve_doc("other/file.md")
        self.assertEqual(result["status"], "not_found")


class TestReadDocFile(unittest.TestCase):
    """Backward-compatible tests for read_doc_file."""

    def test_read_existing_doc(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs_dir = Path(tmp) / "docs" / "usage"
            docs_dir.mkdir(parents=True)
            (docs_dir / "guide.md").write_text("guide content")
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                self.assertEqual(
                    doc_scope.read_doc_file("usage/guide.md"), "guide content"
                )

    def test_ambiguous_bare_name_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs_dir = Path(tmp) / "docs"
            (docs_dir / "usage").mkdir(parents=True)
            (docs_dir / "memo").mkdir(parents=True)
            (docs_dir / "usage" / "x.md").write_text("a")
            (docs_dir / "memo" / "x.md").write_text("b")
            with patch.object(
                doc_scope, "get_docs_dir", return_value=str(Path(tmp) / "docs")
            ):
                self.assertIsNone(doc_scope.read_doc_file("x"))


class TestPrintDocTable(unittest.TestCase):
    """Tests for print_doc_table output."""

    def test_prints_table_with_folder_column(self):
        entries = [
            {
                "row_number": 1,
                "folder": "usage",
                "filename": "topsailai.md",
                "title": "TopsailAI CLI",
                "size_bytes": 12,
            },
            {
                "row_number": 2,
                "folder": "memo",
                "filename": "design.md",
                "title": "Design Notes",
                "size_bytes": 14,
            },
        ]
        with patch("builtins.print") as mock_print:
            doc_scope.print_doc_table(entries)
        output = "\n".join(
            call.args[0] for call in mock_print.call_args_list if call.args
        )
        self.assertIn("usage", output)
        self.assertIn("memo", output)
        self.assertIn("topsailai.md", output)
        self.assertIn("design.md", output)

    def test_prints_warning_when_empty(self):
        with patch("builtins.print") as mock_print:
            doc_scope.print_doc_table([])
        output = "\n".join(
            call.args[0] for call in mock_print.call_args_list if call.args
        )
        self.assertIn("No documentation files found", output)


if __name__ == "__main__":
    unittest.main()
