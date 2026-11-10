#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the legacy fallback of CLI environment variables.

CLI-only variables moved under the ``TOPSAILAI_CLI_`` prefix. An operator who
still exports a previous name must keep working, so every read consults the
prefixed name first and the legacy name second.

Author: DawsonLin
"""

import os
import sys
import unittest
from io import StringIO
from unittest.mock import patch

# Ensure the CLI source is importable.
CLI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, CLI_DIR)

from cli_topsailai import env_compat


class GetEnvFallbackTest(unittest.TestCase):
    """Pin how a prefixed name and its legacy name are resolved."""

    def setUp(self):
        """Clear the once-only warning memory so each test starts clean."""
        env_compat._WARNED.clear()

    def tearDown(self):
        """Restore the warning memory for the next test."""
        env_compat._WARNED.clear()

    def test_the_prefixed_name_is_used_when_present(self):
        """A migrated variable must be read from its prefixed name."""
        environ = {"TOPSAILAI_CLI_SCAN_MAX_TOKENS": "500"}
        self.assertEqual(
            env_compat.get_env("TOPSAILAI_CLI_SCAN_MAX_TOKENS", environ=environ),
            "500",
        )

    def test_the_legacy_name_is_used_when_the_prefixed_name_is_absent(self):
        """An operator who still exports the old name must keep working."""
        environ = {"TOPSAILAI_SCAN_MAX_TOKENS": "500"}
        self.assertEqual(
            env_compat.get_env("TOPSAILAI_CLI_SCAN_MAX_TOKENS", environ=environ),
            "500",
        )

    def test_the_prefixed_name_wins_when_both_are_present(self):
        """The new name must win so a migration can be done one variable at a time."""
        environ = {
            "TOPSAILAI_CLI_SCAN_MAX_TOKENS": "500",
            "TOPSAILAI_SCAN_MAX_TOKENS": "900",
        }
        self.assertEqual(
            env_compat.get_env("TOPSAILAI_CLI_SCAN_MAX_TOKENS", environ=environ),
            "500",
        )

    def test_an_empty_prefixed_value_does_not_fall_back(self):
        """An empty value is configured, because one variable means something by it."""
        environ = {
            "TOPSAILAI_CLI_SCAN_INCLUDE_FILES": "",
            "TOPSAILAI_SCAN_INCLUDE_FILES": "1",
        }
        self.assertEqual(
            env_compat.get_env("TOPSAILAI_CLI_SCAN_INCLUDE_FILES", environ=environ),
            "",
        )

    def test_the_default_is_returned_when_neither_name_is_present(self):
        """An unconfigured variable must return the caller's default."""
        self.assertEqual(
            env_compat.get_env(
                "TOPSAILAI_CLI_SCAN_MAX_TOKENS", environ={}, default="20000"
            ),
            "20000",
        )

    def test_a_name_without_a_legacy_counterpart_returns_the_default(self):
        """A variable that was never renamed must not invent a fallback."""
        self.assertIsNone(
            env_compat.get_env("TOPSAILAI_CLI_RESUME_CONFIRM_SECONDS", environ={})
        )

    def test_the_legacy_name_warns_once(self):
        """A deprecated name must be reported, but only once per process."""
        environ = {"TOPSAILAI_SCAN_MAX_TOKENS": "500"}
        captured = StringIO()
        with patch("sys.stderr", captured):
            env_compat.get_env("TOPSAILAI_CLI_SCAN_MAX_TOKENS", environ=environ)
            env_compat.get_env("TOPSAILAI_CLI_SCAN_MAX_TOKENS", environ=environ)
        output = captured.getvalue()
        self.assertEqual(output.count("TOPSAILAI_SCAN_MAX_TOKENS"), 1)
        self.assertIn("TOPSAILAI_CLI_SCAN_MAX_TOKENS", output)

    def test_warning_can_be_suppressed(self):
        """A caller that resolves many variables must be able to stay quiet."""
        environ = {"TOPSAILAI_SCAN_MAX_TOKENS": "500"}
        captured = StringIO()
        with patch("sys.stderr", captured):
            env_compat.get_env(
                "TOPSAILAI_CLI_SCAN_MAX_TOKENS", environ=environ, warn=False
            )
        self.assertEqual(captured.getvalue(), "")

    def test_the_process_environment_is_read_by_default(self):
        """A caller that passes no mapping must read the process environment."""
        with patch.dict(
            os.environ, {"TOPSAILAI_CLI_SCAN_MAX_TOKENS": "700"}, clear=False
        ):
            self.assertEqual(
                env_compat.get_env("TOPSAILAI_CLI_SCAN_MAX_TOKENS"), "700"
            )


class HasEnvTest(unittest.TestCase):
    """Pin how presence is reported for a prefixed name and its legacy name."""

    def test_the_prefixed_name_counts_as_present(self):
        """A migrated variable must be reported as present."""
        self.assertTrue(
            env_compat.has_env(
                "TOPSAILAI_CLI_SCAN_MAX_TOKENS",
                environ={"TOPSAILAI_CLI_SCAN_MAX_TOKENS": "1"},
            )
        )

    def test_the_legacy_name_counts_as_present(self):
        """An old name must be reported as present so callers do not ignore it."""
        self.assertTrue(
            env_compat.has_env(
                "TOPSAILAI_CLI_SCAN_MAX_TOKENS",
                environ={"TOPSAILAI_SCAN_MAX_TOKENS": "1"},
            )
        )

    def test_absence_is_reported(self):
        """Neither name present must report absence."""
        self.assertFalse(
            env_compat.has_env("TOPSAILAI_CLI_SCAN_MAX_TOKENS", environ={})
        )


class LegacyNameMapTest(unittest.TestCase):
    """Pin the shape of the legacy name map."""

    def test_every_prefixed_name_uses_the_cli_namespace(self):
        """A renamed CLI variable must carry the TOPSAILAI_CLI_ prefix."""
        for name in env_compat.LEGACY_NAMES:
            self.assertTrue(
                name.startswith("TOPSAILAI_CLI_"),
                f"{name} does not use the CLI namespace",
            )

    def test_no_legacy_name_uses_the_cli_namespace(self):
        """A legacy name must be the unprefixed form it replaced."""
        for legacy in env_compat.LEGACY_NAMES.values():
            self.assertFalse(
                legacy.startswith("TOPSAILAI_CLI_"),
                f"{legacy} is not a legacy name",
            )

    def test_legacy_name_lookup(self):
        """The lookup must return the legacy name and nothing else."""
        self.assertEqual(
            env_compat.legacy_name("TOPSAILAI_CLI_SCAN_MAX_TOKENS"),
            "TOPSAILAI_SCAN_MAX_TOKENS",
        )
        self.assertIsNone(env_compat.legacy_name("TOPSAILAI_CLI_UNKNOWN"))


if __name__ == "__main__":
    unittest.main()
