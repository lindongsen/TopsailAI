"""Request-local recovery state for consecutive null LLM responses."""

from __future__ import annotations

import contextvars
import functools
from dataclasses import dataclass
from typing import Optional

from topsailai.ai_base.constants import ROLE_USER

CONTINUE_MESSAGE = "continue"
NULL_RESPONSE_THRESHOLD = 3


@dataclass
class NullResponseRecoveryState:
    """Track one request's live messages and consecutive null responses."""

    messages: list
    operation_id: str = ""
    consecutive_failures: int = 0
    injected_for_streak: bool = False
    injected_messages: list | None = None

    def __post_init__(self) -> None:
        """Create an owned list of messages that must be removed at request exit."""
        if self.injected_messages is None:
            self.injected_messages = []


_active_null_response_recovery = contextvars.ContextVar(
    "topsailai_null_response_recovery", default=None
)


def current_null_response_recovery() -> Optional[NullResponseRecoveryState]:
    """Return the recovery state active in this execution context."""
    return _active_null_response_recovery.get()


def bind_null_response_operation(operation_id: str) -> None:
    """Bind the active recovery state to one LLM request operation."""
    state = current_null_response_recovery()
    if state is not None:
        state.operation_id = operation_id or ""


def observe_attempt_error(operation_id: str, error_category: str) -> bool:
    """Apply the Hook module's threshold decision and inject when it fires."""
    state = current_null_response_recovery()
    if state is None or state.operation_id != operation_id:
        return False
    if error_category != "LLMNullResponseError":
        state.consecutive_failures = 0
        state.injected_for_streak = False
        return False

    state.consecutive_failures += 1
    if state.consecutive_failures < NULL_RESPONSE_THRESHOLD or state.injected_for_streak:
        return False
    message = {"role": ROLE_USER, "content": CONTINUE_MESSAGE}
    state.messages.append(message)
    state.injected_messages.append(message)
    state.injected_for_streak = True
    return True


def _remove_injected_messages(state: NullResponseRecoveryState) -> None:
    """Remove only messages owned by this recovery context, by identity."""
    owned_ids = {id(message) for message in state.injected_messages}
    state.messages[:] = [
        message for message in state.messages if id(message) not in owned_ids
    ]


def track_null_response_recovery(method):
    """Keep recovery state for exactly one complete ``chat()`` request."""
    @functools.wraps(method)
    def wrapper(self, messages, *args, **kwargs):
        state = NullResponseRecoveryState(messages=messages)
        token = _active_null_response_recovery.set(state)
        try:
            return method(self, messages, *args, **kwargs)
        finally:
            _remove_injected_messages(state)
            _active_null_response_recovery.reset(token)

    return wrapper


__all__ = [
    "CONTINUE_MESSAGE", "NULL_RESPONSE_THRESHOLD", "NullResponseRecoveryState",
    "bind_null_response_operation", "current_null_response_recovery",
    "observe_attempt_error", "track_null_response_recovery",
]
