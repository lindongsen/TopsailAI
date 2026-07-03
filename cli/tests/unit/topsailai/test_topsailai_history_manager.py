#!/usr/bin/env python3
"""
Unit tests for the HistoryManager class in cli_topsailai.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from cli_topsailai.history import (
    DEFAULT_HISTORY_MAX_BACKUPS,
    DEFAULT_HISTORY_MAX_ENTRIES,
    DEFAULT_HISTORY_MAX_SIZE_MB,
    HistoryManager,
)


class TestHistoryManager(unittest.TestCase):
    """Tests for HistoryManager."""

    def test_load_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = HistoryManager(tmpdir)
            manager.load_all()
            self.assertEqual(manager.entries, [])

    def test_add_and_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = HistoryManager(tmpdir)
            manager.add("hello")
            manager.save_all()
            self.assertTrue(os.path.exists(manager.history_file))

    def test_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = HistoryManager(tmpdir)
            manager.add("hello world")
            manager.add("goodbye")
            results = manager.search("hello")
            self.assertEqual(len(results), 1)
            self.assertIn("hello", results[0])


class TestHistoryManagerDefaults(unittest.TestCase):
    """Tests for default configuration constants."""

    def test_default_max_entries_is_100(self):
        """DEFAULT_HISTORY_MAX_ENTRIES must be 100 per the coding rules."""
        self.assertEqual(DEFAULT_HISTORY_MAX_ENTRIES, 100)

    def test_default_max_size_mb_is_1(self):
        """DEFAULT_HISTORY_MAX_SIZE_MB must be 1 per the user requirement."""
        self.assertEqual(DEFAULT_HISTORY_MAX_SIZE_MB, 1)

    def test_default_max_backups_is_1(self):
        """DEFAULT_HISTORY_MAX_BACKUPS must be 1 per the user requirement."""
        self.assertEqual(DEFAULT_HISTORY_MAX_BACKUPS, 1)


class TestHistoryManagerLimitedLoad(unittest.TestCase):
    """Tests for limited history loading from large files."""

    def _write_history(self, path: str, count: int) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for i in range(count):
                f.write(json.dumps({"text": f"cmd{i}", "scope": "workspace"}) + "\n")

    def test_loads_only_recent_default_limit(self):
        """Only the most recent 100 entries are loaded by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            self._write_history(path, 150)
            manager = HistoryManager(path)
            manager.load_all()
            self.assertEqual(len(manager.entries), 100)
            self.assertEqual(manager.entries[0]["text"], "cmd50")
            self.assertEqual(manager.entries[-1]["text"], "cmd149")

    def test_env_var_controls_limit(self):
        """TOPSAILAI_HISTORY_MAX_ENTRIES controls how many entries are loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            self._write_history(path, 100)
            manager = HistoryManager(path)
            with patch.dict(
                os.environ, {"TOPSAILAI_HISTORY_MAX_ENTRIES": "10"}
            ):
                manager.load_all()
            self.assertEqual(len(manager.entries), 10)
            self.assertEqual(manager.entries[0]["text"], "cmd90")
            self.assertEqual(manager.entries[-1]["text"], "cmd99")

    def test_invalid_env_var_falls_back_to_default(self):
        """Non-numeric env var falls back to the default limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            self._write_history(path, 5)
            manager = HistoryManager(path)
            with patch.dict(
                os.environ, {"TOPSAILAI_HISTORY_MAX_ENTRIES": "not-a-number"}
            ):
                manager.load_all()
            self.assertEqual(len(manager.entries), 5)

    def test_zero_env_var_falls_back_to_default(self):
        """Zero or negative env var falls back to the default limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            self._write_history(path, 5)
            manager = HistoryManager(path)
            with patch.dict(
                os.environ, {"TOPSAILAI_HISTORY_MAX_ENTRIES": "0"}
            ):
                manager.load_all()
            self.assertEqual(len(manager.entries), 5)

    def test_loads_all_when_file_smaller_than_limit(self):
        """All entries are loaded when the file has fewer than the limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            self._write_history(path, 50)
            manager = HistoryManager(path)
            manager.load_all()
            self.assertEqual(len(manager.entries), 50)
            self.assertEqual(manager.entries[0]["text"], "cmd0")
            self.assertEqual(manager.entries[-1]["text"], "cmd49")

    def test_empty_lines_are_skipped(self):
        """Blank lines in the history file do not count toward the limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                for i in range(12):
                    f.write(json.dumps({"text": f"cmd{i}", "scope": "workspace"}) + "\n")
                    f.write("\n")
            manager = HistoryManager(path)
            with patch.dict(
                os.environ, {"TOPSAILAI_HISTORY_MAX_ENTRIES": "5"}
            ):
                manager.load_all()
            self.assertEqual(len(manager.entries), 5)
            self.assertEqual(manager.entries[-1]["text"], "cmd11")


class TestHistoryManagerRotation(unittest.TestCase):
    """Tests for history file rotation."""

    def _write_oversized_file(self, path: str) -> None:
        """Write a file slightly larger than the 1 MB test threshold."""
        with open(path, "wb") as f:
            f.write(b"x" * (1024 * 1024 + 1))

    def test_rotation_triggered_when_size_exceeded(self):
        """The active file is rotated when it exceeds the size threshold."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            self._write_oversized_file(path)
            manager = HistoryManager(path)
            with patch.dict(
                os.environ,
                {
                    "TOPSAILAI_HISTORY_MAX_SIZE_MB": "1",
                    "TOPSAILAI_HISTORY_MAX_BACKUPS": "1",
                },
            ):
                manager.add("after-rotation")

            self.assertTrue(os.path.exists(path))
            self.assertTrue(os.path.exists(path + ".1"))
            with open(path, "r", encoding="utf-8") as f:
                current = f.read()
            self.assertIn("after-rotation", current)
            with open(path + ".1", "rb") as f:
                self.assertGreater(len(f.read()), 1024 * 1024)

    def test_only_one_backup_kept(self):
        """Only one backup is kept; the previous backup is overwritten."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            manager = HistoryManager(path)
            with patch.dict(
                os.environ,
                {
                    "TOPSAILAI_HISTORY_MAX_SIZE_MB": "1",
                    "TOPSAILAI_HISTORY_MAX_BACKUPS": "1",
                },
            ):
                for i in range(3):
                    self._write_oversized_file(path)
                    manager.add(f"cmd{i}")

            self.assertTrue(os.path.exists(path + ".1"))
            self.assertFalse(os.path.exists(path + ".2"))
            with open(path, "r", encoding="utf-8") as f:
                self.assertIn("cmd2", f.read())

    def test_no_data_loss_during_rotation(self):
        """Existing entries are preserved in the rotated backup file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"text": "first", "scope": "workspace"}\n')
                f.write('{"text": "second", "scope": "workspace"}\n')
            # Pad the file so it exceeds the 1 MB threshold.
            with open(path, "ab") as f:
                f.write(b"x" * (1024 * 1024))

            manager = HistoryManager(path)
            with patch.dict(
                os.environ,
                {
                    "TOPSAILAI_HISTORY_MAX_SIZE_MB": "1",
                    "TOPSAILAI_HISTORY_MAX_BACKUPS": "1",
                },
            ):
                manager.add("third")

            with open(path + ".1", "r", encoding="utf-8") as f:
                backup_text = f.read()
            self.assertIn("first", backup_text)
            self.assertIn("second", backup_text)
            with open(path, "r", encoding="utf-8") as f:
                self.assertIn("third", f.read())

    def test_rotation_not_triggered_below_threshold(self):
        """No rotation occurs when the file is below the size threshold."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"text": "small", "scope": "workspace"}\n')
            manager = HistoryManager(path)
            with patch.dict(
                os.environ,
                {
                    "TOPSAILAI_HISTORY_MAX_SIZE_MB": "1",
                    "TOPSAILAI_HISTORY_MAX_BACKUPS": "1",
                },
            ):
                manager.add("another")
            self.assertFalse(os.path.exists(path + ".1"))


class TestHistoryManagerTimestamp(unittest.TestCase):
    """Tests for millisecond timestamp format and legacy compatibility."""

    def test_append_writes_millisecond_timestamp(self):
        """New entries are written with an integer millisecond timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            manager = HistoryManager(path)
            before_ms = int(time.time() * 1000)
            manager.add("hello")
            after_ms = int(time.time() * 1000)

            with open(path, "r", encoding="utf-8") as f:
                entry = json.loads(f.readline())

            ts = entry["ts"]
            self.assertIsInstance(ts, int)
            self.assertGreaterEqual(ts, 1_000_000_000_000)
            self.assertGreaterEqual(ts, before_ms)
            self.assertLessEqual(ts, after_ms)

    def test_load_normalizes_second_timestamp(self):
        """Integer second timestamps are converted to milliseconds on load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"text": "cmd", "scope": "workspace", "ts": 1700000000}\n')
            manager = HistoryManager(path)
            manager.load_all()
            self.assertEqual(manager.entries[0]["ts"], 1700000000000)

    def test_load_normalizes_float_timestamp(self):
        """Float second timestamps are converted to milliseconds on load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"text": "cmd", "scope": "workspace", "ts": 1700000000.5}\n')
            manager = HistoryManager(path)
            manager.load_all()
            self.assertEqual(manager.entries[0]["ts"], 1700000000500)

    def test_load_normalizes_string_timestamp(self):
        """Numeric string timestamps are converted to milliseconds on load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"text": "cmd", "scope": "workspace", "ts": "1700000000"}\n')
            manager = HistoryManager(path)
            manager.load_all()
            self.assertEqual(manager.entries[0]["ts"], 1700000000000)

    def test_load_normalizes_iso_timestamp(self):
        """ISO 8601 string timestamps are converted to milliseconds on load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            expected_ms = int(dt.timestamp() * 1000)
            entry = {"text": "cmd", "scope": "workspace", "ts": dt.isoformat()}
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            manager = HistoryManager(path)
            manager.load_all()
            self.assertEqual(manager.entries[0]["ts"], expected_ms)

    def test_load_keeps_millisecond_timestamp(self):
        """Timestamps already in milliseconds are left unchanged on load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"text": "cmd", "scope": "workspace", "ts": 1700000000000}\n')
            manager = HistoryManager(path)
            manager.load_all()
            self.assertEqual(manager.entries[0]["ts"], 1700000000000)


if __name__ == "__main__":
    unittest.main()
