"""Public visualization state manager.

This module provides an instance-scoped ``StateVisualizer`` that tracks the
current visualization state (e.g. IDLE, THINKING) and synchronously emits the
corresponding log message via ``print_tool`` when the state changes.

The visualizer can be disabled by setting the environment variable
``DISABLE_VISUALIZER`` to ``1``, ``true`` or ``yes`` (case-insensitive).
"""

from __future__ import annotations

import functools
import os
import threading
from enum import Enum, auto
from typing import Any, Callable, Optional, TypeVar

from topsailai.utils.print_tool import print_info


class VisualizationState(Enum):
    """Finite set of visualization states."""

    IDLE = auto()
    THINKING = auto()


F = TypeVar("F", bound=Callable[..., Any])


class StateVisualizer:
    """Instance-scoped visualization state manager.

    Usage:
        visualizer = StateVisualizer()
        visualizer.start()
        visualizer.set_state(VisualizationState.THINKING)
        # ... do work ...
        visualizer.set_state(VisualizationState.IDLE)
        visualizer.stop()

    The class also supports a context manager for temporarily entering a state:

        with visualizer.state_scope(VisualizationState.THINKING):
            # ... do work ...

    A decorator is provided for the common case of marking an entire function:

        @visualizer.visualize_state(VisualizationState.THINKING)
        def perform_work(...):
            ...
    """

    def __init__(self) -> None:
        """Initialize an independent state visualizer."""
        self._state = VisualizationState.IDLE
        self._last_printed_state: Optional[VisualizationState] = None
        self._lock = threading.RLock()
        self._disabled = self._is_disabled()

    @staticmethod
    def _is_disabled() -> bool:
        value = os.getenv("DISABLE_VISUALIZER", "").strip().lower()
        return value in ("1", "true", "yes")

    def start(self) -> None:
        """Retain the former lifecycle API; synchronous mode needs no startup."""

    def stop(self) -> None:
        """Retain the former lifecycle API; synchronous mode needs no teardown."""

    def _handle_state(self, state: VisualizationState) -> None:
        """Emit the log message associated with ``state``."""
        if state == VisualizationState.THINKING:
            print_info("Thinking...")
        # IDLE and future states intentionally produce no output by default.

    def set_state(self, state: VisualizationState) -> None:
        """Set and synchronously handle a changed visualization state."""
        if self._disabled:
            return

        with self._lock:
            self._state = state
            if state == self._last_printed_state:
                return
            self._last_printed_state = state

        self._handle_state(state)

    def get_state(self) -> VisualizationState:
        """Return the current visualization state."""
        with self._lock:
            return self._state

    def state_scope(self, state: VisualizationState):
        """Context manager that temporarily switches to ``state``.

        The previous state is restored on exit, even if an exception is raised.
        """
        return _StateScope(self, state)

    def visualize_state(self, state: VisualizationState) -> Callable[[F], F]:
        """Decorator that switches to ``state`` while the wrapped function runs.

        The state is set to ``VisualizationState.IDLE`` on exit, even if an
        exception is raised. The decorator works for both plain functions and
        bound methods (including class methods) because it simply forwards all
        positional and keyword arguments unchanged.

        Example:
            @visualizer.visualize_state(VisualizationState.THINKING)
            def perform_work(items):
                ...
        """

        def decorator(func: F) -> F:
            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                self.set_state(state)
                try:
                    return func(*args, **kwargs)
                finally:
                    self.set_state(VisualizationState.IDLE)

            return wrapper  # type: ignore[return-value]

        return decorator



class _StateScope:
    """Context helper used by ``StateVisualizer.state_scope``."""

    def __init__(self, visualizer: StateVisualizer, state: VisualizationState) -> None:
        self._visualizer = visualizer
        self._target_state = state
        self._previous_state: Optional[VisualizationState] = None

    def __enter__(self) -> "_StateScope":
        self._previous_state = self._visualizer.get_state()
        self._visualizer.set_state(self._target_state)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._previous_state is not None:
            self._visualizer.set_state(self._previous_state)
