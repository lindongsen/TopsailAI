"""Tests for request-local null-response Hook recovery."""

from unittest.mock import patch

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
    """A successful injection emits one warning and later retries stay quiet."""
    payload = {"operation_id": "op-1", "error_category": "LLMNullResponseError"}

    with patch(
        "topsailai.ai_base.llm_control.null_response_recovery.print_warning"
    ) as warning:
        assert continue_after_null_responses.main(**payload) is False
        assert continue_after_null_responses.main(**payload) is False
        warning.assert_not_called()
        assert active_state.messages == [{"role": "user", "content": "task"}]
        assert continue_after_null_responses.main(**payload) is True
        assert continue_after_null_responses.main(**payload) is False

    warning.assert_called_once_with(
        "Injected a temporary LLM recovery message after "
        "3 consecutive null responses."
    )
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


@pytest.mark.parametrize("value", [None, "", "   "])
def test_default_recovery_message_is_continue(monkeypatch, value):
    """Unset and blank message configuration both use ``continue``."""
    key = "TOPSAILAI_LLM_NULL_RESPONSE_RECOVERY_MESSAGE"
    if value is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, value)

    messages = [{"role": "user", "content": "task"}]

    class Subject:
        @track_null_response_recovery
        def chat(self, messages):
            state = _active_null_response_recovery.get()
            state.operation_id = "op-1"
            for _ in range(3):
                observe_attempt_error("op-1", "LLMNullResponseError")
            return list(messages)

    result = Subject().chat(messages)

    assert result[-1] == {"role": "user", "content": "continue"}
    assert messages == [{"role": "user", "content": "task"}]


def test_configured_recovery_message_is_injected(monkeypatch):
    """A nonblank configured message replaces the default guidance."""
    monkeypatch.setenv("TOPSAILAI_LLM_NULL_RESPONSE_RECOVERY_MESSAGE", "please continue")
    messages = [{"role": "user", "content": "task"}]

    class Subject:
        @track_null_response_recovery
        def chat(self, messages):
            state = _active_null_response_recovery.get()
            state.operation_id = "op-1"
            for _ in range(3):
                observe_attempt_error("op-1", "LLMNullResponseError")
            return list(messages)

    result = Subject().chat(messages)

    assert result[-1] == {"role": "user", "content": "please continue"}


def test_disabled_recovery_never_injects(monkeypatch):
    """The enable switch prevents message injection without changing retries."""
    monkeypatch.setenv("TOPSAILAI_LLM_NULL_RESPONSE_RECOVERY_ENABLED", "0")
    messages = [{"role": "user", "content": "task"}]

    class Subject:
        @track_null_response_recovery
        def chat(self, messages):
            state = _active_null_response_recovery.get()
            state.operation_id = "op-1"
            outcomes = [
                observe_attempt_error("op-1", "LLMNullResponseError")
                for _ in range(4)
            ]
            return outcomes, list(messages)

    outcomes, observed = Subject().chat(messages)

    assert outcomes == [False, False, False, False]
    assert observed == [{"role": "user", "content": "task"}]


def test_error_after_injection_does_not_rearm_duplicate_guidance(active_state):
    """A later null-response streak reuses the one live recovery message."""
    for _ in range(3):
        observe_attempt_error("op-1", "LLMNullResponseError")
    observe_attempt_error("op-1", "LLMProviderReadError")
    outcomes = [
        observe_attempt_error("op-1", "LLMNullResponseError")
        for _ in range(3)
    ]

    assert outcomes == [False, False, False]
    assert active_state.messages.count(
        {"role": "user", "content": "continue"}
    ) == 1
