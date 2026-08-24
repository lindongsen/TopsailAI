"""Unit tests for story-memory usage statistics."""

import json
import os
import re
import tempfile
from unittest import TestCase, mock

from topsailai.tools.memory_tool_utils import memory_stat


class TestMemoryStat(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = self.temp_dir.name
        self.memory_id = "20260823154500.example.md"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ensure_creates_versioned_zero_stat_with_offset_timestamp(self):
        stat = memory_stat.ensure_memory_stat(self.workspace, self.memory_id)

        self.assertEqual(stat["version"], 1)
        self.assertEqual(stat["memory_id"], self.memory_id)
        self.assertFalse(stat["synced"])
        for event in ("read", "cite", "query", "update"):
            self.assertEqual(stat[event + "_count"], 0)
        self.assertRegex(
            stat["created_at"],
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{2}:\d{2}$",
        )
        self.assertEqual(stat["last_activity_at"], stat["created_at"])

    def test_read_event_increments_and_uses_one_timestamp(self):
        with mock.patch.object(
            memory_stat.time_tool,
            "get_current_local_datetime_with_offset",
            side_effect=["2026-08-23 15:40:00 +08:00", "2026-08-23 15:45:00 +08:00"],
        ):
            memory_stat.ensure_memory_stat(self.workspace, self.memory_id)
            stat = memory_stat.record_memory_event(self.workspace, self.memory_id, "read")

        self.assertEqual(stat["read_count"], 1)
        self.assertEqual(stat["last_read_at"], "2026-08-23 15:45:00 +08:00")
        self.assertEqual(stat["last_activity_at"], stat["last_read_at"])

    def test_direct_write_produces_valid_stat_file(self):
        expected = memory_stat.ensure_memory_stat(self.workspace, self.memory_id)
        stat_file = memory_stat.get_stat_file(self.workspace, self.memory_id)

        with open(stat_file, encoding="utf-8") as fd:
            self.assertEqual(json.load(fd), expected)

    def test_mutation_holds_stable_per_memory_lock(self):
        with mock.patch.object(memory_stat.lock_tool, "FileLock", wraps=memory_stat.lock_tool.FileLock) as lock:
            memory_stat.ensure_memory_stat(self.workspace, self.memory_id)

        _, kwargs = lock.call_args
        self.assertFalse(kwargs["delete_on_release"])

    def test_delete_missing_is_successful_noop(self):
        self.assertFalse(memory_stat.delete_memory_stat(self.workspace, self.memory_id))

    def test_delete_error_propagates(self):
        memory_stat.ensure_memory_stat(self.workspace, self.memory_id)
        with mock.patch.object(memory_stat.os, "remove", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                memory_stat.delete_memory_stat(self.workspace, self.memory_id)


class TestMemoryStatValidation(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = self.temp_dir.name
        self.memory_id = "canonical.md"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_read_memory_stat_returns_persisted_stat(self):
        expected = memory_stat.ensure_memory_stat(self.workspace, self.memory_id)
        self.assertEqual(
            memory_stat.read_memory_stat(self.workspace, self.memory_id), expected
        )

    def test_read_memory_stat_returns_none_when_missing_without_rebuild(self):
        with mock.patch.object(memory_stat, "ensure_memory_stat") as rebuild:
            self.assertIsNone(memory_stat.read_memory_stat(self.workspace, self.memory_id))
        rebuild.assert_not_called()

    def test_retry_succeeds_after_transient_corrupt_read(self):
        expected = memory_stat._new_stat(
            self.memory_id, "2026-08-23 15:45:00 +08:00"
        )
        decode_error = json.JSONDecodeError("partial", "{", 1)
        with mock.patch.object(
            memory_stat, "_read_stat_file", side_effect=[decode_error, expected]
        ), mock.patch.object(memory_stat.time, "sleep") as sleep:
            actual = memory_stat.read_memory_stat(self.workspace, self.memory_id)

        self.assertEqual(actual, expected)
        sleep.assert_called_once_with(memory_stat.READ_RETRY_DELAY_SECONDS)

    def test_persistent_unparseable_stat_rebuilds_zero_counts(self):
        stat_file = memory_stat.get_stat_file(self.workspace, self.memory_id)
        os.makedirs(os.path.dirname(stat_file), exist_ok=True)
        with open(stat_file, "w", encoding="utf-8") as fd:
            fd.write("{")

        with mock.patch.object(memory_stat.time, "sleep") as sleep:
            stat = memory_stat.read_memory_stat(self.workspace, self.memory_id)

        self.assertEqual(sleep.call_count, memory_stat.READ_RETRY_ATTEMPTS - 1)
        self.assertEqual(stat["memory_id"], self.memory_id)
        for event in ("read", "cite", "query", "update"):
            self.assertEqual(stat[event + "_count"], 0)
        with open(stat_file, encoding="utf-8") as fd:
            self.assertEqual(json.load(fd), stat)

    def test_structurally_invalid_stat_rebuilds(self):
        stat_file = memory_stat.get_stat_file(self.workspace, self.memory_id)
        os.makedirs(os.path.dirname(stat_file), exist_ok=True)
        with open(stat_file, "w", encoding="utf-8") as fd:
            json.dump({"version": 1, "memory_id": "different.md"}, fd)

        with mock.patch.object(memory_stat.time, "sleep"):
            stat = memory_stat.read_memory_stat(self.workspace, self.memory_id)

        self.assertEqual(stat["memory_id"], self.memory_id)
        self.assertEqual(stat["read_count"], 0)

    def test_legacy_stat_without_synced_remains_valid_and_unsynced(self):
        """Accept legacy v1 stats and treat their missing synced flag as false."""
        legacy = memory_stat._new_stat(
            self.memory_id, "2026-08-23 15:45:00 +08:00"
        )
        legacy.pop("synced")

        self.assertIs(memory_stat._validate_stat(legacy, self.memory_id), legacy)
        self.assertFalse(memory_stat.is_memory_synced(legacy))

    def test_is_memory_synced_handles_true_false_and_missing_values(self):
        """Normalize persisted synced values through the shared accessor."""
        self.assertTrue(memory_stat.is_memory_synced({"synced": True}))
        self.assertFalse(memory_stat.is_memory_synced({"synced": False}))
        self.assertFalse(memory_stat.is_memory_synced({}))

    def test_synced_true_round_trips_through_mutation(self):
        """Preserve an explicit synced flag through the stat mutation path."""
        memory_stat.mutate_memory_stat(
            self.workspace,
            self.memory_id,
            lambda stat, _timestamp: stat.update(synced=True),
        )

        stat = memory_stat.read_memory_stat(self.workspace, self.memory_id)
        self.assertTrue(memory_stat.is_memory_synced(stat))

    def test_non_rebuilding_reader_returns_valid_stat(self):
        """Read a valid stat without changing its persisted content."""
        expected = memory_stat.ensure_memory_stat(self.workspace, self.memory_id)
        stat_file = memory_stat.get_stat_file(self.workspace, self.memory_id)

        self.assertEqual(
            memory_stat.read_memory_stat_file(stat_file, self.memory_id), expected
        )

    def test_non_rebuilding_reader_returns_none_when_missing(self):
        """Return None for a missing stat without creating a file."""
        stat_file = memory_stat.get_stat_file(self.workspace, self.memory_id)

        self.assertIsNone(
            memory_stat.read_memory_stat_file(stat_file, self.memory_id)
        )
        self.assertFalse(os.path.exists(stat_file))

    def test_non_rebuilding_reader_surfaces_corrupt_json(self):
        """Propagate JSON corruption without rebuilding the stat."""
        stat_file = memory_stat.get_stat_file(self.workspace, self.memory_id)
        os.makedirs(os.path.dirname(stat_file), exist_ok=True)
        with open(stat_file, "w", encoding="utf-8") as fd:
            fd.write("{")

        with self.assertRaises(json.JSONDecodeError):
            memory_stat.read_memory_stat_file(stat_file, self.memory_id)
        with open(stat_file, encoding="utf-8") as fd:
            self.assertEqual(fd.read(), "{")

    def test_non_rebuilding_reader_rejects_version_mismatch(self):
        """Surface an unsupported schema version without rewriting it."""
        stat = memory_stat._new_stat(
            self.memory_id, "2026-08-23 15:45:00 +08:00"
        )
        stat["version"] = memory_stat.STAT_VERSION + 1
        stat_file = memory_stat.get_stat_file(self.workspace, self.memory_id)
        os.makedirs(os.path.dirname(stat_file), exist_ok=True)
        with open(stat_file, "w", encoding="utf-8") as fd:
            json.dump(stat, fd)

        with self.assertRaisesRegex(ValueError, "unsupported"):
            memory_stat.read_memory_stat_file(stat_file, self.memory_id)

    def test_non_rebuilding_reader_rejects_identity_mismatch(self):
        """Surface a mismatch against the caller's expected memory identity."""
        stat = memory_stat._new_stat(
            "different.md", "2026-08-23 15:45:00 +08:00"
        )
        stat_file = memory_stat.get_stat_file(self.workspace, self.memory_id)
        os.makedirs(os.path.dirname(stat_file), exist_ok=True)
        with open(stat_file, "w", encoding="utf-8") as fd:
            json.dump(stat, fd)

        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            memory_stat.read_memory_stat_file(stat_file, self.memory_id)


    def test_rejects_unknown_event(self):
        with self.assertRaisesRegex(ValueError, "unsupported memory stat event"):
            memory_stat.record_memory_event(self.workspace, self.memory_id, "unknown")

    def test_successful_delete_removes_stat(self):
        memory_stat.ensure_memory_stat(self.workspace, self.memory_id)
        stat_file = memory_stat.get_stat_file(self.workspace, self.memory_id)

        self.assertTrue(memory_stat.delete_memory_stat(self.workspace, self.memory_id))
        self.assertFalse(os.path.exists(stat_file))


class TestMemoryStatSchemaBranches(TestCase):
    def test_memory_id_uses_resolved_basename(self):
        self.assertEqual(
            memory_stat.get_memory_id("/workspace/story/day/canonical.md"),
            "canonical.md",
        )

    def test_validation_rejects_malformed_v1_records(self):
        timestamp = "2026-08-23 15:45:00 +08:00"
        valid = memory_stat._new_stat("canonical.md", timestamp)
        invalid_records = [
            ([], "JSON object"),
            ({**valid, "version": 2}, "unsupported"),
            ({**valid, "read_count": -1}, "counter"),
            ({key: value for key, value in valid.items() if key != "last_read_at"}, "timestamp"),
            ({**valid, "last_activity_at": ""}, "timestamp"),
        ]

        for record, message in invalid_records:
            with self.subTest(message=message, record=record):
                with self.assertRaisesRegex(ValueError, message):
                    memory_stat._validate_stat(record, "canonical.md")


class TestDocumentedMemoryStatHelpers(TestCase):
    """Direct tests for documented memory-stat persistence helpers."""

    def test_read_stat_file_with_retry_returns_after_transient_corruption(self):
        """Transient corrupt reads are retried and the later valid value is returned."""
        expected = {"memory_id": "memory.md"}
        with mock.patch.object(
            memory_stat,
            "_read_stat_file",
            side_effect=[ValueError("corrupt"), expected],
        ) as read_stat, mock.patch.object(memory_stat.time, "sleep") as sleep:
            result = memory_stat._read_stat_file_with_retry("stat.json", "memory.md")

        self.assertIs(result, expected)
        self.assertEqual(read_stat.call_count, 2)
        sleep.assert_called_once_with(memory_stat.READ_RETRY_DELAY_SECONDS)

    def test_read_stat_file_with_retry_raises_after_all_attempts(self):
        """Persistent corruption raises after the configured number of attempts."""
        with mock.patch.object(
            memory_stat,
            "_read_stat_file",
            side_effect=ValueError("corrupt"),
        ) as read_stat, mock.patch.object(memory_stat.time, "sleep") as sleep:
            with self.assertRaisesRegex(ValueError, "remains corrupt"):
                memory_stat._read_stat_file_with_retry("stat.json", "memory.md")

        self.assertEqual(read_stat.call_count, memory_stat.READ_RETRY_ATTEMPTS)
        self.assertEqual(sleep.call_count, memory_stat.READ_RETRY_ATTEMPTS - 1)

    def test_write_stat_creates_parent_and_writes_sorted_utf8_json(self):
        """The direct writer creates its parent and emits newline-terminated JSON."""
        with tempfile.TemporaryDirectory() as workspace:
            stat_file = os.path.join(workspace, "nested", "stat.json")
            memory_stat._write_stat(stat_file, {"z": 1, "title": "记忆"})

            with open(stat_file, encoding="utf-8") as stream:
                content = stream.read()
            self.assertTrue(content.endswith("\n"))
            self.assertLess(content.index('"title"'), content.index('"z"'))
            self.assertEqual(json.loads(content), {"z": 1, "title": "记忆"})

    def test_mutate_memory_stat_creates_and_applies_mutation_timestamp(self):
        """Mutation receives the creation timestamp and its valid changes persist."""
        with tempfile.TemporaryDirectory() as workspace, mock.patch.object(
            memory_stat.time_tool,
            "get_current_local_datetime_with_offset",
            return_value="2026-08-24 05:00:00 +00:00",
        ):
            def mutate(stat, timestamp):
                stat["read_count"] += 1
                stat["last_read_at"] = timestamp
                stat["last_activity_at"] = timestamp

            result = memory_stat.mutate_memory_stat(workspace, "memory.md", mutate)
            persisted = memory_stat.read_memory_stat(workspace, "memory.md")

        self.assertEqual(result["read_count"], 1)
        self.assertEqual(result["last_read_at"], "2026-08-24 05:00:00 +00:00")
        self.assertEqual(persisted, result)

    def test_mutate_memory_stat_rejects_invalid_mutation(self):
        """Mutations that violate the stat schema fail before persistence."""
        with tempfile.TemporaryDirectory() as workspace:
            with self.assertRaisesRegex(ValueError, "counter"):
                memory_stat.mutate_memory_stat(
                    workspace,
                    "memory.md",
                    lambda stat, _timestamp: stat.update(read_count=-1),
                )
