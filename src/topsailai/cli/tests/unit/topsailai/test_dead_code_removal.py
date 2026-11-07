"""Dead-code removal guards for the liveness consolidation.

Every name asserted absent here was a transitional thin wrapper or an orphaned
parser left behind by the liveness consolidation. Each one either duplicated the
shared primitive or carried semantics that contradict the active rule, so a
future caller could reintroduce a fixed defect by reaching for it.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import topsailai_project_history as ph
import topsailai_session_info as si
from cli_topsailai import project_scope


class TestDeadCodeRemoved(unittest.TestCase):
    """Transitional wrappers and orphaned parsers must be gone."""

    def test_project_history_orphan_parser_is_gone(self):
        """``_parse_session_stdout_filename`` lost its only caller."""
        self.assertFalse(
            hasattr(ph, "_parse_session_stdout_filename"),
            "the orphaned parser must not survive its only caller",
        )

    def test_session_info_thin_wrapper_is_gone(self):
        """``_is_pid_alive`` only forwarded to the shared primitive."""
        self.assertFalse(
            hasattr(si, "_is_pid_alive"),
            "a pure forwarding wrapper must not shadow the shared primitive",
        )

    def test_project_scope_thin_wrapper_is_gone(self):
        """``_is_pid_alive`` only forwarded to the shared primitive."""
        self.assertFalse(
            hasattr(project_scope, "_is_pid_alive"),
            "a pure forwarding wrapper must not shadow the shared primitive",
        )

    def test_project_scope_pid_state_wrapper_is_gone(self):
        """``_pid_state`` only forwarded to the shared primitive."""
        self.assertFalse(
            hasattr(project_scope, "_pid_state"),
            "a pure forwarding wrapper must not shadow the shared primitive",
        )

    def test_project_scope_candidates_wrapper_is_gone(self):
        """``_session_stdout_candidates`` only forwarded to the shared primitive."""
        self.assertFalse(
            hasattr(project_scope, "_session_stdout_candidates"),
            "a pure forwarding wrapper must not shadow the shared primitive",
        )


class TestBehaviourStillReachable(unittest.TestCase):
    """Removing the wrappers must not remove the behaviour they exposed."""

    def test_project_scope_liveness_is_still_public(self):
        """The real entry point must remain available."""
        self.assertTrue(callable(project_scope.session_liveness))

    def test_session_info_running_check_is_still_public(self):
        """The real entry point must remain available."""
        self.assertTrue(callable(si._is_session_running))

    def test_project_history_running_check_is_still_public(self):
        """The real entry point must remain available."""
        self.assertTrue(callable(ph._is_session_running))

    def test_project_history_probe_is_still_public(self):
        """``_is_pid_alive`` still has a production caller here."""
        self.assertTrue(callable(ph._is_pid_alive))

    def test_session_info_parser_is_still_public(self):
        """``topsailai_sessions_info`` still imports this parser."""
        self.assertTrue(callable(si._parse_session_stdout_filename))


if __name__ == "__main__":
    unittest.main()
