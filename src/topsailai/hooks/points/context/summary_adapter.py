"""Summary-local operation and at-most-once checkpoint dispatch boundary.

Author: DawsonLin
"""

from __future__ import annotations

from concurrent.futures import CancelledError

from topsailai.ai_base.exception import HeavyTaskError, HardInterruptError, LLMBackToChatError
from topsailai.ai_base.llm_control.exception import (
    LLMProviderError, LLMProviderTimeoutError, LLMProviderConnectionError,
    LLMProviderReadError,
)

from topsailai.logger import logger

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from topsailai.hooks.configured_executor import HookOperation
from topsailai.hooks.contracts import DispatchReport, ValidationError
from topsailai.hooks.points.context import (
    before_summary_generate_user2agent, before_summary_generate_agent2llm,
    after_summary_apply_user2agent, after_summary_apply_agent2llm,
    error_summary_generate_user2agent, error_summary_generate_agent2llm,
    error_summary_apply_user2agent, error_summary_apply_agent2llm,
)

_CHECKPOINTS = MappingProxyType({
    "user2agent": MappingProxyType({
        "before_summary_generate": before_summary_generate_user2agent,
        "after_summary_apply": after_summary_apply_user2agent,
        "error_summary_generate": error_summary_generate_user2agent,
        "error_summary_apply": error_summary_apply_user2agent,
    }),
    "agent2llm": MappingProxyType({
        "before_summary_generate": before_summary_generate_agent2llm,
        "after_summary_apply": after_summary_apply_agent2llm,
        "error_summary_generate": error_summary_generate_agent2llm,
        "error_summary_apply": error_summary_apply_agent2llm,
    }),
})


@dataclass(frozen=True, slots=True)
class SummaryCheckpointResult:
    """Distinguish a dispatch attempt from an already-consumed checkpoint."""

    operation_id: str
    point_name: str
    already_handled: bool
    report: DispatchReport | None = None


__all__ = ["SummaryCheckpointResult"]


from contextvars import ContextVar
from functools import wraps
from threading import current_thread
import asyncio

_CURRENT_SUMMARY = ContextVar("current_summary_operation", default=None)


def _summary_owner():
    """Bind custody to an exact thread and task, not a copied context alone."""
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return current_thread(), task


@dataclass(slots=True)
class DirectSummaryOperation:
    """Own bounded checkpoint state for one business summary invocation."""

    layer: str
    operation: HookOperation = field(default_factory=HookOperation)
    _owner: Any = field(default_factory=_summary_owner, repr=False)
    _active: bool = field(default=True, repr=False)
    _handled: set[str] = field(default_factory=set, repr=False)

    def emit(self, checkpoint: str, **classification: Any):
        """Validate before consuming once, then invoke the named direct entry."""
        if not self._active or self._owner != _summary_owner():
            raise ValidationError("summary operation context ownership mismatch")
        if type(checkpoint) is not str or checkpoint not in _CHECKPOINTS[self.layer]:
            raise ValidationError("unknown or inactive summary checkpoint")
        selected = _CHECKPOINTS[self.layer][checkpoint]
        try:
            selected.build_payload(operation_id=self.operation.operation_id, **classification)
        except TypeError as error:
            raise ValidationError("invalid summary classification fields") from error
        if selected.NAME in self._handled:
            return SummaryCheckpointResult(self.operation.operation_id, selected.NAME, True)
        self._handled.add(selected.NAME)
        return getattr(selected, selected.NAME)(
            operation_id=self.operation.operation_id, **classification)


def current_summary_operation():
    """Return only an operation owned by the current thread and task."""
    operation = _CURRENT_SUMMARY.get()
    if operation is None or not operation._active or operation._owner != _summary_owner():
        return None
    return operation


def summary_operation(layer):
    """Scope correlation around a summary without changing its public signature."""
    if layer not in _CHECKPOINTS:
        raise ValidationError("invalid summary layer")

    def decorate(function):
        """Keep all business checkpoints inside the original method."""
        @wraps(function)
        def wrapped(*args, **kwargs):
            """Restore the exact outer operation after every return or exception."""
            operation = DirectSummaryOperation(layer)
            token = _CURRENT_SUMMARY.set(operation)
            try:
                return function(*args, **kwargs)
            finally:
                operation._active = False
                _CURRENT_SUMMARY.reset(token)
        return wrapped
    return decorate


SUMMARY_CONTROL_EXCEPTIONS = (CancelledError, HeavyTaskError, HardInterruptError, LLMBackToChatError)


def emit_summary_checkpoint(checkpoint, **classification):
    """Isolate ordinary observer failures without hiding host control signals."""
    operation = current_summary_operation()
    if operation is None:
        return None
    try:
        return operation.emit(checkpoint, **classification)
    except BaseException as error:
        # An active business exception always outranks its error observer.
        if not checkpoint.startswith("error_") and (
                not isinstance(error, Exception) or isinstance(error, SUMMARY_CONTROL_EXCEPTIONS)):
            raise
        logger.warning("summary observer dispatch failed: checkpoint=%s reason=observer_failure", checkpoint)
        return None


def classify_summary_generation_error(error):
    """Classify request failures without exposing exception text to observers."""
    if isinstance(error, (TimeoutError, LLMProviderTimeoutError)):
        return "timeout"
    if isinstance(error, (ConnectionError, LLMProviderConnectionError, LLMProviderReadError)):
        return "transport"
    if isinstance(error, LLMProviderError):
        return "provider"
    return "unknown"
