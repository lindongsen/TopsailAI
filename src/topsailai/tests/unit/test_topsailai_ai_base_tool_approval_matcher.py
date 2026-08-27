"""
Unit tests for the tool approval matcher module.
"""

import json
import os
from unittest.mock import patch

import pytest

from topsailai.ai_base.tool_approval.matcher import (
    ApprovalRule,
    ConditionMatch,
    RuleMatch,
    _evaluate_condition,
    _evaluate_params,
    _evaluate_params_detail,
    _match_pattern,
    _parse_rule,
    _disable_approval_due_to_config_error,
    clear_approval_rules_cache,
    get_approval_rules,
    is_tool_approval_enabled,
    load_approval_rules,
    match_approval_rule,
    match_approval_rule_detail,
)


class TestMatchPattern:
    """Tests for the pattern matcher."""

    def test_exact_match(self):
        assert _match_pattern("cmd_tool-exec_cmd", "cmd_tool-exec_cmd") is True

    def test_exact_match_case_sensitive(self):
        assert _match_pattern("cmd_tool-exec_cmd", "Cmd_tool-exec_cmd") is False

    def test_wildcard_matches_all(self):
        assert _match_pattern("*", "anything") is True
        assert _match_pattern("*", "") is True

    def test_prefix_wildcard(self):
        assert _match_pattern("cmd_*", "cmd_tool-exec_cmd") is True
        assert _match_pattern("cmd_*", "cmd_tool-read_file") is True
        assert _match_pattern("cmd_*", "file_tool-read_file") is False

    def test_suffix_wildcard(self):
        assert _match_pattern("*_write", "file_tool_write") is True
        assert _match_pattern("*_write", "file_tool-read_file") is False

    def test_middle_wildcard(self):
        assert _match_pattern("file_*_file", "file_tool-write_file") is True
        assert _match_pattern("file_*_file", "file_tool-read_line") is False

    def test_question_mark_is_literal(self):
        # '?' is not a wildcard; it must match a literal '?' in the value.
        assert _match_pattern("cmd_?", "cmd_x") is False
        assert _match_pattern("cmd_?", "cmd_?") is True

    def test_bracket_is_literal(self):
        # '[seq]' is not a character class; it must match literal brackets.
        assert _match_pattern("cmd_[ab]", "cmd_a") is False
        assert _match_pattern("cmd_[ab]", "cmd_[ab]") is True

    def test_star_matches_empty_sequence(self):
        assert _match_pattern("cmd_*_cmd", "cmd__cmd") is True

    def test_only_star_wildcard_supported(self):
        # Verify that other glob metacharacters are treated literally.
        assert _match_pattern("cmd?tool", "cmdxtool") is False
        assert _match_pattern("cmd?tool", "cmd?tool") is True
        assert _match_pattern("cmd[0-9]tool", "cmd5tool") is False
        assert _match_pattern("cmd[0-9]tool", "cmd[0-9]tool") is True


class TestEvaluateCondition:
    """Tests for individual parameter conditions."""

    def test_contains(self):
        assert _evaluate_condition("example test string", "contains", "example test") is True
        assert _evaluate_condition("example other", "contains", "example test") is False

    def test_contains_non_string_operand(self):
        assert _evaluate_condition(123, "contains", "2") is True
        assert _evaluate_condition("example", "contains", 123) is False

    def test_not_contains(self):
        assert _evaluate_condition("ls", "not_contains", "privileged") is True
        assert _evaluate_condition("privileged ls", "not_contains", "privileged") is False

    def test_not_contains_non_string_operand(self):
        assert _evaluate_condition(123, "not_contains", "privileged") is True
        assert _evaluate_condition(123, "not_contains", "23") is False

    def test_eq(self):
        assert _evaluate_condition("/etc/passwd", "eq", "/etc/passwd") is True
        assert _evaluate_condition("/etc/passwd", "eq", "/etc/hosts") is False

    def test_ne(self):
        assert _evaluate_condition("user", "ne", "system") is True
        assert _evaluate_condition("system", "ne", "system") is False

    def test_regex(self):
        assert _evaluate_condition("example test", "regex", r"example\s+test") is True
        assert _evaluate_condition("example other", "regex", r"example\s+test$") is False

    def test_regex_invalid(self):
        assert _evaluate_condition("value", "regex", "[invalid") is False

    def test_regex_non_string_operand(self):
        assert _evaluate_condition(123, "regex", r"\d+") is True
        assert _evaluate_condition(123, "regex", r"^abc$") is False
        assert _evaluate_condition("123", "regex", 123) is False

    def test_in(self):
        assert _evaluate_condition("delete", "in", "delete,write,exec") is True
        assert _evaluate_condition("read", "in", "delete,write,exec") is False

    def test_in_list(self):
        assert _evaluate_condition("delete", "in", ["delete", "write"]) is True

    def test_in_non_string_operand(self):
        assert _evaluate_condition(123, "in", "123,456") is True
        assert _evaluate_condition(123, "in", [123, 456]) is True
        assert _evaluate_condition(123, "in", ["123", "456"]) is True
        assert _evaluate_condition(123, "in", "456,789") is False

    def test_not_in(self):
        assert _evaluate_condition("read", "not_in", "delete,write") is True
        assert _evaluate_condition("delete", "not_in", "delete,write") is False

    def test_not_in_non_string_operand(self):
        assert _evaluate_condition(123, "not_in", "456,789") is True
        assert _evaluate_condition(123, "not_in", [123, 456]) is False
        assert _evaluate_condition(123, "not_in", ["123", "456"]) is False

    def test_starts_with(self):
        assert _evaluate_condition("example prefix here", "starts_with", "example prefix") is True
        assert _evaluate_condition("example other", "starts_with", "example prefix") is False

    def test_starts_with_non_string_operand(self):
        assert _evaluate_condition(123, "starts_with", "12") is True
        assert _evaluate_condition(123, "starts_with", "example") is False

    def test_ends_with(self):
        assert _evaluate_condition("config.env", "ends_with", ".env") is True
        assert _evaluate_condition("config.txt", "ends_with", ".env") is False

    def test_ends_with_non_string_operand(self):
        assert _evaluate_condition(123, "ends_with", "23") is True
        assert _evaluate_condition(123, "ends_with", ".env") is False

    def test_exists(self):
        assert _evaluate_condition("present", "exists", None) is True
        assert _evaluate_condition(None, "exists", None) is False

    def test_numeric_comparisons(self):
        assert _evaluate_condition(600, "gte", 600) is True
        assert _evaluate_condition(600, "gt", 500) is True
        assert _evaluate_condition(400, "lt", 500) is True
        assert _evaluate_condition(500, "lte", 500) is True

    def test_numeric_invalid(self):
        assert _evaluate_condition("abc", "gt", 5) is False

    def test_unknown_operator(self):
        assert _evaluate_condition("value", "unknown_op", "x") is False


class TestEvaluateParams:
    """Tests for combining parameter conditions."""

    def test_empty_params(self):
        assert _evaluate_params({}, [], "and") is True

    def test_and_logic(self):
        params = [
            {"param": "cmd", "op": "contains", "value": "example"},
            {"param": "cmd", "op": "contains", "value": "test"},
        ]
        assert _evaluate_params({"cmd": "example test"}, params, "and") is True
        assert _evaluate_params({"cmd": "example other"}, params, "and") is False

    def test_or_logic(self):
        params = [
            {"param": "cmd", "op": "contains", "value": "example"},
            {"param": "cmd", "op": "contains", "value": "safe_cmd_b"},
        ]
        assert _evaluate_params({"cmd": "safe_cmd_b arg"}, params, "or") is True
        assert _evaluate_params({"cmd": "ls"}, params, "or") is False

    def test_param_none_skipped(self):
        params = [{"param": None, "op": "contains", "value": "example"}]
        assert _evaluate_params({"cmd": "example"}, params, "and") is True


class TestParseRule:
    """Tests for rule parsing."""

    def test_valid_rule(self):
        rule = _parse_rule({
            "name": "test",
            "match": "cmd_*",
            "mode": "require",
            "params": [{"param": "cmd", "op": "contains", "value": "example"}],
            "logic": "or",
            "timeout": 120,
            "policy": "deny",
        })
        assert rule is not None
        assert rule.name == "test"
        assert rule.match == "cmd_*"
        assert rule.mode == "require"
        assert rule.timeout == 120.0
        assert rule.policy == "deny"
        assert rule.logic == "or"

    def test_missing_match(self):
        assert _parse_rule({"mode": "require"}) is None

    def test_missing_mode(self):
        assert _parse_rule({"match": "*"}) is None

    def test_invalid_timeout(self):
        rule = _parse_rule({"match": "*", "mode": "require", "timeout": "abc"})
        assert rule.timeout is None

    def test_unknown_policy(self):
        rule = _parse_rule({"match": "*", "mode": "require", "policy": "unknown"})
        assert rule.policy is None

    def test_unknown_logic(self):
        rule = _parse_rule({"match": "*", "mode": "require", "logic": "xor"})
        assert rule.logic == "and"

    def test_non_dict_rule(self):
        assert _parse_rule("not a dict") is None

    def test_invalid_name_type(self):
        rule = _parse_rule({"name": 123, "match": "*", "mode": "require"})
        assert rule.name is None

    def test_invalid_params_type(self):
        rule = _parse_rule({"match": "*", "mode": "require", "params": "not a list"})
        assert rule.params == []

    def test_invalid_logic_type(self):
        rule = _parse_rule({"match": "*", "mode": "require", "logic": 123})
        assert rule.logic == "and"

    def test_invalid_priority_type(self):
        rule = _parse_rule({"match": "*", "mode": "require", "priority": "abc"})
        assert rule.priority == 0


class TestMatchApprovalRule:
    """Tests for rule matching."""

    def test_first_match_wins(self):
        rules = [
            ApprovalRule("cmd_*", "require", name="first"),
            ApprovalRule("*", "bypass", name="second"),
        ]
        with patch("topsailai.ai_base.tool_approval.matcher.get_approval_rules", return_value=rules):
            rule = match_approval_rule("cmd_tool-exec_cmd", {})
            assert rule is not None
            assert rule.name == "first"

    def test_priority_smaller_first(self):
        rules = [
            ApprovalRule("cmd_*", "bypass", name="low", priority=10),
            ApprovalRule("cmd_*", "require", name="high", priority=1),
        ]
        with patch("topsailai.ai_base.tool_approval.matcher.get_approval_rules", return_value=rules):
            rule = match_approval_rule("cmd_tool-exec_cmd", {})
            assert rule is not None
            assert rule.name == "high"

    def test_priority_larger_later(self):
        rules = [
            ApprovalRule("cmd_*", "require", name="high", priority=1),
            ApprovalRule("cmd_*", "bypass", name="low", priority=10),
        ]
        with patch("topsailai.ai_base.tool_approval.matcher.get_approval_rules", return_value=rules):
            rule = match_approval_rule("cmd_tool-exec_cmd", {})
            assert rule is not None
            assert rule.name == "high"

    def test_same_priority_preserves_order(self):
        rules = [
            ApprovalRule("cmd_*", "require", name="first", priority=5),
            ApprovalRule("cmd_*", "bypass", name="second", priority=5),
        ]
        with patch("topsailai.ai_base.tool_approval.matcher.get_approval_rules", return_value=rules):
            rule = match_approval_rule("cmd_tool-exec_cmd", {})
            assert rule is not None
            assert rule.name == "first"

    def test_no_match(self):
        rules = [ApprovalRule("file_*", "require", name="only")]
        with patch("topsailai.ai_base.tool_approval.matcher.get_approval_rules", return_value=rules):
            assert match_approval_rule("cmd_tool-exec_cmd", {}) is None

    def test_params_must_match(self):
        rules = [
            ApprovalRule(
                "cmd_*",
                "require",
                name="example",
                params=[{"param": "cmd", "op": "contains", "value": "example test"}],
            )
        ]
        with patch("topsailai.ai_base.tool_approval.matcher.get_approval_rules", return_value=rules):
            assert match_approval_rule("cmd_tool-exec_cmd", {"cmd": "example test"}) is not None
            assert match_approval_rule("cmd_tool-exec_cmd", {"cmd": "example other"}) is None



class TestLoadApprovalRules:
    """Tests for configuration loading."""

    def test_empty_rules(self, temp_workspace):
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_RULES": "", "TOPSAILAI_WORK_FOLDER": str(temp_workspace)}, clear=True):
            clear_approval_rules_cache()
            assert load_approval_rules() == []

    def test_inline_json(self):
        rules_json = json.dumps([{"match": "*", "mode": "require"}])
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_RULES": rules_json}, clear=True):
            clear_approval_rules_cache()
            rules = load_approval_rules()
            assert len(rules) == 1
            assert rules[0].match == "*"

    def test_file_path(self, temp_workspace):
        rules_json = json.dumps([{"match": "cmd_*", "mode": "require"}])
        rule_file = temp_workspace / "rules.json"
        rule_file.write_text(rules_json, encoding="utf-8")
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_RULES": str(rule_file)}, clear=True):
            clear_approval_rules_cache()
            rules = load_approval_rules()
            assert len(rules) == 1
            assert rules[0].match == "cmd_*"

    def test_invalid_json_disables_approval(self):
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_RULES": "not json"}, clear=True):
            clear_approval_rules_cache()
            rules = load_approval_rules()
            assert rules == []
            assert os.environ.get("TOPSAILAI_TOOL_APPROVAL_ENABLED") == "0"

    def test_non_array_disables_approval(self):
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_RULES": '{"key": "value"}'}, clear=True):
            clear_approval_rules_cache()
            rules = load_approval_rules()
            assert rules == []
            assert os.environ.get("TOPSAILAI_TOOL_APPROVAL_ENABLED") == "0"

    def test_unreadable_file_disables_approval(self, monkeypatch, tmp_path):
        rule_file = tmp_path / "rules.json"
        rule_file.write_text("[]", encoding="utf-8")

        def raise_permission_error(*args, **kwargs):
            raise PermissionError("Permission denied")

        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_RULES", str(rule_file))
        clear_approval_rules_cache()
        with patch("builtins.open", side_effect=raise_permission_error):
            rules = load_approval_rules()
        assert rules == []
        assert os.environ.get("TOPSAILAI_TOOL_APPROVAL_ENABLED") == "0"


class TestDisableApprovalDueToConfigError:
    """Tests for the config-error disable helper."""

    def test_disables_approval_and_logs_once(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        clear_approval_rules_cache()
        _disable_approval_due_to_config_error()
        assert os.environ.get("TOPSAILAI_TOOL_APPROVAL_ENABLED") == "0"
        # Second call should not raise and keep env disabled.
        _disable_approval_due_to_config_error()
        assert os.environ.get("TOPSAILAI_TOOL_APPROVAL_ENABLED") == "0"


class TestIsToolApprovalEnabled:
    """Tests for the master switch."""

    def test_enabled(self):
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_ENABLED": "1"}, clear=True):
            assert is_tool_approval_enabled() is True

    def test_enabled_true_string(self):
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_ENABLED": "true"}, clear=True):
            assert is_tool_approval_enabled() is True

    def test_enabled_yes_string(self):
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_ENABLED": "yes"}, clear=True):
            assert is_tool_approval_enabled() is True

    def test_enabled_on_string(self):
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_ENABLED": "on"}, clear=True):
            assert is_tool_approval_enabled() is True

    def test_enabled_enabled_string(self):
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_ENABLED": "enabled"}, clear=True):
            assert is_tool_approval_enabled() is True

    def test_enabled_case_insensitive(self):
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_ENABLED": "TRUE"}, clear=True):
            assert is_tool_approval_enabled() is True
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_ENABLED": "Yes"}, clear=True):
            assert is_tool_approval_enabled() is True

    def test_disabled(self):
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_ENABLED": "0"}, clear=True):
            assert is_tool_approval_enabled() is False

    def test_disabled_false_string(self):
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_ENABLED": "false"}, clear=True):
            assert is_tool_approval_enabled() is False

    def test_default_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            assert is_tool_approval_enabled() is False


class TestEvaluateConditionEdgeCases:
    """Tests for condition operators that are not exercised elsewhere."""

    def test_in_operator_with_list(self):
        assert _evaluate_condition("b", "in", ["a", "b", "c"]) is True
        assert _evaluate_condition("d", "in", ["a", "b", "c"]) is False

    def test_not_in_operator_with_list(self):
        assert _evaluate_condition("d", "not_in", ["a", "b", "c"]) is True
        assert _evaluate_condition("a", "not_in", ["a", "b", "c"]) is False

    def test_unknown_operator_returns_false(self):
        assert _evaluate_condition("x", "unknown_op", "x") is False


class TestEvaluateParamsLogic:
    """Tests for parameter logic handling."""

    def test_unknown_logic_defaults_to_and(self):
        # Two conditions, both must pass. First passes, second fails -> False.
        params = [
            {"param": "cmd", "op": "eq", "value": "git"},
            {"param": "cmd", "op": "eq", "value": "rm"},
        ]
        assert _evaluate_params({"cmd": "git"}, params, "unknown") is False

    def test_or_logic_short_circuits(self):
        params = [
            {"param": "cmd", "op": "eq", "value": "git"},
            {"param": "cmd", "op": "eq", "value": "rm"},
        ]
        assert _evaluate_params({"cmd": "rm"}, params, "or") is True


class TestParseRuleEdgeCases:
    """Tests for rule parsing edge cases."""

    def test_invalid_timeout_is_ignored(self):
        rule = _parse_rule({
            "match": "*",
            "mode": "require",
            "timeout": "not-a-number",
        })
        assert rule is not None
        assert rule.timeout is None

    def test_invalid_policy_is_ignored(self):
        rule = _parse_rule({
            "match": "*",
            "mode": "require",
            "policy": ["deny"],
        })
        assert rule is not None
        assert rule.policy is None

    def test_invalid_rule_is_skipped(self):
        rules_json = '[{"match": "*", "mode": "require"}, {"invalid": "rule"}]'
        with patch.dict(
            os.environ,
            {
                "TOPSAILAI_TOOL_APPROVAL_ENABLED": "1",
                "TOPSAILAI_TOOL_APPROVAL_RULES": rules_json,
            },
            clear=True,
        ):
            clear_approval_rules_cache()
            rules = load_approval_rules()
            assert len(rules) == 1
            assert rules[0].match == "*"


class TestLoadApprovalRulesCache:
    """Tests for rule caching behavior."""

    def test_cache_hit_returns_same_object(self):
        rules_json = '[{"match": "*", "mode": "require"}]'
        with patch.dict(
            os.environ,
            {
                "TOPSAILAI_TOOL_APPROVAL_ENABLED": "1",
                "TOPSAILAI_TOOL_APPROVAL_RULES": rules_json,
            },
            clear=True,
        ):
            clear_approval_rules_cache()
            first = load_approval_rules()
            second = load_approval_rules()
            assert first is second


class TestEvaluateConditionEdgeCases:
    """Tests for condition evaluation edge cases."""

    def test_in_with_unsupported_expected_type_returns_false(self):
        assert _evaluate_condition("x", "in", {"x": 1}) is False

    def test_not_in_with_unsupported_expected_type_returns_false(self):
        assert _evaluate_condition("x", "not_in", {"x": 1}) is False


class TestLoadMultipleApprovalRuleFiles:
    """Tests for loading rules from multiple JSON files separated by ';'."""

    def test_multiple_files_aggregated_in_order(self, tmp_path):
        file_a = tmp_path / "rules_a.json"
        file_b = tmp_path / "rules_b.json"
        file_a.write_text(json.dumps([{"match": "cmd_*", "mode": "require", "priority": 1}]), encoding="utf-8")
        file_b.write_text(json.dumps([{"match": "file_*", "mode": "bypass", "priority": 2}]), encoding="utf-8")

        with patch.dict(
            os.environ,
            {"TOPSAILAI_TOOL_APPROVAL_RULES": f"{file_a};{file_b}"},
            clear=True,
        ):
            clear_approval_rules_cache()
            rules = load_approval_rules()

        assert len(rules) == 2
        assert rules[0].match == "cmd_*"
        assert rules[0].mode == "require"
        assert rules[1].match == "file_*"
        assert rules[1].mode == "bypass"

    def test_multiple_files_priority_sorting(self, tmp_path):
        file_a = tmp_path / "rules_a.json"
        file_b = tmp_path / "rules_b.json"
        file_a.write_text(json.dumps([{"match": "cmd_*", "mode": "require", "priority": 10}]), encoding="utf-8")
        file_b.write_text(json.dumps([{"match": "cmd_*", "mode": "bypass", "priority": 1}]), encoding="utf-8")

        with patch.dict(
            os.environ,
            {"TOPSAILAI_TOOL_APPROVAL_RULES": f"{file_a};{file_b}"},
            clear=True,
        ):
            clear_approval_rules_cache()
            rules = load_approval_rules()

        assert len(rules) == 2
        assert rules[0].priority == 1
        assert rules[1].priority == 10

    def test_multiple_files_with_inline_json(self, tmp_path):
        file_a = tmp_path / "rules_a.json"
        file_a.write_text(json.dumps([{"match": "cmd_*", "mode": "require"}]), encoding="utf-8")
        inline = json.dumps([{"match": "file_*", "mode": "bypass"}])

        with patch.dict(
            os.environ,
            {"TOPSAILAI_TOOL_APPROVAL_RULES": f"{file_a};{inline}"},
            clear=True,
        ):
            clear_approval_rules_cache()
            rules = load_approval_rules()

        assert len(rules) == 2

    def test_multiple_files_missing_file_skipped(self, tmp_path, caplog):
        file_a = tmp_path / "rules_a.json"
        file_a.write_text(json.dumps([{"match": "cmd_*", "mode": "require"}]), encoding="utf-8")
        missing = tmp_path / "missing.json"

        with patch.dict(
            os.environ,
            {"TOPSAILAI_TOOL_APPROVAL_RULES": f"{file_a};{missing}"},
            clear=True,
        ):
            clear_approval_rules_cache()
            with caplog.at_level("CRITICAL", logger="topsailai.ai_base.tool_approval.matcher"):
                rules = load_approval_rules()

        assert len(rules) == 1
        assert rules[0].match == "cmd_*"
        assert "Cannot read approval rules file" in caplog.text
        assert str(missing) in caplog.text

    def test_inline_json_with_semicolon_parsed_as_single_source(self):
        inline = json.dumps([{"match": "cmd_*", "mode": "require", "params": [{"param": "cmd", "op": "contains", "value": "a;b"}]}])
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_RULES": inline}, clear=True):
            clear_approval_rules_cache()
            rules = load_approval_rules()
        assert len(rules) == 1
        assert rules[0].params[0]["value"] == "a;b"

    def test_single_file_path_backward_compatible(self, tmp_path):
        rule_file = tmp_path / "rules.json"
        rule_file.write_text(json.dumps([{"match": "cmd_*", "mode": "require"}]), encoding="utf-8")
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_RULES": str(rule_file)}, clear=True):
            clear_approval_rules_cache()
            rules = load_approval_rules()
        assert len(rules) == 1
        assert rules[0].match == "cmd_*"

    def test_inline_json_backward_compatible(self):
        inline = json.dumps([{"match": "*", "mode": "require"}])
        with patch.dict(os.environ, {"TOPSAILAI_TOOL_APPROVAL_RULES": inline}, clear=True):
            clear_approval_rules_cache()
            rules = load_approval_rules()
        assert len(rules) == 1
        assert rules[0].match == "*"

    def test_multiple_files_invalid_json_in_one_file(self, tmp_path, caplog):
        file_a = tmp_path / "rules_a.json"
        file_b = tmp_path / "rules_b.json"
        file_a.write_text(json.dumps([{"match": "cmd_*", "mode": "require"}]), encoding="utf-8")
        file_b.write_text("not valid json", encoding="utf-8")

        with patch.dict(
            os.environ,
            {"TOPSAILAI_TOOL_APPROVAL_RULES": f"{file_a};{file_b}"},
            clear=True,
        ):
            clear_approval_rules_cache()
            with caplog.at_level("CRITICAL", logger="topsailai.ai_base.tool_approval.matcher"):
                rules = load_approval_rules()

        assert len(rules) == 1
        assert rules[0].match == "cmd_*"
        assert "Invalid JSON" in caplog.text

    def test_multiple_files_non_array_in_one_file(self, tmp_path, caplog):
        file_a = tmp_path / "rules_a.json"
        file_b = tmp_path / "rules_b.json"
        file_a.write_text(json.dumps([{"match": "cmd_*", "mode": "require"}]), encoding="utf-8")
        file_b.write_text('{"key": "value"}', encoding="utf-8")

        with patch.dict(
            os.environ,
            {"TOPSAILAI_TOOL_APPROVAL_RULES": f"{file_a};{file_b}"},
            clear=True,
        ):
            clear_approval_rules_cache()
            with caplog.at_level("CRITICAL", logger="topsailai.ai_base.tool_approval.matcher"):
                rules = load_approval_rules()

        assert len(rules) == 1
        assert rules[0].match == "cmd_*"
        assert "must be a JSON array" in caplog.text

    def test_multiple_files_all_invalid_disables_approval(self, tmp_path, caplog):
        file_a = tmp_path / "rules_a.json"
        file_b = tmp_path / "rules_b.json"
        file_a.write_text("not valid", encoding="utf-8")
        file_b.write_text('{"key": "value"}', encoding="utf-8")

        with patch.dict(
            os.environ,
            {"TOPSAILAI_TOOL_APPROVAL_RULES": f"{file_a};{file_b}"},
            clear=True,
        ):
            clear_approval_rules_cache()
            with caplog.at_level("CRITICAL", logger="topsailai.ai_base.tool_approval.matcher"):
                rules = load_approval_rules()

        assert rules == []
        assert "Invalid JSON" in caplog.text
        assert "must be a JSON array" in caplog.text


class TestEvaluateParamsDetail:
    """Tests for the condition-detail evaluator used by approval rendering."""

    def test_empty_params_match_with_no_conditions(self):
        matched, conditions = _evaluate_params_detail({"cmd": "ls"}, [], "and")
        assert matched is True
        assert conditions == []

    def test_all_conditions_reported_without_short_circuit(self):
        params = [
            {"param": "cmd", "op": "contains", "value": "git reset"},
            {"param": "cmd", "op": "contains", "value": "sudo"},
        ]
        matched, conditions = _evaluate_params_detail({"cmd": "git reset"}, params, "and")
        assert matched is False
        assert len(conditions) == 2
        assert conditions[0].matched is True
        assert conditions[1].matched is False
        assert conditions[0].param == "cmd"
        assert conditions[0].op == "contains"
        assert conditions[0].expected == "git reset"
        assert conditions[0].actual == "git reset"

    def test_boolean_parity_with_evaluate_params(self):
        """The detail variant must never change the matching decision."""
        cases = [
            ({"cmd": "git reset"}, [{"param": "cmd", "op": "contains", "value": "git"}], "and"),
            ({"cmd": "git reset"}, [{"param": "cmd", "op": "contains", "value": "sudo"}], "and"),
            ({"cmd": "git reset"}, [{"param": "cmd", "op": "contains", "value": "sudo"}], "or"),
            ({"cmd": "git reset"}, [
                {"param": "cmd", "op": "contains", "value": "sudo"},
                {"param": "cmd", "op": "contains", "value": "git"},
            ], "or"),
            ({"cmd": "git reset"}, [{"param": "missing", "op": "exists"}], "and"),
            ({"cmd": "git reset"}, [{"param": "cmd", "op": "exists"}], "and"),
            ({"cmd": "git reset"}, [{"op": "contains", "value": "git"}], "and"),
            ({"cmd": "git reset"}, [{"param": "cmd", "op": "contains", "value": "git"}], "weird"),
        ]
        for tool_args, params, logic in cases:
            simple = _evaluate_params(tool_args, params, logic)
            detail, _ = _evaluate_params_detail(tool_args, params, logic)
            assert detail == simple, (tool_args, params, logic)

    def test_invalid_condition_is_reported_as_error(self):
        matched, conditions = _evaluate_params_detail({"cmd": "ls"}, ["nope"], "and")
        assert matched is False
        assert len(conditions) == 1
        assert conditions[0].op == "invalid"
        assert conditions[0].error
        assert conditions[0].matched is False

    def test_condition_without_param_is_skipped(self):
        matched, conditions = _evaluate_params_detail(
            {"cmd": "ls"}, [{"op": "contains", "value": "ls"}], "and"
        )
        assert matched is True
        assert conditions == []

    def test_multiline_actual_value_is_preserved(self):
        matched, conditions = _evaluate_params_detail(
            {"content": "a\nsecret\nb"},
            [{"param": "content", "op": "contains", "value": "secret"}],
            "and",
        )
        assert matched is True
        assert conditions[0].actual == "a\nsecret\nb"


class TestMatchApprovalRuleDetail:
    """Tests for the rule matcher variant that also returns condition details."""

    def test_returns_rule_and_conditions(self):
        rules = [
            ApprovalRule(
                "cmd_*",
                "require",
                params=[{"param": "cmd", "op": "contains", "value": "git reset"}],
                name="require git reset",
            )
        ]
        with patch(
            "topsailai.ai_base.tool_approval.matcher.get_approval_rules", return_value=rules
        ):
            result = match_approval_rule_detail(
                "cmd_tool-exec_cmd", {"cmd": "git reset --hard"}
            )
        assert result is not None
        assert result.rule.name == "require git reset"
        assert result.tool_name_matched is True
        assert result.matched is True
        assert len(result.conditions) == 1
        assert result.conditions[0].param == "cmd"

    def test_no_match_returns_none(self):
        rules = [ApprovalRule("file_*", "require", name="only")]
        with patch(
            "topsailai.ai_base.tool_approval.matcher.get_approval_rules", return_value=rules
        ):
            assert match_approval_rule_detail("cmd_tool-exec_cmd", {}) is None

    def test_selection_matches_simple_matcher(self):
        """Both entry points must select the same winning rule."""
        rule_sets = [
            [
                ApprovalRule("cmd_*", "bypass", name="low", priority=10),
                ApprovalRule("cmd_*", "require", name="high", priority=1),
            ],
            [
                ApprovalRule("file_*", "require", name="file"),
                ApprovalRule("*", "require", name="catch-all"),
            ],
        ]
        for rules in rule_sets:
            with patch(
                "topsailai.ai_base.tool_approval.matcher.get_approval_rules",
                return_value=rules,
            ):
                simple = match_approval_rule("cmd_tool-exec_cmd", {"cmd": "ls"})
                detail = match_approval_rule_detail("cmd_tool-exec_cmd", {"cmd": "ls"})
            if simple is None:
                assert detail is None
            else:
                assert detail is not None
                assert detail.rule is simple

    def test_matched_property_mirrors_rule_logic(self):
        rule_and = ApprovalRule(
            "cmd_*",
            "require",
            params=[
                {"param": "cmd", "op": "contains", "value": "git"},
                {"param": "cmd", "op": "contains", "value": "sudo"},
            ],
            logic="and",
            name="and-rule",
        )
        rule_or = ApprovalRule(
            "cmd_*",
            "require",
            params=[
                {"param": "cmd", "op": "contains", "value": "git"},
                {"param": "cmd", "op": "contains", "value": "sudo"},
            ],
            logic="or",
            name="or-rule",
        )
        with patch(
            "topsailai.ai_base.tool_approval.matcher.get_approval_rules",
            return_value=[rule_or],
        ):
            result = match_approval_rule_detail("cmd_tool-exec_cmd", {"cmd": "git reset"})
        assert result is not None
        assert result.matched is True
        assert [condition.matched for condition in result.conditions] == [True, False]

        with patch(
            "topsailai.ai_base.tool_approval.matcher.get_approval_rules",
            return_value=[rule_and],
        ):
            assert match_approval_rule_detail("cmd_tool-exec_cmd", {"cmd": "git reset"}) is None

    def test_no_params_yields_empty_conditions(self):
        rules = [ApprovalRule("cmd_*", "require", name="name-only")]
        with patch(
            "topsailai.ai_base.tool_approval.matcher.get_approval_rules", return_value=rules
        ):
            result = match_approval_rule_detail("cmd_tool-exec_cmd", {"cmd": "ls"})
        assert result is not None
        assert result.conditions == []
        assert result.matched is True
