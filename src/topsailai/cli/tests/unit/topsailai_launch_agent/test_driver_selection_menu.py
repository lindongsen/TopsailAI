#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for interactive agent-driver selection in topsailai_launch_agent.

Author: DawsonLin
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


class TestDriverMenuOptions(unittest.TestCase):
    """Verify the menu candidate list and its single source of truth."""

    def test_menu_options_match_shared_resume_driver_options(self):
        """The launcher-local list must equal the shared resume driver list."""
        from cli_topsailai.legacy_resume_cli import RESUME_DRIVER_OPTIONS

        self.assertEqual(
            tuple(launcher._DRIVER_MENU_OPTIONS), tuple(RESUME_DRIVER_OPTIONS)
        )

    def test_current_driver_is_listed_first_without_duplicates(self):
        """The current driver leads the list and is not repeated."""
        options = launcher._driver_menu_options("topsailai_agent_chats")
        self.assertEqual(options[0], "topsailai_agent_chats")
        self.assertEqual(options.count("topsailai_agent_chats"), 1)
        self.assertEqual(len(options), len(launcher._DRIVER_MENU_OPTIONS))

    def test_unknown_current_driver_is_prepended(self):
        """A custom current driver is offered alongside the built-in ones."""
        options = launcher._driver_menu_options("my-custom-driver")
        self.assertEqual(options[0], "my-custom-driver")
        self.assertEqual(
            len(options), len(launcher._DRIVER_MENU_OPTIONS) + 1
        )

    def test_no_current_driver_lists_builtins_only(self):
        """An empty current driver yields exactly the built-in list."""
        self.assertEqual(
            launcher._driver_menu_options(""),
            list(launcher._DRIVER_MENU_OPTIONS),
        )


class TestSelectDriver(unittest.TestCase):
    """Verify the driver menu prompt behavior."""

    def setUp(self):
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._patches = [
            mock.patch("sys.stdout", self._stdout),
            mock.patch("sys.stderr", self._stderr),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self._patches):
            patch.stop()

    def _select(self, answers, options=None, current="topsailai_agent_chats",
                exists=True):
        """Run _select_driver with scripted prompt answers."""
        options = options if options is not None else launcher._driver_menu_options(
            current
        )
        with mock.patch.object(
            launcher, "_timed_prompt", side_effect=answers
        ), mock.patch.object(
            launcher, "_driver_exists", return_value=exists
        ):
            return launcher._select_driver(current, options, timeout=10.0)

    def test_selects_by_number(self):
        """A numeric answer returns the driver at that position."""
        options = launcher._driver_menu_options("topsailai_agent_chats")
        self.assertEqual(self._select(["2"], options=options), options[1])

    def test_selects_by_exact_name(self):
        """An exact driver name returns that driver."""
        self.assertEqual(
            self._select(["ai-team-flow-dev"]), "ai-team-flow-dev"
        )

    def test_empty_answer_returns_to_item_page(self):
        """An empty answer keeps the current driver."""
        self.assertEqual(self._select([""]), "")

    def test_back_command_returns_to_item_page(self):
        """'b' keeps the current driver and returns to the item page."""
        self.assertEqual(self._select(["b"]), "")

    def test_timeout_returns_to_item_page(self):
        """A prompt timeout yields the 'b' default and keeps the driver."""
        with mock.patch.object(
            launcher, "_timed_prompt", return_value="b"
        ), mock.patch.object(launcher, "_driver_exists", return_value=True):
            result = launcher._select_driver(
                "topsailai_agent_chats",
                launcher._driver_menu_options("topsailai_agent_chats"),
                timeout=0.01,
            )
        self.assertEqual(result, "")

    def test_custom_command_is_accepted_when_resolvable(self):
        """'c' followed by a resolvable command returns that command."""
        self.assertEqual(
            self._select(["c", "python3 my_driver.py"]), "python3 my_driver.py"
        )

    def test_custom_command_is_rejected_when_unresolvable(self):
        """An unresolvable custom command is rejected and the menu continues."""
        with mock.patch.object(
            launcher, "_timed_prompt", side_effect=["c", "missing-driver", "b"]
        ), mock.patch.object(
            launcher, "_driver_exists", return_value=False
        ):
            result = launcher._select_driver(
                "topsailai_agent_chats",
                launcher._driver_menu_options("topsailai_agent_chats"),
                timeout=10.0,
            )
        self.assertEqual(result, "")
        self.assertIn("Driver not found: missing-driver", self._stderr.getvalue())

    def test_unresolvable_numbered_driver_is_rejected(self):
        """A numbered choice that cannot be resolved is not returned."""
        options = launcher._driver_menu_options("topsailai_agent_chats")
        with mock.patch.object(
            launcher, "_timed_prompt", side_effect=["2", "b"]
        ), mock.patch.object(
            launcher, "_driver_exists", return_value=False
        ):
            result = launcher._select_driver(
                "topsailai_agent_chats", options, timeout=10.0
            )
        self.assertEqual(result, "")
        self.assertIn("Driver not found", self._stderr.getvalue())

    def test_invalid_answers_are_bounded(self):
        """Repeated invalid answers stop the menu instead of looping forever."""
        with mock.patch.object(
            launcher, "_timed_prompt", return_value="nonsense"
        ), mock.patch.object(launcher, "_driver_exists", return_value=True):
            result = launcher._select_driver(
                "topsailai_agent_chats",
                launcher._driver_menu_options("topsailai_agent_chats"),
                timeout=10.0,
            )
        self.assertEqual(result, "")
        self.assertIn("Too many invalid selections", self._stderr.getvalue())

    def test_current_driver_is_marked(self):
        """The menu marks the current driver so the user sees the baseline."""
        self._select(["b"])
        self.assertIn("topsailai_agent_chats (current)", self._stderr.getvalue())


class TestItemPageDriverCommand(unittest.TestCase):
    """Verify the 'd' command on the context-item page."""

    def setUp(self):
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._patches = [
            mock.patch("sys.stdout", self._stdout),
            mock.patch("sys.stderr", self._stderr),
            mock.patch("sys.stdin.isatty", return_value=True),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self._patches):
            patch.stop()

    def _select_item(self, answers, context_map, current_driver="base-driver"):
        state = launcher.SelectionState()
        with mock.patch.object(
            launcher, "_timed_prompt", side_effect=answers
        ), mock.patch.object(launcher, "_driver_exists", return_value=True):
            item = launcher._select_context_item(
                context_map,
                {},
                timeout=10.0,
                state=state,
                current_driver=current_driver,
            )
        return item, state

    def test_d_opens_menu_then_returns_to_item_page(self):
        """'d' selects a driver, re-renders the item page, and the item is chosen."""
        context_map = {"_": [], "default": [], "memo": []}
        item, state = self._select_item(
            ["d", "2", "memo"], context_map
        )

        self.assertEqual(item, "memo")
        self.assertEqual(state.item, "memo")
        self.assertEqual(state.driver_override, "topsailai_agent_chats")
        # The item page is rendered once on entry and once after the menu.
        self.assertEqual(
            self._stderr.getvalue().count("Multiple context items are configured"),
            2,
        )
        self.assertIn("Driver selected: topsailai_agent_chats", self._stderr.getvalue())

    def test_driver_word_alias_opens_menu(self):
        """The 'driver' alias behaves like 'd'."""
        context_map = {"_": [], "default": [], "memo": []}
        item, state = self._select_item(["driver", "3", "default"], context_map)

        self.assertEqual(item, "default")
        self.assertEqual(state.driver_override, "topsailai_agent_plan_tasks")

    def test_back_from_menu_keeps_current_driver(self):
        """Returning from the menu leaves the driver override unset."""
        context_map = {"_": [], "default": [], "memo": []}
        item, state = self._select_item(["d", "b", "memo"], context_map)

        self.assertEqual(item, "memo")
        self.assertEqual(state.driver_override, "")

    def test_item_named_d_is_not_shadowed(self):
        """An item literally named 'd' is selected as an item, not a command."""
        context_map = {"_": [], "d": [], "memo": []}
        item, state = self._select_item(["d"], context_map)

        self.assertEqual(item, "d")
        self.assertEqual(state.driver_override, "")
        self.assertNotIn("Select the agent driver to launch", self._stderr.getvalue())

    def test_item_named_driver_is_not_shadowed(self):
        """An item literally named 'driver' is selected as an item."""
        context_map = {"_": [], "driver": [], "memo": []}
        item, state = self._select_item(["driver"], context_map)

        self.assertEqual(item, "driver")
        self.assertEqual(state.driver_override, "")

    def test_state_is_optional_for_existing_callers(self):
        """Omitting state keeps the historical string return value."""
        context_map = {"_": [], "default": [], "memo": []}
        with mock.patch.object(
            launcher, "_timed_prompt", return_value="memo"
        ), mock.patch.object(launcher, "_driver_exists", return_value=True):
            item = launcher._select_context_item(context_map, {}, timeout=10.0)
        self.assertEqual(item, "memo")

    def test_invalid_answer_message_mentions_driver_command(self):
        """The invalid-selection hint advertises the driver command."""
        context_map = {"_": [], "default": [], "memo": []}
        self._select_item(["bogus", "memo"], context_map)
        self.assertIn(
            "'d' to select the agent driver", self._stderr.getvalue()
        )


class TestMainDriverPrecedence(unittest.TestCase):
    """Verify the menu choice wins over every settings.yaml driver source."""

    def setUp(self):
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv
        self._original_env_driver = os.environ.get("TOPSAILAI_AGENT_DRIVER")
        self._stdout = StringIO()
        self._stderr = StringIO()

    def tearDown(self):
        os.chdir(self._original_dir)
        sys.argv = self._original_argv
        if self._original_env_driver is not None:
            os.environ["TOPSAILAI_AGENT_DRIVER"] = self._original_env_driver
        elif "TOPSAILAI_AGENT_DRIVER" in os.environ:
            del os.environ["TOPSAILAI_AGENT_DRIVER"]

    def _write_settings(self, workspace, context, environment, driver="file-driver"):
        settings_dir = os.path.join(workspace, ".topsailai")
        os.makedirs(settings_dir, exist_ok=True)
        settings_path = os.path.join(settings_dir, "settings.yaml")
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write(f'ai_agent_driver: "{driver}"\n')
            f.write('workspace: "."\n')
            f.write("context:\n")
            for key, value in context.items():
                if not value:
                    f.write(f"  {key}: []\n")
                else:
                    f.write(f"  {key}:\n")
                    for path in value:
                        f.write(f'    - "{path}"\n')
            f.write("environment:\n")
            for key, value in environment.items():
                if not value:
                    f.write(f"  {key}: {{}}\n")
                else:
                    f.write(f"  {key}:\n")
                    for env_key, env_value in value.items():
                        f.write(f'    {env_key}: "{env_value}"\n')
        return settings_path

    def _run_main(self, argv, answers, isatty=True):
        sys.argv = argv
        with mock.patch("sys.stdout", self._stdout), mock.patch(
            "sys.stderr", self._stderr
        ), mock.patch("sys.stdin.isatty", return_value=isatty), mock.patch.object(
            launcher, "_timed_prompt", side_effect=answers
        ), mock.patch.object(
            launcher, "_driver_exists", return_value=True
        ):
            with self.assertRaises(SystemExit) as cm:
                launcher.main()
        return cm.exception.code

    def _multi_item_settings(self, tmpdir):
        return self._write_settings(
            tmpdir,
            context={
                "_": ["base.md"],
                "default": ["default.md"],
                "memo": ["memo.md"],
            },
            environment={
                "_": {"TOPSAILAI_INTERACTIVE_MODE": "1"},
                "default": {"TOPSAILAI_AGENT_DRIVER": "item-env-driver"},
                "memo": {"TOPSAILAI_AGENT_DRIVER": "memo-env-driver"},
            },
            driver="file-driver",
        )

    def test_menu_choice_overrides_driver_flag(self):
        """The menu choice beats --driver."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._multi_item_settings(tmpdir)

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run", "--driver", "flag-driver"],
                answers=["d", "2", "memo"],
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn("topsailai_agent_chats", stdout_output)
            self.assertNotIn("flag-driver", stdout_output)

    def test_menu_choice_overrides_item_environment(self):
        """The menu choice beats the selected item's TOPSAILAI_AGENT_DRIVER."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._multi_item_settings(tmpdir)

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"],
                answers=["d", "3", "memo"],
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn("topsailai_agent_plan_tasks", stdout_output)
            self.assertNotIn("memo-env-driver", stdout_output)

    def test_menu_choice_overrides_os_environment(self):
        """The menu choice beats TOPSAILAI_AGENT_DRIVER from the OS environment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                context={"_": ["base.md"], "default": [], "memo": []},
                environment={"_": {"TOPSAILAI_INTERACTIVE_MODE": "1"}},
                driver="file-driver",
            )
            os.environ["TOPSAILAI_AGENT_DRIVER"] = "os-driver"

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"],
                answers=["d", "2", "memo"],
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn("topsailai_agent_chats", stdout_output)
            self.assertNotIn("os-driver", stdout_output)

    def test_without_menu_choice_priority_is_unchanged(self):
        """Not using the menu preserves the historical priority order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._multi_item_settings(tmpdir)

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run"],
                answers=["memo"],
            )

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn("memo-env-driver", stdout_output)
            self.assertNotIn("file-driver", stdout_output)

    def test_driver_flag_still_wins_without_menu_choice(self):
        """--driver keeps its precedence when the menu is not used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._multi_item_settings(tmpdir)

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run", "--driver", "flag-driver"],
                answers=["memo"],
            )

            self.assertEqual(exit_code, 0)
            self.assertIn("flag-driver", self._stdout.getvalue())


class TestSelectDriverFlag(unittest.TestCase):
    """Verify --select-driver reaches the menu when no item page is shown."""

    def setUp(self):
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv
        self._stdout = StringIO()
        self._stderr = StringIO()

    def tearDown(self):
        os.chdir(self._original_dir)
        sys.argv = self._original_argv

    def _write_single_item_settings(self, workspace):
        settings_dir = os.path.join(workspace, ".topsailai")
        os.makedirs(settings_dir, exist_ok=True)
        settings_path = os.path.join(settings_dir, "settings.yaml")
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write('ai_agent_driver: "file-driver"\n')
            f.write('workspace: "."\n')
            f.write("context:\n")
            f.write("  _: []\n")
            f.write("  memo:\n")
            f.write('    - "memo.md"\n')
            f.write("environment:\n")
            f.write("  _: {}\n")
            f.write("  memo: {}\n")
        return settings_path

    def _run_main(self, argv, answers, isatty):
        sys.argv = argv
        with mock.patch("sys.stdout", self._stdout), mock.patch(
            "sys.stderr", self._stderr
        ), mock.patch("sys.stdin.isatty", return_value=isatty), mock.patch.object(
            launcher, "_timed_prompt", side_effect=answers
        ), mock.patch.object(
            launcher, "_driver_exists", return_value=True
        ):
            with self.assertRaises(SystemExit) as cm:
                launcher.main()
        return cm.exception.code

    def test_select_driver_opens_menu_with_single_item(self):
        """--select-driver opens the menu even when the item page is skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_single_item_settings(tmpdir)

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run", "--select-driver"],
                answers=["2"],
                isatty=True,
            )

            self.assertEqual(exit_code, 0)
            self.assertIn(
                "Select the agent driver to launch", self._stderr.getvalue()
            )
            stdout_output = self._stdout.getvalue()
            self.assertIn("topsailai_agent_chats", stdout_output)
            self.assertNotIn("file-driver", stdout_output)

    def test_select_driver_warns_in_non_tty(self):
        """--select-driver never blocks when stdin is not a terminal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_single_item_settings(tmpdir)

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run", "--select-driver"],
                answers=[],
                isatty=False,
            )

            self.assertEqual(exit_code, 0)
            self.assertIn(
                "--select-driver ignored because stdin is not a terminal",
                self._stderr.getvalue(),
            )
            self.assertIn("file-driver", self._stdout.getvalue())

    def test_select_driver_back_keeps_resolved_driver(self):
        """Returning from the menu keeps the settings.yaml driver."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_single_item_settings(tmpdir)

            exit_code = self._run_main(
                ["topsailai_launch_agent.py", "--dry-run", "--select-driver"],
                answers=["b"],
                isatty=True,
            )

            self.assertEqual(exit_code, 0)
            self.assertIn("file-driver", self._stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
