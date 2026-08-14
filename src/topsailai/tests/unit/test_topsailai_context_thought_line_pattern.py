"""Unit tests for thought/final-answer abnormal line-ratio detection.

Author: DawsonLin
"""

import json
from unittest import TestCase, main
from unittest.mock import MagicMock, patch

from topsailai.context.thought_line_pattern import (
    DEFAULT_MIN_LINES,
    ThoughtLinePatternRule,
    _compute_match,
    _split_non_empty_lines,
    evaluate_and_maybe_inject,
    parse_rules,
)

TRIGGER_TEXT = "p\np\ny"
FULLWIDTH_BAR = "\uff5c"
HALFWIDTH_BAR = "|"


class FakeStat:
    """Mutable stand-in for per-agent detection state."""


def make_rule(**overrides):
    """Return a rule that fires for two matching lines out of three."""
    values = {
        "pattern": "p",
        "line_ratio": 0.6,
        "min_lines": 3,
        "case_sensitive": True,
        "enabled": True,
        "dedup": True,
        "agent_role": "*",
        "warning": "",
    }
    values.update(overrides)
    return ThoughtLinePatternRule(**values)


def make_agent(role="worker"):
    """Return a mock agent with isolated mutable detection state."""
    agent = MagicMock()
    agent.agent_role = role
    agent.llm_model = None
    agent._tool_stat = FakeStat()
    return agent


def evaluate(
    agent,
    text,
    rules=None,
    enabled=True,
    step_type="thought",
    on_warning=None,
):
    """Evaluate text with deterministic agent, rules, and event dependencies."""
    configured_rules = rules if rules is not None else [make_rule()]
    with (
        patch(
            "topsailai.context.thought_line_pattern.is_enabled",
            return_value=enabled,
        ),
        patch(
            "topsailai.context.thought_line_pattern.parse_rules",
            return_value=configured_rules,
        ),
        patch(
            "topsailai.utils.thread_local_tool.get_agent_object",
            return_value=agent,
        ),
        patch(
            "topsailai.context.tool_stat.get_agent_tool_stat",
            return_value=agent._tool_stat,
        ),
        patch(
            "topsailai.ai_base.agent_types.init.get_agent_role",
            return_value="worker",
        ),
        patch("topsailai.events.record_event"),
    ):
        return evaluate_and_maybe_inject(
            text,
            step_type,
            on_warning=on_warning,
        )


class TestLineMatching(TestCase):
    """Test non-empty line counting and strict ratio matching."""

    def test_split_excludes_empty_lines(self):
        """Whitespace-only lines do not contribute to either count."""
        self.assertEqual(
            _split_non_empty_lines("a\n\n b \n\t\nx"),
            ["a", "b", "x"],
        )

    def test_rule_fires_above_threshold(self):
        """Two matching lines out of three exceed a 0.6 threshold."""
        match = _compute_match(TRIGGER_TEXT, make_rule())
        self.assertIsNotNone(match)
        _, matched, total = match
        self.assertEqual((matched, total), (2, 3))

    def test_rule_does_not_fire_at_exact_threshold(self):
        """The threshold comparison is strict rather than inclusive."""
        rule = make_rule(line_ratio=2 / 3)
        self.assertIsNone(_compute_match(TRIGGER_TEXT, rule))

    def test_rule_does_not_fire_below_minimum_lines(self):
        """Text shorter than min_lines is ignored."""
        self.assertIsNone(_compute_match(TRIGGER_TEXT, make_rule(min_lines=4)))

    def test_empty_lines_are_excluded_from_ratio(self):
        """Extra blank lines do not dilute the matching ratio."""
        text = "p\n\n p \n \t \ny"
        match = _compute_match(text, make_rule())
        self.assertIsNotNone(match)
        self.assertEqual(match[1:], (2, 3))

    def test_case_sensitivity_is_configurable(self):
        """Case-insensitive matching finds uppercase forms when requested."""
        self.assertIsNone(_compute_match(TRIGGER_TEXT, make_rule(pattern="P")))
        self.assertIsNotNone(
            _compute_match(
                TRIGGER_TEXT,
                make_rule(pattern="P", case_sensitive=False),
            )
        )

    def test_unicode_match_is_exact(self):
        """The fullwidth vertical line matches itself but not ASCII pipe."""
        fullwidth_text = f"a{FULLWIDTH_BAR}b\na{FULLWIDTH_BAR}c\nx"
        halfwidth_text = f"a{HALFWIDTH_BAR}b\na{HALFWIDTH_BAR}c\nx"
        rule = make_rule(pattern=FULLWIDTH_BAR)
        self.assertEqual(_compute_match(fullwidth_text, rule)[1:], (2, 3))
        self.assertIsNone(_compute_match(halfwidth_text, rule))


class TestRuleParsing(TestCase):
    """Test fail-closed rule parsing and validated defaults."""

    def test_invalid_top_level_inputs_return_empty(self):
        """Empty, malformed, and non-list inputs disable all rules."""
        self.assertEqual(parse_rules(""), [])
        with self.assertLogs(
            "topsailai.context.thought_line_pattern", level="WARNING"
        ):
            self.assertEqual(parse_rules("not-json"), [])
        with self.assertLogs(
            "topsailai.context.thought_line_pattern", level="WARNING"
        ):
            self.assertEqual(parse_rules('{"pattern": "p"}'), [])

    def test_invalid_individual_rules_are_skipped(self):
        """Missing patterns and out-of-range ratios are rejected."""
        invalid_rules = [
            {"line_ratio": 0.5},
            {"pattern": "p", "line_ratio": 0},
            {"pattern": "p", "line_ratio": -0.1},
            {"pattern": "p", "line_ratio": 1.01},
            "not-a-dict",
        ]
        with self.assertLogs(
            "topsailai.context.thought_line_pattern", level="WARNING"
        ):
            self.assertEqual(parse_rules(json.dumps(invalid_rules)), [])

    def test_valid_rule_preserves_all_fields(self):
        """One configured rule produces one object with exact field values."""
        raw = json.dumps(
            [
                {
                    "pattern": "topsailai.",
                    "line_ratio": 0.9,
                    "min_lines": 7,
                    "case_sensitive": False,
                    "enabled": True,
                    "dedup": False,
                    "agent_role": "worker",
                    "warning": "Custom {pattern}",
                }
            ]
        )
        rules = parse_rules(raw)
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertEqual(rule.pattern, "topsailai.")
        self.assertEqual(rule.line_ratio, 0.9)
        self.assertEqual(rule.min_lines, 7)
        self.assertFalse(rule.case_sensitive)
        self.assertTrue(rule.enabled)
        self.assertFalse(rule.dedup)
        self.assertEqual(rule.agent_role, "worker")
        self.assertEqual(rule.warning, "Custom {pattern}")

    def test_rule_defaults_and_boundary_one(self):
        """Optional defaults apply and the ratio boundary 1.0 is valid."""
        rules = parse_rules(json.dumps([{"pattern": "p", "line_ratio": 1.0}]))
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertEqual(rule.line_ratio, 1.0)
        self.assertEqual(rule.min_lines, DEFAULT_MIN_LINES)
        self.assertTrue(rule.case_sensitive)
        self.assertTrue(rule.enabled)
        self.assertTrue(rule.dedup)
        self.assertEqual(rule.agent_role, "*")

    def test_mixed_input_keeps_only_valid_rule(self):
        """Invalid entries do not discard a valid sibling rule."""
        raw = json.dumps(
            ["junk", {"pattern": "p", "line_ratio": 0.6, "min_lines": 3}]
        )
        with self.assertLogs(
            "topsailai.context.thought_line_pattern", level="WARNING"
        ):
            rules = parse_rules(raw)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].pattern, "p")


class TestEvaluation(TestCase):
    """Test gating, role filtering, merged warnings, and dedup re-arming."""

    def test_master_switch_disables_evaluation(self):
        """Disabled detection never injects an observation."""
        agent = make_agent()
        self.assertFalse(evaluate(agent, TRIGGER_TEXT, enabled=False))
        agent.add_user_message.assert_not_called()

    def test_enabled_match_injects_observation(self):
        """A hit adds one structured user observation and reports success."""
        agent = make_agent()
        self.assertTrue(evaluate(agent, TRIGGER_TEXT))
        agent.add_user_message.assert_called_once()
        content = agent.add_user_message.call_args.args[0]
        self.assertEqual(content["step_name"], "observation")
        self.assertIn("CRITICAL-SYSTEM-ALERT", content["raw_text"])

    def test_warning_callback_receives_exact_injected_text_once(self):
        """A real hit exposes the exact merged warning before injection."""
        agent = make_agent()
        on_warning = MagicMock()

        self.assertTrue(
            evaluate(
                agent,
                TRIGGER_TEXT,
                step_type="final_answer",
                on_warning=on_warning,
            )
        )

        injected_text = agent.add_user_message.call_args.args[0]["raw_text"]
        on_warning.assert_called_once_with(injected_text)

    def test_role_filtering(self):
        """A worker-only rule does not run for a manager agent."""
        agent = make_agent(role="manager")
        rules = [make_rule(agent_role="worker")]
        self.assertFalse(evaluate(agent, TRIGGER_TEXT, rules=rules))
        agent.add_user_message.assert_not_called()

    def test_multiple_hits_merge_into_one_warning(self):
        """Multiple matching rules produce one observation containing both."""
        agent = make_agent()
        rules = [
            make_rule(pattern="p"),
            make_rule(pattern="y", line_ratio=0.2),
        ]
        self.assertTrue(evaluate(agent, TRIGGER_TEXT, rules=rules))
        agent.add_user_message.assert_called_once()
        warning = agent.add_user_message.call_args.args[0]["raw_text"]
        self.assertIn('pattern="p"', warning)
        self.assertIn('pattern="y"', warning)

    def test_dedup_rearms_after_non_matching_response(self):
        """A sustained match stays detected while warnings dedup, then re-arms."""
        agent = make_agent()
        rules = [make_rule()]
        on_warning = MagicMock()
        self.assertTrue(evaluate(agent, TRIGGER_TEXT, rules=rules, on_warning=on_warning))
        self.assertTrue(evaluate(agent, TRIGGER_TEXT, rules=rules, on_warning=on_warning))
        self.assertFalse(evaluate(agent, "x\ny\nz", rules=rules, on_warning=on_warning))
        self.assertTrue(evaluate(agent, TRIGGER_TEXT, rules=rules, on_warning=on_warning))
        self.assertEqual(agent.add_user_message.call_count, 2)
        self.assertEqual(on_warning.call_count, 2)

    def test_disabled_rule_is_ignored(self):
        """A rule-level disabled flag prevents matching and injection."""
        agent = make_agent()
        self.assertFalse(
            evaluate(agent, TRIGGER_TEXT, rules=[make_rule(enabled=False)])
        )
        agent.add_user_message.assert_not_called()


if __name__ == "__main__":
    main()
