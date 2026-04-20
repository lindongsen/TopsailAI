"""
Unit tests for tool_stat module.

Author: AI
Created: 2026-04-15
Purpose: Comprehensive unit tests for ToolStat class functionality
"""

import unittest
from unittest.mock import patch
import threading
import time
import json
import os
import tempfile
from datetime import datetime, timedelta

from topsailai.context.tool_stat import ToolStat, get_default_stat, record_tool_call


class TestToolStatBasic(unittest.TestCase):
    """Test basic functionality of ToolStat class."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()

    def test_initialization(self):
        """Test ToolStat initialization with default and custom max_records."""
        # Default initialization
        stat = ToolStat()
        self.assertEqual(stat.total_calls, 0)
        self.assertEqual(stat.total_errors, 0)
        self.assertEqual(stat.success_rate, 0.0)
        self.assertEqual(len(stat), 0)

        # Custom max_records
        stat_custom = ToolStat(max_records=100)
        self.assertEqual(stat_custom._max_records, 100)

    def test_record_success(self):
        """Test recording successful tool calls."""
        seq = self.stat.record("curl", {"url": "example.com"})
        self.assertEqual(seq, 1)
        self.assertEqual(self.stat.total_calls, 1)
        self.assertEqual(self.stat.total_errors, 0)
        self.assertEqual(self.stat.success_rate, 100.0)

    def test_record_with_error(self):
        """Test recording tool calls with errors."""
        seq = self.stat.record("curl", {"url": "bad.com"}, error="Connection refused")
        self.assertEqual(seq, 1)
        self.assertEqual(self.stat.total_calls, 1)
        self.assertEqual(self.stat.total_errors, 1)
        self.assertEqual(self.stat.success_rate, 0.0)

    def test_record_with_metadata(self):
        """Test recording tool calls with metadata."""
        metadata = {"user": "test_user", "session": "abc123"}
        seq = self.stat.record("api_call", {"endpoint": "/test"}, metadata=metadata)

        records = self.stat.get_by_tool("api_call")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["metadata"], metadata)

    def test_record_sequence(self):
        """Test that sequence numbers increment correctly."""
        seq1 = self.stat.record("tool1")
        seq2 = self.stat.record("tool2")
        seq3 = self.stat.record("tool3")

        self.assertEqual(seq1, 1)
        self.assertEqual(seq2, 2)
        self.assertEqual(seq3, 3)


class TestToolStatProperties(unittest.TestCase):
    """Test ToolStat property methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()

    def test_stat_property(self):
        """Test the stat property returns correct aggregated stats."""
        self.stat.record("curl", {"url": "a.com"})
        self.stat.record("curl", {"url": "b.com"}, error="err")
        self.stat.record("http", {"url": "c.com"})

        stats = self.stat.stat
        self.assertEqual(stats["curl"]["total_count"], 2)
        self.assertEqual(stats["curl"]["success_count"], 1)
        self.assertEqual(stats["curl"]["error_count"], 1)
        self.assertEqual(stats["http"]["total_count"], 1)

    def test_errors_property(self):
        """Test the errors property returns correct error records."""
        self.stat.record("curl", {"url": "a.com"})
        self.stat.record("curl", {"url": "b.com"}, error="Connection refused")
        self.stat.record("curl", {"url": "c.com"}, error="Timeout")

        errors = self.stat.errors
        self.assertEqual(len(errors["curl"]), 2)
        self.assertEqual(errors["curl"][0]["error"], "Connection refused")
        self.assertEqual(errors["curl"][1]["error"], "Timeout")

    def test_total_calls_property(self):
        """Test total_calls property."""
        self.assertEqual(self.stat.total_calls, 0)
        self.stat.record("tool1")
        self.assertEqual(self.stat.total_calls, 1)
        self.stat.record("tool2")
        self.assertEqual(self.stat.total_calls, 2)

    def test_total_errors_property(self):
        """Test total_errors property."""
        self.assertEqual(self.stat.total_errors, 0)
        self.stat.record("tool1")
        self.stat.record("tool2", error="err")
        self.assertEqual(self.stat.total_errors, 1)

    def test_success_rate_property(self):
        """Test success_rate calculation."""
        # Empty state
        self.assertEqual(self.stat.success_rate, 0.0)

        # All success
        self.stat.record("tool1")
        self.stat.record("tool2")
        self.assertEqual(self.stat.success_rate, 100.0)

        # Mixed
        self.stat.record("tool3", error="err")
        self.assertAlmostEqual(self.stat.success_rate, 66.67, places=2)

    def test_uptime_property(self):
        """Test uptime property returns positive value."""
        uptime = self.stat.uptime
        self.assertGreaterEqual(uptime, 0)
        time.sleep(0.01)
        self.assertGreater(self.stat.uptime, uptime)

    def test_tool_calls_property_returns_copy(self):
        """Test that tool_calls returns a copy, not the original."""
        self.stat.record("tool1")
        calls1 = self.stat.tool_calls
        calls2 = self.stat.tool_calls

        # Should be equal in content
        self.assertEqual(calls1, calls2)

        # But should be different objects
        self.assertIsNot(calls1, calls2)


class TestToolStatQueryMethods(unittest.TestCase):
    """Test ToolStat query methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()
        self.stat.record("curl", {"url": "a.com"})
        self.stat.record("curl", {"url": "b.com"}, error="err1")
        self.stat.record("http", {"url": "c.com"})
        self.stat.record("http", {"url": "d.com"})

    def test_get_by_tool(self):
        """Test get_by_tool returns correct records."""
        curl_records = self.stat.get_by_tool("curl")
        self.assertEqual(len(curl_records), 2)

        http_records = self.stat.get_by_tool("http")
        self.assertEqual(len(http_records), 2)

        nonexistent = self.stat.get_by_tool("nonexistent")
        self.assertEqual(len(nonexistent), 0)

    def test_get_by_tool_returns_copy(self):
        """Test get_by_tool returns copies, not originals."""
        records = self.stat.get_by_tool("curl")
        records[0]["modified"] = True

        # Original should be unchanged
        self.assertNotIn("modified", self.stat.get_by_tool("curl")[0])

    def test_get_by_time_range(self):
        """Test get_by_time_range filtering."""
        # Record a call
        before_record = datetime.now()
        self.stat.record("time_test", {"test": True})
        after_record = datetime.now()

        # Get records in range
        results = self.stat.get_by_time_range(start=before_record, end=after_record)
        self.assertGreaterEqual(len(results), 1)

        # Test with no bounds (4 from setUp + 1 from this test = 5)
        all_results = self.stat.get_by_time_range()
        self.assertEqual(len(all_results), 5)

    def test_get_by_time_range_no_results(self):
        """Test get_by_time_range with range that excludes all records."""
        future_start = datetime.now() + timedelta(days=1)
        future_end = datetime.now() + timedelta(days=2)

        results = self.stat.get_by_time_range(start=future_start, end=future_end)
        self.assertEqual(len(results), 0)

    def test_get_recent(self):
        """Test get_recent returns most recent calls."""
        self.stat.record("new_tool1")
        self.stat.record("new_tool2")

        recent = self.stat.get_recent(3)
        self.assertEqual(len(recent), 3)

        # Last record should be new_tool2
        self.assertEqual(recent[-1]["tool_call"], "new_tool2")

    def test_get_recent_exceeds_total(self):
        """Test get_recent when count exceeds total records."""
        recent = self.stat.get_recent(100)
        self.assertEqual(len(recent), 4)  # Only 4 records from setUp

    def test_get_tool_stats(self):
        """Test get_tool_stats for specific tool."""
        stats = self.stat.get_tool_stats("curl")

        self.assertEqual(stats["total_count"], 2)
        self.assertEqual(stats["success_count"], 1)
        self.assertEqual(stats["error_count"], 1)
        self.assertEqual(stats["success_rate"], 50.0)
        self.assertIsNotNone(stats["last_called"])
        self.assertEqual(stats["last_error"], "err1")

    def test_get_tool_stats_nonexistent(self):
        """Test get_tool_stats for non-existent tool."""
        stats = self.stat.get_tool_stats("nonexistent")

        self.assertEqual(stats["total_count"], 0)
        self.assertEqual(stats["success_count"], 0)
        self.assertEqual(stats["error_count"], 0)
        self.assertEqual(stats["success_rate"], 0.0)
        self.assertIsNone(stats["last_called"])
        self.assertIsNone(stats["last_error"])

    def test_get_most_called(self):
        """Test get_most_called returns tools sorted by call count."""
        # Add more curl calls
        self.stat.record("curl", {"url": "d.com"})
        self.stat.record("curl", {"url": "e.com"})

        most_called = self.stat.get_most_called(5)

        self.assertEqual(most_called[0][0], "curl")
        self.assertEqual(most_called[0][1], 4)

    def test_get_most_errored(self):
        """Test get_most_errored returns tools sorted by error count."""
        self.stat.record("curl", {"url": "f.com"}, error="err2")
        self.stat.record("http", {"url": "e.com"}, error="err3")

        most_errored = self.stat.get_most_errored(5)

        self.assertEqual(most_errored[0][0], "curl")
        self.assertEqual(most_errored[0][1], 2)

    def test_search_errors(self):
        """Test search_errors finds matching error patterns."""
        self.stat.record("tool1", error="Connection refused error")
        self.stat.record("tool2", error="Connection timeout")
        self.stat.record("tool3", error="File not found")

        results = self.stat.search_errors("connection")
        self.assertEqual(len(results), 2)

        # Case insensitive
        results_upper = self.stat.search_errors("CONNECTION")
        self.assertEqual(len(results_upper), 2)

    def test_search_errors_no_match(self):
        """Test search_errors with no matching patterns."""
        results = self.stat.search_errors("nonexistent_error")
        self.assertEqual(len(results), 0)


class TestToolStatManagement(unittest.TestCase):
    """Test ToolStat management methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()
        self.stat.record("tool1")
        self.stat.record("tool2")
        self.stat.record("tool3", error="err")

    def test_clear_all(self):
        """Test clear removes all records."""
        self.stat.clear()

        self.assertEqual(self.stat.total_calls, 0)
        self.assertEqual(self.stat.total_errors, 0)
        self.assertEqual(len(self.stat), 0)

    def test_clear_specific_tool(self):
        """Test clear removes records for specific tool only."""
        self.stat.clear("tool1")

        self.assertEqual(self.stat.total_calls, 2)
        self.assertEqual(self.stat.get_by_tool("tool1"), [])

    def test_reset(self):
        """Test reset clears all and resets timing."""
        time.sleep(0.01)
        old_uptime = self.stat.uptime

        self.stat.reset()

        self.assertEqual(self.stat.total_calls, 0)
        self.assertLess(self.stat.uptime, old_uptime)


class TestToolStatExport(unittest.TestCase):
    """Test ToolStat export functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()
        self.stat.record("curl", {"url": "a.com"})
        self.stat.record("curl", {"url": "b.com"}, error="err")

    def test_export(self):
        """Test export returns complete data dictionary."""
        export_data = self.stat.export()

        self.assertIn("export_time", export_data)
        self.assertIn("uptime_seconds", export_data)
        self.assertIn("summary", export_data)
        self.assertIn("stats", export_data)
        self.assertIn("errors", export_data)
        self.assertIn("records", export_data)

        self.assertEqual(export_data["summary"]["total_calls"], 2)
        self.assertEqual(export_data["summary"]["total_errors"], 1)
        self.assertEqual(export_data["summary"]["unique_tools"], 1)

    def test_export_json(self):
        """Test export_json returns valid JSON string."""
        json_str = self.stat.export_json()

        # Should be valid JSON
        data = json.loads(json_str)
        self.assertEqual(data["summary"]["total_calls"], 2)

    def test_export_json_indent(self):
        """Test export_json with custom indent."""
        json_str = self.stat.export_json(indent=4)

        # Should contain 4-space indentation
        self.assertIn("    ", json_str)

    def test_save_to_file(self):
        """Test save_to_file writes valid JSON file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filepath = f.name

        try:
            self.stat.save_to_file(filepath)

            # Verify file was written
            self.assertTrue(os.path.exists(filepath))

            # Verify content is valid JSON
            with open(filepath, 'r') as f:
                data = json.load(f)

            self.assertEqual(data["summary"]["total_calls"], 2)
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)


class TestToolStatContextManager(unittest.TestCase):
    """Test ToolStat context manager functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()

    def test_track_success(self):
        """Test track context manager with successful execution."""
        with self.stat.track("api_call", {"endpoint": "/test"}) as result:
            result["success"] = True

        self.assertEqual(self.stat.total_calls, 1)
        self.assertEqual(self.stat.total_errors, 0)

        records = self.stat.get_by_tool("api_call")
        self.assertEqual(records[0]["metadata"]["success"], True)

    def test_track_failure(self):
        """Test track context manager with failed execution."""
        with self.stat.track("api_call", {"endpoint": "/test"}) as result:
            result["error"] = "Server error"

        self.assertEqual(self.stat.total_calls, 1)
        self.assertEqual(self.stat.total_errors, 1)

    def test_track_exception(self):
        """Test track context manager with exception."""
        try:
            with self.stat.track("risky_call") as result:
                raise ValueError("Something went wrong")
        except ValueError:
            pass

        self.assertEqual(self.stat.total_calls, 1)
        self.assertEqual(self.stat.total_errors, 1)

        errors = self.stat.errors["risky_call"]
        self.assertIn("Something went wrong", errors[0]["error"])


class TestToolStatRecordPruning(unittest.TestCase):
    """Test ToolStat record pruning functionality."""

    def test_max_records_pruning(self):
        """Test that old records are pruned when max_records exceeded."""
        stat = ToolStat(max_records=5)

        for i in range(10):
            stat.record(f"tool_{i % 3}")

        self.assertEqual(stat.total_calls, 5)

        # Should only have the last 5 records (i=5 to i=9)
        # i=5: tool_2, i=6: tool_0, i=7: tool_1, i=8: tool_2, i=9: tool_0
        recent = stat.get_recent(5)
        self.assertEqual(recent[0]["tool_call"], "tool_2")
        self.assertEqual(recent[4]["tool_call"], "tool_0")


class TestToolStatThreadSafety(unittest.TestCase):
    """Test ToolStat thread safety."""

    def test_concurrent_record(self):
        """Test concurrent recording from multiple threads."""
        stat = ToolStat()
        num_threads = 10
        calls_per_thread = 100

        def record_calls(thread_id):
            for i in range(calls_per_thread):
                if i % 10 == 0:
                    stat.record(f"thread_{thread_id}", error="err")
                else:
                    stat.record(f"thread_{thread_id}")

        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=record_calls, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        expected_total = num_threads * calls_per_thread
        self.assertEqual(stat.total_calls, expected_total)

    def test_concurrent_read_write(self):
        """Test concurrent reads and writes."""
        stat = ToolStat()
        num_writers = 5
        num_readers = 5
        writes_per_thread = 50
        reads_per_thread = 50

        def writer(writer_id):
            for i in range(writes_per_thread):
                stat.record(f"writer_{writer_id}")

        def reader():
            for _ in range(reads_per_thread):
                _ = stat.total_calls
                _ = stat.stat
                _ = stat.errors

        threads = []
        for i in range(num_writers):
            t = threading.Thread(target=writer, args=(i,))
            threads.append(t)
            t.start()

        for i in range(num_readers):
            t = threading.Thread(target=reader)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Should complete without errors
        self.assertGreater(stat.total_calls, 0)


class TestToolStatStringMethods(unittest.TestCase):
    """Test ToolStat string representation methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()

    def test_len(self):
        """Test __len__ returns correct count."""
        self.assertEqual(len(self.stat), 0)
        self.stat.record("tool1")
        self.assertEqual(len(self.stat), 1)

    def test_repr(self):
        """Test __repr__ returns valid string."""
        self.stat.record("tool1")
        self.stat.record("tool2", error="err")

        repr_str = repr(self.stat)
        self.assertIn("ToolStat", repr_str)
        self.assertIn("total_calls=2", repr_str)
        self.assertIn("total_errors=1", repr_str)

    def test_str(self):
        """Test __str__ returns human-readable string."""
        self.stat.record("curl")
        self.stat.record("curl")
        self.stat.record("http", error="err")

        str_repr = str(self.stat)
        self.assertIn("ToolStat Summary", str_repr)
        self.assertIn("Total Calls: 3", str_repr)
        self.assertIn("curl: 2", str_repr)


class TestModuleFunctions(unittest.TestCase):
    """Test module-level convenience functions."""

    def test_get_default_stat(self):
        """Test get_default_stat returns singleton."""
        stat1 = get_default_stat()
        stat2 = get_default_stat()

        self.assertIs(stat1, stat2)
    @patch.dict(os.environ, {"TOPSAILAI_ENABLE_TOOL_STAT": "1"})
    def test_record_tool_call(self):
        """Test record_tool_call convenience function."""
        # Get fresh default stat
        import topsailai.context.tool_stat as tool_stat_module
        tool_stat_module._default_stat = None

        seq = record_tool_call("test_tool", {"arg": "value"}, error=None)

        self.assertEqual(seq, 1)

        stat = get_default_stat()
        self.assertEqual(stat.total_calls, 1)


if __name__ == "__main__":
    unittest.main()
