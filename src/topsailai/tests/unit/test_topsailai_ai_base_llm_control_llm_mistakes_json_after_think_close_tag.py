'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-28
Purpose: Unit tests for json_after_think_close_tag mistake fixer.
'''

import os

import pytest

from topsailai.ai_base.llm_control.llm_mistakes.json_after_think_close_tag import (
    THINKING_CLOSE_TAGS,
    _parse_action_json,
    _split_at_thinking_close,
    fix_json_after_thinking_close,
)
from topsailai.ai_base.llm_control.message import format_response


FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "mistakes",
    "response",
    "json-after-think-close-tag.txt",
)


def _load_fixture():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def test_split_at_thinking_close_finds_xml_tag():
    text = "Hello\n</thinking>\n{\"tool_call\": \"x\", \"tool_args\": {}}"
    result = _split_at_thinking_close(text)
    assert result is not None
    assert result[0] == "Hello"
    assert result[1] == '{"tool_call": "x", "tool_args": {}}'


def test_split_at_thinking_close_finds_kimi_tag():
    from topsailai.ai_base.llm_control.llm_mistakes.kimi import THINKING_CLOSE

    text = f"Hello\n{THINKING_CLOSE}\n{{\"tool_call\": \"x\", \"tool_args\": {{}}}}"
    result = _split_at_thinking_close(text)
    assert result is not None
    assert result[0] == "Hello"
    assert result[1] == '{"tool_call": "x", "tool_args": {}}'


def test_split_at_thinking_close_prefers_first_tag():
    from topsailai.ai_base.llm_control.llm_mistakes.kimi import THINKING_CLOSE

    text = f"A\n</thinking>\nB\n{THINKING_CLOSE}\nC"
    result = _split_at_thinking_close(text)
    assert result == ("A", f"B\n{THINKING_CLOSE}\nC")


def test_split_at_thinking_close_returns_none_without_tag():
    assert _split_at_thinking_close("just some text") is None


def test_split_at_thinking_close_returns_none_for_non_string():
    assert _split_at_thinking_close(["not", "a", "string"]) is None


def test_split_at_thinking_close_returns_none_when_no_trailing_content():
    assert _split_at_thinking_close("Hello\n</thinking>") is None


def test_parse_action_json_valid():
    text = '{"tool_call": "cmd_tool-exec_cmd", "tool_args": {"cmd": ["ls"]}}'
    result = _parse_action_json(text)
    assert result == {
        "tool_call": "cmd_tool-exec_cmd",
        "tool_args": {"cmd": ["ls"]},
    }


def test_parse_action_json_missing_tool_call():
    assert _parse_action_json('{"tool_args": {}}') is None


def test_parse_action_json_missing_tool_args():
    assert _parse_action_json('{"tool_call": "x"}') is None


def test_parse_action_json_invalid_json():
    assert _parse_action_json("not json") is None


def test_fix_json_after_thinking_close_returns_thought_and_action():
    text = "Hello\n</thinking>\n{\"tool_call\": \"cmd_tool-exec_cmd\", \"tool_args\": {\"cmd\": [\"ls\", \"-la\", \"/tmp\"]}}"
    result = fix_json_after_thinking_close(text)
    assert result == [
        {"step_name": "thought", "raw_text": "Hello"},
        {
            "step_name": "action",
            "tool_call": "cmd_tool-exec_cmd",
            "tool_args": {"cmd": ["ls", "-la", "/tmp"]},
        },
    ]


def test_fix_json_after_thinking_close_returns_action_only_without_leading_text():
    text = '</thinking>\n{"tool_call": "x", "tool_args": {}}'
    result = fix_json_after_thinking_close(text)
    assert result == [
        {"step_name": "action", "tool_call": "x", "tool_args": {}},
    ]


def test_fix_json_after_thinking_close_returns_none_for_non_matching():
    assert fix_json_after_thinking_close("just text") is None
    assert fix_json_after_thinking_close('{"tool_call": "x", "tool_args": {}}') is None


def test_fix_json_after_thinking_close_returns_none_for_list_input():
    assert fix_json_after_thinking_close([{"step_name": "action"}]) is None


def test_format_response_fixture_parses_correctly():
    content = _load_fixture()
    result = format_response(content)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0] == {"step_name": "thought", "raw_text": "Hello"}
    assert result[1]["step_name"] == "action"
    assert result[1]["tool_call"] == "cmd_tool-exec_cmd"
    assert result[1]["tool_args"] == {"cmd": ["ls", "-la", "/tmp"]}


def test_thinking_close_tags_include_expected_markers():
    from topsailai.ai_base.llm_control.llm_mistakes.kimi import THINKING_CLOSE

    assert "</thinking>" in THINKING_CLOSE_TAGS
    assert THINKING_CLOSE in THINKING_CLOSE_TAGS
