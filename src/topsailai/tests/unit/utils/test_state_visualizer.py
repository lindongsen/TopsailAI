"""Unit tests for ``StateVisualizer``.

These tests verify the singleton behaviour, state transitions, background
thread printing, the ``DISABLE_VISUALIZER`` environment switch, and clean
shutdown via ``stop()``.
"""

from __future__ import annotations

import os
import threading
import time
from unittest import mock

import pytest

from topsailai.utils.state_visualizer import StateVisualizer, VisualizationState

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton instance before and after each test.

    This guarantees that tests are isolated from each other even though
    ``StateVisualizer`` is a singleton.
    """
    original_instance = StateVisualizer._instance
    # Stop the original instance first to reduce cross-test interference from
    # any lingering background worker.
    if original_instance is not None:
        original_instance.stop()
    StateVisualizer._instance = None
    yield
    # Restore the original instance so that production code that already
    # imported the singleton is not left with a stale reference.
    StateVisualizer._instance = original_instance


class TestStateVisualizerSingleton:
    def test_multiple_calls_return_same_instance(self):
        first = StateVisualizer()
        second = StateVisualizer()
        assert first is second


class TestStateVisualizerStateAccess:
    def test_set_and_get_state(self):
        visualizer = StateVisualizer()
        assert visualizer.get_state() == VisualizationState.IDLE

        visualizer.set_state(VisualizationState.THINKING)
        assert visualizer.get_state() == VisualizationState.THINKING

        visualizer.set_state(VisualizationState.IDLE)
        assert visualizer.get_state() == VisualizationState.IDLE


class TestStateVisualizerPrinting:
    def test_thinking_state_prints_once(self, monkeypatch):
        visualizer = StateVisualizer()
        visualizer.start()

        with mock.patch(
            "topsailai.utils.state_visualizer.print_info"
        ) as mock_print_info:
            visualizer.set_state(VisualizationState.THINKING)
            self._wait_for_worker(visualizer)

            visualizer.set_state(VisualizationState.THINKING)
            self._wait_for_worker(visualizer)

        mock_print_info.assert_called_once_with("Thinking...")

    def test_idle_state_does_not_print(self, monkeypatch):
        visualizer = StateVisualizer()
        visualizer.start()

        with mock.patch(
            "topsailai.utils.state_visualizer.print_info"
        ) as mock_print_info:
            visualizer.set_state(VisualizationState.IDLE)
            self._wait_for_worker(visualizer)

        mock_print_info.assert_not_called()

    def test_state_change_prints_again(self, monkeypatch):
        visualizer = StateVisualizer()
        visualizer.start()

        with mock.patch(
            "topsailai.utils.state_visualizer.print_info"
        ) as mock_print_info:
            visualizer.set_state(VisualizationState.THINKING)
            self._wait_for_worker(visualizer)

            visualizer.set_state(VisualizationState.IDLE)
            self._wait_for_worker(visualizer)

            visualizer.set_state(VisualizationState.THINKING)
            self._wait_for_worker(visualizer)

        assert mock_print_info.call_count == 2
        mock_print_info.assert_called_with("Thinking...")

    @staticmethod
    def _wait_for_worker(visualizer: StateVisualizer, timeout: float = 2.0) -> None:
        """Wait until the background worker has caught up with the latest state.

        The worker wakes up on state changes, but a small timeout is used to
        avoid flakiness on slow CI runners.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with visualizer._condition:
                if visualizer._last_printed_state == visualizer._state:
                    return
            time.sleep(0.01)
        raise TimeoutError("Background worker did not process the state change")


class TestStateVisualizerDisabled:
    def test_disabled_does_not_start_worker(self, monkeypatch):
        monkeypatch.setenv("DISABLE_VISUALIZER", "1")

        visualizer = StateVisualizer()
        visualizer.start()

        assert visualizer._disabled is True
        assert visualizer._worker is None

    def test_disabled_set_state_does_not_print(self, monkeypatch):
        monkeypatch.setenv("DISABLE_VISUALIZER", "true")

        visualizer = StateVisualizer()
        visualizer.start()

        # When disabled, no background worker should be spawned at all.
        assert visualizer._worker is None

        with mock.patch(
            "topsailai.utils.state_visualizer.print_info"
        ) as mock_print_info:
            visualizer.set_state(VisualizationState.THINKING)

        mock_print_info.assert_not_called()

    @pytest.mark.parametrize("value", ["1", "true", "True", "YES", " yes "])
    def test_various_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("DISABLE_VISUALIZER", value)

        visualizer = StateVisualizer()
        visualizer.start()

        assert visualizer._disabled is True
        assert visualizer._worker is None


class TestStateVisualizerLifecycle:
    def test_stop_terminates_worker(self):
        visualizer = StateVisualizer()
        visualizer.start()

        worker = visualizer._worker
        assert worker is not None
        assert worker.is_alive()

        visualizer.stop()

        assert not worker.is_alive()
        assert visualizer._worker is None

    def test_stop_is_idempotent(self):
        visualizer = StateVisualizer()
        visualizer.start()
        visualizer.stop()

        # A second stop should not raise or block indefinitely.
        visualizer.stop()

        assert visualizer._worker is None

    def test_worker_is_daemon(self):
        visualizer = StateVisualizer()
        visualizer.start()

        worker = visualizer._worker
        assert worker is not None
        assert worker.daemon is True

        visualizer.stop()
