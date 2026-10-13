"""Unit tests for per-agent startup completion state."""

import threading
import unittest

from topsailai.context.agent_startup import AgentStartupState


class TestAgentStartupState(unittest.TestCase):
    """Test terminal startup publication and cancellation."""

    def test_started_state_wakes_waiter_and_is_sticky(self):
        """A successful startup remains published after later calls."""
        state = AgentStartupState()
        result = []
        worker = threading.Thread(target=lambda: result.append(state.wait(1)))
        worker.start()
        state.mark_started()
        worker.join(1)

        self.assertEqual(result, [True])
        state.cancel()
        self.assertTrue(state.started)
        self.assertTrue(state.wait(0))

    def test_cancelled_state_releases_waiter_without_starting(self):
        """Cancellation wakes waiter without authorizing naming."""
        state = AgentStartupState()
        state.cancel()

        self.assertFalse(state.started)
        self.assertFalse(state.wait(0))

    def test_pending_wait_times_out_without_publishing(self):
        """A bounded wait returns false and leaves the state pending."""
        state = AgentStartupState()

        self.assertFalse(state.wait(0))
        self.assertFalse(state.started)
    def test_instances_are_independent(self):
        """One agent cannot publish startup for another agent."""
        first = AgentStartupState()
        second = AgentStartupState()
        first.mark_started()

        self.assertTrue(first.started)
        self.assertFalse(second.started)
