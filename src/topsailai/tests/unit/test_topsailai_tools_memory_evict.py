"""Unit tests for synchronized memory LRU eviction."""

import json
import os
import tempfile
from unittest import TestCase, mock

from topsailai.tools.memory_tool_utils import memory_evict, memory_stat


class TestMemoryEvict(TestCase):
    """Exercise healthy-pair selection and safe stat-first deletion."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = self.temp_dir.name
        self.day_dir = os.path.join(self.workspace, "story", "2026-08-24")
        os.makedirs(self.day_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_pair(
        self,
        memory_id: str,
        last_activity_at: str,
        synced: bool = True,
    ) -> tuple[str, str]:
        """Create one healthy Markdown/stat pair and return both paths."""
        memory_file = os.path.join(self.day_dir, memory_id)
        with open(memory_file, "w", encoding="utf-8") as fd:
            fd.write("content")
        stat = memory_stat.ensure_memory_stat(self.workspace, memory_id)
        stat["last_activity_at"] = last_activity_at
        stat["synced"] = synced
        stat_file = memory_stat.get_stat_file(self.workspace, memory_id)
        with open(stat_file, "w", encoding="utf-8") as fd:
            json.dump(stat, fd)
        return memory_file, stat_file

    def test_non_positive_limit_is_disabled(self):
        """Verify zero and negative limits return empty summaries."""
        self._write_pair("kept.md", "2026-08-24 01:00:00 +00:00")

        for max_count in (0, -1):
            summary = memory_evict.evict_memory_stats(
                self.workspace, max_count, dry_run=False
            )
            self.assertEqual(summary.scanned, 0)
            self.assertEqual(summary.evicted, 0)
            self.assertEqual(summary.errors, 0)

    def test_not_over_limit_does_not_evict(self):
        """Verify a healthy store within its limit remains unchanged."""
        memory_file, stat_file = self._write_pair(
            "kept.md", "2026-08-24 01:00:00 +00:00"
        )

        summary = memory_evict.evict_memory_stats(
            self.workspace, 1, dry_run=False
        )

        self.assertEqual(summary.scanned, 1)
        self.assertEqual(summary.eligible, 1)
        self.assertEqual(summary.evicted, 0)
        self.assertTrue(os.path.exists(memory_file))
        self.assertTrue(os.path.exists(stat_file))

    def test_oldest_synced_memory_is_evicted_first(self):
        """Verify LRU ordering removes the oldest synchronized pair."""
        oldest = self._write_pair("oldest.md", "2026-08-24 01:00:00 +00:00")
        newest = self._write_pair("newest.md", "2026-08-24 02:00:00 +00:00")

        summary = memory_evict.evict_memory_stats(
            self.workspace, 1, dry_run=False
        )

        self.assertEqual(summary.evicted, 1)
        self.assertFalse(os.path.exists(oldest[0]))
        self.assertFalse(os.path.exists(oldest[1]))
        self.assertTrue(os.path.exists(newest[0]))
        self.assertTrue(os.path.exists(newest[1]))

    def test_equal_activity_uses_memory_id_tie_break(self):
        """Verify equal timestamps evict lexicographically smaller IDs first."""
        timestamp = "2026-08-24 01:00:00 +00:00"
        first = self._write_pair("a.md", timestamp)
        second = self._write_pair("b.md", timestamp)

        victims = memory_evict.select_eviction_victims(self.workspace, 1)

        self.assertEqual(victims, [(first[0], first[1])])
        self.assertTrue(os.path.exists(second[0]))

    def test_unsynced_memory_is_fully_protected(self):
        """Verify unsynced local-only memories are never selected as victims."""
        unsynced = self._write_pair(
            "old-local.md", "2026-08-24 01:00:00 +00:00", synced=False
        )
        synced = self._write_pair(
            "new-remote.md", "2026-08-24 02:00:00 +00:00", synced=True
        )

        summary = memory_evict.evict_memory_stats(
            self.workspace, 1, dry_run=False
        )

        self.assertEqual(summary.protected_unsynced, 1)
        self.assertEqual(summary.evicted, 1)
        self.assertTrue(os.path.exists(unsynced[0]))
        self.assertTrue(os.path.exists(unsynced[1]))
        self.assertFalse(os.path.exists(synced[0]))
        self.assertFalse(os.path.exists(synced[1]))

    def test_all_unsynced_can_remain_above_limit(self):
        """Verify protection may leave the store above its configured bound."""
        for memory_id in ("a.md", "b.md"):
            self._write_pair(
                memory_id, "2026-08-24 01:00:00 +00:00", synced=False
            )

        summary = memory_evict.evict_memory_stats(
            self.workspace, 1, dry_run=False
        )

        self.assertEqual(summary.scanned, 2)
        self.assertEqual(summary.eligible, 0)
        self.assertEqual(summary.protected_unsynced, 2)
        self.assertEqual(summary.evicted, 0)

    def test_dry_run_logs_plan_without_deleting(self):
        """Verify dry-run reports both planned deletions and preserves files."""
        memory_file, stat_file = self._write_pair(
            "planned.md", "2026-08-24 01:00:00 +00:00"
        )
        self._write_pair("newer.md", "2026-08-24 02:00:00 +00:00")

        with mock.patch.object(memory_evict.logger, "info") as mock_info:
            summary = memory_evict.evict_memory_stats(self.workspace, 1)

        self.assertEqual(summary.evicted, 1)
        self.assertTrue(os.path.exists(memory_file))
        self.assertTrue(os.path.exists(stat_file))
        mock_info.assert_any_call(
            "would delete evicted memory stat: [%s]", stat_file
        )
        mock_info.assert_any_call("would delete evicted memory: [%s]", memory_file)

    def test_live_delete_is_stat_first_and_logged(self):
        """Verify live deletion removes stat before Markdown and logs both."""
        memory_file, stat_file = self._write_pair(
            "old.md", "2026-08-24 01:00:00 +00:00"
        )
        self._write_pair("new.md", "2026-08-24 02:00:00 +00:00")
        real_remove = os.remove
        removed = []

        def capture(path: str) -> None:
            removed.append(path)
            real_remove(path)

        with mock.patch.object(memory_evict.os, "remove", side_effect=capture), \
                mock.patch.object(memory_evict.logger, "info") as mock_info:
            summary = memory_evict.evict_memory_stats(
                self.workspace, 1, dry_run=False
            )

        self.assertEqual(summary.evicted, 1)
        self.assertEqual(removed, [stat_file, memory_file])
        mock_info.assert_any_call("delete evicted memory stat: [%s]", stat_file)
        mock_info.assert_any_call("delete evicted memory: [%s]", memory_file)

    def test_single_failure_is_counted_and_later_victim_continues(self):
        """Verify one failed victim does not prevent later eviction attempts."""
        first = self._write_pair("a.md", "2026-08-24 01:00:00 +00:00")
        second = self._write_pair("b.md", "2026-08-24 02:00:00 +00:00")
        self._write_pair("c.md", "2026-08-24 03:00:00 +00:00")
        real_remove = os.remove

        def fail_first(path: str) -> None:
            if path == first[1]:
                raise OSError("fixture failure")
            real_remove(path)

        with mock.patch.object(memory_evict.os, "remove", side_effect=fail_first), \
                mock.patch.object(memory_evict.logger, "exception") as mock_error:
            summary = memory_evict.evict_memory_stats(
                self.workspace, 1, dry_run=False
            )

        self.assertEqual(summary.errors, 1)
        self.assertEqual(summary.evicted, 1)
        self.assertTrue(os.path.exists(first[0]))
        self.assertTrue(os.path.exists(first[1]))
        self.assertFalse(os.path.exists(second[0]))
        self.assertFalse(os.path.exists(second[1]))
        mock_error.assert_called_once()

    def test_orphan_and_corrupt_stats_are_untouched(self):
        """Verify eviction ignores records reserved for reconciliation."""
        orphan_file = memory_stat.get_stat_file(self.workspace, "orphan.md")
        os.makedirs(os.path.dirname(orphan_file), exist_ok=True)
        with open(orphan_file, "w", encoding="utf-8") as fd:
            json.dump(memory_stat._new_stat("orphan.md", "2026-08-24 01:00:00 +00:00"), fd)
        corrupt_file = memory_stat.get_stat_file(self.workspace, "corrupt.md")
        with open(corrupt_file, "w", encoding="utf-8") as fd:
            fd.write("{")

        summary = memory_evict.evict_memory_stats(
            self.workspace, 1, dry_run=False
        )

        self.assertEqual(summary.scanned, 0)
        self.assertEqual(summary.evicted, 0)
        self.assertTrue(os.path.exists(orphan_file))
        self.assertTrue(os.path.exists(corrupt_file))

    def test_global_lock_precedes_victim_lock(self):
        """Verify eviction preserves the global-to-stat lock ordering."""
        self._write_pair("old.md", "2026-08-24 01:00:00 +00:00")
        self._write_pair("new.md", "2026-08-24 02:00:00 +00:00")
        entered = []

        class TrackingLock:
            """Record lock entry without touching filesystem lock state."""

            def __init__(self, name, delete_on_release=False):
                self.name = name

            def __enter__(self):
                entered.append(self.name)
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        with mock.patch.object(memory_evict.lock_tool, "FileLock", TrackingLock):
            memory_evict.evict_memory_stats(self.workspace, 1)

        self.assertEqual(entered[0], "story_tool")
        self.assertTrue(entered[1].startswith("memory_stat_"))
