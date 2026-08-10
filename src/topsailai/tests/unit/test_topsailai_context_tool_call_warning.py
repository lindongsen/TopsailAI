"""
Unit tests for repeated tool-call warning detection in context/tool_call_warning.py

Author: DawsonLin
Purpose: Test rule parsing/validation, matching/precedence, rolling-window
         counting, trigger/dedup state, warning rendering, and per-agent
         isolation for the repeated tool-call warning feature.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from unittest import TestCase, main
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from topsailai.context.tool_call_warning import (
    ToolCallWarningRule,
    parse_rules,
    match_rule,
    render_warning,
    count_calls_in_window,
    count_calls_consecutive,
    evaluate_tool_call,
    detect_tool_call_warning,
    _get_trigger_state,
    _rule_key,
    ENV_TOOL_CALL_WARNING_RULES,
    DEFAULT_WINDOW_SECONDS,
)
from topsailai.context.tool_stat import ToolStat
# Import agent_types.init eagerly so that ai_base/agent_types/context.py binds
# get_agent_object to the original function before any patch is applied.
# If context.py is first imported while thread_local_tool.get_agent_object is
# patched (via _maybe_emit_warning -> init -> react -> tool -> context), it
# permanently binds to the mock and breaks other test files that rely on a
# clean thread-local agent.
import topsailai.ai_base.agent_types.init  # noqa: F401


def _rule(**kwargs):
    """Build a ToolCallWarningRule with sensible defaults."""
    defaults = {
        "agent_role": "*",
        "tool_call": "tool_a",
        "max_calls": 2,
        "window_seconds": 60,
        "warning": "Warning: {tool_call} called {count} times",
        "enabled": True,
        "dedup": True,
    }
    defaults.update(kwargs)
    return ToolCallWarningRule(**defaults)


class TestParseRules(TestCase):
    """Test rule parsing and validation."""

    def test_empty_unset_returns_empty(self):
        """Empty or unset config returns no rules (feature disabled)."""
        self.assertEqual(parse_rules(None), [])
        self.assertEqual(parse_rules(""), [])
        self.assertEqual(parse_rules("   "), [])

    def test_invalid_json_returns_empty(self):
        """Invalid JSON fails closed (empty rules, no exception)."""
        with self.assertLogs("topsailai.context.tool_call_warning", level="WARNING"):
            rules = parse_rules("not-json")
        self.assertEqual(rules, [])

    def test_non_list_json_returns_empty(self):
        """A non-list JSON payload disables the feature."""
        with self.assertLogs("topsailai.context.tool_call_warning", level="WARNING"):
            rules = parse_rules('{"tool_call": "tool_a"}')
        self.assertEqual(rules, [])

    def test_valid_rule_parsed(self):
        """A valid rule dict is parsed with all fields."""
        raw = json.dumps([
            {
                "agent_role": "manager",
                "tool_call": "tool_a",
                "max_calls": 3,
                "window_seconds": 30,
                "warning": "W {tool_call} {count}",
                "enabled": True,
                "dedup": False,
            }
        ])
        rules = parse_rules(raw)
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertEqual(rule.agent_role, "manager")
        self.assertEqual(rule.tool_call, "tool_a")
        self.assertEqual(rule.max_calls, 3)
        self.assertEqual(rule.window_seconds, 30)
        self.assertEqual(rule.warning, "W {tool_call} {count}")
        self.assertTrue(rule.enabled)
        self.assertFalse(rule.dedup)

    def test_defaults_applied(self):
        """Missing optional fields use defaults."""
        raw = json.dumps([{"tool_call": "tool_a", "max_calls": 2, "warning": "W"}])
        rules = parse_rules(raw)
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertEqual(rule.agent_role, "*")
        self.assertEqual(rule.window_seconds, DEFAULT_WINDOW_SECONDS)
        self.assertTrue(rule.enabled)
        self.assertTrue(rule.dedup)

    def test_unknown_role_becomes_wildcard(self):
        """Unknown agent_role is treated as wildcard."""
        raw = json.dumps([{"agent_role": "bogus", "tool_call": "t", "max_calls": 1, "warning": "W"}])
        with self.assertLogs("topsailai.context.tool_call_warning", level="WARNING"):
            rules = parse_rules(raw)
        self.assertEqual(rules[0].agent_role, "*")

    def test_non_positive_window_preserved_for_consecutive(self):
        """Non-positive window_seconds is preserved for strict consecutive counting."""
        raw = json.dumps([{"tool_call": "t", "max_calls": 1, "warning": "W", "window_seconds": -5}])
        rules = parse_rules(raw)
        self.assertEqual(rules[0].window_seconds, -5)

    def test_zero_window_preserved_for_consecutive(self):
        """A zero window_seconds is preserved for strict consecutive counting."""
        raw = json.dumps([{"tool_call": "t", "max_calls": 1, "warning": "W", "window_seconds": 0}])
        with self.assertLogs("topsailai.context.tool_call_warning", level="WARNING"):
            rules = parse_rules(raw)
        self.assertEqual(rules[0].window_seconds, 0)

    def test_missing_tool_call_skipped(self):
        """A rule without tool_call is skipped."""
        raw = json.dumps([{"max_calls": 1, "warning": "W"}])
        with self.assertLogs("topsailai.context.tool_call_warning", level="WARNING"):
            rules = parse_rules(raw)
        self.assertEqual(rules, [])

    def test_non_positive_max_calls_skipped(self):
        """A rule with max_calls <= 0 is skipped."""
        raw = json.dumps([{"tool_call": "t", "max_calls": 0, "warning": "W"}])
        with self.assertLogs("topsailai.context.tool_call_warning", level="WARNING"):
            rules = parse_rules(raw)
        self.assertEqual(rules, [])

    def test_missing_warning_skipped(self):
        """A rule without warning text is skipped."""
        raw = json.dumps([{"tool_call": "t", "max_calls": 1}])
        with self.assertLogs("topsailai.context.tool_call_warning", level="WARNING"):
            rules = parse_rules(raw)
        self.assertEqual(rules, [])

    def test_non_dict_item_skipped(self):
        """A non-dict item in the list is skipped."""
        raw = json.dumps(["not-a-dict", {"tool_call": "t", "max_calls": 1, "warning": "W"}])
        with self.assertLogs("topsailai.context.tool_call_warning", level="WARNING"):
            rules = parse_rules(raw)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].tool_call, "t")

    def test_reads_from_env_when_no_value(self):
        """When env_value is None, rules are read from the environment."""
        raw = json.dumps([{"tool_call": "t", "max_calls": 1, "warning": "W"}])
        with patch.dict(os.environ, {ENV_TOOL_CALL_WARNING_RULES: raw}):
            rules = parse_rules()
        self.assertEqual(len(rules), 1)


class TestMatchRule(TestCase):
    """Test rule matching and precedence."""

    def test_manager_specific_rule_matches_manager(self):
        """A manager-specific rule matches a manager agent."""
        rules = [_rule(agent_role="manager", tool_call="tool_a")]
        self.assertIsNotNone(match_rule(rules, "manager", "tool_a"))

    def test_worker_rule_does_not_match_manager(self):
        """A worker-specific rule does not match a manager agent."""
        rules = [_rule(agent_role="worker", tool_call="tool_a")]
        self.assertIsNone(match_rule(rules, "manager", "tool_a"))

    def test_wildcard_role_matches_any(self):
        """A wildcard role matches any agent role."""
        rules = [_rule(agent_role="*", tool_call="tool_a")]
        self.assertIsNotNone(match_rule(rules, "manager", "tool_a"))
        self.assertIsNotNone(match_rule(rules, "worker", "tool_a"))

    def test_exact_tool_precedence_over_wildcard_by_order(self):
        """Exact-tool rule declared first wins over a wildcard fallback."""
        rules = [
            _rule(agent_role="manager", tool_call="tool_a", max_calls=3),
            _rule(agent_role="*", tool_call="tool_a", max_calls=8),
        ]
        matched = match_rule(rules, "manager", "tool_a")
        self.assertIs(matched, rules[0])

    def test_first_match_wins_by_declared_order(self):
        """The first matching rule wins regardless of specificity."""
        rules = [
            _rule(agent_role="*", tool_call="*", max_calls=5),
            _rule(agent_role="manager", tool_call="tool_a", max_calls=3),
        ]
        matched = match_rule(rules, "manager", "tool_a")
        self.assertIs(matched, rules[0])

    def test_disabled_rule_skipped(self):
        """A disabled rule is not considered for matching."""
        rules = [_rule(agent_role="*", tool_call="tool_a", enabled=False)]
        self.assertIsNone(match_rule(rules, "worker", "tool_a"))

    def test_no_match_returns_none(self):
        """No matching rule returns None."""
        rules = [_rule(agent_role="manager", tool_call="tool_b")]
        self.assertIsNone(match_rule(rules, "worker", "tool_a"))


class TestRenderWarning(TestCase):
    """Test warning template rendering."""

    def test_all_placeholders_render(self):
        """All supported placeholders are replaced."""
        rendered = render_warning(
            "{tool_call} {count} {agent_role} {window_seconds} {max_calls} {member_suggestion}",
            tool_call="tool_a",
            count=5,
            agent_role="manager",
            window_seconds=60,
            max_calls=3,
            member_suggestion="Consider delegating the task to a member agent to handle it.",
        )
        self.assertEqual(
            rendered,
            "tool_a 5 manager 60 3 Consider delegating the task to a member agent to handle it.",
        )

    def test_member_suggestion_empty_by_default(self):
        """member_suggestion renders empty when not provided."""
        rendered = render_warning(
            "{member_suggestion}",
            tool_call="tool_a",
            count=5,
            agent_role="worker",
        )
        self.assertEqual(rendered, "")

    def test_unrelated_braces_preserved(self):
        """Braces that are not placeholders are preserved unchanged."""
        rendered = render_warning("Warning {tool_call} (literal {x})", tool_call="t")
        self.assertEqual(rendered, "Warning t (literal {x})")

    def test_missing_placeholder_left_unchanged(self):
        """A placeholder with no provided value stays as-is."""
        rendered = render_warning("W {tool_call} {unknown}", tool_call="t")
        self.assertEqual(rendered, "W t {unknown}")


class TestCountCallsInWindow(TestCase):
    """Test rolling-window counting."""

    def _stat_with_calls(self, tool_name, timestamps):
        """Build a ToolStat with calls at the given datetimes."""
        stat = ToolStat()
        for ts in timestamps:
            with patch("topsailai.context.tool_stat.datetime") as mock_dt:
                mock_dt.now.return_value = ts
                mock_dt.datetime = datetime
                mock_dt.timedelta = timedelta
                stat.record(tool_name, {"x": 1})
        return stat

    def test_counts_calls_within_window(self):
        """Calls within the window are counted."""
        now = datetime(2026, 8, 10, 12, 0, 0)
        stat = self._stat_with_calls("tool_a", [now - timedelta(seconds=10), now - timedelta(seconds=20)])
        self.assertEqual(count_calls_in_window(stat, "tool_a", 60, now), 2)

    def test_calls_outside_window_not_counted(self):
        """Calls older than the window are not counted."""
        now = datetime(2026, 8, 10, 12, 0, 0)
        stat = self._stat_with_calls("tool_a", [now - timedelta(seconds=120)])
        self.assertEqual(count_calls_in_window(stat, "tool_a", 60, now), 0)

    def test_boundary_inclusive(self):
        """A call exactly at the window start is counted."""
        now = datetime(2026, 8, 10, 12, 0, 0)
        stat = self._stat_with_calls("tool_a", [now - timedelta(seconds=60)])
        self.assertEqual(count_calls_in_window(stat, "tool_a", 60, now), 1)

    def test_other_tool_not_counted(self):
        """Calls to a different tool are not counted."""
        now = datetime(2026, 8, 10, 12, 0, 0)
        stat = self._stat_with_calls("tool_a", [now - timedelta(seconds=10)])
        self.assertEqual(count_calls_in_window(stat, "tool_b", 60, now), 0)

class TestCountCallsConsecutive(TestCase):
    """Test strict consecutive counting (window_seconds <= 0)."""

    def _stat_with_sequence(self, tool_sequence):
        """Build a ToolStat with calls in the given tool order."""
        stat = ToolStat()
        now = datetime(2026, 8, 10, 12, 0, 0)
        for idx, tool in enumerate(tool_sequence):
            with patch("topsailai.context.tool_stat.datetime") as mock_dt:
                mock_dt.now.return_value = now + timedelta(seconds=idx)
                mock_dt.datetime = datetime
                mock_dt.timedelta = timedelta
                stat.record(tool, {"i": idx})
        return stat

    def test_consecutive_same_tool_counts(self):
        """Trailing consecutive calls to the same tool are counted."""
        stat = self._stat_with_sequence(["tool_a", "tool_a", "tool_a"])
        self.assertEqual(count_calls_consecutive(stat, "tool_a"), 3)

    def test_different_tool_in_between_resets(self):
        """A different tool in between resets the consecutive counter."""
        stat = self._stat_with_sequence(["tool_a", "tool_b", "tool_a"])
        self.assertEqual(count_calls_consecutive(stat, "tool_a"), 1)

    def test_trailing_other_tool_returns_zero(self):
        """When the last call is a different tool, the count is zero."""
        stat = self._stat_with_sequence(["tool_a", "tool_a", "tool_b"])
        self.assertEqual(count_calls_consecutive(stat, "tool_a"), 0)

    def test_empty_stat_returns_zero(self):
        """An empty stat returns zero."""
        stat = ToolStat()
        self.assertEqual(count_calls_consecutive(stat, "tool_a"), 0)


class TestEvaluateConsecutive(TestCase):
    """Test evaluate_tool_call with strict consecutive semantics."""

    def _stat_with_sequence(self, tool_sequence):
        stat = ToolStat()
        now = datetime(2026, 8, 10, 12, 0, 0)
        for idx, tool in enumerate(tool_sequence):
            with patch("topsailai.context.tool_stat.datetime") as mock_dt:
                mock_dt.now.return_value = now + timedelta(seconds=idx)
                mock_dt.datetime = datetime
                mock_dt.timedelta = timedelta
                stat.record(tool, {"i": idx})
        return stat

    def test_triggers_when_consecutive_exceeds_max(self):
        """Consecutive calls exceeding max_calls trigger a warning."""
        stat = self._stat_with_sequence(["tool_a", "tool_a", "tool_a"])
        rules = [_rule(tool_call="tool_a", max_calls=2, window_seconds=0)]
        result = evaluate_tool_call(stat, rules, "worker", "tool_a")
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 3)

    def test_no_trigger_when_interleaved(self):
        """Interleaved calls do not count toward the consecutive threshold."""
        stat = self._stat_with_sequence(["tool_a", "tool_b", "tool_a", "tool_a"])
        rules = [_rule(tool_call="tool_a", max_calls=2, window_seconds=0)]
        result = evaluate_tool_call(stat, rules, "worker", "tool_a")
        self.assertIsNone(result)

    def test_window_based_still_works(self):
        """Positive window_seconds keeps the rolling-window behavior."""
        now = datetime(2026, 8, 10, 12, 0, 0)
        stat = ToolStat()
        for i in range(3):
            with patch("topsailai.context.tool_stat.datetime") as mock_dt:
                mock_dt.now.return_value = now
                mock_dt.datetime = datetime
                mock_dt.timedelta = timedelta
                stat.record("tool_a", {"i": i})
        rules = [_rule(tool_call="tool_a", max_calls=2, window_seconds=60)]
        result = evaluate_tool_call(stat, rules, "worker", "tool_a", now)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 3)

class TestEvaluateToolCall(TestCase):
    """Test the evaluate_tool_call trigger decision."""

    def test_no_rules_returns_none(self):
        """No rules means no trigger."""
        stat = ToolStat()
        self.assertIsNone(evaluate_tool_call(stat, [], "worker", "tool_a"))

    def test_triggers_when_count_exceeds_max(self):
        """A trigger fires when count exceeds max_calls."""
        now = datetime(2026, 8, 10, 12, 0, 0)
        stat = ToolStat()
        for i in range(3):
            with patch("topsailai.context.tool_stat.datetime") as mock_dt:
                mock_dt.now.return_value = now
                mock_dt.datetime = datetime
                mock_dt.timedelta = timedelta
                stat.record("tool_a", {"i": i})
        rules = [_rule(tool_call="tool_a", max_calls=2, window_seconds=60)]
        result = evaluate_tool_call(stat, rules, "worker", "tool_a", now)
        self.assertIsNotNone(result)
        rule, count = result
        self.assertEqual(count, 3)
        self.assertIs(rule, rules[0])

    def test_no_trigger_when_count_within_max(self):
        """No trigger when count is within max_calls."""
        now = datetime(2026, 8, 10, 12, 0, 0)
        stat = ToolStat()
        for i in range(2):
            with patch("topsailai.context.tool_stat.datetime") as mock_dt:
                mock_dt.now.return_value = now
                mock_dt.datetime = datetime
                mock_dt.timedelta = timedelta
                stat.record("tool_a", {"i": i})
        rules = [_rule(tool_call="tool_a", max_calls=2, window_seconds=60)]
        self.assertIsNone(evaluate_tool_call(stat, rules, "worker", "tool_a", now))

    def test_different_args_count_toward_same_tool(self):
        """Different arguments still count toward the same tool threshold."""
        now = datetime(2026, 8, 10, 12, 0, 0)
        stat = ToolStat()
        for i in range(3):
            with patch("topsailai.context.tool_stat.datetime") as mock_dt:
                mock_dt.now.return_value = now
                mock_dt.datetime = datetime
                mock_dt.timedelta = timedelta
                stat.record("tool_a", {"i": i})
        rules = [_rule(tool_call="tool_a", max_calls=2, window_seconds=60)]
        result = evaluate_tool_call(stat, rules, "worker", "tool_a", now)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 3)


class TestDetectToolCallWarningDecorator(TestCase):
    """Test the decorator wiring and dedup behavior."""

    def setUp(self):
        import topsailai.context.tool_stat as module
        module._default_stat = None

    def _make_wrapped(self, result="ok"):
        """Create a wrapped function that records a tool call and returns."""
        from topsailai.context.tool_stat import record_tool_call

        @detect_tool_call_warning
        def dummy_tool(tool_func, args, tool_name=None):
            record_tool_call(tool_name, args, result=result)
            return result

        return dummy_tool

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        ENV_TOOL_CALL_WARNING_RULES: json.dumps([
            {"agent_role": "*", "tool_call": "tool_a", "max_calls": 2,
             "window_seconds": 60, "warning": "W {tool_call} {count}"}
        ]),
    })
    def test_returns_original_result_unchanged(self):
        """The original tool result is returned unchanged."""
        wrapped = self._make_wrapped(result="ok")
        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=None):
            result = wrapped(None, {"x": 1}, tool_name="tool_a")
        self.assertEqual(result, "ok")

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        ENV_TOOL_CALL_WARNING_RULES: json.dumps([
            {"agent_role": "*", "tool_call": "tool_a", "max_calls": 2,
             "window_seconds": 60, "warning": "W {tool_call} {count}"}
        ]),
    })
    def test_warning_injected_via_agent(self):
        """A warning is injected via agent.add_user_message when triggered."""
        agent = MagicMock()
        agent.agent_role = "worker"
        agent.llm_model = None
        agent._tool_stat = ToolStat()
        wrapped = self._make_wrapped(result="ok")

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent):
            for _ in range(3):
                wrapped(None, {"x": 1}, tool_name="tool_a")
        # First two calls are within max_calls; the third triggers.
        self.assertTrue(agent.add_user_message.called)
        args, kwargs = agent.add_user_message.call_args
        content = args[0]
        self.assertIsInstance(content, dict)
        self.assertEqual(content.get("step_name"), "observation")
        self.assertIn("W tool_a 3", content.get("raw_text", ""))
        self.assertFalse(kwargs.get("need_print", True))

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        ENV_TOOL_CALL_WARNING_RULES: json.dumps([
            {"agent_role": "worker", "tool_call": "tool_a", "max_calls": 2,
             "window_seconds": 60, "warning": "W {tool_call} {count}"}
        ]),
    })
    def test_worker_rule_does_not_trigger_for_manager(self):
        """A worker-specific rule does not trigger for a manager agent."""
        agent = MagicMock()
        agent.agent_role = "manager"
        agent.llm_model = None
        agent._tool_stat = ToolStat()
        wrapped = self._make_wrapped(result="ok")

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent):
            for _ in range(5):
                wrapped(None, {"x": 1}, tool_name="tool_a")

        self.assertFalse(agent.add_user_message.called)

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        ENV_TOOL_CALL_WARNING_RULES: json.dumps([
            {"agent_role": "*", "tool_call": "tool_a", "max_calls": 2,
             "window_seconds": 60, "warning": "W {tool_call} {count}", "dedup": True}
        ]),
    })
    def test_dedup_warns_once_then_rearms(self):
        """With dedup, warning fires once per sustained over-limit period and re-arms."""
        agent = MagicMock()
        agent.agent_role = "worker"
        agent.llm_model = None
        agent._tool_stat = ToolStat()
        wrapped = self._make_wrapped(result="ok")

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent):
            # 3 calls: third triggers (count=3 > 2).
            for _ in range(3):
                wrapped(None, {"x": 1}, tool_name="tool_a")
            # 4th call: still over limit, dedup suppresses.
            wrapped(None, {"x": 1}, tool_name="tool_a")
            # 5th call: still over limit, dedup suppresses.
            wrapped(None, {"x": 1}, tool_name="tool_a")

        self.assertEqual(agent.add_user_message.call_count, 1)

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        ENV_TOOL_CALL_WARNING_RULES: json.dumps([
            {"agent_role": "*", "tool_call": "tool_a", "max_calls": 2,
             "window_seconds": 60, "warning": "W {tool_call} {count}", "dedup": False}
        ]),
    })
    def test_no_dedup_warns_every_over_limit_call(self):
        """With dedup=False, every over-limit call warns."""
        agent = MagicMock()
        agent.agent_role = "worker"
        agent.llm_model = None
        agent._tool_stat = ToolStat()
        wrapped = self._make_wrapped(result="ok")

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent):
            for _ in range(5):
                wrapped(None, {"x": 1}, tool_name="tool_a")

        # Calls 3, 4, 5 all exceed max_calls=2.
        self.assertEqual(agent.add_user_message.call_count, 3)

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        ENV_TOOL_CALL_WARNING_RULES: json.dumps([
            {"agent_role": "*", "tool_call": "tool_a", "max_calls": 2,
             "window_seconds": 60, "warning": "W {tool_call} {count}", "dedup": True}
        ]),
    })
    def test_per_agent_isolation(self):
        """Different agents have independent warning state."""
        agent_a = MagicMock()
        agent_a.agent_role = "worker"
        agent_a.llm_model = None
        agent_a._tool_stat = ToolStat()
        agent_b = MagicMock()
        agent_b.agent_role = "worker"
        agent_b.llm_model = None
        agent_b._tool_stat = ToolStat()
        wrapped = self._make_wrapped(result="ok")

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent_a):
            for _ in range(3):
                wrapped(None, {"x": 1}, tool_name="tool_a")

        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=agent_b):
            for _ in range(3):
                wrapped(None, {"x": 1}, tool_name="tool_a")

        # Each agent triggers independently.
        self.assertEqual(agent_a.add_user_message.call_count, 1)
        self.assertEqual(agent_b.add_user_message.call_count, 1)

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        ENV_TOOL_CALL_WARNING_RULES: "invalid-json",
    })
    def test_invalid_config_does_not_block(self):
        """Invalid config fails safely without blocking tool execution."""
        wrapped = self._make_wrapped(result="ok")
        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=None):
            result = wrapped(None, {"x": 1}, tool_name="tool_a")
        self.assertEqual(result, "ok")

    @patch.dict(os.environ, {
        "TOPSAILAI_ENABLE_TOOL_STAT": "1",
        ENV_TOOL_CALL_WARNING_RULES: json.dumps([
            {"agent_role": "*", "tool_call": "tool_a", "max_calls": 2,
             "window_seconds": 60, "warning": "W {tool_call} {count}"}
        ]),
    })
    def test_exception_in_evaluation_does_not_block(self):
        """An exception during evaluation is swallowed (advisory only)."""
        wrapped = self._make_wrapped(result="ok")
        with patch("topsailai.utils.thread_local_tool.get_agent_object", return_value=None):
            with patch("topsailai.context.tool_call_warning._maybe_emit_warning",
                       side_effect=RuntimeError("boom")):
                result = wrapped(None, {"x": 1}, tool_name="tool_a")
        self.assertEqual(result, "ok")


class TestTriggerState(TestCase):
    """Test the per-agent trigger state helper."""

    def test_state_created_and_shared(self):
        """Trigger state is created and reused on the same stat."""
        stat = ToolStat()
        state1 = _get_trigger_state(stat)
        state2 = _get_trigger_state(stat)
        self.assertIs(state1, state2)
        self.assertEqual(state1, {})

    def test_rule_key_stable(self):
        """Rule key is stable across equal rules."""
        r1 = _rule(agent_role="manager", tool_call="tool_a", max_calls=3, window_seconds=30)
        r2 = _rule(agent_role="manager", tool_call="tool_a", max_calls=3, window_seconds=30)
        self.assertEqual(_rule_key(r1), _rule_key(r2))


if __name__ == "__main__":
    main()