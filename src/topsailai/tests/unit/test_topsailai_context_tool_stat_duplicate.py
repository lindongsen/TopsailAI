"""
Unit tests for duplicate tool-call detection in context/tool_stat.py

Author: km3-programmer
Purpose: Test ToolStat duplicate detection, per-agent isolation,
         record_tool_call delegation, and the detect_duplicate_tool_call decorator.
"""

import os
import sys
import json
import logging
import datetime as dt
from unittest import TestCase, main
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from topsailai.context.tool_stat import (
    ToolStat,
    get_default_stat,
    get_agent_tool_stat,
    record_tool_call,
    detect_duplicate_tool_call,
    _default_stat,
)


class TestToolStatNormalize(TestCase):
    """Test ToolStat._normalize deterministic serialization."""

    def test_normalize_dict_sorted_keys(self):
        """Dict keys are sorted in normalized output."""
        a = ToolStat._normalize({"z": 1, "a": 2, "m": 3})
        b = ToolStat._normalize({"a": 2, "m": 3, "z": 1})
        self.assertEqual(a, b)
        self.assertEqual(json.loads(a), {"a": 2, "m": 3, "z": 1})

    def test_normalize_list(self):
        """Lists are serialized preserving order."""
        self.assertEqual(ToolStat._normalize([3, 1, 2]), "[3, 1, 2]")

    def test_normalize_primitive(self):
        """Primitives are serialized as JSON."""
        self.assertEqual(ToolStat._normalize("hello"), '"hello"')
        self.assertEqual(ToolStat._normalize(42), "42")
        self.assertEqual(ToolStat._normalize(True), "true")
        self.assertEqual(ToolStat._normalize(None), "null")

    def test_normalize_nested(self):
        """Nested structures are normalized recursively with sorted keys."""
        a = ToolStat._normalize({"outer": {"z": 1, "a": [2, 1]}})
        b = ToolStat._normalize({"outer": {"a": [2, 1], "z": 1}})
        self.assertEqual(a, b)

    def test_normalize_non_serializable_fallback(self):
        """Non-JSON-serializable values fall back to str()."""

        class BadObj:
            def __str__(self):
                return "bad-object"

            # json.dumps will call default=str only after __repr__ fails; force failure.
            def __repr__(self):
                raise ValueError("cannot represent")

        normalized = ToolStat._normalize(BadObj())
        # default=str serializes the str() output as a JSON string.
        self.assertEqual(normalized, '"bad-object"')

    def test_normalize_exception_fallback(self):
        """_normalize falls back to str() when json.dumps raises."""

        class BrokenObj:
            def __str__(self):
                return "fallback-string"

        # Patch json.dumps to simulate a serialization failure despite default=str.
        with patch("topsailai.context.tool_stat.json.dumps") as mock_dumps:
            mock_dumps.side_effect = ValueError("serialization failed")
            normalized = ToolStat._normalize(BrokenObj())

        self.assertEqual(normalized, "fallback-string")


class TestToolStatIsLastCallDuplicate(TestCase):
    """Test ToolStat.is_last_call_duplicate behavior."""

    def setUp(self):
        self.stat = ToolStat()

    def test_duplicate_same_tool_args_result(self):
        """True when last two calls match tool_name, args, and result."""
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.assertTrue(self.stat.is_last_call_duplicate())

    def test_not_duplicate_different_tool_name(self):
        """False when tool_name differs."""
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.stat.record("tool_b", {"x": 1}, result="ok")
        self.assertFalse(self.stat.is_last_call_duplicate())

    def test_not_duplicate_different_args(self):
        """False when args differ."""
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.stat.record("tool_a", {"x": 2}, result="ok")
        self.assertFalse(self.stat.is_last_call_duplicate())

    def test_not_duplicate_different_result(self):
        """False when result differs."""
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.stat.record("tool_a", {"x": 1}, result="not ok")
        self.assertFalse(self.stat.is_last_call_duplicate())

    def test_not_duplicate_only_one_record(self):
        """False when fewer than two records exist."""
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.assertFalse(self.stat.is_last_call_duplicate())

    def test_duplicate_dict_key_order_independence(self):
        """Args with different dict key order are still duplicates."""
        self.stat.record("tool_a", {"z": 1, "a": 2}, result="ok")
        self.stat.record("tool_a", {"a": 2, "z": 1}, result="ok")
        self.assertTrue(self.stat.is_last_call_duplicate())

    def test_not_duplicate_after_clear(self):
        """Clearing records resets duplicate detection."""
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.assertTrue(self.stat.is_last_call_duplicate())
        self.stat.clear()
        self.assertFalse(self.stat.is_last_call_duplicate())

class TestToolStatConsecutiveDuplicateCount(TestCase):
    """Test ToolStat.consecutive_duplicate_count state tracking."""

    def setUp(self):
        self.stat = ToolStat()

    def test_initial_count_is_zero(self):
        """A fresh ToolStat has consecutive_duplicate_count == 0."""
        self.assertEqual(self.stat.consecutive_duplicate_count, 0)
        self.assertEqual(self.stat.get_consecutive_duplicate_count(), 0)

    def test_s1_s2_s3_s4_pattern(self):
        """S1=0, S2 duplicate=1, S3 duplicate=2, S4 not duplicate=0."""
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.assertEqual(self.stat.consecutive_duplicate_count, 0)

        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.assertEqual(self.stat.consecutive_duplicate_count, 1)

        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.assertEqual(self.stat.consecutive_duplicate_count, 2)

        self.stat.record("tool_a", {"x": 2}, result="ok")
        self.assertEqual(self.stat.consecutive_duplicate_count, 0)

    def test_count_stored_in_metadata(self):
        """Each record stores consecutive_duplicate_count in metadata."""
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.stat.record("tool_a", {"x": 2}, result="ok")

        calls = self.stat.tool_calls
        self.assertEqual(calls[0]["metadata"]["consecutive_duplicate_count"], 0)
        self.assertEqual(calls[1]["metadata"]["consecutive_duplicate_count"], 1)
        self.assertEqual(calls[2]["metadata"]["consecutive_duplicate_count"], 2)
        self.assertEqual(calls[3]["metadata"]["consecutive_duplicate_count"], 0)

    def test_different_args_resets_count(self):
        """Different arguments reset the consecutive duplicate count."""
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.assertEqual(self.stat.consecutive_duplicate_count, 1)

        self.stat.record("tool_a", {"x": 2}, result="ok")
        self.assertEqual(self.stat.consecutive_duplicate_count, 0)

    def test_different_result_resets_count(self):
        """Different result resets the consecutive duplicate count."""
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.assertEqual(self.stat.consecutive_duplicate_count, 1)

        self.stat.record("tool_a", {"x": 1}, result="not ok")
        self.assertEqual(self.stat.consecutive_duplicate_count, 0)

    def test_different_tool_resets_count(self):
        """Different tool name resets the consecutive duplicate count."""
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.assertEqual(self.stat.consecutive_duplicate_count, 1)

        self.stat.record("tool_b", {"x": 1}, result="ok")
        self.assertEqual(self.stat.consecutive_duplicate_count, 0)

    def test_clear_resets_count(self):
        """clear() resets the consecutive duplicate count."""
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.assertEqual(self.stat.consecutive_duplicate_count, 1)

        self.stat.clear()
        self.assertEqual(self.stat.consecutive_duplicate_count, 0)

    def test_reset_resets_count(self):
        """reset() resets the consecutive duplicate count."""
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.stat.record("tool_a", {"x": 1}, result="ok")
        self.assertEqual(self.stat.consecutive_duplicate_count, 1)

        self.stat.reset()
        self.assertEqual(self.stat.consecutive_duplicate_count, 0)



class TestGetAgentToolStat(TestCase):
    """Test get_agent_tool_stat per-agent isolation and fallback."""

    def setUp(self):
        """Reset global default stat before each test."""
        import topsailai.context.tool_stat as module
        module._default_stat = None

    def test_returns_default_when_no_agent(self):
        """Returns global default stat when no agent is active."""
        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=None):
            stat = get_agent_tool_stat()
        self.assertIs(stat, get_default_stat())

    def test_returns_agent_tool_stat_when_present(self):
        """Returns agent.llm_model.tool_stat when available."""
        agent_tool_stat = ToolStat()
        agent = type("Agent", (), {"llm_model": type("LLM", (), {"tool_stat": agent_tool_stat})()})()

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent):
            stat = get_agent_tool_stat()

        self.assertIs(stat, agent_tool_stat)

    def test_creates_tool_stat_on_agent_when_missing(self):
        """Creates and attaches _tool_stat when agent has no tool_stat."""
        agent = type("Agent", (), {})()

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent):
            stat = get_agent_tool_stat()

        self.assertIsInstance(stat, ToolStat)
        self.assertIs(agent._tool_stat, stat)

    def test_per_agent_isolation(self):
        """Different agents receive different ToolStat instances."""
        agent_a = type("Agent", (), {})()
        agent_b = type("Agent", (), {})()

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent_a):
            stat_a = get_agent_tool_stat()

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent_b):
            stat_b = get_agent_tool_stat()

        self.assertIsNot(stat_a, stat_b)
        self.assertIs(stat_a, agent_a._tool_stat)
        self.assertIs(stat_b, agent_b._tool_stat)

    def test_accepts_explicit_agent_argument(self):
        """When an agent is passed explicitly, thread-local agent is ignored."""
        agent = type("Agent", (), {})()
        other_agent = type("Agent", (), {"_tool_stat": ToolStat()})()

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=other_agent):
            stat = get_agent_tool_stat(agent)

        self.assertIsInstance(stat, ToolStat)
        self.assertIs(agent._tool_stat, stat)
        self.assertIsNot(stat, other_agent._tool_stat)

    def test_explicit_agent_uses_llm_model_tool_stat(self):
        """Explicit agent with llm_model.tool_stat returns that stat."""
        agent_tool_stat = ToolStat()
        agent = type("Agent", (), {"llm_model": type("LLM", (), {"tool_stat": agent_tool_stat})()})()

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=None):
            stat = get_agent_tool_stat(agent)

        self.assertIs(stat, agent_tool_stat)

    def test_explicit_none_uses_thread_local_agent(self):
        """Passing None explicitly falls back to thread-local agent lookup."""
        agent = type("Agent", (), {})()

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent):
            stat = get_agent_tool_stat(None)

        self.assertIs(stat, agent._tool_stat)

class TestRecordToolCallDelegation(TestCase):
    """Test record_tool_call routes to agent-bound ToolStat."""

    def setUp(self):
        import topsailai.context.tool_stat as module
        module._default_stat = None

    @patch.dict(os.environ, {"TOPSAILAI_ENABLE_TOOL_STAT": "1"})
    def test_records_to_default_stat_without_agent(self):
        """When no agent is active, recording goes to default stat."""
        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=None):
            record_tool_call("tool_a", {"x": 1}, result="ok")

        self.assertEqual(get_default_stat().total_calls, 1)

    @patch.dict(os.environ, {"TOPSAILAI_ENABLE_TOOL_STAT": "1"})
    def test_records_to_agent_stat_when_agent_active(self):
        """When agent is active, recording goes to agent-bound stat."""
        agent = type("Agent", (), {"_tool_stat": ToolStat()})()

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent):
            record_tool_call("tool_a", {"x": 1}, result="ok")

        self.assertEqual(agent._tool_stat.total_calls, 1)
        self.assertEqual(get_default_stat().total_calls, 0)

    @patch.dict(os.environ, {"TOPSAILAI_ENABLE_TOOL_STAT": "0"})
    def test_disabled_returns_zero(self):
        """When disabled, record_tool_call returns 0 and does not record."""
        result = record_tool_call("tool_a", {"x": 1}, result="ok")
        self.assertEqual(result, 0)
        self.assertEqual(get_default_stat().total_calls, 0)


class TestDetectDuplicateToolCallDecorator(TestCase):
    """Test detect_duplicate_tool_call decorator behavior."""

    def setUp(self):
        import topsailai.context.tool_stat as module
        module._default_stat = None

    def _make_wrapped(self, result="ok"):
        """Create a wrapped dummy function that records two identical calls."""
        call_count = [0]

        @detect_duplicate_tool_call
        def dummy_tool(tool_func, args, tool_name=None):
            call_count[0] += 1
            # Simulate the recording that exec_tool_func would perform.
            record_tool_call(tool_name, args, result=result)
            return result

        return dummy_tool, call_count

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        "TOPSAILAI_DUP_TOOL_CALL_ENABLED": "0",
    })
    def test_disabled_returns_original_result(self):
        """When detection is disabled, original result is returned."""
        wrapped, _ = self._make_wrapped()

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=None):
            result = wrapped(None, {"x": 1}, tool_name="tool_a")

        self.assertEqual(result, "ok")

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        "TOPSAILAI_DUP_TOOL_CALL_ENABLED": "1",
    })
    def test_no_duplicate_returns_original_result(self):
        """When no duplicate, original result is returned."""
        wrapped, _ = self._make_wrapped()

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=None):
            result1 = wrapped(None, {"x": 1}, tool_name="tool_a")
            result2 = wrapped(None, {"x": 2}, tool_name="tool_a")

        self.assertEqual(result1, "ok")
        self.assertEqual(result2, "ok")


    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        "TOPSAILAI_DUP_TOOL_CALL_ENABLED": "1",
        "TOPSAILAI_DUP_TOOL_CALL_NOTICE": "Duplicate call to {tool_name} (#{consecutive_count})",
    })
    def test_consecutive_count_in_wrapped_result_and_notice(self):
        """Consecutive count increments and is rendered in notice/result."""
        wrapped, _ = self._make_wrapped()

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=None):
            wrapped(None, {"x": 1}, tool_name="tool_a")          # count = 0
            result1 = wrapped(None, {"x": 1}, tool_name="tool_a")  # count = 1
            result2 = wrapped(None, {"x": 1}, tool_name="tool_a")  # count = 2
            result3 = wrapped(None, {"x": 2}, tool_name="tool_a")  # not duplicate

        self.assertIsInstance(result1, dict)
        self.assertEqual(result1["consecutive_duplicate_count"], 1)
        self.assertEqual(result1["notice"], "Duplicate call to tool_a (#1)")

        self.assertIsInstance(result2, dict)
        self.assertEqual(result2["consecutive_duplicate_count"], 2)
        self.assertEqual(result2["notice"], "Duplicate call to tool_a (#2)")

        self.assertEqual(result3, "ok")

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        "TOPSAILAI_DUP_TOOL_CALL_ENABLED": "1",
        "TOPSAILAI_DUP_TOOL_CALL_NOTICE": "Duplicate call to {tool_name}",
    })
    def test_duplicate_with_notice_wraps_result(self):
        """When duplicate and notice template set, result is wrapped."""
        wrapped, _ = self._make_wrapped()

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=None):
            wrapped(None, {"x": 1}, tool_name="tool_a")
            result = wrapped(None, {"x": 1}, tool_name="tool_a")

        self.assertIsInstance(result, dict)
        self.assertEqual(result["original_result"], "ok")
        self.assertEqual(result["notice"], "Duplicate call to tool_a")
        self.assertIn("Duplicate tool call detected", result["reason"])
        self.assertEqual(result["consecutive_duplicate_count"], 1)

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        "TOPSAILAI_DUP_TOOL_CALL_ENABLED": "1",
    })
    def test_duplicate_without_notice_returns_original_result(self):
        """When duplicate but notice template empty, original result returned."""
        wrapped, _ = self._make_wrapped()

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=None):
            wrapped(None, {"x": 1}, tool_name="tool_a")
            with self.assertLogs("topsailai.context.tool_stat", level=logging.WARNING):
                result = wrapped(None, {"x": 1}, tool_name="tool_a")

        self.assertEqual(result, "ok")

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        "TOPSAILAI_DUP_TOOL_CALL_ENABLED": "1",
    })
    def test_exception_propagates_unchanged(self):
        """Exceptions from the wrapped function propagate unchanged."""

        @detect_duplicate_tool_call
        def failing_tool(tool_func, args, tool_name=None):
            raise ValueError("tool failure")

        with self.assertRaises(ValueError) as ctx:
            failing_tool(None, {"x": 1}, tool_name="tool_a")

        self.assertEqual(str(ctx.exception), "tool failure")

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        "TOPSAILAI_DUP_TOOL_CALL_ENABLED": "1",
        "TOPSAILAI_DUP_TOOL_CALL_NOTICE": "Duplicate: {tool_name}",
    })
    def test_per_agent_isolation_in_decorator(self):
        """Decorator respects per-agent ToolStat isolation."""
        agent_a = type("Agent", (), {})()
        agent_b = type("Agent", (), {})()

        @detect_duplicate_tool_call
        def dummy_tool(tool_func, args, tool_name=None):
            record_tool_call(tool_name, args, result="ok")
            return "ok"

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent_a):
            dummy_tool(None, {"x": 1}, tool_name="tool_a")
            result_a = dummy_tool(None, {"x": 1}, tool_name="tool_a")

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent_b):
            result_b = dummy_tool(None, {"x": 1}, tool_name="tool_a")

        self.assertIsInstance(result_a, dict)
        self.assertEqual(result_a["original_result"], "ok")
        self.assertEqual(result_b, "ok")


class TestToolStatMissingCoverage(TestCase):
    """Additional tests to cover previously missed lines in tool_stat.py."""

    def setUp(self):
        """Reset global default stat before each test."""
        import topsailai.context.tool_stat as module
        module._default_stat = None

    def test_get_by_time_range(self):
        """get_by_time_range filters records by start/end datetimes."""
        stat = ToolStat()
        # Patch datetime.now so we can control timestamps deterministically.
        base = dt.datetime(2026, 6, 29, 12, 0, 0)
        timestamps = [
            base,
            base + dt.timedelta(seconds=10),
            base + dt.timedelta(seconds=20),
        ]

        with patch("topsailai.context.tool_stat.datetime") as mock_dt:
            mock_dt.now.side_effect = timestamps
            mock_dt.datetime = dt.datetime
            mock_dt.timedelta = dt.timedelta
            for i in range(3):
                stat.record("tool_a", {"i": i + 1})

        middle = timestamps[1]
        start = middle - dt.timedelta(seconds=5)
        end = middle + dt.timedelta(seconds=5)

        result = stat.get_by_time_range(start, end)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tool_args"]["i"], 2)

    def test_get_by_time_range_start_only(self):
        """get_by_time_range excludes records before start."""
        stat = ToolStat()
        base = dt.datetime(2026, 6, 29, 12, 0, 0)
        timestamps = [
            base,
            base + dt.timedelta(seconds=10),
        ]

        with patch("topsailai.context.tool_stat.datetime") as mock_dt:
            mock_dt.now.side_effect = timestamps
            mock_dt.datetime = dt.datetime
            mock_dt.timedelta = dt.timedelta
            for i in range(2):
                stat.record("tool_a", {"i": i + 1})

        start = timestamps[1]
        result = stat.get_by_time_range(start=start)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tool_args"]["i"], 2)

    def test_get_by_time_range_end_only(self):
        """get_by_time_range excludes records after end."""
        stat = ToolStat()
        base = dt.datetime(2026, 6, 29, 12, 0, 0)
        timestamps = [
            base,
            base + dt.timedelta(seconds=10),
        ]

        with patch("topsailai.context.tool_stat.datetime") as mock_dt:
            mock_dt.now.side_effect = timestamps
            mock_dt.datetime = dt.datetime
            mock_dt.timedelta = dt.timedelta
            for i in range(2):
                stat.record("tool_a", {"i": i + 1})

        end = timestamps[0]
        result = stat.get_by_time_range(end=end)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tool_args"]["i"], 1)

    def test_get_by_time_range_invalid_timestamp(self):
        """get_by_time_range skips records with invalid timestamps."""
        stat = ToolStat()
        stat._tool_calls.append({
            "tool_call": "bad",
            "timestamp": "not-a-timestamp",
            "tool_args": {},
        })
        stat.record("tool_a", {"i": 1})

        result = stat.get_by_time_range()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tool_call"], "tool_a")

    def test_str_with_errors(self):
        """__str__ includes top errored tools section when errors exist."""
        stat = ToolStat()
        stat.record("tool_a", error="fail")
        output = str(stat)
        self.assertIn("Top Errored Tools", output)
        self.assertIn("tool_a", output)

    def test_decorator_tool_name_fallback(self):
        """Decorator falls back to tool_func.__name__ when tool_name is omitted."""

        @detect_duplicate_tool_call
        def named_tool(tool_func, args, tool_name=None):
            record_tool_call(tool_name, args, result="ok")
            return "ok"

        with patch.dict(os.environ, {
            "TOPSAILAI_ENABLE_TOOL_STAT": "1",
            "TOPSAILAI_DUP_TOOL_CALL_ENABLED": "1",
            "TOPSAILAI_DUP_TOOL_CALL_NOTICE": "Dup {tool_name}",
        }):
            with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=None):
                named_tool(named_tool, {"x": 1})
                result = named_tool(named_tool, {"x": 1})

        self.assertIsInstance(result, dict)
        self.assertIn("named_tool", result["notice"])


class TestToolStatMainBlock(TestCase):
    """Run the module as __main__ to cover usage examples."""

    def test_main_block_runs(self):
        """Executing tool_stat.py as __main__ completes without errors."""
        import runpy
        import io
        import topsailai.context.tool_stat as module

        # Reset default stat so the main block starts clean.
        module._default_stat = None

        captured = io.StringIO()
        with patch("sys.stdout", new=captured):
            runpy.run_module("topsailai.context.tool_stat", run_name="__main__")

        output = captured.getvalue()
        self.assertIn("ToolStat Usage Examples", output)
        self.assertIn("All examples completed successfully!", output)


if __name__ == "__main__":
    main()
