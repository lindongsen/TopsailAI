"""Unit tests for provider-neutral LLM retry interaction policy."""

import pytest

from topsailai.ai_base.llm_control.llm_retry import (
    LLMRetryInteractionPolicy,
    read_retry_exhaustion_action,
)


def test_policy_prompts_only_with_interactivity_and_input():
    """Prompt availability requires both explicit interactivity and input."""
    def input_func(prompt):
        """Return the supplied prompt for policy testing."""
        return prompt

    assert LLMRetryInteractionPolicy().can_prompt() is False
    assert LLMRetryInteractionPolicy(input_func=input_func).can_prompt() is False
    assert LLMRetryInteractionPolicy(interactive_enabled=True).can_prompt() is False
    assert LLMRetryInteractionPolicy(
        interactive_enabled=True,
        input_func=input_func,
    ).can_prompt() is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "max_manual_retry_cycles",
            -1,
            "max_manual_retry_cycles must be a non-negative integer",
        ),
        (
            "max_manual_retry_cycles",
            True,
            "max_manual_retry_cycles must be a non-negative integer",
        ),
        (
            "max_invalid_choices",
            0,
            "max_invalid_choices must be a positive integer",
        ),
        (
            "max_invalid_choices",
            False,
            "max_invalid_choices must be a positive integer",
        ),
    ],
)
def test_policy_rejects_invalid_limits(field, value, message):
    """Retry-policy bounds retain their existing validation semantics."""
    with pytest.raises(ValueError, match=message):
        LLMRetryInteractionPolicy(**{field: value})


def _policy(input_func=None, *, allow_back_to_chat=False, max_invalid_choices=3):
    """Build a minimal interactive policy for exhaustion-action tests."""
    return LLMRetryInteractionPolicy(
        interactive_enabled=True,
        allow_back_to_chat=allow_back_to_chat,
        input_func=input_func,
        max_invalid_choices=max_invalid_choices,
    )


def test_read_retry_exhaustion_action_retry():
    """The retry menu choice maps to the retry action."""
    input_func = lambda _prompt: "1"
    assert read_retry_exhaustion_action(
        _policy(input_func), allow_retry=True, warning_func=lambda _m: None
    ) == "retry"


def test_read_retry_exhaustion_action_back():
    """The back choice maps to the back action when allowed."""
    input_func = lambda _prompt: "2"
    assert read_retry_exhaustion_action(
        _policy(input_func, allow_back_to_chat=True),
        allow_retry=True,
        warning_func=lambda _m: None,
    ) == "back"


def test_read_retry_exhaustion_action_exit():
    """The exit choice maps to the exit action."""
    input_func = lambda _prompt: "2"
    assert read_retry_exhaustion_action(
        _policy(input_func), allow_retry=True, warning_func=lambda _m: None
    ) == "exit"


def test_read_retry_exhaustion_action_retry_disabled_renumbers():
    """When retry is disabled, back/exit are renumbered and retry is unavailable."""
    input_func = lambda _prompt: "1"
    policy = _policy(input_func, allow_back_to_chat=True)
    assert read_retry_exhaustion_action(
        policy, allow_retry=False, warning_func=lambda _m: None
    ) == "back"


def test_read_retry_exhaustion_action_invalid_choices_warn_and_exit():
    """Invalid choices invoke the warning and fail closed after the bound."""
    warnings = []
    input_func = lambda _prompt: "invalid"
    result = read_retry_exhaustion_action(
        _policy(input_func, max_invalid_choices=3),
        allow_retry=True,
        warning_func=warnings.append,
    )
    assert result == "exit"
    assert len(warnings) == 3


def test_read_retry_exhaustion_action_eof_fails_closed():
    """EOFError at the menu maps to exit without warning."""
    def input_func(_prompt):
        raise EOFError("stdin closed")

    assert read_retry_exhaustion_action(
        _policy(input_func), allow_retry=True, warning_func=lambda _m: None
    ) == "exit"


def test_read_retry_exhaustion_action_keyboard_interrupt_fails_closed():
    """KeyboardInterrupt at the menu maps to exit without warning."""
    def input_func(_prompt):
        raise KeyboardInterrupt("ctrl-c")

    assert read_retry_exhaustion_action(
        _policy(input_func), allow_retry=True, warning_func=lambda _m: None
    ) == "exit"
