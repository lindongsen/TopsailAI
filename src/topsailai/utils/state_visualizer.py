"""Public visualization state manager.

This module provides a singleton ``StateVisualizer`` that tracks the current
visualization state (e.g. IDLE, THINKING) and emits corresponding log messages
via ``print_tool``. A background thread waits on a ``threading.Condition`` and
prints a message only when the state transitions to a new value.

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
    """Singleton visualization state manager.

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

        @_state_visualizer.visualize_state(VisualizationState.THINKING)
        def call_llm_model(self, ...):
            ...
    """

    _instance: Optional["StateVisualizer"] = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "StateVisualizer":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # ``__init__`` may run multiple times because ``__new__`` always returns
        # the same object. Guard against re-initialization with a marker.
        if getattr(self, "_initialized", False):
            return

        self._initialized = True
        self._state = VisualizationState.IDLE
        self._last_printed_state: Optional[VisualizationState] = None
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._disabled = self._is_disabled()

    @staticmethod
    def _is_disabled() -> bool:
        value = os.getenv("DISABLE_VISUALIZER", "").strip().lower()
        return value in ("1", "true", "yes")

    def start(self) -> None:
        """Start the background state-checking thread if not disabled."""
        if self._disabled:
            return

        with self._condition:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop_event.clear()
            self._worker = threading.Thread(target=self._run, daemon=True)
            self._worker.start()

    def stop(self) -> None:
        """Signal the background thread to stop and wait for it to finish."""
        if self._disabled:
            return

        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()

        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=2.0)
        self._worker = None

    def _run(self) -> None:
        """Background loop: wait for state changes and print accordingly."""
        while not self._stop_event.is_set():
            with self._condition:
                # Wait until the state changes or we are asked to stop.
                while (
                    not self._stop_event.is_set()
                    and self._state == self._last_printed_state
                ):
                    self._condition.wait(timeout=0.5)

                if self._stop_event.is_set():
                    break

                state = self._state
                self._last_printed_state = state

            self._handle_state(state)

    def _handle_state(self, state: VisualizationState) -> None:
        """Emit the log message associated with ``state``."""
        if state == VisualizationState.THINKING:
            print_info("Thinking...")
        # IDLE and future states intentionally produce no output by default.

    def set_state(self, state: VisualizationState) -> None:
        """Set the current visualization state and notify the worker thread."""
        if self._disabled:
            return

        with self._condition:
            self._state = state
            self._condition.notify_all()

    def get_state(self) -> VisualizationState:
        """Return the current visualization state."""
        with self._condition:
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
            @_state_visualizer.visualize_state(VisualizationState.THINKING)
            def call_llm_model(self, messages):
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
