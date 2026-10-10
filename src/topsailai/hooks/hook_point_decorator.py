"""Sync and async decorators for catalog-declared Hook points."""

from __future__ import annotations

import contextvars
import functools
import inspect
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping

from topsailai.hooks.configured_executor import (
    ConfiguredHookExecutor,
    HookOperation,
)
from topsailai.hooks.hook_point_catalog import HookPointDeclaration


@dataclass(frozen=True, slots=True)
class HookInvocationView:
    """Expose only declaration-authorized detached JSON values to a builder."""

    point: HookPointDeclaration
    phase: str
    arguments: Mapping[str, Any]
    operation: HookOperation
    result: Mapping[str, Any]
    error: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _Decoration:
    """Identify one complete decorator declaration for idempotence checks."""

    before: HookPointDeclaration | None
    success: HookPointDeclaration | None
    error: HookPointDeclaration | None
    executor_attribute: str | None
    executor_provider: Callable[[], ConfiguredHookExecutor] | None
    payload_builder: Callable[[HookInvocationView], Any] | None


_CURRENT_OPERATION: contextvars.ContextVar[HookOperation | None] = contextvars.ContextVar(
    "topsailai_hook_operation", default=None
)
_MARKER = "__topsailai_hook_point_decoration__"


def hook_point(
    *,
    before: HookPointDeclaration | None = None,
    success: HookPointDeclaration | None = None,
    error: HookPointDeclaration | None = None,
    executor_attribute: str | None = None,
    executor_provider: Callable[[], ConfiguredHookExecutor] | None = None,
    payload_builder: Callable[[HookInvocationView], Any] | None = None,
):
    """Decorate one ordinary sync or async callable with distinct Hook points."""
    decoration = _validate_decoration(
        before,
        success,
        error,
        executor_attribute,
        executor_provider,
        payload_builder,
    )

    def decorate(function):
        """Validate and wrap one callable exactly once."""
        if inspect.isgeneratorfunction(function) or inspect.isasyncgenfunction(function):
            raise TypeError("Hook-point decorators do not support generator callables")
        existing = getattr(function, _MARKER, None)
        if existing is not None:
            if existing == decoration:
                return function
            raise ValueError("conflicting Hook-point decoration")
        if not inspect.isfunction(function):
            raise TypeError("Hook-point decorator requires an ordinary function")
        signature = inspect.signature(function)
        wrapped = (
            _wrap_async(function, signature, decoration)
            if inspect.iscoroutinefunction(function)
            else _wrap_sync(function, signature, decoration)
        )
        setattr(wrapped, _MARKER, decoration)
        return wrapped

    return decorate


def _validate_decoration(
    before,
    success,
    error,
    executor_attribute,
    executor_provider,
    payload_builder,
) -> _Decoration:
    """Validate one complete decorator declaration at definition time."""
    points = ((before, "before"), (success, "success"), (error, "error"))
    if all(point is None for point, _ in points):
        raise ValueError("at least one Hook-point declaration is required")
    for point, phase in points:
        if point is not None and (
            type(point) is not HookPointDeclaration or point.phase != phase
        ):
            raise ValueError("Hook-point declaration phase mismatch")
    modes = {point.mode for point, _ in points if point is not None}
    if modes not in ({"sync"}, {"async"}):
        raise ValueError("Hook-point decorator requires one callable execution mode")
    has_attribute = type(executor_attribute) is str and bool(executor_attribute)
    has_provider = callable(executor_provider)
    if has_attribute == has_provider:
        raise ValueError("exactly one Hook Executor source is required")
    if payload_builder is not None and not callable(payload_builder):
        raise ValueError("invalid Hook payload builder")
    return _Decoration(
        before,
        success,
        error,
        executor_attribute if has_attribute else None,
        executor_provider if has_provider else None,
        payload_builder,
    )


def _wrap_sync(function, signature, decoration):
    """Build a synchronous wrapper with exact success/error cardinality."""
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        operation, token = _enter_operation()
        try:
            executor = _resolve_executor(decoration, bound.arguments)
            if decoration.before is not None:
                _dispatch_sync(executor, decoration.before, bound.arguments, operation, decoration)
            try:
                result = function(*args, **kwargs)
            except Exception as business_error:
                if decoration.error is not None:
                    try:
                        _dispatch_sync(
                            executor,
                            decoration.error,
                            bound.arguments,
                            operation,
                            decoration,
                            error=business_error,
                        )
                    except Exception:
                        pass
                raise
            if decoration.success is not None:
                _dispatch_sync(
                    executor,
                    decoration.success,
                    bound.arguments,
                    operation,
                    decoration,
                    result=result,
                )
            return result
        finally:
            _CURRENT_OPERATION.reset(token)

    return wrapped


def _wrap_async(function, signature, decoration):
    """Build an asynchronous wrapper with exact success/error cardinality."""
    @functools.wraps(function)
    async def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        operation, token = _enter_operation()
        try:
            executor = _resolve_executor(decoration, bound.arguments)
            if decoration.before is not None:
                await _dispatch_async(executor, decoration.before, bound.arguments, operation, decoration)
            try:
                result = await function(*args, **kwargs)
            except Exception as business_error:
                if decoration.error is not None:
                    try:
                        await _dispatch_async(
                            executor,
                            decoration.error,
                            bound.arguments,
                            operation,
                            decoration,
                            error=business_error,
                        )
                    except Exception:
                        pass
                raise
            if decoration.success is not None:
                await _dispatch_async(
                    executor,
                    decoration.success,
                    bound.arguments,
                    operation,
                    decoration,
                    result=result,
                )
            return result
        finally:
            _CURRENT_OPERATION.reset(token)

    return wrapped


def _enter_operation() -> tuple[HookOperation, contextvars.Token]:
    """Create and publish one nested occurrence operation."""
    parent = _CURRENT_OPERATION.get()
    operation = HookOperation(
        parent_operation_id=None if parent is None else parent.operation_id,
        depth=0 if parent is None else parent.depth + 1,
    )
    return operation, _CURRENT_OPERATION.set(operation)


def _resolve_executor(decoration: _Decoration, arguments) -> ConfiguredHookExecutor:
    """Resolve one injected Executor without environment or Runtime creation."""
    if decoration.executor_provider is not None:
        executor = decoration.executor_provider()
    else:
        receiver = next(iter(arguments.values()), None)
        executor = getattr(receiver, decoration.executor_attribute, None)
    required = ("dispatch", "adispatch")
    if any(not callable(getattr(executor, name, None)) for name in required):
        raise ValueError("Hook Executor dependency is unavailable")
    return executor


def _detached_fields(source, fields, point):
    """Return one bounded JSON snapshot containing only declared fields."""
    from topsailai.hooks.validation import freeze_json

    selected = {name: source[name] for name in fields if name in source}
    detached = freeze_json(selected, max_bytes=point.definition.payload_limit_bytes)
    return MappingProxyType(detached)


def _safe_error_metadata(error, fields):
    """Return authorized tokens without invoking exception formatting code."""
    metadata = {}
    if "type" in fields:
        metadata["type"] = type(error).__name__
    if "message" in fields:
        arguments = BaseException.args.__get__(error)
        if len(arguments) == 1 and type(arguments[0]) is str:
            metadata["message"] = arguments[0]
    return metadata


def _view(point, arguments, operation, result=None, error=None) -> HookInvocationView:
    """Build one default-deny detached invocation view."""
    result_source = result if type(result) is dict else {}
    error_source = {} if error is None else _safe_error_metadata(error, point.error_fields)
    return HookInvocationView(
        point,
        point.phase,
        _detached_fields(arguments, point.argument_fields, point),
        operation,
        _detached_fields(result_source, point.result_fields, point),
        _detached_fields(error_source, point.error_fields, point),
    )


def _payload(decoration, view):
    """Build metadata-only payload unless an explicit builder is supplied."""
    if decoration.payload_builder is None:
        return {}
    return decoration.payload_builder(view)


def _dispatch_sync(executor, point, arguments, operation, decoration, result=None, error=None):
    """Dispatch one synchronous phase through the shared Executor."""
    view = _view(point, arguments, operation, result, error)
    return executor.dispatch(point, payload=_payload(decoration, view), operation=operation)


async def _dispatch_async(executor, point, arguments, operation, decoration, result=None, error=None):
    """Dispatch one asynchronous phase through the shared Executor."""
    view = _view(point, arguments, operation, result, error)
    return await executor.adispatch(
        point,
        payload=_payload(decoration, view),
        operation=operation,
    )
