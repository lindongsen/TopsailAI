"""
Unit tests for tools/cmd_tool.get_cmd_timeout environment key resolution.

Test coverage:
- The preferred TOPSAILAI_TOOL_CMD_TIMEOUT_MAP key raises a matching timeout
- The misspelled legacy TOPSALAI_TOOL_CMD_TIMEOUT_MAP key still applies
- The preferred key wins when both keys are configured
- An unconfigured map leaves the caller timeout untouched

Author: DawsonLin
"""

import json
import os
import unittest


MAP_VALUE = json.dumps([
    {"cmd": "pytest ", "min_timeout": 600, "max_timeout": 0},
])

PREFERRED_KEY = "TOPSAILAI_TOOL_CMD_TIMEOUT_MAP"
LEGACY_KEY = "TOPSALAI_TOOL_CMD_TIMEOUT_MAP"


class TestGetCmdTimeoutEnvKeys(unittest.TestCase):
    """Test cases for the command timeout map environment keys."""

    def setUp(self):
        """Clear both timeout map keys before each test."""
        self._saved = {}
        for key in (PREFERRED_KEY, LEGACY_KEY):
            self._saved[key] = os.environ.pop(key, None)

    def tearDown(self):
        """Restore the original environment."""
        for key, value in self._saved.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value

    def test_preferred_key_raises_timeout(self):
        """The correctly spelled key must raise a matching timeout."""
        from topsailai.tools.cmd_tool import get_cmd_timeout

        os.environ[PREFERRED_KEY] = MAP_VALUE
        self.assertEqual(get_cmd_timeout("pytest -q", 120), 600)

    def test_legacy_key_still_applies(self):
        """The misspelled legacy key must keep working for old deployments."""
        from topsailai.tools.cmd_tool import get_cmd_timeout

        os.environ[LEGACY_KEY] = MAP_VALUE
        self.assertEqual(get_cmd_timeout("pytest -q", 120), 600)

    def test_preferred_key_wins_over_legacy(self):
        """The preferred key must take precedence when both are configured."""
        from topsailai.tools.cmd_tool import get_cmd_timeout

        os.environ[PREFERRED_KEY] = MAP_VALUE
        os.environ[LEGACY_KEY] = json.dumps([
            {"cmd": "pytest ", "min_timeout": 900, "max_timeout": 0},
        ])
        self.assertEqual(get_cmd_timeout("pytest -q", 120), 600)

    def test_unconfigured_map_keeps_timeout(self):
        """An unconfigured map must not change the caller timeout."""
        from topsailai.tools.cmd_tool import get_cmd_timeout

        self.assertEqual(get_cmd_timeout("pytest -q", 120), 120)


if __name__ == "__main__":
    unittest.main()
