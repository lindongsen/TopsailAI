"""Publish repeated LLM request failures into Agent Runtime Data."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
import functools
import logging

from topsailai.ai_base.llm_control.configuration import (
    get_llm_request_retry_state_threshold,
)
from topsailai.ai_base.runtime_data import RuntimeDataLease, RuntimeDataStore
from topsailai.utils.thread_local_tool import get_agent_object


logger = logging.getLogger(__name__)
RUNTIME_STATE_KEY = "llm.request.retrying"


@dataclass
class RetryRuntimeState:
    """Track one complete LLM request's runtime-state publication."""

    store: RuntimeDataStore | None
    threshold: int
    operation_id: str = ""
    failed_attempts: int = 0
    lease: RuntimeDataLease | None = None
    publication_disabled: bool = False


_active_retry_runtime_state = contextvars.ContextVar(
    "topsailai_llm_retry_runtime_state", default=None
)


def current_retry_runtime_state() -> RetryRuntimeState | None:
    """Return the retry-state tracker active in this execution context."""
    return _active_retry_runtime_state.get()


def bind_retry_runtime_operation(operation_id: str) -> None:
    """Bind the current tracker to one validated LLM request operation."""
    state = current_retry_runtime_state()
    if state is not None:
        state.operation_id = operation_id or ""


def _state_value(state: RetryRuntimeState, category: str) -> dict:
    """Build the bounded public value for one failed attempt."""
    return {
        "phase": "fault_retrying",
        "failed_attempts": state.failed_attempts,
        "next_retry_number": state.failed_attempts + 1,
        "threshold": state.threshold,
        "last_error_category": category[:128],
    }


def observe_retry_attempt_error(
    operation_id: str,
    error_category: str,
) -> bool:
    """Activate or update retry state after one failed provider attempt."""
    state = current_retry_runtime_state()
    if (
        state is None
        or state.store is None
        or state.threshold == 0
        or state.publication_disabled
        or state.operation_id != operation_id
    ):
        return False
    state.failed_attempts += 1
    if state.failed_attempts < state.threshold:
        return False
    value = _state_value(state, error_category)
    try:
        if state.lease is None:
            state.lease = state.store.activate(
                RUNTIME_STATE_KEY,
                operation_id,
                value,
                public=True,
            )
            return True
        return state.store.update(state.lease, value)
    except Exception as error:
        state.publication_disabled = True
        logger.warning(
            "LLM retry Runtime Data publication failed category=%s",
            type(error).__name__,
            exc_info=False,
        )
        return False


def _outcome_for_error(error: BaseException) -> str:
    """Map request termination to a bounded settled-history outcome."""
    category = type(error).__name__
    if category in ("HardInterruptError", "KeyboardInterrupt"):
        return "interrupted"
    if category == "LLMBackToChatError":
        return "abandoned"
    return "failed"


def _settle(state: RetryRuntimeState, outcome: str) -> None:
    """Best-effort settle one published generation without masking results."""
    if state.store is None or state.lease is None:
        return
    try:
        state.store.deactivate(state.lease, outcome=outcome)
    except Exception as error:
        logger.warning(
            "LLM retry Runtime Data settlement failed category=%s",
            type(error).__name__,
            exc_info=False,
        )


def track_retry_runtime_state(method):
    """Scope retry Runtime Data to exactly one complete ``chat()`` request."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        agent = get_agent_object()
        runtime = getattr(agent, "runtime", None) if agent is not None else None
        store = getattr(runtime, "runtime_data", None)
        if not isinstance(store, RuntimeDataStore):
            store = None
        state = RetryRuntimeState(
            store=store,
            threshold=get_llm_request_retry_state_threshold(),
        )
        token = _active_retry_runtime_state.set(state)
        try:
            result = method(self, *args, **kwargs)
        except BaseException as error:
            _settle(state, _outcome_for_error(error))
            raise
        else:
            _settle(state, "recovered")
            return result
        finally:
            _active_retry_runtime_state.reset(token)

    return wrapper


__all__ = [
    "RUNTIME_STATE_KEY",
    "RetryRuntimeState",
    "bind_retry_runtime_operation",
    "current_retry_runtime_state",
    "observe_retry_attempt_error",
    "track_retry_runtime_state",
]
