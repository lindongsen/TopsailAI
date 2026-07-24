"""Unit tests for the action-with-final-answer LLM mistake fixer.

Author: DawsonLin
"""

from topsailai.ai_base.llm_control.llm_mistakes.action_with_final_answer import (
    fix_action_with_final_answer,
)


def test_no_action_returns_none():
    """Do not change a final answer when no action exists."""
    message = [{"step_name": "final_answer", "raw_text": "done"}]

    assert fix_action_with_final_answer(message) is None


def test_action_only_returns_none():
    """Do not change an action-only response."""
    message = [{"step_name": "action", "raw_text": "call"}]

    assert fix_action_with_final_answer(message) is None


def test_final_becomes_thought_without_existing_thought():
    """Convert a final answer to thought when an action is also present."""
    message = [
        {"step_name": "action", "raw_text": "call"},
        {"step_name": "final_answer", "raw_text": "premature"},
    ]

    result = fix_action_with_final_answer(message)

    assert result == [
        {"step_name": "action", "raw_text": "call"},
        {"step_name": "thought", "raw_text": "premature"},
    ]


def test_final_appends_to_first_existing_thought():
    """Append final text to the first thought with a newline separator."""
    message = [
        {"step_name": "thought", "raw_text": "reason"},
        {"step_name": "action", "raw_text": "call"},
        {"step_name": "final_answer", "raw_text": "premature"},
        {"step_name": "thought", "raw_text": "other"},
    ]

    result = fix_action_with_final_answer(message)

    assert result == [
        {"step_name": "thought", "raw_text": "reason\npremature"},
        {"step_name": "action", "raw_text": "call"},
        {"step_name": "thought", "raw_text": "other"},
    ]


def test_multiple_final_steps_append_in_order():
    """Append every final step to the first thought in original order."""
    message = [
        {"step_name": "thought", "raw_text": "reason"},
        {"step_name": "final", "raw_text": "first"},
        {"step_name": "action", "raw_text": "call"},
        {"step_name": "final_answer", "raw_text": "second"},
    ]

    result = fix_action_with_final_answer(message)

    assert result == [
        {"step_name": "thought", "raw_text": "reason\nfirst\nsecond"},
        {"step_name": "action", "raw_text": "call"},
    ]


def test_final_before_action_becomes_thought():
    """Prevent an early final step from terminating before a later action."""
    message = [
        {"step_name": "final_answer", "raw_text": "premature"},
        {"step_name": "action", "raw_text": "call"},
    ]

    result = fix_action_with_final_answer(message)

    assert result == [
        {"step_name": "thought", "raw_text": "premature"},
        {"step_name": "action", "raw_text": "call"},
    ]


def test_missing_and_empty_raw_text_are_handled():
    """Treat missing or empty raw text as empty content while merging."""
    message = [
        {"step_name": "thought"},
        {"step_name": "action", "raw_text": "call"},
        {"step_name": "final_answer"},
        {"step_name": "final_response", "raw_text": ""},
    ]

    result = fix_action_with_final_answer(message)

    assert result == [
        {"step_name": "thought", "raw_text": "\n\n"},
        {"step_name": "action", "raw_text": "call"},
    ]
