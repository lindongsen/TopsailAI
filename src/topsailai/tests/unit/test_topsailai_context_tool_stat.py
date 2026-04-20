"""
Unit tests for context/tool_stat.py

Author: mm-m25
Purpose: Test ToolStat class for tool call statistics tracking
"""

import os
import sys
import json
import tempfile
import threading
import time
from unittest import TestCase, main
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from topsailai.context.tool_stat import (
    ToolStat,
    get_default_stat,
    record_tool_call,
    _default_stat
)


class TestToolStatInit(TestCase):
    """Test ToolStat initialization."""

    def test_tool_stat_init_default(self):
        """Test initialization with default max_records."""
        stat = ToolStat()
        self.assertEqual(stat._max_records, 10000)
        self.assertEqual(stat.total_calls, 0)
        self.assertEqual(stat.total_errors, 0)

    def test_tool_stat_init_custom(self):
        """Test initialization with custom max_records."""
        stat = ToolStat(max_records=100)
        self.assertEqual(stat._max_records, 100)
        self.assertEqual(stat.total_calls, 0)


class TestToolStatRecording(TestCase):
    """Test recording tool calls."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()

    def test_record_successful_call(self):
        """Test recording a successful tool call."""
        seq = self.stat.record("curl", {"url": "https://example.com"})
        self.assertEqual(seq, 1)
        self.assertEqual(self.stat.total_calls, 1)
        self.assertEqual(self.stat.total_errors, 0)

    def test_record_failed_call(self):
        """Test recording a failed tool call."""
        seq = self.stat.record("curl", {"url": "https://bad.com"}, error="Connection refused")
        self.assertEqual(seq, 1)
        self.assertEqual(self.stat.total_calls, 1)
        self.assertEqual(self.stat.total_errors, 1)

    def test_record_with_metadata(self):
        """Test recording with metadata."""
        metadata = {"user_id": 123, "session": "abc"}
        self.stat.record("api", {"endpoint": "/test"}, metadata=metadata)
        calls = self.stat.get_by_tool("api")
        self.assertEqual(calls[0]["metadata"], metadata)

    def test_record_sequence_numbers(self):
        """Test that sequence numbers increment correctly."""
        seq1 = self.stat.record("tool1")
        seq2 = self.stat.record("tool2")
        seq3 = self.stat.record("tool3")
        self.assertEqual(seq1, 1)
        self.assertEqual(seq2, 2)
        self.assertEqual(seq3, 3)


class TestToolStatProperties(TestCase):
    """Test ToolStat property accessors."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()

    def test_stat_property(self):
        """Test aggregated statistics property."""
        self.stat.record("curl", {"url": "a.com"})
        self.stat.record("curl", {"url": "b.com"})
        self.stat.record("curl", {"url": "c.com"}, error="Timeout")
        stats = self.stat.stat
        self.assertEqual(stats["curl"]["total_count"], 3)
        self.assertEqual(stats["curl"]["success_count"], 2)
        self.assertEqual(stats["curl"]["error_count"], 1)

    def test_errors_property(self):
        """Test errors property returns error records grouped by tool."""
        self.stat.record("curl", {"url": "a.com"})
        self.stat.record("curl", {"url": "b.com"}, error="Timeout")
        errors = self.stat.errors
        self.assertEqual(len(errors["curl"]), 1)
        self.assertEqual(errors["curl"][0]["error"], "Timeout")

    def test_total_calls(self):
        """Test total_calls property."""
        self.assertEqual(self.stat.total_calls, 0)
        self.stat.record("tool1")
        self.stat.record("tool2")
        self.assertEqual(self.stat.total_calls, 2)

    def test_total_errors(self):
        """Test total_errors property."""
        self.assertEqual(self.stat.total_errors, 0)
        self.stat.record("tool1")
        self.stat.record("tool2", error="Fail")
        self.assertEqual(self.stat.total_errors, 1)

    def test_success_rate(self):
        """Test success_rate calculation."""
        self.stat.record("tool1")
        self.stat.record("tool2", error="Fail")
        self.stat.record("tool3")
        # 2 success out of 3 = 66.67%
        self.assertAlmostEqual(self.stat.success_rate, 66.67, places=1)

    def test_success_rate_empty(self):
        """Test success_rate returns 0 for empty tracker."""
        self.assertEqual(self.stat.success_rate, 0.0)

    def test_uptime(self):
        """Test uptime property."""
        self.stat.record("tool1")
        time.sleep(0.01)
        self.assertGreater(self.stat.uptime, 0)


class TestToolStatQueries(TestCase):
    """Test ToolStat query methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()

    def test_get_by_tool(self):
        """Test get_by_tool returns records for specific tool."""
        self.stat.record("curl", {"url": "a.com"})
        self.stat.record("curl", {"url": "b.com"})
        self.stat.record("file", {"path": "/test"})
        curl_calls = self.stat.get_by_tool("curl")
        self.assertEqual(len(curl_calls), 2)
        self.assertEqual(curl_calls[0]["tool_call"], "curl")

    def test_get_by_tool_nonexistent(self):
        """Test get_by_tool returns empty list for unknown tool."""
        result = self.stat.get_by_tool("nonexistent")
        self.assertEqual(result, [])

    def test_get_recent(self):
        """Test get_recent returns most recent calls."""
        for i in range(15):
            self.stat.record("tool", {"index": i})
        recent = self.stat.get_recent(5)
        self.assertEqual(len(recent), 5)
        # Last record should have index 14
        self.assertEqual(recent[-1]["tool_args"]["index"], 14)

    def test_get_recent_default(self):
        """Test get_recent with default count."""
        for i in range(15):
            self.stat.record("tool", {"index": i})
        recent = self.stat.get_recent()
        self.assertEqual(len(recent), 10)  # Default is 10

    def test_get_tool_stats(self):
        """Test get_tool_stats returns detailed stats for a tool."""
        self.stat.record("api", {"call": 1})
        self.stat.record("api", {"call": 2})
        self.stat.record("api", {"call": 3}, error="Fail")
        stats = self.stat.get_tool_stats("api")
        self.assertEqual(stats["total_count"], 3)
        self.assertEqual(stats["success_count"], 2)
        self.assertEqual(stats["error_count"], 1)
        self.assertAlmostEqual(stats["success_rate"], 66.67, places=1)
        self.assertIsNotNone(stats["last_called"])
        self.assertEqual(stats["last_error"], "Fail")

    def test_get_tool_stats_nonexistent(self):
        """Test get_tool_stats for unknown tool."""
        stats = self.stat.get_tool_stats("unknown")
        self.assertEqual(stats["total_count"], 0)
        self.assertEqual(stats["success_rate"], 0.0)

    def test_get_most_called(self):
        """Test get_most_called returns tools sorted by call count."""
        for _ in range(10):
            self.stat.record("tool_a")
        for _ in range(5):
            self.stat.record("tool_b")
        for _ in range(3):
            self.stat.record("tool_c")
        most_called = self.stat.get_most_called(2)
        self.assertEqual(most_called[0], ("tool_a", 10))
        self.assertEqual(most_called[1], ("tool_b", 5))

    def test_get_most_errored(self):
        """Test get_most_errored returns tools sorted by error count."""
        self.stat.record("tool_a")
        self.stat.record("tool_a", error="Err")
        self.stat.record("tool_a", error="Err")
        self.stat.record("tool_b", error="Err")
        most_errored = self.stat.get_most_errored(2)
        self.assertEqual(most_errored[0], ("tool_a", 2))
        self.assertEqual(most_errored[1], ("tool_b", 1))


class TestToolStatSearch(TestCase):
    """Test ToolStat search functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()

    def test_search_errors(self):
        """Test search_errors finds matching error patterns."""
        self.stat.record("tool1", error="Connection timeout")
        self.stat.record("tool2", error="Connection refused")
        self.stat.record("tool3", error="File not found")
        results = self.stat.search_errors("connection")
        self.assertEqual(len(results), 2)

    def test_search_errors_case_insensitive(self):
        """Test search_errors is case insensitive."""
        self.stat.record("tool1", error="CONNECTION TIMEOUT")
        self.stat.record("tool2", error="connection timeout")
        results = self.stat.search_errors("Connection")
        self.assertEqual(len(results), 2)

    def test_search_errors_no_match(self):
        """Test search_errors returns empty for no matches."""
        self.stat.record("tool1", error="Success")
        results = self.stat.search_errors("error")
        self.assertEqual(len(results), 0)


class TestToolStatClearReset(TestCase):
    """Test ToolStat clear and reset methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()

    def test_clear_all(self):
        """Test clear removes all records."""
        self.stat.record("tool1")
        self.stat.record("tool2")
        self.stat.clear()
        self.assertEqual(self.stat.total_calls, 0)
        self.assertEqual(self.stat._call_sequence, 0)

    def test_clear_by_tool(self):
        """Test clear removes records for specific tool only."""
        self.stat.record("tool1")
        self.stat.record("tool2")
        self.stat.record("tool1")
        self.stat.clear("tool1")
        self.assertEqual(self.stat.total_calls, 1)
        self.assertEqual(self.stat.get_by_tool("tool1"), [])

    def test_reset(self):
        """Test reset clears all and resets timing."""
        self.stat.record("tool1")
        time.sleep(0.01)
        old_uptime = self.stat.uptime
        self.stat.reset()
        self.assertEqual(self.stat.total_calls, 0)
        self.assertLess(self.stat.uptime, old_uptime)


class TestToolStatExport(TestCase):
    """Test ToolStat export methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()

    def test_export(self):
        """Test export returns complete dictionary."""
        self.stat.record("tool1", {"arg": "value"})
        self.stat.record("tool2", error="Fail")
        export = self.stat.export()
        self.assertIn("export_time", export)
        self.assertIn("summary", export)
        self.assertIn("stats", export)
        self.assertIn("errors", export)
        self.assertIn("records", export)
        self.assertEqual(export["summary"]["total_calls"], 2)

    def test_export_json(self):
        """Test export_json returns valid JSON string."""
        self.stat.record("tool1")
        json_str = self.stat.export_json()
        data = json.loads(json_str)
        self.assertEqual(data["summary"]["total_calls"], 1)

    def test_save_to_file(self):
        """Test save_to_file writes JSON to file."""
        self.stat.record("tool1")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        try:
            self.stat.save_to_file(temp_path)
            with open(temp_path, 'r') as f:
                data = json.load(f)
            self.assertEqual(data["summary"]["total_calls"], 1)
        finally:
            os.unlink(temp_path)

    def test_export_content_structure(self):
        """Test export structure contains expected fields."""
        self.stat.record("curl", {"url": "test.com"})
        export = self.stat.export()
        summary = export["summary"]
        self.assertIn("total_calls", summary)
        self.assertIn("total_errors", summary)
        self.assertIn("success_rate", summary)
        self.assertIn("unique_tools", summary)


class TestToolStatContextManager(TestCase):
    """Test ToolStat track context manager."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat()

    def test_track_success(self):
        """Test track context manager records successful operation."""
        with self.stat.track("api_call", {"endpoint": "/test"}) as result:
            result["data"] = {"status": 200}
        self.assertEqual(self.stat.total_calls, 1)
        self.assertEqual(self.stat.total_errors, 0)

    def test_track_failure(self):
        """Test track context manager records failed operation."""
        try:
            with self.stat.track("api_call", {"endpoint": "/test"}) as result:
                raise ValueError("Test error")
        except ValueError:
            pass
        self.assertEqual(self.stat.total_calls, 1)
        self.assertEqual(self.stat.total_errors, 1)
        errors = self.stat.errors["api_call"]
        self.assertEqual(errors[0]["error"], "Test error")


class TestToolStatGlobalFunctions(TestCase):
    """Test module-level global functions."""

    def setUp(self):
        """Reset global state before each test."""
        import topsailai.context.tool_stat as module
        module._default_stat = None

    def test_get_default_stat(self):
        """Test get_default_stat returns singleton instance."""
        stat1 = get_default_stat()
        stat2 = get_default_stat()
        self.assertIs(stat1, stat2)

    @patch.dict(os.environ, {"TOPSAILAI_ENABLE_TOOL_STAT": "1"})
    def test_record_tool_call_enabled(self):
        """Test record_tool_call records when enabled."""
        record_tool_call("test_tool", {"arg": "value"})
        stat = get_default_stat()
        self.assertEqual(stat.total_calls, 1)

    @patch.dict(os.environ, {"TOPSAILAI_ENABLE_TOOL_STAT": "0"})
    def test_record_tool_call_disabled(self):
        """Test record_tool_call does not record when disabled."""
        result = record_tool_call("test_tool", {"arg": "value"})
        self.assertEqual(result, 0)

    @patch.dict(os.environ, {"DEBUG": "1"})
    def test_record_tool_call_debug(self):
        """Test record_tool_call records when DEBUG is set."""
        record_tool_call("debug_tool", {"arg": "value"})
        stat = get_default_stat()
        self.assertEqual(stat.total_calls, 1)


class TestToolStatEdgeCases(TestCase):
    """Test edge cases and boundary conditions."""

    def setUp(self):
        """Set up test fixtures."""
        self.stat = ToolStat(max_records=5)

    def test_max_records_pruning(self):
        """Test that old records are pruned when max_records exceeded."""
        for i in range(10):
            self.stat.record("tool", {"index": i})
        self.assertEqual(self.stat.total_calls, 5)
        # Should have records 6-10 (indices 5-9)
        recent = self.stat.get_recent(5)
        self.assertEqual(recent[0]["tool_args"]["index"], 5)
        self.assertEqual(recent[-1]["tool_args"]["index"], 9)

    def test_empty_stats(self):
        """Test operations on empty tracker."""
        self.assertEqual(self.stat.stat, {})
        self.assertEqual(self.stat.errors, {})
        self.assertEqual(self.stat.get_by_tool("any"), [])
        self.assertEqual(self.stat.get_recent(), [])

    def test_repr(self):
        """Test __repr__ returns valid string."""
        self.stat.record("tool1")
        self.stat.record("tool2", error="Fail")
        repr_str = repr(self.stat)
        self.assertIn("ToolStat", repr_str)
        self.assertIn("total_calls=2", repr_str)

    def test_str(self):
        """Test __str__ returns human-readable string."""
        self.stat.record("tool1")
        self.stat.record("tool2")
        str_output = str(self.stat)
        self.assertIn("ToolStat Summary", str_output)
        self.assertIn("Total Calls: 2", str_output)

    def test_len(self):
        """Test __len__ returns number of records."""
        self.assertEqual(len(self.stat), 0)
        self.stat.record("tool1")
        self.assertEqual(len(self.stat), 1)

    def test_tool_calls_property(self):
        """Test tool_calls property returns copy of records."""
        self.stat.record("tool1")
        calls = self.stat.tool_calls
        calls.append({"fake": "record"})
        self.assertEqual(len(self.stat._tool_calls), 1)

    def test_multiple_tools_stats(self):
        """Test stats with multiple different tools."""
        self.stat.record("curl", {"url": "a.com"})
        self.stat.record("file", {"path": "/a"})
        self.stat.record("curl", {"url": "b.com"}, error="Err")
        self.stat.record("db", {"query": "SELECT"})
        stats = self.stat.stat
        self.assertEqual(len(stats), 3)
        self.assertEqual(stats["curl"]["total_count"], 2)
        self.assertEqual(stats["file"]["total_count"], 1)


class TestToolStatThreadSafety(TestCase):
    """Test thread safety of ToolStat."""

    def test_concurrent_recording(self):
        """Test concurrent recording from multiple threads."""
        stat = ToolStat()
        threads = []
        num_threads = 5
        calls_per_thread = 20

        def worker(thread_id):
            for i in range(calls_per_thread):
                stat.record(f"thread_{thread_id}", {"iteration": i})

        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        expected_calls = num_threads * calls_per_thread
        self.assertEqual(stat.total_calls, expected_calls)
        self.assertEqual(len(stat.stat), num_threads)

    def test_concurrent_read_write(self):
        """Test concurrent reads and writes."""
        stat = ToolStat()
        threads = []
        num_threads = 5

        def writer(thread_id):
            for i in range(10):
                stat.record(f"tool_{thread_id}", {"i": i})

        def reader(thread_id):
            for _ in range(10):
                _ = stat.total_calls
                _ = stat.stat
                _ = stat.get_recent()

        for i in range(num_threads):
            threads.append(threading.Thread(target=writer, args=(i,)))
            threads.append(threading.Thread(target=reader, args=(i,)))

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Should complete without errors
        self.assertGreater(stat.total_calls, 0)


if __name__ == "__main__":
    main()
