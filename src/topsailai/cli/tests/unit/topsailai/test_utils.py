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


if __name__ == "__main__":
    unittest.main()
