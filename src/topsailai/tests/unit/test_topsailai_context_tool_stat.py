"""
Unit tests for context/tool_stat.py

Test Coverage:
- ToolStat class initialization and configuration
- Tool call recording with success and error cases
- Statistics aggregation (total_calls, total_errors, success_rate)
- Tool-specific statistics retrieval
- Time-based queries and filtering
- Error tracking and search
- Export functionality (dict, JSON, file)
- Context manager (track) functionality
- Thread safety for concurrent operations
- Edge cases and boundary conditions

Author: mm-m25
"""

import pytest
import json
import tempfile
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import patch, MagicMock, mock_open
from collections import defaultdict

from context.tool_stat import (
    ToolStat,
    get_default_stat,
    record_tool_call,
    _default_stat,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def empty_stat():
    """Create a fresh ToolStat instance with no records."""
    return ToolStat()


@pytest.fixture
def stat_with_data():
    """Create a ToolStat instance with sample data."""
    stat = ToolStat()
    # Successful calls
    stat.record("curl", {"url": "https://api.example.com/users"})
    stat.record("curl", {"url": "https://api.example.com/posts"})
    stat.record("database.query", {"sql": "SELECT * FROM users"})
    stat.record("file.read", {"path": "/etc/config.json"})
    stat.record("file.read", {"path": "/etc/secrets.json"})
    # Failed calls
    stat.record("curl", {"url": "https://broken.example.com"}, error="Connection timeout")
    stat.record("database.query", {"sql": "INVALID SQL"}, error="Syntax error")
    return stat


@pytest.fixture
def stat_with_errors():
    """Create a ToolStat instance with various error types."""
    stat = ToolStat()
    stat.record("api_call", {"endpoint": "/users"}, error="404 Not Found")
    stat.record("api_call", {"endpoint": "/posts"}, error="500 Internal Server Error")
    stat.record("api_call", {"endpoint": "/comments"}, error="Connection refused")
    stat.record("file.read", {"path": "/missing"}, error="File not found")
    return stat


# =============================================================================
# Test Class: TestToolStatInitialization
# =============================================================================

class TestToolStatInitialization:
    """Tests for ToolStat initialization and configuration."""

    def test_default_initialization(self, empty_stat):
        """Test ToolStat initializes with default values."""
        assert empty_stat.total_calls == 0
        assert empty_stat.total_errors == 0
        assert empty_stat.success_rate == 0.0
        assert empty_stat._max_records == 10000
        assert isinstance(empty_stat._lock, type(threading.RLock()))

    def test_custom_max_records(self):
        """Test ToolStat with custom max_records parameter."""
        stat = ToolStat(max_records=100)
        assert stat._max_records == 100

    def test_initial_state_properties(self, empty_stat):
        """Test all properties return correct initial state."""
        assert empty_stat.tool_calls == []
        assert empty_stat.stat == {}
        assert empty_stat.errors == {}
        assert empty_stat.total_calls == 0
        assert empty_stat.total_errors == 0
        assert empty_stat.success_rate == 0.0
        assert empty_stat.uptime >= 0

    def test_len_magic_method(self, empty_stat):
        """Test __len__ returns correct count."""
        assert len(empty_stat) == 0
        empty_stat.record("test_tool", {"arg": 1})
        assert len(empty_stat) == 1

    def test_repr_magic_method(self, empty_stat):
        """Test __repr__ returns valid string representation."""
        repr_str = repr(empty_stat)
        assert "ToolStat" in repr_str
        assert "total_calls=0" in repr_str
        assert "total_errors=0" in repr_str

    def test_str_magic_method(self, empty_stat):
        """Test __str__ returns human-readable summary."""
        str_repr = str(empty_stat)
        assert "ToolStat Summary" in str_repr
        assert "Total Calls: 0" in str_repr
        assert "Success Rate:" in str_repr


# =============================================================================
# Test Class: TestToolStatRecord
# =============================================================================

class TestToolStatRecord:
    """Tests for ToolStat.record() method."""

    def test_record_success_call(self, empty_stat):
        """Test recording a successful tool call."""
        seq = empty_stat.record("curl", {"url": "https://example.com"})
        assert seq == 1
        assert empty_stat.total_calls == 1
        assert empty_stat.total_errors == 0
        assert empty_stat.success_rate == 100.0

    def test_record_error_call(self, empty_stat):
        """Test recording a failed tool call."""
        seq = empty_stat.record("curl", {"url": "https://broken.com"}, error="Connection refused")
        assert seq == 1
        assert empty_stat.total_calls == 1
        assert empty_stat.total_errors == 1
        assert empty_stat.success_rate == 0.0

    def test_record_with_result(self, empty_stat):
        """Test recording a call with result data."""
        seq = empty_stat.record(
            "database.query",
            {"sql": "SELECT * FROM users"},
            result={"rows": 100, "columns": 5}
        )
        assert seq == 1
        calls = empty_stat.tool_calls
        assert calls[0]["result"] == {"rows": 100, "columns": 5}

    def test_record_with_metadata(self, empty_stat):
        """Test recording a call with metadata."""
        seq = empty_stat.record(
            "api_call",
            {"endpoint": "/users"},
            metadata={"source": "test", "version": "1.0"}
        )
        assert seq == 1
        calls = empty_stat.tool_calls
        assert calls[0]["metadata"] == {"source": "test", "version": "1.0"}

    def test_record_sequence_numbers(self, empty_stat):
        """Test that sequence numbers increment correctly."""
        seq1 = empty_stat.record("tool_a", {"arg": 1})
        seq2 = empty_stat.record("tool_b", {"arg": 2})
        seq3 = empty_stat.record("tool_c", {"arg": 3})
        assert seq1 == 1
        assert seq2 == 2
        assert seq3 == 3

    def test_record_timestamp_format(self, empty_stat):
        """Test that timestamps are in ISO format."""
        empty_stat.record("test_tool", {"arg": 1})
        calls = empty_stat.tool_calls
        timestamp = calls[0]["timestamp"]
        # Should be parseable as ISO format
        parsed = datetime.fromisoformat(timestamp)
        assert isinstance(parsed, datetime)

    def test_record_pruning_old_records(self):
        """Test that old records are pruned when max_records exceeded."""
        stat = ToolStat(max_records=5)
        for i in range(10):
            stat.record("tool", {"index": i})
        assert stat.total_calls == 5
        # Should keep the last 5 records
        calls = stat.tool_calls
        assert calls[0]["tool_args"]["index"] == 5
        assert calls[-1]["tool_args"]["index"] == 9

    def test_record_multiple_tools(self, empty_stat):
        """Test recording calls for multiple different tools."""
        empty_stat.record("tool_a", {"arg": 1})
        empty_stat.record("tool_b", {"arg": 2})
        empty_stat.record("tool_a", {"arg": 3})
        empty_stat.record("tool_c", {"arg": 4})
        assert empty_stat.total_calls == 4
        assert len(empty_stat.stat) == 3


# =============================================================================
# Test Class: TestToolStatStatistics
# =============================================================================

class TestToolStatStatistics:
    """Tests for ToolStat statistics aggregation."""

    def test_stat_property_empty(self, empty_stat):
        """Test stat property with no records."""
        assert empty_stat.stat == {}

    def test_stat_property_aggregation(self, stat_with_data):
        """Test stat property correctly aggregates data."""
        stats = stat_with_data.stat
        assert stats["curl"]["total_count"] == 3
        assert stats["curl"]["error_count"] == 1
        assert stats["curl"]["success_count"] == 2
        assert stats["database.query"]["total_count"] == 2
        assert stats["database.query"]["error_count"] == 1
        assert stats["file.read"]["total_count"] == 2
        assert stats["file.read"]["error_count"] == 0

    def test_total_calls_property(self, stat_with_data):
        """Test total_calls property."""
        assert stat_with_data.total_calls == 7

    def test_total_errors_property(self, stat_with_data):
        """Test total_errors property."""
        assert stat_with_data.total_errors == 2

    def test_success_rate_full_success(self, empty_stat):
        """Test success_rate with all successful calls."""
        empty_stat.record("tool", {"arg": 1})
        empty_stat.record("tool", {"arg": 2})
        assert empty_stat.success_rate == 100.0

    def test_success_rate_full_failure(self, empty_stat):
        """Test success_rate with all failed calls."""
        empty_stat.record("tool", {"arg": 1}, error="Error 1")
        empty_stat.record("tool", {"arg": 2}, error="Error 2")
        assert empty_stat.success_rate == 0.0

    def test_success_rate_mixed(self, stat_with_data):
        """Test success_rate with mixed success/failure."""
        # 7 total, 2 errors = 5/7 * 100
        expected_rate = (5 / 7) * 100
        assert abs(stat_with_data.success_rate - expected_rate) < 0.01

    def test_uptime_property(self, empty_stat):
        """Test uptime property returns positive value."""
        assert empty_stat.uptime >= 0


# =============================================================================
# Test Class: TestToolStatErrors
# =============================================================================

class TestToolStatErrors:
    """Tests for ToolStat error tracking."""

    def test_errors_property_empty(self, empty_stat):
        """Test errors property with no records."""
        assert empty_stat.errors == {}

    def test_errors_property_grouping(self, stat_with_errors):
        """Test errors are grouped by tool name."""
        errors = stat_with_errors.errors
        assert "api_call" in errors
        assert "file.read" in errors
        assert len(errors["api_call"]) == 3
        assert len(errors["file.read"]) == 1

    def test_errors_property_content(self, stat_with_errors):
        """Test error records contain required fields."""
        errors = stat_with_errors.errors
        error_record = errors["api_call"][0]
        assert "tool_call" in error_record
        assert "tool_args" in error_record
        assert "error" in error_record
        assert "timestamp" in error_record
        assert "sequence" in error_record

    def test_errors_no_false_positives(self, empty_stat):
        """Test that successful calls don't appear in errors."""
        empty_stat.record("tool", {"arg": 1})
        assert empty_stat.errors == {}


# =============================================================================
# Test Class: TestToolStatQueries
# =============================================================================

class TestToolStatQueries:
    """Tests for ToolStat query methods."""

    def test_get_by_tool(self, stat_with_data):
        """Test get_by_tool returns correct records."""
        curl_calls = stat_with_data.get_by_tool("curl")
        assert len(curl_calls) == 3
        for call in curl_calls:
            assert call["tool_call"] == "curl"

    def test_get_by_tool_nonexistent(self, empty_stat):
        """Test get_by_tool with non-existent tool."""
        result = empty_stat.get_by_tool("nonexistent")
        assert result == []

    def test_get_recent_default(self, stat_with_data):
        """Test get_recent with default count (10)."""
        recent = stat_with_data.get_recent()
        assert len(recent) == 7  # All calls since less than 10

    def test_get_recent_custom_count(self, empty_stat):
        """Test get_recent with custom count."""
        for i in range(20):
            empty_stat.record("tool", {"index": i})
        recent = empty_stat.get_recent(5)
        assert len(recent) == 5
        # Should be the last 5 records
        assert recent[0]["tool_args"]["index"] == 15
        assert recent[-1]["tool_args"]["index"] == 19

    def test_get_recent_more_than_available(self, empty_stat):
        """Test get_recent when count exceeds available records."""
        empty_stat.record("tool", {"arg": 1})
        empty_stat.record("tool", {"arg": 2})
        recent = empty_stat.get_recent(10)
        assert len(recent) == 2

    def test_get_tool_stats_existing(self, stat_with_data):
        """Test get_tool_stats for existing tool."""
        stats = stat_with_data.get_tool_stats("curl")
        assert stats["total_count"] == 3
        assert stats["success_count"] == 2
        assert stats["error_count"] == 1
        assert stats["success_rate"] == pytest.approx(66.67, rel=0.01)
        assert stats["last_called"] is not None
        assert stats["last_error"] == "Connection timeout"

    def test_get_tool_stats_nonexistent(self, empty_stat):
        """Test get_tool_stats for non-existent tool."""
        stats = empty_stat.get_tool_stats("nonexistent")
        assert stats["total_count"] == 0
        assert stats["success_count"] == 0
        assert stats["error_count"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["last_called"] is None
        assert stats["last_error"] is None

    def test_get_most_called(self, stat_with_data):
        """Test get_most_called returns tools sorted by count."""
        most_called = stat_with_data.get_most_called(5)
        # curl has 3, database.query has 2, file.read has 2
        assert most_called[0][0] == "curl"
        assert most_called[0][1] == 3

    def test_get_most_called_limit(self, empty_stat):
        """Test get_most_called respects limit parameter."""
        for i in range(10):
            empty_stat.record(f"tool_{i}", {"arg": i})
        most_called = empty_stat.get_most_called(3)
        assert len(most_called) == 3

    def test_get_most_errored(self, stat_with_errors):
        """Test get_most_errored returns tools sorted by error count."""
        most_errored = stat_with_errors.get_most_errored(5)
        assert most_errored[0][0] == "api_call"
        assert most_errored[0][1] == 3

    def test_search_errors(self, stat_with_errors):
        """Test search_errors finds matching error patterns."""
        results = stat_with_errors.search_errors("not found")
        # Both "404 Not Found" and "File not found" contain "not found"
        assert len(results) == 2
        tool_calls = [r["tool_call"] for r in results]
        assert "file.read" in tool_calls
        assert "api_call" in tool_calls

    def test_search_errors_case_insensitive(self, stat_with_errors):
        """Test search_errors is case insensitive."""
        results = stat_with_errors.search_errors("NOT FOUND")
        # Both "404 Not Found" and "File not found" match (case insensitive)
        assert len(results) == 2

    def test_search_errors_no_matches(self, stat_with_errors):
        """Test search_errors with no matching patterns."""
        results = stat_with_errors.search_errors("nonexistent error")
        assert results == []


# =============================================================================
# Test Class: TestToolStatTimeRange
# =============================================================================

class TestToolStatTimeRange:
    """Tests for time-based queries."""

    def test_get_by_time_range_no_bounds(self, empty_stat):
        """Test get_by_time_range with no bounds returns all."""
        empty_stat.record("tool", {"arg": 1})
        empty_stat.record("tool", {"arg": 2})
        result = empty_stat.get_by_time_range()
        assert len(result) == 2

    def test_get_by_time_range_start_only(self, empty_stat):
        """Test get_by_time_range with start bound only."""
        empty_stat.record("tool", {"index": 0})
        time.sleep(0.01)
        start_time = datetime.now()
        time.sleep(0.01)
        empty_stat.record("tool", {"index": 1})
        result = empty_stat.get_by_time_range(start=start_time)
        assert len(result) == 1
        assert result[0]["tool_args"]["index"] == 1

    def test_get_by_time_range_end_only(self, empty_stat):
        """Test get_by_time_range with end bound only."""
        empty_stat.record("tool", {"index": 0})
        time.sleep(0.01)
        end_time = datetime.now()
        time.sleep(0.01)
        empty_stat.record("tool", {"index": 1})
        result = empty_stat.get_by_time_range(end=end_time)
        assert len(result) == 1
        assert result[0]["tool_args"]["index"] == 0

    def test_get_by_time_range_both_bounds(self, empty_stat):
        """Test get_by_time_range with both start and end bounds."""
        empty_stat.record("tool", {"index": 0})
        time.sleep(0.01)
        start_time = datetime.now()
        time.sleep(0.01)
        empty_stat.record("tool", {"index": 1})
        time.sleep(0.01)
        end_time = datetime.now()
        time.sleep(0.01)
        empty_stat.record("tool", {"index": 2})
        result = empty_stat.get_by_time_range(start=start_time, end=end_time)
        assert len(result) == 1
        assert result[0]["tool_args"]["index"] == 1


# =============================================================================
# Test Class: TestToolStatClearAndReset
# =============================================================================

class TestToolStatClearAndReset:
    """Tests for clear and reset operations."""

    def test_clear_all(self, stat_with_data):
        """Test clear() removes all records."""
        stat_with_data.clear()
        assert stat_with_data.total_calls == 0
        assert stat_with_data.stat == {}
        assert stat_with_data.errors == {}

    def test_clear_specific_tool(self, stat_with_data):
        """Test clear(tool_call) removes only that tool's records."""
        stat_with_data.clear("curl")
        assert stat_with_data.total_calls == 4  # 7 - 3 curl calls
        assert "curl" not in stat_with_data.stat

    def test_clear_nonexistent_tool(self, stat_with_data):
        """Test clear with non-existent tool has no effect."""
        initial_count = stat_with_data.total_calls
        stat_with_data.clear("nonexistent")
        assert stat_with_data.total_calls == initial_count

    def test_reset(self, stat_with_data):
        """Test reset() clears all and resets timing."""
        stat_with_data.reset()
        assert stat_with_data.total_calls == 0
        assert stat_with_data.stat == {}
        assert stat_with_data.uptime < 1  # Should be very small


# =============================================================================
# Test Class: TestToolStatExport
# =============================================================================

class TestToolStatExport:
    """Tests for export functionality."""

    def test_export_structure(self, stat_with_data):
        """Test export() returns correct structure."""
        export_data = stat_with_data.export()
        assert "export_time" in export_data
        assert "uptime_seconds" in export_data
        assert "summary" in export_data
        assert "stats" in export_data
        assert "errors" in export_data
        assert "records" in export_data

    def test_export_summary(self, stat_with_data):
        """Test export() summary section."""
        export_data = stat_with_data.export()
        summary = export_data["summary"]
        assert summary["total_calls"] == 7
        assert summary["total_errors"] == 2
        assert summary["unique_tools"] == 3

    def test_export_json(self, stat_with_data):
        """Test export_json() returns valid JSON string."""
        json_str = stat_with_data.export_json()
        data = json.loads(json_str)
        assert data["summary"]["total_calls"] == 7

    def test_export_json_custom_indent(self, stat_with_data):
        """Test export_json() with custom indent."""
        json_str = stat_with_data.export_json(indent=4)
        assert "    " in json_str

    def test_save_to_file(self, stat_with_data):
        """Test save_to_file() writes valid JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        try:
            stat_with_data.save_to_file(temp_path)
            with open(temp_path, 'r') as f:
                data = json.load(f)
            assert data["summary"]["total_calls"] == 7
        finally:
            os.unlink(temp_path)


# =============================================================================
# Test Class: TestToolStatTrackContextManager
# =============================================================================

class TestToolStatTrackContextManager:
    """Tests for the track() context manager."""

    def test_track_success(self, empty_stat):
        """Test track context manager with successful operation."""
        with empty_stat.track("api_call", {"endpoint": "/users"}) as result:
            result["data"] = {"status": 200}
        assert empty_stat.total_calls == 1
        assert empty_stat.total_errors == 0
        assert empty_stat.tool_calls[0]["result"] == {"status": 200}

    def test_track_failure(self, empty_stat):
        """Test track context manager with exception."""
        try:
            with empty_stat.track("api_call", {"endpoint": "/broken"}) as result:
                raise ConnectionError("Network unavailable")
        except ConnectionError:
            pass
        assert empty_stat.total_calls == 1
        assert empty_stat.total_errors == 1
        assert "Network unavailable" in empty_stat.tool_calls[0]["error"]

    def test_track_metadata_success(self, empty_stat):
        """Test track sets success metadata on success."""
        with empty_stat.track("tool", {"arg": 1}) as result:
            result["data"] = "success"
        metadata = empty_stat.tool_calls[0]["metadata"]
        assert metadata["success"] is True

    def test_track_metadata_failure(self, empty_stat):
        """Test track sets success metadata on failure."""
        try:
            with empty_stat.track("tool", {"arg": 1}) as result:
                raise ValueError("test error")
        except ValueError:
            pass
        metadata = empty_stat.tool_calls[0]["metadata"]
        assert metadata["success"] is False


# =============================================================================
# Test Class: TestToolStatThreadSafety
# =============================================================================

class TestToolStatThreadSafety:
    """Tests for thread safety of ToolStat operations."""

    def test_concurrent_record(self, empty_stat):
        """Test concurrent record() calls from multiple threads."""
        num_threads = 5
        calls_per_thread = 20
        def worker(thread_id):
            for i in range(calls_per_thread):
                empty_stat.record(f"thread_{thread_id}", {"iteration": i})
        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        assert empty_stat.total_calls == num_threads * calls_per_thread
        assert len(empty_stat.stat) == num_threads

    def test_concurrent_read_write(self, empty_stat):
        """Test concurrent reads and writes."""
        def writer():
            for i in range(50):
                empty_stat.record("writer", {"index": i})
        def reader():
            for _ in range(50):
                _ = empty_stat.stat
                _ = empty_stat.total_calls
                _ = empty_stat.errors
        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert empty_stat.total_calls == 50

    def test_lock_type(self, empty_stat):
        """Test that ToolStat uses RLock for reentrant locking."""
        assert isinstance(empty_stat._lock, type(threading.RLock()))


# =============================================================================
# Test Class: TestModuleLevelFunctions
# =============================================================================

class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_default_stat_creates_instance(self):
        """Test get_default_stat() creates instance if none exists."""
        import context.tool_stat as tool_stat_module
        tool_stat_module._default_stat = None
        stat = get_default_stat()
        assert isinstance(stat, ToolStat)
        stat2 = get_default_stat()
        assert stat is stat2

    def test_record_tool_call_disabled_by_default(self):
        """Test record_tool_call returns 0 when disabled."""
        import context.tool_stat as tool_stat_module
        tool_stat_module._default_stat = None
        with patch.dict(os.environ, {}, clear=True):
            result = record_tool_call("test_tool", {"arg": 1})
            assert result == 0

    def test_record_tool_call_enabled_by_env(self):
        """Test record_tool_call works when enabled via env var."""
        import context.tool_stat as tool_stat_module
        tool_stat_module._default_stat = None
        with patch.dict(os.environ, {"TOPSAILAI_ENABLE_TOOL_STAT": "1"}):
            result = record_tool_call("test_tool", {"arg": 1})
            assert result == 1

    def test_record_tool_call_enabled_by_debug(self):
        """Test record_tool_call works when DEBUG env var is set."""
        import context.tool_stat as tool_stat_module
        tool_stat_module._default_stat = None
        with patch.dict(os.environ, {"DEBUG": "1"}):
            result = record_tool_call("test_tool", {"arg": 1})
            assert result == 1


# =============================================================================
# Test Class: TestToolStatEdgeCases
# =============================================================================

class TestToolStatEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_record_with_none_args(self, empty_stat):
        """Test recording with None tool_args."""
        seq = empty_stat.record("tool", None)
        assert seq == 1
        assert empty_stat.tool_calls[0]["tool_args"] is None

    def test_record_with_complex_args(self, empty_stat):
        """Test recording with complex nested arguments."""
        complex_args = {
            "nested": {"deep": {"value": 123}},
            "list": [1, 2, 3],
            "tuple": (4, 5, 6)
        }
        empty_stat.record("tool", complex_args)
        assert empty_stat.tool_calls[0]["tool_args"] == complex_args

    def test_record_with_empty_string_error(self, empty_stat):
        """Test recording with empty string error (falsy, not counted as error)."""
        empty_stat.record("tool", {"arg": 1}, error="")
        assert empty_stat.total_calls == 1
        assert empty_stat.total_errors == 0
        assert empty_stat.success_rate == 100.0

    def test_get_most_called_empty(self, empty_stat):
        """Test get_most_called with no records."""
        result = empty_stat.get_most_called()
        assert result == []

    def test_get_most_errored_empty(self, empty_stat):
        """Test get_most_errored with no records."""
        result = empty_stat.get_most_errored()
        assert result == []

    def test_export_empty_stat(self, empty_stat):
        """Test export with no records."""
        export_data = empty_stat.export()
        assert export_data["summary"]["total_calls"] == 0
        assert export_data["summary"]["total_errors"] == 0
        assert export_data["records"] == []

    def test_str_with_data(self, stat_with_data):
        """Test __str__ with actual data."""
        str_repr = str(stat_with_data)
        assert "Total Calls: 7" in str_repr
        assert "Total Errors: 2" in str_repr
        assert "curl" in str_repr

    def test_repr_with_data(self, stat_with_data):
        """Test __repr__ with actual data."""
        repr_str = repr(stat_with_data)
        assert "total_calls=7" in repr_str
        assert "total_errors=2" in repr_str


# =============================================================================
# Test Class: TestToolStatIntegration
# =============================================================================

class TestToolStatIntegration:
    """Integration tests for complete workflows."""

    def test_full_workflow(self, empty_stat):
        """Test a complete workflow: record, query, export."""
        empty_stat.record("api.users.list", {"page": 1})
        empty_stat.record("api.users.get", {"id": 123})
        empty_stat.record("api.users.create", {"name": "John"}, error="Validation failed")
        empty_stat.record("api.users.update", {"id": 123, "name": "Jane"})
        assert empty_stat.total_calls == 4
        assert empty_stat.total_errors == 1
        assert empty_stat.success_rate == 75.0
        user_stats = empty_stat.get_tool_stats("api.users.list")
        assert user_stats["total_count"] == 1
        assert user_stats["success_count"] == 1
        errors = empty_stat.search_errors("validation")
        assert len(errors) == 1
        export_data = empty_stat.export()
        assert export_data["summary"]["unique_tools"] == 4
        empty_stat.clear()
        assert empty_stat.total_calls == 0

    def test_error_tracking_workflow(self, empty_stat):
        """Test error tracking workflow."""
        empty_stat.record("tool_a", {"arg": 1}, error="Error type A")
        empty_stat.record("tool_a", {"arg": 2}, error="Error type A")
        empty_stat.record("tool_a", {"arg": 3}, error="Error type B")
        empty_stat.record("tool_b", {"arg": 1}, error="Error type C")
        errors = empty_stat.errors
        assert len(errors["tool_a"]) == 3
        assert len(errors["tool_b"]) == 1
        type_a_errors = empty_stat.search_errors("type a")
        assert len(type_a_errors) == 2
        most_errored = empty_stat.get_most_errored()
        assert most_errored[0] == ("tool_a", 3)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
