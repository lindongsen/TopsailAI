"""Unit tests for memory stat reconciliation core behavior."""

import json
import os
import tempfile
from unittest import TestCase, mock

from topsailai.tools.memory_tool_utils import memory_reconcile, memory_stat


class TestMemoryReconcile(TestCase):
    """Exercise reconciliation classifications and dry-run behavior."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = self.temp_dir.name
        self.day_dir = os.path.join(self.workspace, "story", "2026-08-24")
        os.makedirs(self.day_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_memory(self, memory_id: str, day: str = "2026-08-24") -> str:
        """Create a Markdown memory fixture and return its path."""
        folder = os.path.join(self.workspace, "story", day)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, memory_id)
        with open(path, "w", encoding="utf-8") as fd:
            fd.write("content")
        return path

    def _write_raw_stat(self, memory_id: str, value) -> str:
        """Create a raw stat fixture without normal validation."""
        path = memory_stat.get_stat_file(self.workspace, memory_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fd:
            if isinstance(value, str):
                fd.write(value)
            else:
                json.dump(value, fd)
        return path

    def test_healthy_pair_is_untouched(self):
        memory_id = "healthy.md"
        self._write_memory(memory_id)
        expected = memory_stat.ensure_memory_stat(self.workspace, memory_id)

        summary = memory_reconcile.reconcile_memory_stats(self.workspace)

        self.assertEqual(summary.scanned, 2)
        self.assertEqual(summary.healthy, 1)
        self.assertEqual(summary.to_dict()["dry_run"], True)
        self.assertEqual(memory_stat.read_memory_stat(self.workspace, memory_id), expected)

    def test_default_dry_run_reports_without_mutating(self):
        missing_id = "missing.md"
        orphan_id = "orphan.md"
        self._write_memory(missing_id)
        orphan_file = self._write_raw_stat(
            orphan_id,
            memory_stat._new_stat(orphan_id, "2026-08-24 04:00:00 +00:00"),
        )

        summary = memory_reconcile.reconcile_memory_stats(self.workspace)

        self.assertEqual(summary.rebuilt, 1)
        self.assertEqual(summary.purged_orphan, 1)
        self.assertFalse(os.path.exists(memory_stat.get_stat_file(self.workspace, missing_id)))
        self.assertTrue(os.path.exists(orphan_file))

    def test_live_mode_rebuilds_missing_and_purges_orphan(self):
        missing_id = "missing.md"
        orphan_id = "orphan.md"
        memory_file = self._write_memory(missing_id)
        os.utime(memory_file, (1_700_000_000, 1_700_000_000))
        self._write_raw_stat(
            orphan_id,
            memory_stat._new_stat(orphan_id, "2026-08-24 04:00:00 +00:00"),
        )

        summary = memory_reconcile.reconcile_memory_stats(
            self.workspace, dry_run=False
        )

        self.assertEqual(summary.rebuilt, 1)
        self.assertEqual(summary.purged_orphan, 1)
        rebuilt = memory_stat.read_memory_stat(self.workspace, missing_id)
        self.assertEqual(rebuilt["read_count"], 0)
        self.assertFalse(os.path.exists(memory_stat.get_stat_file(self.workspace, orphan_id)))

    def test_corrupt_stat_is_quarantined_then_rebuilt(self):
        memory_id = "corrupt.md"
        self._write_memory(memory_id)
        stat_file = self._write_raw_stat(memory_id, "{")

        summary = memory_reconcile.reconcile_memory_stats(
            self.workspace, dry_run=False
        )

        self.assertEqual(summary.quarantined, 1)
        self.assertEqual(summary.rebuilt, 0)
        self.assertFalse(os.path.exists(stat_file))
        quarantine = os.path.join(
            self.workspace, "story", ".stats", memory_reconcile.QUARANTINE_FOLDER
        )
        self.assertEqual(len(os.listdir(quarantine)), 1)

    def test_version_and_identity_mismatches_are_quarantined(self):
        first_id = "version.md"
        second_id = "identity.md"
        self._write_memory(first_id)
        self._write_memory(second_id)
        version_stat = memory_stat._new_stat(
            first_id, "2026-08-24 04:00:00 +00:00"
        )
        version_stat["version"] = memory_stat.STAT_VERSION + 1
        self._write_raw_stat(first_id, version_stat)
        self._write_raw_stat(
            second_id,
            memory_stat._new_stat("different.md", "2026-08-24 04:00:00 +00:00"),
        )

        summary = memory_reconcile.reconcile_memory_stats(self.workspace)

        self.assertEqual(summary.quarantined, 2)
        self.assertEqual(summary.healthy, 0)

    def test_duplicate_memory_ids_make_existing_stat_ambiguous(self):
        memory_id = "duplicate.md"
        self._write_memory(memory_id, "2026-08-23")
        self._write_memory(memory_id, "2026-08-24")
        self._write_raw_stat(
            memory_id,
            memory_stat._new_stat(memory_id, "2026-08-24 04:00:00 +00:00"),
        )

        summary = memory_reconcile.reconcile_memory_stats(self.workspace)

        self.assertEqual(summary.quarantined, 1)
        self.assertEqual(summary.rebuilt, 0)

    def test_existing_stats_are_processed_in_sorted_filename_order(self):
        for memory_id in ("z.md", "a.md"):
            self._write_raw_stat(
                memory_id,
                memory_stat._new_stat(memory_id, "2026-08-24 04:00:00 +00:00"),
            )
        observed = []
        original = memory_reconcile._process_stat

        def capture(workspace, stat_file, markdown_by_id, dry_run, summary):
            observed.append(os.path.basename(stat_file))
            return original(workspace, stat_file, markdown_by_id, dry_run, summary)

        with mock.patch.object(memory_reconcile, "_process_stat", side_effect=capture):
            memory_reconcile.reconcile_memory_stats(self.workspace)

        self.assertEqual(observed, sorted(observed))

    def test_empty_store_returns_zero_summary(self):
        summary = memory_reconcile.reconcile_memory_stats(self.workspace)

        self.assertEqual(summary.scanned, 0)
        self.assertEqual(summary.errors, 0)
        self.assertGreaterEqual(summary.elapsed_ms, 0)

    def test_record_failure_isolated_from_later_records(self):
        for memory_id in ("a.md", "b.md"):
            self._write_raw_stat(
                memory_id,
                memory_stat._new_stat(memory_id, "2026-08-24 04:00:00 +00:00"),
            )
        original = memory_reconcile._process_stat
        calls = []

        def fail_first(workspace, stat_file, markdown_by_id, dry_run, summary):
            calls.append(stat_file)
            if len(calls) == 1:
                raise OSError("fixture failure")
            return original(workspace, stat_file, markdown_by_id, dry_run, summary)

        with mock.patch.object(memory_reconcile, "_process_stat", side_effect=fail_first):
            summary = memory_reconcile.reconcile_memory_stats(self.workspace)

        self.assertEqual(summary.errors, 1)
        self.assertEqual(summary.purged_orphan, 1)
        self.assertEqual(len(calls), 2)


    def _write_quarantine_file(self, name: str, mtime: float) -> str:
        """Create a quarantined stat fixture with a controlled mtime."""
        folder = os.path.join(
            self.workspace,
            "story",
            memory_stat.STAT_FOLDER,
            memory_reconcile.QUARANTINE_FOLDER,
        )
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as fd:
            fd.write("quarantined")
        os.utime(path, (mtime, mtime))
        return path

    def test_retention_removes_expired_quarantine_with_log(self):
        """Verify live age retention deletes expired files observably."""
        now = 2_000_000_000.0
        expired = self._write_quarantine_file("expired.json", now - 31 * 86400)
        recent = self._write_quarantine_file("recent.json", now - 29 * 86400)

        with mock.patch.object(memory_reconcile.time, "time", return_value=now), \
                mock.patch.object(memory_reconcile.logger, "info") as mock_info:
            memory_reconcile.reconcile_memory_stats(
                self.workspace,
                dry_run=False,
                quarantine_max_age_days=30,
            )

        self.assertFalse(os.path.exists(expired))
        self.assertTrue(os.path.exists(recent))
        mock_info.assert_called_once_with(
            "delete %s quarantine memory stat: [%s]", "expired", expired
        )

    def test_retention_count_removes_oldest_first(self):
        """Verify count retention keeps only the newest quarantined files."""
        oldest = self._write_quarantine_file("oldest.json", 100.0)
        middle = self._write_quarantine_file("middle.json", 200.0)
        newest = self._write_quarantine_file("newest.json", 300.0)

        memory_reconcile.reconcile_memory_stats(
            self.workspace,
            dry_run=False,
            quarantine_max_count=2,
        )

        self.assertFalse(os.path.exists(oldest))
        self.assertTrue(os.path.exists(middle))
        self.assertTrue(os.path.exists(newest))

    def test_zero_retention_limits_disable_cleanup(self):
        """Verify zero disables both age-based and count-based cleanup."""
        first = self._write_quarantine_file("first.json", 1.0)
        second = self._write_quarantine_file("second.json", 2.0)

        memory_reconcile.reconcile_memory_stats(
            self.workspace,
            dry_run=False,
            quarantine_max_age_days=0,
            quarantine_max_count=0,
        )

        self.assertTrue(os.path.exists(first))
        self.assertTrue(os.path.exists(second))

    def test_dry_run_reports_retention_without_deleting(self):
        """Verify dry-run logs planned retention while preserving files."""
        quarantine_file = self._write_quarantine_file("planned.json", 1.0)

        with mock.patch.object(memory_reconcile.logger, "info") as mock_info:
            memory_reconcile.reconcile_memory_stats(
                self.workspace,
                quarantine_max_count=0,
                quarantine_max_age_days=1,
            )

        self.assertTrue(os.path.exists(quarantine_file))
        mock_info.assert_called_once_with(
            "would delete %s quarantine memory stat: [%s]",
            "expired",
            quarantine_file,
        )
