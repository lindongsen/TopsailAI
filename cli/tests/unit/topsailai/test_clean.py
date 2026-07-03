#!/usr/bin/env python3
"""
Unit tests for cleanup helpers in cli_topsailai.

Covers:
- clean_expired_files()
- clean_by_numbers()
"""

import sys
import os
import unittest
import tempfile
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import cli_topsailai.state as cli_state
from cli_topsailai.cleaning import clean_by_numbers, clean_expired_files


def _make_file_record(path: str) -> dict:
    """Build a log-file record matching discover_log_files output."""
    stat_info = os.stat(path)
    return {
        "filename": os.path.basename(path),
        "path": path,
        "session_id": None,
        "pid": None,
        "size": stat_info.st_size,
        "mtime": stat_info.st_mtime,
        "ctime": stat_info.st_ctime,
    }


class TestCleanExpiredFiles(unittest.TestCase):
    """Tests for clean_expired_files()."""

    @mock.patch("cli_topsailai.cleaning.input")
    def test_deletes_only_old_idle_files(self, mock_input):
        mock_input.return_value = "y"
        with tempfile.TemporaryDirectory() as tmp:
            old_path = os.path.join(tmp, "old.session.stdout")
            new_path = os.path.join(tmp, "new.session.stdout")
            with open(old_path, "w") as f:
                f.write("old")
            with open(new_path, "w") as f:
                f.write("new")
            # Make old file 4 days old
            old_mtime = time.time() - 4 * 24 * 3600
            os.utime(old_path, (old_mtime, old_mtime))

            files = [
                _make_file_record(old_path),
                _make_file_record(new_path),
            ]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 1)
            self.assertFalse(os.path.exists(old_path))
            self.assertTrue(os.path.exists(new_path))

    @mock.patch("cli_topsailai.cleaning.input")
    def test_no_expired_files(self, mock_input):
        with tempfile.TemporaryDirectory() as tmp:
            new_path = os.path.join(tmp, "new.session.stdout")
            with open(new_path, "w") as f:
                f.write("new")
            files = [_make_file_record(new_path)]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 0)
            self.assertTrue(os.path.exists(new_path))

    @mock.patch("cli_topsailai.cleaning.input")
    def test_cancelled_confirmation(self, mock_input):
        mock_input.return_value = "n"
        with tempfile.TemporaryDirectory() as tmp:
            old_path = os.path.join(tmp, "old.session.stdout")
            with open(old_path, "w") as f:
                f.write("old")
            old_mtime = time.time() - 4 * 24 * 3600
            os.utime(old_path, (old_mtime, old_mtime))

            files = [_make_file_record(old_path)]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 0)
            self.assertTrue(os.path.exists(old_path))

    @mock.patch("cli_topsailai.cleaning.input")
    def test_eof_cancels(self, mock_input):
        mock_input.side_effect = EOFError()
        with tempfile.TemporaryDirectory() as tmp:
            old_path = os.path.join(tmp, "old.session.stdout")
            with open(old_path, "w") as f:
                f.write("old")
            old_mtime = time.time() - 4 * 24 * 3600
            os.utime(old_path, (old_mtime, old_mtime))

            files = [_make_file_record(old_path)]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 0)


class TestCleanByNumbers(unittest.TestCase):
    """Tests for clean_by_numbers()."""

    @mock.patch("cli_topsailai.cleaning.input")
    def test_deletes_selected_indices(self, mock_input):
        mock_input.return_value = "y"
        with tempfile.TemporaryDirectory() as tmp:
            path1 = os.path.join(tmp, "a.session.stdout")
            path2 = os.path.join(tmp, "b.session.stdout")
            path3 = os.path.join(tmp, "c.session.stdout")
            for p in [path1, path2, path3]:
                with open(p, "w") as f:
                    f.write("x")

            files = [
                _make_file_record(path1),
                _make_file_record(path2),
                _make_file_record(path3),
            ]
            deleted_count = clean_by_numbers(tmp, files, [0, 2])
            self.assertEqual(deleted_count, 2)
            self.assertFalse(os.path.exists(path1))
            self.assertTrue(os.path.exists(path2))
            self.assertFalse(os.path.exists(path3))

    @mock.patch("cli_topsailai.cleaning.input")
    def test_invalid_index_ignored(self, mock_input):
        mock_input.return_value = "y"
        with tempfile.TemporaryDirectory() as tmp:
            path1 = os.path.join(tmp, "a.session.stdout")
            with open(path1, "w") as f:
                f.write("x")
            files = [_make_file_record(path1)]
            deleted_count = clean_by_numbers(tmp, files, [5])
            self.assertEqual(deleted_count, 0)

    @mock.patch("cli_topsailai.cleaning.input")
    def test_cancelled_confirmation(self, mock_input):
        mock_input.return_value = "n"
        with tempfile.TemporaryDirectory() as tmp:
            path1 = os.path.join(tmp, "a.session.stdout")
            with open(path1, "w") as f:
                f.write("x")
            files = [_make_file_record(path1)]
            deleted_count = clean_by_numbers(tmp, files, [0])
            self.assertEqual(deleted_count, 0)
            self.assertTrue(os.path.exists(path1))


if __name__ == "__main__":
    unittest.main()
