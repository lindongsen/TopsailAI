#!/usr/bin/env python3
"""Unit tests for launcher session-id environment setup."""

import os
import sys
import unittest
from unittest import mock

CLI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, CLI_DIR)

import topsailai_launch_agent as launcher


class TestSessionId(unittest.TestCase):
    """Verify session-id creation and compatibility behavior."""

    def test_generates_session_id_when_both_variables_are_missing(self):
        environment = {}

        with mock.patch.object(launcher.time, "strftime", return_value="20260915010101"):
            session_id = launcher._ensure_session_id(environment)

        self.assertEqual(session_id, "20260915010101")
        self.assertEqual(environment["TOPSAILAI_SESSION_ID"], session_id)
        self.assertEqual(environment["SESSION_ID"], session_id)

    def test_preserves_topsailai_session_id(self):
        environment = {"TOPSAILAI_SESSION_ID": "existing-topsailai"}

        session_id = launcher._ensure_session_id(environment)

        self.assertEqual(session_id, "existing-topsailai")
        self.assertEqual(environment["SESSION_ID"], session_id)

    def test_preserves_legacy_session_id(self):
        environment = {"SESSION_ID": "existing-legacy"}

        session_id = launcher._ensure_session_id(environment)

        self.assertEqual(session_id, "existing-legacy")
        self.assertEqual(environment["TOPSAILAI_SESSION_ID"], session_id)


if __name__ == "__main__":
    unittest.main()
