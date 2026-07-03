#!/usr/bin/env python3
"""
Unit tests for YAML command loading in cli_topsailai.
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

import cli_topsailai.state as cli_state
from cli_topsailai.yaml_commands import load_yaml_commands


class TestYamlCommands(unittest.TestCase):
    """Tests for YAML command loading."""

    def tearDown(self):
        cli_state.yaml_commands = []

    def test_load_yaml_commands_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "commands.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("commands:\n")
            commands = load_yaml_commands(path)
            self.assertIsInstance(commands, list)

    def test_load_yaml_commands_missing(self):
        commands = load_yaml_commands("/nonexistent/path.yaml")
        self.assertEqual(commands, [])


if __name__ == "__main__":
    unittest.main()
