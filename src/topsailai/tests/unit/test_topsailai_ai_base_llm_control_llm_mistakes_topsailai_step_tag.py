'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-30
Purpose: Unit tests for the topsailai step-tag mistake fixer.
'''

import pytest

from topsailai.ai_base.llm_control.llm_mistakes.topsailai_step_tag import (
    fix_topsailai_step_tag,
)
from topsailai.ai_base.llm_control.message import format_response


FIXTURE_CONTENT = """<topsailai.thought>
I need to read both files. Let me use cmd_tool to cat them.
</topsailai.thought>

<topsailai.action>
{
  "tool_call": "cmd_tool-exec_cmd",
  "tool_args": {
    "cmd": "cat -n /TopsailAI/src/topsailai/workspace/session_meta.py",
    "no_need_stderr": 1
  }
}
</topsailai.action>
"""


def test_fix_topsailai_step_tag_fixture():
    result = fix_topsailai_step_tag(FIXTURE_CONTENT)
    assert result is not None
    assert "<topsailai.thought>" not in result
    assert "</topsailai.thought>" not in result
    assert "<topsailai.action>" not in result
    assert "</topsailai.action>" not in result
    assert "topsailai.thought" in result
    assert "topsailai.action" in result


def test_fix_topsailai_step_tag_opening_with_newline():
    result = fix_topsailai_step_tag("<topsailai.thought>\nhello")
    assert result == "topsailai.thought\nhello"


def test_fix_topsailai_step_tag_opening_with_leading_newline():
    result = fix_topsailai_step_tag("\n<topsailai.thought>hello")
    assert result == "\ntopsailai.thoughthello"


def test_fix_topsailai_step_tag_closing_on_own_line():
    result = fix_topsailai_step_tag("hello\n</topsailai.thought>\nworld")
    assert result == "hello\nworld"


def test_fix_topsailai_step_tag_closing_inline():
    result = fix_topsailai_step_tag("hello</topsailai.thought>world")
    assert result == "helloworld"


def test_fix_topsailai_step_tag_multiple_tags():
    result = fix_topsailai_step_tag(
        "<topsailai.thought>think\n</topsailai.thought>\n<topsailai.action>act\n</topsailai.action>"
    )
    assert result == "topsailai.thoughtthink\ntopsailai.actionact"


def test_fix_topsailai_step_tag_no_change_when_canonical():
    text = "topsailai.thought\nhello\ntopsailai.action\n{}"
    assert fix_topsailai_step_tag(text) is None


def test_fix_topsailai_step_tag_non_string_returns_none():
    assert fix_topsailai_step_tag([{"step_name": "thought"}]) is None
    assert fix_topsailai_step_tag({"step_name": "thought"}) is None
    assert fix_topsailai_step_tag(None) is None


def test_fix_topsailai_step_tag_format_response_integration():
    result = format_response(FIXTURE_CONTENT)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0].get("step_name") == "thought"
    assert "read both files" in result[0].get("raw_text", "")
    assert result[1].get("step_name") == "action"
