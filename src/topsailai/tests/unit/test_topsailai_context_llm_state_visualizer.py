"""Unit tests for LLM-specific state visualization."""

from unittest import mock

from topsailai.context.llm_state_visualizer import (
    LLMStateVisualizer,
    visualize_model_state,
)
from topsailai.context.llm_request_stat import LLMRequestStat
from topsailai.utils.state_visualizer import StateVisualizer, VisualizationState


def test_llm_visualizer_extends_generic_visualizer():
    """The context visualizer should reuse the generic state implementation."""
    request_stat = LLMRequestStat()
    visualizer = LLMStateVisualizer(request_stat)

    assert isinstance(visualizer, StateVisualizer)
    assert visualizer.request_stat is request_stat


def test_llm_visualizer_prints_stat_immediately_before_thinking():
    """A Thinking transition should print its context statistics first."""
    calls = mock.Mock()
    request_stat = mock.Mock()
    calls.attach_mock(request_stat.print_request_stat, "print_request_stat")
    visualizer = LLMStateVisualizer(request_stat)

    with mock.patch(
        "topsailai.utils.state_visualizer.print_info",
        calls.print_info,
    ):
        visualizer._handle_state(VisualizationState.THINKING)

    assert calls.mock_calls == [
        mock.call.print_request_stat(),
        mock.call.print_info("Thinking..."),
    ]


def test_llm_visualizer_does_not_print_stat_for_idle():
    """An idle transition should not produce request statistics."""
    request_stat = mock.Mock()
    visualizer = LLMStateVisualizer(request_stat)

    visualizer._handle_state(VisualizationState.IDLE)

    request_stat.print_request_stat.assert_not_called()


def test_model_decorator_uses_runtime_visualizer_and_restores_idle():
    """The LLM decorator should resolve the current model instance at call time."""
    visualizer = mock.Mock()
    model = mock.Mock()
    model._get_state_visualizer.return_value = visualizer

    @visualize_model_state(VisualizationState.THINKING)
    def execute(current_model, value):
        assert current_model is model
        return value

    assert execute(model, "done") == "done"
    assert visualizer.mock_calls == [
        mock.call.start(),
        mock.call.set_state(VisualizationState.THINKING),
        mock.call.set_state(VisualizationState.IDLE),
    ]


def test_model_decorator_restores_idle_after_error():
    """The LLM decorator should restore idle when the wrapped call fails."""
    visualizer = mock.Mock()
    model = mock.Mock()
    model._get_state_visualizer.return_value = visualizer

    @visualize_model_state(VisualizationState.THINKING)
    def execute(current_model):
        raise RuntimeError("failed")

    try:
        execute(model)
    except RuntimeError as error:
        assert str(error) == "failed"
    else:
        raise AssertionError("RuntimeError was not raised")

    assert visualizer.mock_calls[-1] == mock.call.set_state(VisualizationState.IDLE)
