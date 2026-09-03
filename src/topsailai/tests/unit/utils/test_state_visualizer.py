"""Unit tests for ``StateVisualizer``.

These tests verify independent instances, synchronous state transitions, the
``DISABLE_VISUALIZER`` environment switch, and compatible lifecycle methods.
"""

from __future__ import annotations

from unittest import mock

import pytest

from topsailai.utils.state_visualizer import StateVisualizer, VisualizationState


class TestStateVisualizerInstances:
    def test_multiple_calls_return_independent_instances(self):
        first = StateVisualizer()
        second = StateVisualizer()
        try:
            assert first is not second
            assert not hasattr(first, "request_stat")
            assert not hasattr(second, "request_stat")
        finally:
            first.stop()
            second.stop()


class TestStateVisualizerStateAccess:
    def test_set_and_get_state(self):
        visualizer = StateVisualizer()
        assert visualizer.get_state() == VisualizationState.IDLE

        visualizer.set_state(VisualizationState.THINKING)
        assert visualizer.get_state() == VisualizationState.THINKING

        visualizer.set_state(VisualizationState.IDLE)
        assert visualizer.get_state() == VisualizationState.IDLE


class TestStateVisualizerPrinting:
    def test_thinking_state_prints_synchronously_once(self):
        visualizer = StateVisualizer()

        with mock.patch(
            "topsailai.utils.state_visualizer.print_info"
        ) as mock_print_info:
            visualizer.set_state(VisualizationState.THINKING)
            mock_print_info.assert_called_once_with("Thinking...")

            visualizer.set_state(VisualizationState.THINKING)

        mock_print_info.assert_called_once_with("Thinking...")

    def test_idle_state_does_not_print(self):
        visualizer = StateVisualizer()

        with mock.patch(
            "topsailai.utils.state_visualizer.print_info"
        ) as mock_print_info:
            visualizer.set_state(VisualizationState.IDLE)

        mock_print_info.assert_not_called()

    def test_state_change_prints_again(self):
        visualizer = StateVisualizer()

        with mock.patch(
            "topsailai.utils.state_visualizer.print_info"
        ) as mock_print_info:
            visualizer.set_state(VisualizationState.THINKING)
            visualizer.set_state(VisualizationState.IDLE)
            visualizer.set_state(VisualizationState.THINKING)

        assert mock_print_info.call_count == 2
        mock_print_info.assert_called_with("Thinking...")


class TestStateVisualizerDisabled:
    def test_disabled_start_is_noop(self, monkeypatch):
        monkeypatch.setenv("DISABLE_VISUALIZER", "1")

        visualizer = StateVisualizer()
        visualizer.start()

        assert visualizer._disabled is True
        assert not hasattr(visualizer, "_worker")

    def test_disabled_set_state_does_not_print(self, monkeypatch):
        monkeypatch.setenv("DISABLE_VISUALIZER", "true")
        visualizer = StateVisualizer()

        with mock.patch(
            "topsailai.utils.state_visualizer.print_info"
        ) as mock_print_info:
            visualizer.set_state(VisualizationState.THINKING)

        assert visualizer.get_state() == VisualizationState.IDLE
        mock_print_info.assert_not_called()

    @pytest.mark.parametrize("value", ["1", "true", "True", "YES", " yes "])
    def test_various_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("DISABLE_VISUALIZER", value)

        visualizer = StateVisualizer()
        visualizer.start()

        assert visualizer._disabled is True
        assert not hasattr(visualizer, "_worker")


class TestStateVisualizerLifecycle:
    def test_start_and_stop_are_compatible_noops(self):
        visualizer = StateVisualizer()

        assert visualizer.start() is None
        assert visualizer.stop() is None
        assert not hasattr(visualizer, "_worker")

    def test_stop_is_idempotent(self):
        visualizer = StateVisualizer()
        visualizer.start()
        visualizer.stop()

        assert visualizer.stop() is None
