"""Tests for request-local null-response Hook recovery."""

import pytest

from topsailai.ai_base.llm_control.null_response_recovery import (
    NullResponseRecoveryState,
    _active_null_response_recovery,
    observe_attempt_error,
    track_null_response_recovery,
)
from topsailai.hooks.points.aibase.error_llm_chat_attempt.modules import (
    continue_after_null_responses,
)


@pytest.fixture
def active_state():
    """Provide one bound request state and restore the ContextVar afterwards."""
    messages = [{"role": "user", "content": "task"}]
    state = NullResponseRecoveryState(messages=messages, operation_id="op-1")
    token = _active_null_response_recovery.set(state)
    try:
        yield state
    finally:
        _active_null_response_recovery.reset(token)


def test_hook_module_injects_continue_when_streak_reaches_three(active_state):
    """The Hook module owns both threshold evaluation and message injection."""
    payload = {"operation_id": "op-1", "error_category": "LLMNullResponseError"}

    assert continue_after_null_responses.main(**payload) is False
    assert continue_after_null_responses.main(**payload) is False
    assert active_state.messages == [{"role": "user", "content": "task"}]
    assert continue_after_null_responses.main(**payload) is True
    assert active_state.messages[-1] == {"role": "user", "content": "continue"}


def test_threshold_injects_only_once_for_one_continuous_streak(active_state):
    """Failures beyond the threshold do not append duplicate guidance."""
    for _ in range(7):
        observe_attempt_error("op-1", "LLMNullResponseError")

    assert active_state.messages.count(
        {"role": "user", "content": "continue"}
    ) == 1


def test_different_error_resets_streak(active_state):
    """Only three consecutive null responses trigger recovery."""
    observe_attempt_error("op-1", "LLMNullResponseError")
    observe_attempt_error("op-1", "LLMNullResponseError")
    observe_attempt_error("op-1", "LLMProviderTimeoutError")
    assert observe_attempt_error("op-1", "LLMNullResponseError") is False
    assert observe_attempt_error("op-1", "LLMNullResponseError") is False
    assert observe_attempt_error("op-1", "LLMNullResponseError") is True


def test_different_operation_cannot_mutate_active_request(active_state):
    """A stale or unrelated Hook event cannot inject into this request."""
    for _ in range(3):
        assert observe_attempt_error("op-2", "LLMNullResponseError") is False

    assert active_state.consecutive_failures == 0
    assert len(active_state.messages) == 1


def test_tracking_decorator_clears_state_after_request():
    """Request-local mutable state never leaks after the chat exits."""
    seen = []

    class Subject:
        @track_null_response_recovery
        def chat(self, messages):
            from topsailai.ai_base.llm_control.null_response_recovery import (
                current_null_response_recovery,
            )
            seen.append(current_null_response_recovery())

    messages = [{"role": "user", "content": "task"}]
    messages_with_guidance = []

    class InjectingSubject:
        @track_null_response_recovery
        def chat(self, messages):
            state = _active_null_response_recovery.get()
            state.operation_id = "op-1"
            for _ in range(3):
                observe_attempt_error("op-1", "LLMNullResponseError")
            messages_with_guidance.extend(messages)

    Subject().chat([])
    InjectingSubject().chat(messages)

    assert seen[0] is not None
    assert messages_with_guidance[-1] == {"role": "user", "content": "continue"}
    assert messages == [{"role": "user", "content": "task"}]
    from topsailai.ai_base.llm_control.null_response_recovery import (
        current_null_response_recovery,
    )
    assert current_null_response_recovery() is None
