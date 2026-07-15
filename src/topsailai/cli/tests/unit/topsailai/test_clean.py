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

    @mock.patch("cli_topsailai.cleaning.input")
    @mock.patch("cli_topsailai.cleaning.is_file_in_use", return_value=False)
    def test_deletes_related_session_files(self, mock_in_use, mock_input):
        mock_input.return_value = "y"
        with tempfile.TemporaryDirectory() as tmp:
            stdout = os.path.join(tmp, "old.1234.session.stdout")
            stderr = os.path.join(tmp, "old.1234.session.stderr")
            pipe = os.path.join(tmp, "old.1234.session.pipe")
            inject = os.path.join(tmp, "old.1234.session.agent2llm_inject_messages.jsonl")
            task_stdout = os.path.join(tmp, "old.1234.step-1.task.stdout")
            for p in [stdout, stderr, pipe, inject, task_stdout]:
                with open(p, "w") as f:
                    f.write("x")

            old_mtime = time.time() - 4 * 24 * 3600
            for p in [stdout, stderr, pipe, inject, task_stdout]:
                os.utime(p, (old_mtime, old_mtime))

            files = [_make_file_record(stdout)]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 5)
            self.assertFalse(os.path.exists(stdout))
            self.assertFalse(os.path.exists(stderr))
            self.assertFalse(os.path.exists(pipe))
            self.assertFalse(os.path.exists(inject))
            self.assertFalse(os.path.exists(task_stdout))

    @mock.patch("cli_topsailai.cleaning.input")
    @mock.patch("cli_topsailai.cleaning.is_file_in_use", return_value=False)
    def test_does_not_delete_unrelated_files(self, mock_in_use, mock_input):
        mock_input.return_value = "y"
        with tempfile.TemporaryDirectory() as tmp:
            old_stdout = os.path.join(tmp, "old.1234.session.stdout")
            other_stdout = os.path.join(tmp, "other.5678.session.stdout")
            for p in [old_stdout, other_stdout]:
                with open(p, "w") as f:
                    f.write("x")

            old_mtime = time.time() - 4 * 24 * 3600
            os.utime(old_stdout, (old_mtime, old_mtime))
            os.utime(other_stdout, (old_mtime, old_mtime))

            files = [_make_file_record(old_stdout)]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 1)
            self.assertFalse(os.path.exists(old_stdout))
            self.assertTrue(os.path.exists(other_stdout))

    @mock.patch("cli_topsailai.cleaning.input")
    @mock.patch("cli_topsailai.cleaning.is_file_in_use")
    def test_skips_in_use_related_files(self, mock_in_use, mock_input):
        mock_input.return_value = "y"

        def _in_use_side_effect(path):
            return path.endswith(".session.stderr")

        mock_in_use.side_effect = _in_use_side_effect
        with tempfile.TemporaryDirectory() as tmp:
            stdout = os.path.join(tmp, "old.1234.session.stdout")
            stderr = os.path.join(tmp, "old.1234.session.stderr")
            pipe = os.path.join(tmp, "old.1234.session.pipe")
            for p in [stdout, stderr, pipe]:
                with open(p, "w") as f:
                    f.write("x")

            old_mtime = time.time() - 4 * 24 * 3600
            for p in [stdout, stderr, pipe]:
                os.utime(p, (old_mtime, old_mtime))

            files = [_make_file_record(stdout)]
            deleted_count = clean_expired_files(tmp, files)
            self.assertEqual(deleted_count, 2)
            self.assertFalse(os.path.exists(stdout))
            self.assertTrue(os.path.exists(stderr))
            self.assertFalse(os.path.exists(pipe))

    @mock.patch("cli_topsailai.cleaning.input")
    @mock.patch("cli_topsailai.cleaning.is_file_in_use", return_value=True)
    def test_skips_in_use_expired_file(self, mock_in_use, mock_input):
        mock_input.return_value = "y"
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


class TestCleanByNumbersRelatedFiles(unittest.TestCase):
    """Tests for clean_by_numbers() related-file expansion."""

    @mock.patch("cli_topsailai.cleaning.input")
    @mock.patch("cli_topsailai.cleaning.is_file_in_use", return_value=False)
    def test_deletes_related_files_by_number(self, mock_in_use, mock_input):
        mock_input.return_value = "y"
        with tempfile.TemporaryDirectory() as tmp:
            stdout = os.path.join(tmp, "s.1.session.stdout")
            stderr = os.path.join(tmp, "s.1.session.stderr")
            pipe = os.path.join(tmp, "s.1.session.pipe")
            for p in [stdout, stderr, pipe]:
                with open(p, "w") as f:
                    f.write("x")

            files = [_make_file_record(stdout)]
            deleted_count = clean_by_numbers(tmp, files, [0])
            self.assertEqual(deleted_count, 3)
            self.assertFalse(os.path.exists(stdout))
            self.assertFalse(os.path.exists(stderr))
            self.assertFalse(os.path.exists(pipe))


if __name__ == "__main__":
    unittest.main()
