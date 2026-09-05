#!/usr/bin/env python3
"""
Unit tests for utility helpers in cli_topsailai.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from cli_topsailai.core import _preprocess_agent_mode
from cli_topsailai.paths import expand_path, get_workspace_root


class TestUtils(unittest.TestCase):
    """Tests for utility helpers."""

    def test_expand_path_tilde(self):
        home = os.path.expanduser("~")
        self.assertEqual(expand_path("~"), home)

    def test_get_workspace_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = get_workspace_root(tmpdir)
            self.assertEqual(root, tmpdir)

    def test_preprocess_agent_mode_short_and_long_forms_match(self):
        """Short and long agent-mode forms should normalize identically."""
        cases = (
            (["--agent-mode", "raw"], ["-m", "raw"]),
            (["--agent-mode=raw"], ["-m=raw"]),
            (["--agent-mode", "workspace"], ["-m", "workspace"]),
        )

        for long_args, short_args in cases:
            with self.subTest(short_args=short_args):
                self.assertEqual(
                    _preprocess_agent_mode(short_args),
                    _preprocess_agent_mode(long_args),
                )


if __name__ == "__main__":
    unittest.main()
