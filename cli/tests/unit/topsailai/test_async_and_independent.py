#!/usr/bin/env python3
"""
Unit tests for async and independent_process configuration in topsailai.py.

Covers:
- is_independent_process()
- is_async_command()
- run_external_command() with async_cmd=True
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import topsailai as cli


class TestIsIndependentProcess(unittest.TestCase):
    """Tests for is_independent_process."""

    def test_bool_true(self):
        """Boolean True is independent."""
        self.assertTrue(cli.is_independent_process({"independent_process": True}))

    def test_bool_false(self):
        """Boolean False is not independent."""
        self.assertFalse(cli.is_independent_process({"independent_process": False}))

    def test_int_one(self):
        """Integer 1 is independent."""
        self.assertTrue(cli.is_independent_process({"independent_process": 1}))

    def test_int_zero(self):
        """Integer 0 is not independent."""
        self.assertFalse(cli.is_independent_process({"independent_process": 0}))

    def test_string_true(self):
        """String 'true' is independent."""
        self.assertTrue(cli.is_independent_process({"independent_process": "true"}))

    def test_string_one(self):
        """String '1' is independent."""
        self.assertTrue(cli.is_independent_process({"independent_process": "1"}))

    def test_string_yes(self):
        """String 'yes' is independent."""
        self.assertTrue(cli.is_independent_process({"independent_process": "yes"}))

    def test_string_false(self):
        """String 'false' is not independent."""
        self.assertFalse(cli.is_independent_process({"independent_process": "false"}))

    def test_missing_key(self):
        """Missing key defaults to False."""
        self.assertFalse(cli.is_independent_process({}))


class TestIsAsyncCommand(unittest.TestCase):
    """Tests for is_async_command."""

    def test_bool_true(self):
        """Boolean True is async."""
        self.assertTrue(cli.is_async_command({"async": True}))

    def test_bool_false(self):
        """Boolean False is not async."""
        self.assertFalse(cli.is_async_command({"async": False}))

    def test_int_one(self):
        """Integer 1 is async."""
        self.assertTrue(cli.is_async_command({"async": 1}))

    def test_int_zero(self):
        """Integer 0 is not async."""
        self.assertFalse(cli.is_async_command({"async": 0}))

    def test_string_true(self):
        """String 'true' is async."""
        self.assertTrue(cli.is_async_command({"async": "true"}))

    def test_string_one(self):
        """String '1' is async."""
        self.assertTrue(cli.is_async_command({"async": "1"}))

    def test_string_yes(self):
        """String 'yes' is async."""
        self.assertTrue(cli.is_async_command({"async": "yes"}))

    def test_string_false(self):
        """String 'false' is not async."""
        self.assertFalse(cli.is_async_command({"async": "false"}))

    def test_missing_key(self):
        """Missing key defaults to False."""
        self.assertFalse(cli.is_async_command({}))


class TestRunExternalCommandAsync(unittest.TestCase):
    """Tests for run_external_command with async_cmd=True."""

    def tearDown(self):
        cli._child_processes.clear()

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_async_launches_background(self, mock_print, mock_popen):
        """Async command launches process and returns immediately."""
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        cli.run_external_command(
            ["echo", "hello"],
            {},
            independent=False,
            async_cmd=True,
        )

        mock_popen.assert_called_once()
        kwargs = mock_popen.call_args.kwargs
        self.assertEqual(kwargs.get("stdout"), cli.subprocess.DEVNULL)
        self.assertEqual(kwargs.get("stderr"), cli.subprocess.DEVNULL)
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("Async process started" in p for p in printed))
        self.assertTrue(any("pid=12345" in p for p in printed))

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_async_uses_independent_kwargs(self, mock_print, mock_popen):
        """Async command uses start_new_session or DETACHED_PROCESS."""
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_popen.return_value = mock_proc

        cli.run_external_command(
            ["sleep", "10"],
            {},
            independent=False,
            async_cmd=True,
        )

        kwargs = mock_popen.call_args.kwargs
        if sys.platform == "win32":
            self.assertIn("creationflags", kwargs)
        else:
            self.assertTrue(kwargs.get("start_new_session"))

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_async_no_communicate(self, mock_print, mock_popen):
        """Async command does not call communicate."""
        mock_proc = MagicMock()
        mock_proc.pid = 1111
        mock_popen.return_value = mock_proc

        cli.run_external_command(
            ["echo", "hi"],
            {},
            independent=False,
            async_cmd=True,
        )

        mock_proc.communicate.assert_not_called()

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_non_async_runs_synchronously(self, mock_print, mock_popen):
        """Non-async command runs synchronously and prints output."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("sync output\n", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        cli.run_external_command(
            ["echo", "hello"],
            {},
            independent=False,
            async_cmd=False,
        )

        mock_proc.communicate.assert_called_once()
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("Execution completed" in p for p in printed))


class TestHandleYamlCommandAsync(unittest.TestCase):
    """Tests that handle_yaml_command passes async flag correctly."""

    def setUp(self):
        cli.current_scope = "session"
        cli.current_session_id = "s1"

    def tearDown(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli._child_processes.clear()

    @patch("topsailai.run_external_command")
    @patch("builtins.print")
    def test_async_passed_to_run_external(self, mock_print, mock_run):
        """Async instruction passes async_cmd=True to run_external_command."""
        instruction = {
            "cmd": "/task.async {driver}",
            "shell": "run {driver}",
            "async": True,
            "independent_process": True,
        }
        variables = {"driver": "ai-team-flow-dev"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        args = mock_run.call_args
        self.assertTrue(args.kwargs.get("async_cmd") or args.args[3])

    @patch("topsailai.run_external_command")
    @patch("builtins.print")
    def test_non_async_passed_to_run_external(self, mock_print, mock_run):
        """Non-async instruction passes async_cmd=False to run_external_command."""
        instruction = {
            "cmd": "/task.run {driver}",
            "shell": "run {driver}",
            "async": False,
        }
        variables = {"driver": "ai-team-flow-dev"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        args = mock_run.call_args
        self.assertFalse(args.kwargs.get("async_cmd") or args.args[3])


if __name__ == "__main__":
    unittest.main()


class TestIsUseOsSystem(unittest.TestCase):
    """Tests for is_use_os_system."""

    def test_bool_true(self):
        """Boolean True uses os.system."""
        self.assertTrue(cli.is_use_os_system({"use_os_system": True}))

    def test_bool_false(self):
        """Boolean False does not use os.system."""
        self.assertFalse(cli.is_use_os_system({"use_os_system": False}))

    def test_int_one(self):
        """Integer 1 uses os.system."""
        self.assertTrue(cli.is_use_os_system({"use_os_system": 1}))

    def test_int_zero(self):
        """Integer 0 does not use os.system."""
        self.assertFalse(cli.is_use_os_system({"use_os_system": 0}))

    def test_string_true(self):
        """String 'true' uses os.system."""
        self.assertTrue(cli.is_use_os_system({"use_os_system": "true"}))

    def test_string_one(self):
        """String '1' uses os.system."""
        self.assertTrue(cli.is_use_os_system({"use_os_system": "1"}))

    def test_string_yes(self):
        """String 'yes' uses os.system."""
        self.assertTrue(cli.is_use_os_system({"use_os_system": "yes"}))

    def test_string_false(self):
        """String 'false' does not use os.system."""
        self.assertFalse(cli.is_use_os_system({"use_os_system": "false"}))

    def test_missing_key(self):
        """Missing key defaults to False."""
        self.assertFalse(cli.is_use_os_system({}))


class TestRunExternalCommandOsSystem(unittest.TestCase):
    """Tests for run_external_command with use_os_system=True."""

    def tearDown(self):
        cli._child_processes.clear()

    @patch("topsailai.os.system")
    @patch("builtins.print")
    def test_os_system_executes(self, mock_print, mock_system):
        """use_os_system=True executes via os.system."""
        mock_system.return_value = 0

        cli.run_external_command(
            ["echo", "hello"],
            {},
            independent=False,
            use_os_system=True,
        )

        mock_system.assert_called_once()
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("os.system" in p for p in printed))
        self.assertTrue(any("Execution completed" in p for p in printed))

    @patch("topsailai.os.system")
    @patch("builtins.print")
    def test_os_system_with_env(self, mock_print, mock_system):
        """use_os_system=True sets environment variables temporarily."""
        mock_system.return_value = 0
        original_value = os.environ.get("TEST_VAR")

        cli.run_external_command(
            ["echo", "hello"],
            {"TEST_VAR": "test_value"},
            independent=False,
            use_os_system=True,
        )

        self.assertEqual(os.environ.get("TEST_VAR"), original_value)
        mock_system.assert_called_once()

    @patch("topsailai.os.system")
    @patch("builtins.print")
    def test_os_system_nonzero_exit(self, mock_print, mock_system):
        """use_os_system=True prints error on non-zero exit code."""
        mock_system.return_value = 1

        cli.run_external_command(
            ["false"],
            {},
            independent=False,
            use_os_system=True,
        )

        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("exited with code 1" in p for p in printed))

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_use_os_system_skips_subprocess(self, mock_print, mock_popen):
        """use_os_system=True does not call subprocess.Popen."""
        with patch("topsailai.os.system", return_value=0):
            cli.run_external_command(
                ["echo", "hello"],
                {},
                independent=False,
                use_os_system=True,
            )
        mock_popen.assert_not_called()


class TestHandleYamlCommandOsSystem(unittest.TestCase):
    """Tests that handle_yaml_command passes use_os_system flag correctly."""

    def setUp(self):
        cli.current_scope = "session"
        cli.current_session_id = "s1"

    def tearDown(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli._child_processes.clear()

    @patch("topsailai.run_external_command")
    @patch("builtins.print")
    def test_use_os_system_passed_to_run_external(self, mock_print, mock_run):
        """use_os_system instruction passes use_os_system=True to run_external_command."""
        instruction = {
            "cmd": "/dtach",
            "shell": "dtach -A /tmp/topsailai.dtach.{session_id} bash",
            "use_os_system": True,
        }
        variables = {"session_id": "s1"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        args = mock_run.call_args
        self.assertTrue(args.kwargs.get("use_os_system") or args.args[4])

    @patch("topsailai.run_external_command")
    @patch("builtins.print")
    def test_non_use_os_system_passed_to_run_external(self, mock_print, mock_run):
        """Non-use_os_system instruction passes use_os_system=False to run_external_command."""
        instruction = {
            "cmd": "/task.run {driver}",
            "shell": "run {driver}",
        }
        variables = {"driver": "ai-team-flow-dev"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        args = mock_run.call_args
        self.assertFalse(args.kwargs.get("use_os_system") or args.args[4])


class TestLaunchIndependentProcess(unittest.TestCase):
    """Tests for launch_independent_process."""

    def tearDown(self):
        cli._child_processes.clear()

    @patch("topsailai.subprocess.Popen")
    def test_linux_uses_start_new_session(self, mock_popen):
        """Linux/macOS path uses start_new_session."""
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        with patch.object(cli.sys, "platform", "linux"):
            result = cli.launch_independent_process(["sleep", "1"])

        self.assertEqual(result, mock_proc)
        kwargs = mock_popen.call_args.kwargs
        self.assertTrue(kwargs.get("start_new_session"))
        self.assertNotIn("creationflags", kwargs)

    @patch("topsailai.subprocess.Popen")
    def test_windows_uses_detached_process(self, mock_popen):
        """Windows path uses DETACHED_PROCESS creation flag."""
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        with patch.object(cli.sys, "platform", "win32"):
            with patch.object(cli.subprocess, "DETACHED_PROCESS", 0x00000008, create=True):
                result = cli.launch_independent_process(["sleep", "1"])

        self.assertEqual(result, mock_proc)
        kwargs = mock_popen.call_args.kwargs
        self.assertEqual(kwargs.get("creationflags"), 0x00000008)
        self.assertNotIn("start_new_session", kwargs)


class TestRunExternalCommandIndependent(unittest.TestCase):
    """Tests for run_external_command with independent=True."""

    def tearDown(self):
        cli._child_processes.clear()

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_independent_runs_synchronously(self, mock_print, mock_popen):
        """Independent command runs synchronously and prints output."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("independent output\n", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        cli.run_external_command(
            ["echo", "hello"],
            {},
            independent=True,
        )

        mock_proc.communicate.assert_called_once()
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("Execution completed" in p for p in printed))

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_independent_kills_survivor(self, mock_print, mock_popen):
        """Independent command kills process still running after communicate."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.side_effect = [None, 0]
        mock_popen.return_value = mock_proc

        cli.run_external_command(
            ["sleep", "10"],
            {},
            independent=True,
        )

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=1)

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_independent_wait_exception_swallowed(self, mock_print, mock_popen):
        """Independent command swallows wait exception after kill."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.side_effect = [None, None]
        mock_proc.wait.side_effect = cli.subprocess.TimeoutExpired("cmd", 1)
        mock_popen.return_value = mock_proc

        cli.run_external_command(
            ["sleep", "10"],
            {},
            independent=True,
        )

        mock_proc.kill.assert_called_once()

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_non_independent_kills_survivor(self, mock_print, mock_popen):
        """Non-independent command kills process still running after communicate."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.side_effect = [None, 0]
        mock_popen.return_value = mock_proc

        cli.run_external_command(
            ["sleep", "10"],
            {},
            independent=False,
        )

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=1)

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_non_independent_wait_exception_swallowed(self, mock_print, mock_popen):
        """Non-independent command swallows wait exception after kill."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.side_effect = [None, None]
        mock_proc.wait.side_effect = cli.subprocess.TimeoutExpired("cmd", 1)
        mock_popen.return_value = mock_proc

        cli.run_external_command(
            ["sleep", "10"],
            {},
            independent=False,
        )

        mock_proc.kill.assert_called_once()

    @patch("topsailai.os.system")
    @patch("builtins.print")
    def test_os_system_restores_existing_env(self, mock_print, mock_system):
        """use_os_system restores pre-existing environment variable value."""
        mock_system.return_value = 0
        original_value = os.environ.get("TEST_RESTORE_VAR")
        os.environ["TEST_RESTORE_VAR"] = "original"
        try:
            cli.run_external_command(
                ["echo", "hello"],
                {"TEST_RESTORE_VAR": "new_value"},
                independent=False,
                use_os_system=True,
            )
            self.assertEqual(os.environ.get("TEST_RESTORE_VAR"), "original")
        finally:
            if original_value is None:
                os.environ.pop("TEST_RESTORE_VAR", None)
            else:
                os.environ["TEST_RESTORE_VAR"] = original_value
