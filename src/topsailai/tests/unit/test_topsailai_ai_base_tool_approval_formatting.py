"""
Unit tests for the human-readable tool approval rendering module.
"""

import os
from unittest.mock import patch

import pytest

from topsailai.ai_base.tool_approval.formatting import (
    DEFAULT_DISPLAY_MAX_LINES,
    DEFAULT_DISPLAY_MAX_VALUE_CHARS,
    format_approval_request,
    format_matched,
    format_tool_args,
    get_display_max_lines,
    get_display_max_value_chars,
)
from topsailai.ai_base.tool_approval.matcher import ApprovalRule


class TestDisplayLimits:
    """Tests for the environment-driven rendering size guards."""

    def test_defaults_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            assert get_display_max_lines() == DEFAULT_DISPLAY_MAX_LINES
            assert get_display_max_value_chars() == DEFAULT_DISPLAY_MAX_VALUE_CHARS

    def test_valid_values_are_used(self):
        env = {
            "TOPSAILAI_TOOL_APPROVAL_DISPLAY_MAX_LINES": "7",
            "TOPSAILAI_TOOL_APPROVAL_DISPLAY_MAX_VALUE_CHARS": "64",
        }
        with patch.dict(os.environ, env, clear=True):
            assert get_display_max_lines() == 7
            assert get_display_max_value_chars() == 64

    @pytest.mark.parametrize("raw", ["0", "-3", "abc", ""])
    def test_invalid_values_fall_back_to_default(self, raw):
        env = {
            "TOPSAILAI_TOOL_APPROVAL_DISPLAY_MAX_LINES": raw,
            "TOPSAILAI_TOOL_APPROVAL_DISPLAY_MAX_VALUE_CHARS": raw,
        }
        with patch.dict(os.environ, env, clear=True):
            assert get_display_max_lines() == DEFAULT_DISPLAY_MAX_LINES
            assert get_display_max_value_chars() == DEFAULT_DISPLAY_MAX_VALUE_CHARS


class TestFormatToolArgs:
    """Tests for readable tool argument rendering."""

    def test_empty_args_render_as_empty_string(self):
        assert format_tool_args({}) == ""
        assert format_tool_args(None) == ""

    def test_scalars_render_inline(self):
        text = format_tool_args({"cmd": "ls -l", "timeout": 30, "force": True, "note": None})
        assert text == (
            "cmd: ls -l\n"
            "timeout: 30\n"
            "force: true\n"
            "note: null"
        )

    def test_nested_containers_are_indented(self):
        text = format_tool_args(
            {"opts": {"nested": {"deep": [1, 2]}, "flag": False}},
            max_lines=40,
            max_value_chars=200,
        )
        assert text == (
            "opts:\n"
            "  nested:\n"
            "    deep:\n"
            "      - 1\n"
            "      - 2\n"
            "  flag: false"
        )

    def test_empty_containers_render_as_placeholders(self):
        text = format_tool_args({"a": {}, "b": []})
        assert text == "a: {}\nb: []"

    def test_multiline_string_keeps_real_line_breaks(self):
        """The core readability requirement: no escaped \n sequences."""
        text = format_tool_args({"content": "line one\nline two\nline three"})
        assert text == (
            "content:\n"
            "  | line one\n"
            "  | line two\n"
            "  | line three"
        )
        assert "\\n" not in text

    def test_multiline_string_with_trailing_newline_is_compact(self):
        text = format_tool_args({"content": "a\nb\n"})
        assert text == "content:\n  | a\n  | b"

    def test_crlf_string_is_normalized_to_block(self):
        text = format_tool_args({"content": "a\r\nb"})
        assert text == "content:\n  | a\n  | b"

    def test_multiline_string_inside_list_is_block(self):
        text = format_tool_args({"files": ["a.py", "b\nc"]})
        assert text == (
            "files:\n"
            "  - a.py\n"
            "  -\n"
            "    | b\n"
            "    | c"
        )

    def test_multiline_string_in_single_key_dict_is_block(self):
        text = format_tool_args({"patches": [{"diff": "-a\n+b"}]})
        assert text == (
            "patches:\n"
            "  - diff:\n"
            "      | -a\n"
            "      | +b"
        )

    def test_line_cap_annotates_omitted_lines(self):
        value = "\n".join(f"line {index}" for index in range(10))
        text = format_tool_args({"content": value}, max_lines=3)
        lines = text.split("\n")
        assert lines[0] == "content:"
        assert lines[1] == "  | line 0"
        assert lines[3] == "  | line 2"
        assert lines[4] == "  ... (+7 lines)"

    def test_char_cap_annotates_omitted_chars(self):
        text = format_tool_args({"cmd": "x" * 50}, max_value_chars=10)
        assert text == "cmd: xxxxxxxxxx... (+40 chars)"

    def test_char_cap_applies_per_block_line(self):
        text = format_tool_args({"c": "aaaa\nbbbbbb"}, max_value_chars=3)
        assert text == (
            "c:\n"
            "  | aaa... (+1 chars)\n"
            "  | bbb... (+3 chars)"
        )

    def test_huge_key_is_also_bounded(self):
        text = format_tool_args({"k" * 10: "v"}, max_value_chars=3)
        assert text == "kkk... (+7 chars): v"

    def test_non_dict_args_are_rendered_defensively(self):
        assert format_tool_args("plain") == "| plain"
        assert format_tool_args(["a", "b"]) == "- a\n- b"

    def test_non_string_scalars_use_str(self):
        text = format_tool_args({"value": 1.5})
        assert text == "value: 1.5"


class TestFormatMatched:
    """Tests for the minimal matched-rule focus block."""

    @staticmethod
    def _rule(**kwargs):
        params = {
            "match": "cmd_*",
            "mode": "require",
            "name": "require dangerous cmd",
        }
        params.update(kwargs)
        return ApprovalRule(**params)

    def test_no_rule_renders_empty(self):
        """Without a rule the caller omits the block entirely."""
        assert format_matched(None) == ""

    def test_only_rule_and_pattern_are_rendered(self):
        text = format_matched(self._rule())
        # The block is intentionally exactly two lines: no outer section title,
        # no "Matched"/"Match" prefix, no "(mode: ...)" suffix and no condition
        # details, because the full arguments are shown separately.
        assert text.splitlines() == [
            "Rule: require dangerous cmd",
            "Pattern: cmd_*",
        ]

    def test_no_verbose_sections(self):
        text = format_matched(self._rule())
        assert "mode" not in text
        assert "Trigger" not in text
        assert "Why approval is needed" not in text

    def test_unnamed_rule(self):
        text = format_matched(self._rule(name=None))
        assert "Rule: <unnamed>" in text

    def test_dict_shaped_rule_is_rendered(self):
        """Rules originate from JSON, so a plain dict must render like ApprovalRule."""
        rule = {
            "name": "require dangerous",
            "match": "cmd_*",
            "mode": "require",
            "logic": "or",
        }
        assert format_matched(rule).splitlines() == [
            "Rule: require dangerous",
            "Pattern: cmd_*",
        ]

    def test_dict_shaped_rule_without_name(self):
        text = format_matched({"match": "file_tool-write_file", "mode": "require"})
        assert "Rule: <unnamed>" in text
        assert "Pattern: file_tool-write_file" in text

    def test_conditions_argument_is_not_needed(self):
        """The signature takes only the rule; conditions are no longer rendered."""
        import inspect

        assert list(inspect.signature(format_matched).parameters) == ["rule"]


class TestFormatApprovalRequest:
    """Tests for the assembled approval prompt."""

    class _Instance:
        """Minimal stand-in for ToolApprovalInstance."""

        def __init__(self, **kwargs):
            self.id = kwargs.get("id", "abc123")
            self.tool_name = kwargs.get("tool_name", "cmd_tool-exec_cmd")
            self.tool_args = kwargs.get("tool_args", {})
            self.timeout = kwargs.get("timeout", 30)
            self.policy = kwargs.get("policy", "deny")
            self.rule_name = kwargs.get("rule_name", None)
            self.matched_rule = kwargs.get("matched_rule", None)
            self.matched_conditions = kwargs.get("matched_conditions", None)

    def test_header_and_sections(self):
        text = format_approval_request(self._Instance())
        assert text.startswith("[APPROVAL REQUEST] abc123")
        assert "Tool   : cmd_tool-exec_cmd" in text
        assert "Timeout: 30s" in text
        assert "Policy : deny" in text
        assert "Args:" in text
        assert "(none)" in text
        assert "Type 'approve'(yes) or 'deny'(no)" in text

    def test_matched_rule_block_is_shown(self):
        rule = ApprovalRule(
            match="cmd_*",
            mode="require",
            params=[{"param": "cmd", "op": "contains", "value": "danger flag"}],
            name="require dangerous cmd",
        )
        instance = self._Instance(
            matched_rule=rule,
            tool_args={"cmd": "echo dangerous flag"},
        )
        text = format_approval_request(instance)
        # The focus block is exactly the two minimal lines, indented once.
        assert "  Rule: require dangerous cmd\n  Pattern: cmd_*" in text
        # No verbose sections remain.
        assert "Why approval is needed" not in text
        assert "Trigger" not in text
        # The rule name must not be duplicated as a top-level Rule line.
        assert "  Rule   :" not in text

    def test_rule_name_fallback_when_no_rule_object(self):
        instance = self._Instance(rule_name="catch-all approval")
        text = format_approval_request(instance)
        assert "Rule   : catch-all approval" in text

    def test_args_are_indented_and_multiline_preserved(self):
        instance = self._Instance(tool_args={"content": "one\ntwo"})
        text = format_approval_request(instance)
        assert "    content:\n      | one\n      | two" in text
        assert "\\n" not in text

    def test_missing_attributes_are_tolerated(self):
        class Bare:
            pass

        text = format_approval_request(Bare())
        assert "[APPROVAL REQUEST] <unknown>" in text
        assert "Tool   : <unknown>" in text
        # Without a matched rule the focus block is omitted entirely.
        assert "Rule:" not in text
