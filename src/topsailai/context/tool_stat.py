'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-15
  Purpose: Tool call statistics tracking and analysis

  Features:
  - Record tool calls with arguments and errors
  - Aggregate statistics by tool name
  - Error tracking and retrieval
  - Success rate calculation
  - Time-based analysis
  - Export capabilities
  - Thread-safe operations
'''

import os

from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from collections import defaultdict
from contextlib import contextmanager
import threading
import json


class ToolStat:
    """
    A comprehensive tool call statistics tracker.

    Records tool invocations, tracks errors, and provides
    aggregated statistics for analysis and monitoring.

    Example:
        >>> stat = ToolStat()
        >>> stat.record("curl", {"url": "example.com"}, error=None)
        >>> stat.record("curl", {"url": "bad"}, error="Connection refused")
        >>> print(stat.stat)
        {'curl': {'error_count': 1, 'total_count': 2, 'success_count': 1}}
        >>> print(stat.errors)
        {'curl': [{'tool_call': 'curl', 'tool_args': {'url': 'bad'}, ...}]}
    """

    def __init__(self, max_records: int = 10000):
        """
        Initialize the ToolStat tracker.

        Args:
            max_records: Maximum number of tool call records to keep (default: 10000)
                        Older records are pruned when limit is exceeded.
        """
        self._tool_calls: List[Dict[str, Any]] = []
        self._max_records = max_records
        self._lock = threading.RLock()
        self._start_time = datetime.now()
        self._call_sequence = 0  # Unique sequence number for each call

    @property
    def tool_calls(self) -> List[Dict[str, Any]]:
        """Return a copy of the tool call records (thread-safe)."""
        with self._lock:
            return self._tool_calls.copy()

    @property
    def stat(self) -> Dict[str, Dict[str, int]]:
        """
        Get aggregated statistics grouped by tool name.

        Returns:
            Dict mapping tool names to their statistics:
            {
                "{tool_call}": {
                    "error_count": int,    # Number of calls with errors
                    "total_count": int,    # Total number of calls
                    "success_count": int,  # Number of successful calls
                }
            }
        """
        with self._lock:
            stats: Dict[str, Dict[str, int]] = defaultdict(
                lambda: {"error_count": 0, "total_count": 0, "success_count": 0}
            )

            for call in self._tool_calls:
                tool_name = call["tool_call"]
                stats[tool_name]["total_count"] += 1
                if call.get("error"):
                    stats[tool_name]["error_count"] += 1
                else:
                    stats[tool_name]["success_count"] += 1

            return dict(stats)

    @property
    def errors(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all tool calls that resulted in errors, grouped by tool name.

        Returns:
            Dict mapping tool names to lists of error records:
            {
                "{tool_call}": [
                    {
                        "tool_call": str,
                        "tool_args": Any,
                        "error": str,
                        "timestamp": str,
                        "sequence": int
                    },
                    ...
                ]
            }
        """
        with self._lock:
            errors_by_tool: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

            for call in self._tool_calls:
                if call.get("error"):
                    errors_by_tool[call["tool_call"]].append(call.copy())

            return dict(errors_by_tool)

    @property
    def total_calls(self) -> int:
        """Get the total number of recorded tool calls."""
        with self._lock:
            return len(self._tool_calls)

    @property
    def total_errors(self) -> int:
        """Get the total number of tool calls with errors."""
        with self._lock:
            return sum(1 for call in self._tool_calls if call.get("error"))

    @property
    def success_rate(self) -> float:
        """
        Calculate the overall success rate.

        Returns:
            Success rate as a percentage (0-100), or 0.0 if no calls recorded.
        """
        with self._lock:
            total = len(self._tool_calls)
            if total == 0:
                return 0.0
            errors = sum(1 for call in self._tool_calls if call.get("error"))
            return ((total - errors) / total) * 100

    @property
    def uptime(self) -> float:
        """Get the tracking duration in seconds since initialization."""
        return (datetime.now() - self._start_time).total_seconds()

    def record(
        self,
        tool_call: str,
        tool_args: Any = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Record a tool call invocation.

        Args:
            tool_call: Name of the tool being called
            tool_args: Arguments passed to the tool (can be any serializable type)
            error: Error message if the call failed, None otherwise
            metadata: Optional additional metadata to store with the call

        Returns:
            The sequence number assigned to this call
        """
        with self._lock:
            self._call_sequence += 1
            record = {
                "tool_call": tool_call,
                "tool_args": tool_args,
                "error": error,
                "timestamp": datetime.now().isoformat(),
                "sequence": self._call_sequence,
            }

            if metadata:
                record["metadata"] = metadata

            self._tool_calls.append(record)

            # Prune old records if limit exceeded
            if len(self._tool_calls) > self._max_records:
                self._tool_calls = self._tool_calls[-self._max_records:]

            return self._call_sequence

    def get_by_tool(self, tool_call: str) -> List[Dict[str, Any]]:
        """
        Get all records for a specific tool.

        Args:
            tool_call: Name of the tool to filter by

        Returns:
            List of all records for the specified tool
        """
        with self._lock:
            return [call.copy() for call in self._tool_calls if call["tool_call"] == tool_call]

    def get_by_time_range(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Get tool calls within a time range.

        Args:
            start: Start datetime (inclusive), None for no lower bound
            end: End datetime (inclusive), None for no upper bound

        Returns:
            List of tool call records within the time range
        """
        with self._lock:
            result = []
            for call in self._tool_calls:
                try:
                    call_time = datetime.fromisoformat(call["timestamp"])
                    if start and call_time < start:
                        continue
                    if end and call_time > end:
                        continue
                    result.append(call.copy())
                except (ValueError, KeyError):
                    continue
            return result

    def get_recent(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        Get the most recent tool calls.

        Args:
            count: Number of recent calls to return (default: 10)

        Returns:
            List of the most recent tool call records
        """
        with self._lock:
            return [call.copy() for call in self._tool_calls[-count:]]

    def get_tool_stats(self, tool_call: str) -> Dict[str, Any]:
        """
        Get detailed statistics for a specific tool.

        Args:
            tool_call: Name of the tool

        Returns:
            Dict containing detailed stats for the tool:
            {
                "total_count": int,
                "success_count": int,
                "error_count": int,
                "success_rate": float,
                "last_called": str (ISO timestamp) or None,
                "last_error": str or None
            }
        """
        with self._lock:
            tool_calls = [c for c in self._tool_calls if c["tool_call"] == tool_call]

            if not tool_calls:
                return {
                    "total_count": 0,
                    "success_count": 0,
                    "error_count": 0,
                    "success_rate": 0.0,
                    "last_called": None,
                    "last_error": None
                }

            error_calls = [c for c in tool_calls if c.get("error")]

            return {
                "total_count": len(tool_calls),
                "success_count": len(tool_calls) - len(error_calls),
                "error_count": len(error_calls),
                "success_rate": ((len(tool_calls) - len(error_calls)) / len(tool_calls)) * 100,
                "last_called": tool_calls[-1]["timestamp"],
                "last_error": error_calls[-1]["error"] if error_calls else None
            }

    def get_most_called(self, limit: int = 5) -> List[tuple]:
        """
        Get the most frequently called tools.

        Args:
            limit: Maximum number of tools to return (default: 5)

        Returns:
            List of (tool_name, count) tuples sorted by count descending
        """
        with self._lock:
            counts: Dict[str, int] = defaultdict(int)
            for call in self._tool_calls:
                counts[call["tool_call"]] += 1

            return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_most_errored(self, limit: int = 5) -> List[tuple]:
        """
        Get the tools with the most errors.

        Args:
            limit: Maximum number of tools to return (default: 5)

        Returns:
            List of (tool_name, error_count) tuples sorted by error count descending
        """
        with self._lock:
            error_counts: Dict[str, int] = defaultdict(int)
            for call in self._tool_calls:
                if call.get("error"):
                    error_counts[call["tool_call"]] += 1

            return sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:limit]

    def search_errors(self, pattern: str) -> List[Dict[str, Any]]:
        """
        Search for errors containing a specific pattern.

        Args:
            pattern: Substring to search for in error messages

        Returns:
            List of tool call records with matching errors
        """
        with self._lock:
            return [
                call.copy() for call in self._tool_calls
                if call.get("error") and pattern.lower() in call["error"].lower()
            ]

    def clear(self, tool_call: Optional[str] = None):
        """
        Clear recorded tool calls.

        Args:
            tool_call: If specified, only clear records for this tool.
                      If None, clear all records.
        """
        with self._lock:
            if tool_call is None:
                self._tool_calls.clear()
                self._call_sequence = 0
            else:
                self._tool_calls = [
                    c for c in self._tool_calls if c["tool_call"] != tool_call
                ]

    def reset(self):
        """Reset the tracker to initial state (clears all data and resets timing)."""
        with self._lock:
            self._tool_calls.clear()
            self._call_sequence = 0
            self._start_time = datetime.now()

    def export(self) -> Dict[str, Any]:
        """
        Export all statistics and records to a dictionary.

        Returns:
            Dict containing all tracked data:
            {
                "export_time": str,
                "uptime_seconds": float,
                "summary": {...},
                "stats": {...},
                "errors": {...},
                "records": [...]
            }
        """
        with self._lock:
            return {
                "export_time": datetime.now().isoformat(),
                "uptime_seconds": self.uptime,
                "summary": {
                    "total_calls": len(self._tool_calls),
                    "total_errors": self.total_errors,
                    "success_rate": self.success_rate,
                    "unique_tools": len(set(c["tool_call"] for c in self._tool_calls))
                },
                "stats": self.stat,
                "errors": self.errors,
                "records": self._tool_calls.copy()
            }

    def export_json(self, indent: int = 2) -> str:
        """
        Export all statistics to JSON string.

        Args:
            indent: JSON indentation level (default: 2)

        Returns:
            JSON string representation of all data
        """
        return json.dumps(self.export(), indent=indent, default=str)

    def save_to_file(self, filepath: str):
        """
        Save statistics to a JSON file.

        Args:
            filepath: Path to the output file
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self.export_json())

    @contextmanager
    def track(self, tool_call: str, tool_args: Any = None):
        """
        Context manager for tracking tool calls with automatic error handling.

        Args:
            tool_call: Name of the tool being called
            tool_args: Arguments passed to the tool

        Example:
            >>> stat = ToolStat()
            >>> with stat.track("curl", {"url": "example.com"}) as result:
            ...     # Your tool call here
            ...     result["success"] = True
        """
        result = {"success": False, "error": None}
        try:
            yield result
            result["success"] = True
        except Exception as e:
            result["error"] = str(e)
            raise
        finally:
            self.record(
                tool_call=tool_call,
                tool_args=tool_args,
                error=result.get("error"),
                metadata={"success": result.get("success", False)}
            )

    def __len__(self) -> int:
        """Return the number of recorded tool calls."""
        return self.total_calls

    def __repr__(self) -> str:
        """Return a string representation of the tracker."""
        return (
            f"ToolStat(total_calls={self.total_calls}, "
            f"total_errors={self.total_errors}, "
            f"success_rate={self.success_rate:.1f}%)"
        )

    def __str__(self) -> str:
        """Return a human-readable string representation."""
        lines = [
            f"ToolStat Summary",
            f"{'=' * 40}",
            f"Total Calls: {self.total_calls}",
            f"Total Errors: {self.total_errors}",
            f"Success Rate: {self.success_rate:.2f}%",
            f"Uptime: {self.uptime:.2f}s",
            f"",
            f"Top Called Tools:"
        ]

        for tool, count in self.get_most_called(5):
            lines.append(f"  - {tool}: {count}")

        if self.total_errors > 0:
            lines.append("")
            lines.append("Top Errored Tools:")
            for tool, count in self.get_most_errored(5):
                lines.append(f"  - {tool}: {count}")

        return "\n".join(lines)


# Convenience function for quick usage
_default_stat: Optional[ToolStat] = None


def get_default_stat() -> ToolStat:
    """Get or create the default global ToolStat instance."""
    global _default_stat
    if _default_stat is None:
        _default_stat = ToolStat()
    return _default_stat

def record_tool_call(
    tool_call: str,
    tool_args: Any = None,
    error: Optional[str] = None,
    metadata: Any = None,
) -> int:
    """
    Record a tool call using the default global instance.

    Args:
        tool_call: Name of the tool being called
        tool_args: Arguments passed to the tool
        error: Error message if the call failed

    Returns:
        The sequence number assigned to this call
    """
    if os.getenv("TOPSAILAI_ENABLE_TOOL_STAT") not in ["1", "true"]:
        return 0
    return get_default_stat().record(tool_call, tool_args, error, metadata)



# =============================================================================
# USAGE EXAMPLES
# =============================================================================

if __name__ == "__main__":
    """
    Common usage examples for ToolStat.

    Run this module directly to see examples:
        python tool_stat.py
    """

    print("=" * 60)
    print("ToolStat Usage Examples")
    print("=" * 60)

    # -------------------------------------------------------------------------
    # Example 1: Basic Recording of Tool Calls
    # -------------------------------------------------------------------------
    print("\n1. Basic Recording of Tool Calls")
    print("-" * 40)

    stat = ToolStat()

    # Record successful calls
    stat.record("curl", {"url": "https://api.example.com/users"})
    stat.record("database.query", {"sql": "SELECT * FROM users"})
    stat.record("file.read", {"path": "/etc/config.json"})

    # Record a failed call
    stat.record("curl", {"url": "https://broken.example.com"}, error="Connection timeout")

    print(f"Total calls: {stat.total_calls}")
    print(f"Total errors: {stat.total_errors}")
    print(f"Success rate: {stat.success_rate:.1f}%")
    print(f"Statistics: {stat.stat}")

    # -------------------------------------------------------------------------
    # Example 2: Using the Context Manager (track)
    # -------------------------------------------------------------------------
    print("\n2. Using the Context Manager (track)")
    print("-" * 40)

    stat2 = ToolStat()

    # Successful operation
    with stat2.track("api_call", {"endpoint": "/users"}) as result:
        result["response"] = {"status": 200, "data": [1, 2, 3]}

    # Failed operation (automatic error recording)
    try:
        with stat2.track("api_call", {"endpoint": "/broken"}) as result:
            raise ConnectionError("Network unavailable")
    except ConnectionError:
        pass  # Expected error

    print(f"Total calls: {stat2.total_calls}")
    print(f"Errors: {stat2.errors}")

    # -------------------------------------------------------------------------
    # Example 3: Querying Statistics
    # -------------------------------------------------------------------------
    print("\n3. Querying Statistics")
    print("-" * 40)

    # Create some test data
    stat3 = ToolStat()
    for i in range(20):
        stat3.record("tool_a", {"index": i})
    for i in range(10):
        stat3.record("tool_b", {"index": i}, error="Test error" if i % 3 == 0 else None)

    # Get all calls for a specific tool
    tool_a_calls = stat3.get_by_tool("tool_a")
    print(f"tool_a calls: {len(tool_a_calls)}")

    # Get recent calls
    recent = stat3.get_recent(5)
    print(f"Recent 5 calls: {[c['tool_call'] for c in recent]}")

    # Get detailed stats for a tool
    tool_b_stats = stat3.get_tool_stats("tool_b")
    print(f"tool_b stats: {tool_b_stats}")

    # Get most called tools
    most_called = stat3.get_most_called(3)
    print(f"Most called: {most_called}")

    # Get tools with most errors
    most_errored = stat3.get_most_errored(3)
    print(f"Most errored: {most_errored}")

    # Search for specific errors
    error_matches = stat3.search_errors("test")
    print(f"Error matches for 'test': {len(error_matches)}")

    # -------------------------------------------------------------------------
    # Example 4: Exporting Data
    # -------------------------------------------------------------------------
    print("\n4. Exporting Data")
    print("-" * 40)

    stat4 = ToolStat()
    stat4.record("test_tool", {"arg": "value"})
    stat4.record("test_tool", {"arg": "bad"}, error="Failed")

    # Export to dictionary
    export_dict = stat4.export()
    print(f"Export keys: {list(export_dict.keys())}")

    # Export to JSON string
    json_str = stat4.export_json(indent=2)
    print(f"JSON export (truncated): {json_str[:100]}...")

    # Save to file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = f.name
    stat4.save_to_file(temp_path)
    print(f"Saved to: {temp_path}")

    # -------------------------------------------------------------------------
    # Example 5: Using Module-Level Functions
    # -------------------------------------------------------------------------
    print("\n5. Using Module-Level Functions")
    print("-" * 40)

    # Get the default global instance
    default_stat = get_default_stat()
    print(f"Default stat instance: {default_stat}")

    # Record using the global instance
    record_tool_call("global_tool", {"param": 123})
    record_tool_call("global_tool", {"param": 456}, error="Some error")

    print(f"Default stat total calls: {default_stat.total_calls}")
    print(f"Default stat errors: {default_stat.errors}")

    # -------------------------------------------------------------------------
    # Example 6: Custom Configuration
    # -------------------------------------------------------------------------
    print("\n6. Custom Configuration")
    print("-" * 40)

    # Create with custom max records (for memory-constrained environments)
    limited_stat = ToolStat(max_records=100)

    for i in range(150):
        limited_stat.record("tool", {"iteration": i})

    print(f"Recorded 150 calls, but only keeping last: {limited_stat.total_calls}")

    # -------------------------------------------------------------------------
    # Example 7: String Representation
    # -------------------------------------------------------------------------
    print("\n7. String Representation")
    print("-" * 40)

    stat7 = ToolStat()
    for i in range(10):
        stat7.record("api", {"call": i})
    stat7.record("api", {"call": "bad"}, error="Timeout")

    # __repr__ - concise representation
    print(f"repr: {repr(stat7)}")

    # __str__ - human-readable summary
    print(f"\nstr:\n{str(stat7)}")

    # __len__ - number of records
    print(f"len: {len(stat7)}")

    # -------------------------------------------------------------------------
    # Example 8: Thread Safety
    # -------------------------------------------------------------------------
    print("\n8. Thread Safety (Concurrent Access)")
    print("-" * 40)

    import threading

    thread_stat = ToolStat()
    threads = []

    def worker(thread_id):
        for i in range(10):
            thread_stat.record(f"thread_{thread_id}", {"iteration": i})

    # Create and start multiple threads
    for i in range(5):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    print(f"Concurrent calls from 5 threads: {thread_stat.total_calls}")
    print(f"Unique tools: {len(thread_stat.stat)}")

    print("\n" + "=" * 60)
    print("All examples completed successfully!")
    print("=" * 60)
