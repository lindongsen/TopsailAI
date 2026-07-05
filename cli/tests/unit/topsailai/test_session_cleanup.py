#!/usr/bin/env python3
"""
Unit tests for session disk cleanup helpers in cli_topsailai.

Covers:
- find_related_files()
- find_related_files_for_path()
- find_session_disk_files()
- delete_session_disk_files()
- clean_orphaned_session_files()
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from cli_topsailai.session_cleanup import (
    clean_orphaned_session_files,
    delete_session_disk_files,
    find_related_files,
    find_related_files_for_path,
    find_session_disk_files,
)


class TestFindRelatedFiles(unittest.TestCase):
    """Tests for find_related_files()."""

    def test_no_task_dir(self):
        self.assertEqual(find_related_files("/nonexistent/path", "s.1"), [])

    def test_finds_related_session_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = [
                "my-session.1234.session.stdout",
                "my-session.1234.session.stderr",
                "my-session.1234.session.pipe",
                "my-session.1234.session.agent2llm_inject_messages.jsonl",
                "my-session.1234.step-1.task.stdout",
                "my-session.1234.step-1.task.stderr",
                "other-session.5678.session.stdout",
            ]
            for name in files:
                open(os.path.join(tmp, name), "w").close()

            related = find_related_files(tmp, "my-session.1234")
            basenames = {os.path.basename(p) for p in related}
            self.assertEqual(
                basenames,
                {
                    "my-session.1234.session.stdout",
                    "my-session.1234.session.stderr",
                    "my-session.1234.session.pipe",
                    "my-session.1234.session.agent2llm_inject_messages.jsonl",
                    "my-session.1234.step-1.task.stdout",
                    "my-session.1234.step-1.task.stderr",
                },
            )

    def test_does_not_match_partial_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "my-session.1234.session.stdout"), "w").close()
            open(os.path.join(tmp, "my-session.12345.session.stdout"), "w").close()

            related = find_related_files(tmp, "my-session.1234")
            basenames = {os.path.basename(p) for p in related}
            self.assertEqual(
                basenames,
                {"my-session.1234.session.stdout"},
            )


class TestFindRelatedFilesForPath(unittest.TestCase):
    """Tests for find_related_files_for_path()."""

    def test_finds_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout = os.path.join(tmp, "s.1.session.stdout")
            stderr = os.path.join(tmp, "s.1.session.stderr")
            pipe = os.path.join(tmp, "s.1.session.pipe")
            for p in [stdout, stderr, pipe]:
                open(p, "w").close()

            related = find_related_files_for_path(tmp, stdout)
            basenames = {os.path.basename(p) for p in related}
            self.assertEqual(basenames, {"s.1.session.stdout", "s.1.session.stderr", "s.1.session.pipe"})

    def test_unknown_file_returns_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notes.txt")
            open(path, "w").close()
            related = find_related_files_for_path(tmp, path)
            self.assertEqual(related, [path])


class TestFindSessionDiskFiles(unittest.TestCase):
    """Tests for find_session_disk_files()."""

    def test_finds_all_session_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = [
                "my-session.1234.session.stdout",
                "my-session.1234.session.stderr",
                "my-session.1234.step-1.task.stdout",
                "other.9999.session.stdout",
            ]
            for name in files:
                open(os.path.join(tmp, name), "w").close()

            found = find_session_disk_files(tmp, "my-session")
            basenames = {os.path.basename(p) for p in found}
            self.assertEqual(
                basenames,
                {
                    "my-session.1234.session.stdout",
                    "my-session.1234.session.stderr",
                    "my-session.1234.step-1.task.stdout",
                },
            )

    def test_requires_pid_digit_after_prefix(self):
        """Names like 'my-session.extra...' must not match session 'my-session'."""
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "my-session.1234.session.stdout"), "w").close()
            open(os.path.join(tmp, "my-session.extra.session.stdout"), "w").close()
            open(os.path.join(tmp, "my-session.1234.session.stderr"), "w").close()

            found = find_session_disk_files(tmp, "my-session")
            basenames = {os.path.basename(p) for p in found}
            self.assertEqual(
                basenames,
                {
                    "my-session.1234.session.stdout",
                    "my-session.1234.session.stderr",
                },
            )

    def test_temp_session_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "topsailai.1234.session.stdout"), "w").close()
            open(os.path.join(tmp, "topsailai.1234.session.pipe"), "w").close()

            found = find_session_disk_files(tmp, "topsailai")
            basenames = {os.path.basename(p) for p in found}
            self.assertEqual(
                basenames,
                {"topsailai.1234.session.stdout", "topsailai.1234.session.pipe"},
            )


class TestDeleteSessionDiskFiles(unittest.TestCase):
    """Tests for delete_session_disk_files()."""

    @patch("cli_topsailai.session_cleanup.is_file_in_use", return_value=False)
    def test_deletes_all_session_files(self, _mock_in_use):
        with tempfile.TemporaryDirectory() as tmp:
            files = [
                "my-session.1234.session.stdout",
                "my-session.1234.session.stderr",
                "my-session.1234.session.pipe",
            ]
            for name in files:
                open(os.path.join(tmp, name), "w").close()

            deleted, failed = delete_session_disk_files(tmp, "my-session")
            self.assertEqual(len(deleted), 3)
            self.assertEqual(failed, [])
            for name in files:
                self.assertFalse(os.path.exists(os.path.join(tmp, name)))

    @patch("cli_topsailai.session_cleanup.is_file_in_use", return_value=False)
    def test_dry_run_does_not_delete(self, _mock_in_use):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "my-session.1234.session.stdout")
            open(path, "w").close()

            deleted, failed = delete_session_disk_files(tmp, "my-session", dry_run=True)
            self.assertEqual(len(deleted), 1)
            self.assertEqual(failed, [])
            self.assertTrue(os.path.exists(path))

    @patch("cli_topsailai.session_cleanup.is_file_in_use", return_value=False)
    def test_missing_dir_returns_empty(self, _mock_in_use):
        deleted, failed = delete_session_disk_files("/nonexistent/path", "my-session")
        self.assertEqual(deleted, [])
        self.assertEqual(failed, [])

    @patch("cli_topsailai.session_cleanup.is_file_in_use", return_value=True)
    def test_skips_in_use_files(self, _mock_in_use):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "my-session.1234.session.stdout")
            open(path, "w").close()

            deleted, failed = delete_session_disk_files(tmp, "my-session")
            self.assertEqual(deleted, [])
            self.assertEqual(failed, [])
            self.assertTrue(os.path.exists(path))


class TestCleanOrphanedSessionFiles(unittest.TestCase):
    """Tests for clean_orphaned_session_files()."""

    @patch("cli_topsailai.session_cleanup.is_file_in_use", return_value=False)
    def test_deletes_orphaned_files(self, _mock_in_use):
        with tempfile.TemporaryDirectory() as tmp:
            # Orphaned files (no matching .stdout)
            orphan_pipe = os.path.join(tmp, "s.1.session.pipe")
            orphan_jsonl = os.path.join(tmp, "s.1.session.agent2llm_inject_messages.jsonl")
            orphan_stderr = os.path.join(tmp, "s.1.session.stderr")
            orphan_task_stdout = os.path.join(tmp, "s.1.step-1.task.stdout")
            orphan_task_stderr = os.path.join(tmp, "s.1.step-1.task.stderr")
            # Non-orphaned file (matching .stdout exists)
            stdout = os.path.join(tmp, "s.2.session.stdout")
            pipe = os.path.join(tmp, "s.2.session.pipe")
            for p in [
                orphan_pipe,
                orphan_jsonl,
                orphan_stderr,
                orphan_task_stdout,
                orphan_task_stderr,
                stdout,
                pipe,
            ]:
                open(p, "w").close()

            deleted, failed = clean_orphaned_session_files(tmp)
            self.assertEqual(len(deleted), 5)
            self.assertEqual(failed, [])
            self.assertFalse(os.path.exists(orphan_pipe))
            self.assertFalse(os.path.exists(orphan_jsonl))
            self.assertFalse(os.path.exists(orphan_stderr))
            self.assertFalse(os.path.exists(orphan_task_stdout))
            self.assertFalse(os.path.exists(orphan_task_stderr))
            self.assertTrue(os.path.exists(stdout))
            self.assertTrue(os.path.exists(pipe))

    @patch("cli_topsailai.session_cleanup.is_file_in_use", return_value=False)
    def test_dry_run_reports_without_deleting(self, _mock_in_use):
        with tempfile.TemporaryDirectory() as tmp:
            orphan_pipe = os.path.join(tmp, "s.1.session.pipe")
            open(orphan_pipe, "w").close()

            deleted, failed = clean_orphaned_session_files(tmp, dry_run=True)
            self.assertEqual(len(deleted), 1)
            self.assertEqual(failed, [])
            self.assertTrue(os.path.exists(orphan_pipe))

    @patch("cli_topsailai.session_cleanup.is_file_in_use", return_value=True)
    def test_skips_in_use_orphaned_files(self, _mock_in_use):
        with tempfile.TemporaryDirectory() as tmp:
            orphan_pipe = os.path.join(tmp, "s.1.session.pipe")
            open(orphan_pipe, "w").close()

            deleted, failed = clean_orphaned_session_files(tmp)
            self.assertEqual(deleted, [])
            self.assertEqual(failed, [])
            self.assertTrue(os.path.exists(orphan_pipe))


if __name__ == "__main__":
    unittest.main()
