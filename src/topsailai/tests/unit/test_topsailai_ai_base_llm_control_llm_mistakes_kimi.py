"""
Unit tests for topsailai.ai_base.llm_control.llm_mistakes.kimi
"""

import os
import pytest

from topsailai.ai_base.llm_control.llm_mistakes.kimi import (
    _get_current_model_name,
    _is_kimi_model,
    _strip_trailing_garbage,
    fix_kimi_trailing_garbage,
    MISTAKES,
)


GARBAGE = "<|tool_call_end|><|tool_calls_section_end|>"


class TestIsKimiModel:
    """Tests for _is_kimi_model function."""

    def test_kimi_model(self):
        assert _is_kimi_model("Kimi-K2.5") is True

    def test_kimi_model_lowercase(self):
        assert _is_kimi_model("kimi-k2.5") is True

    def test_kimi_model_prefix(self):
        assert _is_kimi_model("kimi-v1") is True

    def test_non_kimi_model(self):
        assert _is_kimi_model("gpt-4") is False

    def test_empty_string(self):
        assert _is_kimi_model("") is False

    def test_none(self):
        assert _is_kimi_model(None) is False


class TestStripTrailingGarbage:
    """Tests for _strip_trailing_garbage function."""

    def test_backtick_space_garbage(self):
        """Strip trailing garbage with backtick and space."""
        text = '{"tool_call": "xxx"} ` ' + GARBAGE
        result = _strip_trailing_garbage(text)
        assert result == '{"tool_call": "xxx"}'

    def test_garbage_without_backtick(self):
        """Strip trailing garbage without backtick."""
        text = '{"tool_call": "xxx"} ' + GARBAGE
        result = _strip_trailing_garbage(text)
        assert result == '{"tool_call": "xxx"}'

    def test_garbage_with_newlines(self):
        """Strip trailing garbage with newlines."""
        text = '{"tool_call": "xxx"}\n` ' + GARBAGE + '\n'
        result = _strip_trailing_garbage(text)
        assert result == '{"tool_call": "xxx"}'

    def test_no_garbage(self):
        """No garbage present, text unchanged."""
        text = '{"tool_call": "xxx"}'
        result = _strip_trailing_garbage(text)
        assert result == text

    def test_empty_string(self):
        """Empty string returns empty string."""
        result = _strip_trailing_garbage("")
        assert result == ""

    def test_only_garbage(self):
        """Only garbage present, returns empty string."""
        text = '` ' + GARBAGE
        result = _strip_trailing_garbage(text)
        assert result == ""

    def test_idempotent(self):
        """Running twice yields same result."""
        text = '{"tool_call": "xxx"} ` ' + GARBAGE
        result1 = _strip_trailing_garbage(text)
        result2 = _strip_trailing_garbage(result1)
        assert result1 == result2


class TestGetCurrentModelName:
    """Tests for _get_current_model_name function."""

    def test_fallback_to_env_var(self, monkeypatch):
        """Fallback to OPENAI_MODEL when no agent context."""
        monkeypatch.setenv("OPENAI_MODEL", "Kimi-K2.5")
        result = _get_current_model_name()
        assert result == "Kimi-K2.5"

    def test_env_var_empty(self, monkeypatch):
        """Returns empty string when no agent and no env var."""
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        result = _get_current_model_name()
        assert result == ""

    def test_rsp_obj_model(self):
        """Use rsp_obj.model as secondary signal."""
        class FakeRsp:
            model = "Kimi-K2.5"
        result = _get_current_model_name(rsp_obj=FakeRsp())
        assert result == "Kimi-K2.5"


class TestFixKimiTrailingGarbage:
    """Tests for fix_kimi_trailing_garbage function."""

    def test_non_kimi_model(self, monkeypatch):
        """Non-Kimi model returns None."""
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4")
        message = [{"step_name": "action", "raw_text": '{"tool_call": "xxx"} ` ' + GARBAGE}]
        result = fix_kimi_trailing_garbage(message)
        assert result is None

    def test_kimi_model_strips_garbage(self, monkeypatch):
        """Kimi model strips trailing garbage."""
        monkeypatch.setenv("OPENAI_MODEL", "Kimi-K2.5")
        message = [{"step_name": "action", "raw_text": '{"tool_call": "xxx"} ` ' + GARBAGE}]
        result = fix_kimi_trailing_garbage(message)
        assert result is not None
        assert result[0]["raw_text"] == '{"tool_call": "xxx"}'

    def test_non_string_raw_text(self, monkeypatch):
        """Non-string raw_text is skipped."""
        monkeypatch.setenv("OPENAI_MODEL", "Kimi-K2.5")
        message = [{"step_name": "action", "raw_text": {"tool_call": "xxx"}}]
        result = fix_kimi_trailing_garbage(message)
        assert result is None

    def test_non_action_item(self, monkeypatch):
        """Non-action items are skipped."""
        monkeypatch.setenv("OPENAI_MODEL", "Kimi-K2.5")
        message = [{"step_name": "thought", "raw_text": 'hello ` ' + GARBAGE}]
        result = fix_kimi_trailing_garbage(message)
        assert result is None

    def test_no_garbage_in_action(self, monkeypatch):
        """Action without garbage returns None."""
        monkeypatch.setenv("OPENAI_MODEL", "Kimi-K2.5")
        message = [{"step_name": "action", "raw_text": '{"tool_call": "xxx"}'}]
        result = fix_kimi_trailing_garbage(message)
        assert result is None

    def test_non_list_message(self, monkeypatch):
        """Non-list message returns None."""
        monkeypatch.setenv("OPENAI_MODEL", "Kimi-K2.5")
        result = fix_kimi_trailing_garbage("hello")
        assert result is None

    def test_idempotent(self, monkeypatch):
        """Running twice yields same result."""
        monkeypatch.setenv("OPENAI_MODEL", "Kimi-K2.5")
        message = [{"step_name": "action", "raw_text": '{"tool_call": "xxx"} ` ' + GARBAGE}]
        result1 = fix_kimi_trailing_garbage(message)
        assert result1 is not None
        result2 = fix_kimi_trailing_garbage(result1)
        assert result2 is None
        assert result1[0]["raw_text"] == '{"tool_call": "xxx"}'

    def test_empty_after_strip(self, monkeypatch):
        """Only garbage present, raw_text becomes empty."""
        monkeypatch.setenv("OPENAI_MODEL", "Kimi-K2.5")
        message = [{"step_name": "action", "raw_text": '` ' + GARBAGE}]
        result = fix_kimi_trailing_garbage(message)
        assert result is not None
        assert result[0]["raw_text"] == ""

    def test_multiple_items_some_cleaned(self, monkeypatch):
        """Multiple items, only action items with garbage are cleaned."""
        monkeypatch.setenv("OPENAI_MODEL", "Kimi-K2.5")
        message = [
            {"step_name": "thought", "raw_text": 'hello ` ' + GARBAGE},
            {"step_name": "action", "raw_text": '{"tool_call": "xxx"} ` ' + GARBAGE},
            {"step_name": "action", "raw_text": '{"tool_call": "yyy"}'},
        ]
        result = fix_kimi_trailing_garbage(message)
        assert result is not None
        # thought item unchanged
        assert result[0]["raw_text"] == 'hello ` ' + GARBAGE
        # action item with garbage cleaned
        assert result[1]["raw_text"] == '{"tool_call": "xxx"}'
        # action item without garbage unchanged
        assert result[2]["raw_text"] == '{"tool_call": "yyy"}'


class TestMistakesDict:
    """Tests for MISTAKES dictionary."""

    def test_contains_fix_kimi_trailing_garbage(self):
        assert "fix_kimi_trailing_garbage" in MISTAKES
        assert MISTAKES["fix_kimi_trailing_garbage"] == fix_kimi_trailing_garbage

    def test_mistakes_length(self):
        assert len(MISTAKES) == 1
