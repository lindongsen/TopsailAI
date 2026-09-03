"""LLM-specific state visualization coordinated with request statistics."""

from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

from topsailai.context.llm_request_stat import LLMRequestStat
from topsailai.utils.state_visualizer import StateVisualizer, VisualizationState


F = TypeVar("F", bound=Callable[..., Any])


class LLMStateVisualizer(StateVisualizer):
    """Visualize LLM state and print statistics for the same execution context."""

    def __init__(self, request_stat: LLMRequestStat) -> None:
        """Bind request statistics while retaining generic state behavior."""
        super().__init__()
        self.request_stat = request_stat

    def _handle_state(self, state: VisualizationState) -> None:
        """Print LLM statistics before the generic Thinking message."""
        if state == VisualizationState.THINKING:
            self.request_stat.print_request_stat()
        super()._handle_state(state)


def visualize_model_state(state: VisualizationState) -> Callable[[F], F]:
    """Decorate a model method using that model instance's visualizer."""
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(model: Any, *args: Any, **kwargs: Any) -> Any:
            visualizer = model._get_state_visualizer()
            visualizer.start()
            visualizer.set_state(state)
            try:
                return func(model, *args, **kwargs)
            finally:
                visualizer.set_state(VisualizationState.IDLE)

        return wrapper  # type: ignore[return-value]

    return decorator
