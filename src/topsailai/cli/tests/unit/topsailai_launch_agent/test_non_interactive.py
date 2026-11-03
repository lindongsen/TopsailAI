#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the --non-interactive option in topsailai_launch_agent.

``--non-interactive`` promises that the launcher itself never prompts: a
missing settings file uses the built-in default configuration, an existing
configuration uses the ``default`` context item when present, and any remaining
ambiguity falls back to the base item ``_`` so an agent is always launched.

The flag governs only this CLI's own prompting. It must not change the launched
agent's ``TOPSAILAI_INTERACTIVE_MODE``.
"""

import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest import mock

# Ensure the CLI source is importable.
CLI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, CLI_DIR)

import topsailai_launch_agent as launcher


# Every helper that can ask the user something. Patching them to raise proves
# the non-interactive path never reaches a prompt.
_PROMPT_HELPERS = (
    "_prompt",
    "_prompt_yn",
    "_prompt_list",
    "_prompt_context_sources",
    "_timed_input",
    "_timed_prompt",
    "_timed_prompt_yn",
    "_run_interactive_setup",
    "_run_context_setup",
    "_select_context_item",
    "_select_driver",
)


class NonInteractiveTestBase(unittest.TestCase):
    """Shared harness for the non-interactive launcher tests."""

    def setUp(self):
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv
        self._stdout = StringIO()
        self._stderr = StringIO()

    def tearDown(self):
        os.chdir(self._original_dir)
        sys.argv = self._original_argv

    def _write_settings(self, workspace, context=None, environment=None,
                        driver="test-driver"):
        """Write a minimal settings.yaml and return its path."""
        settings_dir = os.path.join(workspace, ".topsailai")
        os.makedirs(settings_dir, exist_ok=True)
        settings_path = os.path.join(settings_dir, "settings.yaml")
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write(f'ai_agent_driver: "{driver}"\n')
            f.write('workspace: "."\n')
            f.write("context:\n")
            if context is None:
                f.write("  _: []\n")
            else:
                for key, value in context.items():
                    if not value:
                        f.write(f"  {key}: []\n")
                    else:
                        f.write(f"  {key}:\n")
                        for path in value:
                            f.write(f'    - "{path}"\n')
            f.write("environment:\n")
            if environment is None:
                f.write("  _: {}\n")
            else:
                for key, value in environment.items():
                    if not value:
                        f.write(f"  {key}: {{}}\n")
                    else:
                        f.write(f"  {key}:\n")
                        for env_key, env_value in value.items():
                            f.write(f'    {env_key}: "{env_value}"\n')
        return settings_path

    def _run_main(self, argv, isatty=True, forbid_prompts=True):
        """Run main() with a simulated TTY and no reachable prompt helper."""
        sys.argv = argv
        patches = [
            mock.patch("sys.stdout", self._stdout),
            mock.patch("sys.stderr", self._stderr),
            mock.patch("sys.stdin.isatty", return_value=isatty),
            mock.patch.object(launcher, "_driver_exists", return_value=True),
        ]
        if forbid_prompts:
            for name in _PROMPT_HELPERS:
                patches.append(
                    mock.patch.object(
                        launcher,
                        name,
                        side_effect=AssertionError(
                            f"{name} must not be called with --non-interactive"
                        ),
                    )
                )
        for patch in patches:
            patch.start()
        try:
            with self.assertRaises(SystemExit) as cm:
                launcher.main()
        finally:
            for patch in reversed(patches):
                patch.stop()
        return cm.exception.code


class TestNonInteractiveMissingSettings(NonInteractiveTestBase):
    """A missing settings file must launch with the built-in defaults."""

    def test_missing_settings_uses_default_config_without_prompt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            settings_path = os.path.join(tmpdir, ".topsailai", "settings.yaml")

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--non-interactive", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            self.assertFalse(os.path.isfile(settings_path))
            self.assertIn(
                launcher.DEFAULT_CONFIG["ai_agent_driver"],
                self._stdout.getvalue(),
            )
            self.assertIn(
                "--non-interactive requested", self._stderr.getvalue()
            )

    def test_missing_settings_does_not_prompt_even_on_a_tty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)

            # forbid_prompts=True already fails the test if any prompt helper
            # is reached; the TTY simulation makes the interactive branch
            # reachable so the assertion is meaningful.
            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--non-interactive", "--dry-run"],
                isatty=True,
            )

            self.assertEqual(exit_code, 0)
            self.assertNotIn("Choose how to proceed", self._stderr.getvalue())

    def test_missing_settings_keeps_interactive_mode_env(self):
        """The flag must not flip the agent's TOPSAILAI_INTERACTIVE_MODE."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--non-interactive", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            output = self._stdout.getvalue()
            self.assertIn(
                f"TOPSAILAI_INTERACTIVE_MODE="
                f"{launcher.DEFAULT_CONFIG['environment']['_']['TOPSAILAI_INTERACTIVE_MODE']}",
                output,
            )
            self.assertNotIn("TOPSAILAI_INTERACTIVE_MODE=0", output)


class TestNonInteractiveItemSelection(NonInteractiveTestBase):
    """Item resolution must be deterministic and prompt-free."""

    def test_default_item_is_used_when_configured(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={"_": [], "default": [], "memo": []},
                environment={"_": {"TOPSAILAI_INTERACTIVE_MODE": "1"}},
            )

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--non-interactive", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            self.assertIn(
                "[TopsailAI-Launcher] Context item: default",
                self._stdout.getvalue(),
            )
            self.assertNotIn(
                "Multiple context items are configured",
                self._stderr.getvalue(),
            )

    def test_single_item_is_used_automatically(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={"_": [], "memo": []},
                environment={"_": {"TOPSAILAI_INTERACTIVE_MODE": "1"}},
            )

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--non-interactive", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            self.assertIn(
                "[TopsailAI-Launcher] Context item: memo",
                self._stdout.getvalue(),
            )

    def test_multiple_items_without_default_fall_back_to_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={"_": [], "memo": [], "review": []},
                environment={"_": {"TOPSAILAI_INTERACTIVE_MODE": "1"}},
            )

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--non-interactive", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            self.assertIn(
                "[TopsailAI-Launcher] Context item: _",
                self._stdout.getvalue(),
            )
            stderr_output = self._stderr.getvalue()
            self.assertIn("none is 'default'", stderr_output)
            self.assertIn("memo, review", stderr_output)

    def test_empty_context_skips_setup_prompt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={},
                environment={"_": {"TOPSAILAI_INTERACTIVE_MODE": "1"}},
            )

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--non-interactive", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            self.assertIn(
                "[TopsailAI-Launcher] Context item: _",
                self._stdout.getvalue(),
            )
            stderr_output = self._stderr.getvalue()
            self.assertIn("context is empty", stderr_output)
            self.assertIn("--non-interactive", stderr_output)
            self.assertNotIn("Would you like to configure context", stderr_output)

    def test_explicit_item_is_respected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={"_": [], "default": [], "memo": []},
                environment={"_": {"TOPSAILAI_INTERACTIVE_MODE": "1"}},
            )

            exit_code = self._run_main(
                [
                    "topsailai_launch_agent.py",
                    "--non-interactive",
                    "--item",
                    "memo",
                    "--dry-run",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertIn(
                "[TopsailAI-Launcher] Context item: memo",
                self._stdout.getvalue(),
            )

    def test_interactive_mode_env_from_settings_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={"_": [], "default": []},
                environment={"_": {"TOPSAILAI_INTERACTIVE_MODE": "1"}},
            )

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--non-interactive", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            output = self._stdout.getvalue()
            self.assertIn("TOPSAILAI_INTERACTIVE_MODE=1", output)
            self.assertNotIn("TOPSAILAI_INTERACTIVE_MODE=0", output)


class TestNonInteractiveFlagConflicts(NonInteractiveTestBase):
    """Flags that exist only to open an interactive flow must be rejected."""

    def _run_expecting_parser_error(self, argv):
        sys.argv = argv
        with mock.patch("sys.stdout", self._stdout), mock.patch(
            "sys.stderr", self._stderr
        ):
            with self.assertRaises(SystemExit) as cm:
                launcher.main()
        return cm.exception.code

    def test_setup_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)

            exit_code = self._run_expecting_parser_error(
                ["topsailai_launch_agent.py", "--non-interactive", "--setup"]
            )

            self.assertEqual(exit_code, 2)
            self.assertIn(
                "--non-interactive cannot be combined with --setup",
                self._stderr.getvalue(),
            )

    def test_select_driver_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)

            exit_code = self._run_expecting_parser_error(
                [
                    "topsailai_launch_agent.py",
                    "--non-interactive",
                    "--select-driver",
                ]
            )

            self.assertEqual(exit_code, 2)
            self.assertIn(
                "--non-interactive cannot be combined with --select-driver",
                self._stderr.getvalue(),
            )


class TestResolveNonInteractiveItem(unittest.TestCase):
    """Verify the prompt-free item preference order."""

    def test_default_wins(self):
        self.assertEqual(
            launcher._resolve_non_interactive_item(["memo", "default", "review"]),
            ("default", False),
        )

    def test_single_item_is_used(self):
        self.assertEqual(
            launcher._resolve_non_interactive_item(["memo"]), ("memo", False)
        )

    def test_multiple_items_without_default_fall_back(self):
        self.assertEqual(
            launcher._resolve_non_interactive_item(["memo", "review"]),
            ("_", True),
        )

    def test_no_items_fall_back(self):
        self.assertEqual(launcher._resolve_non_interactive_item([]), ("_", True))


if __name__ == "__main__":
    unittest.main()
