#!/usr/bin/env python3
"""Unit tests for the workspace-scope watch command.

The watch command refreshes the ordinary workspace task list on a fixed
interval and prints one hint line per cycle. These tests pin the recognition
contract, the scope gate, the loop behaviour and the discovery surfaces.

Author: DawsonLin
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from cli_topsailai import completer, core, help_text, state, yaml_commands

FILES = [
    {"filename": "a.stdout", "session_id": "s1", "pid": 111, "path": "/x/a.stdout"},
    {"filename": "b.stdout", "session_id": "s2", "pid": 222, "path": "/x/b.stdout"},
]

WATCH_SPELLINGS = ["watch", "/watch", "WATCH", "/WATCH"]


def _reset_state(scope="workspace", managed=False):
    """Return a context manager that pins the prompt globals for one call."""
    return _StatePatch(scope, managed)


class _StatePatch:
    """Patch the module-level prompt state for the duration of a block."""

    def __init__(self, scope, managed):
        self.scope = scope
        self.managed = managed
        self._saved = {}

    def __enter__(self):
        for name, value in (
            ("current_scope", self.scope),
            ("current_session_id", "s1" if self.scope == "session" else None),
            ("workspace_showing_managed_projects", self.managed),
            ("history_manager", None),
            ("yaml_commands", yaml_commands.load_yaml_commands()),
        ):
            self._saved[name] = getattr(state, name)
            setattr(state, name, value)
        return state

    def __exit__(self, *exc_info):
        for name, value in self._saved.items():
            setattr(state, name, value)
        return False


def _run_command(scope, command, managed=False):
    """Return (action, value, output) for one command in one scope."""
    inputs = iter([command, "q"])
    buffer = io.StringIO()
    with _reset_state(scope, managed):
        with patch.object(core, "_read_input_with_prompt", lambda _p: next(inputs)):
            with redirect_stdout(buffer):
                action, value = core.prompt_selection(list(FILES), "/unused")
    return action, value, buffer.getvalue()


class TestWatchRecognition(unittest.TestCase):
    """The watch command is recognised only in the ordinary workspace list."""

    def test_every_spelling_returns_the_watch_list_action(self):
        for command in WATCH_SPELLINGS:
            with self.subTest(command=command):
                action, value, _ = _run_command("workspace", command)
                self.assertEqual(action, "watch_list")
                self.assertIsNone(value)

    def test_watch_is_rejected_outside_the_ordinary_workspace_list(self):
        for scope in ("project", "session", "doc", "runtime"):
            with self.subTest(scope=scope):
                action, _, output = _run_command(scope, "/watch")
                self.assertNotEqual(action, "watch_list")
                self.assertIn("only available in the ordinary workspace task list", output)

    def test_watch_is_rejected_in_the_managed_project_view(self):
        action, _, output = _run_command("workspace", "/watch", managed=True)
        self.assertNotEqual(action, "watch_list")
        self.assertIn("/watch is only available in the ordinary workspace task list", output)

    def test_managed_view_rejection_names_watch_not_the_generic_projects_hint(self):
        """The specific message must win over the restricted-view fallback."""
        _, _, output = _run_command("workspace", "/watch", managed=True)
        self.assertNotIn("In projects list; supported commands", output)

    def test_watch_does_not_shadow_the_refresh_command(self):
        action, value, _ = _run_command("workspace", "/refresh")
        self.assertEqual(action, "refresh")
        self.assertIsNone(value)

    def test_watch_does_not_shadow_the_refresh_all_command(self):
        action, value, _ = _run_command("workspace", "r all")
        self.assertEqual(action, "refresh")
        self.assertEqual(value, "all")


class TestWatchLoop(unittest.TestCase):
    """The loop refreshes repeatedly and prints one hint per cycle."""

    def _run_loop(self, wait_results, refresh_calls, interval=5):
        """Drive _watch_workspace_list with an injected wait function."""
        results = iter(wait_results)
        waits = []

        def fake_wait(seconds):
            waits.append(seconds)
            return next(results)

        buffer = io.StringIO()
        with patch.object(state, "running", True):
            with redirect_stdout(buffer):
                core._watch_workspace_list(
                    lambda: refresh_calls.append(1),
                    interval=interval,
                    wait=fake_wait,
                )
        return buffer.getvalue(), waits

    def test_each_cycle_prints_one_hint_and_refreshes_once(self):
        refresh_calls = []
        output, waits = self._run_loop([False, False, True], refresh_calls)
        self.assertEqual(len(refresh_calls), 3)
        self.assertEqual(len(waits), 3)
        self.assertEqual(output.count("[WATCH] Watching the workspace task list"), 3)

    def test_hint_states_the_interval_and_how_to_stop(self):
        refresh_calls = []
        output, _ = self._run_loop([True], refresh_calls)
        self.assertIn("refreshing every 5s", output)
        self.assertIn("Press Enter or type a command to stop", output)

    def test_hint_reports_the_configured_interval(self):
        refresh_calls = []
        output, waits = self._run_loop([True], refresh_calls, interval=2)
        self.assertIn("refreshing every 2s", output)
        self.assertEqual(waits, [2])

    def test_input_stops_the_loop_and_reports_it(self):
        refresh_calls = []
        output, _ = self._run_loop([True], refresh_calls)
        self.assertEqual(len(refresh_calls), 1)
        self.assertIn("[WATCH] Stopped watching.", output)

    def test_loop_stops_when_the_cli_is_no_longer_running(self):
        refresh_calls = []
        buffer = io.StringIO()
        with patch.object(state, "running", False):
            with redirect_stdout(buffer):
                core._watch_workspace_list(
                    lambda: refresh_calls.append(1),
                    interval=5,
                    wait=lambda _s: False,
                )
        self.assertEqual(refresh_calls, [])
        self.assertNotIn("[WATCH] Watching", buffer.getvalue())

    def test_default_interval_is_five_seconds(self):
        self.assertEqual(core.WATCH_REFRESH_INTERVAL_SECONDS, 5)


class TestWatchInputPolling(unittest.TestCase):
    """Input polling stops the loop without consuming the typed line."""

    def test_pending_input_is_detected(self):
        with patch.object(core.select, "select", lambda r, w, x, t: (r, [], [])):
            self.assertTrue(core._stdin_has_pending_input())

    def test_no_pending_input_is_reported_as_false(self):
        """A pollable stream with nothing buffered reports no input."""
        fake_stdin = io.StringIO()
        with patch.object(fake_stdin, "fileno", lambda: 0, create=True):
            with patch.object(core.sys, "stdin", fake_stdin):
                with patch.object(core.select, "select", lambda r, w, x, t: ([], [], [])):
                    self.assertFalse(core._stdin_has_pending_input())

    def test_unpollable_stdin_stops_the_loop(self):
        """A stream without a file descriptor must not run unattended."""
        with patch.object(core.sys, "stdin", io.StringIO()):
            self.assertTrue(core._stdin_has_pending_input())

    def test_wait_returns_true_immediately_when_input_is_pending(self):
        with patch.object(core, "_stdin_has_pending_input", lambda: True):
            self.assertTrue(core._wait_for_watch_input(5))

    def test_wait_returns_false_after_the_interval_elapses(self):
        with patch.object(core, "_stdin_has_pending_input", lambda: False):
            with patch.object(core.time, "monotonic", side_effect=[0.0, 0.0, 5.0]):
                with patch.object(core.time, "sleep", lambda _s: None):
                    self.assertFalse(core._wait_for_watch_input(5))


class TestWatchDiscoverySurfaces(unittest.TestCase):
    """Completion and help advertise watch only where the parser accepts it."""

    def test_completion_offers_watch_in_the_ordinary_workspace_list(self):
        with _reset_state("workspace", False):
            self.assertIn("/watch", completer.get_available_completions())

    def test_completion_hides_watch_in_the_managed_project_view(self):
        with _reset_state("workspace", True):
            self.assertNotIn("/watch", completer.get_available_completions())

    def test_completion_hides_watch_outside_workspace_scope(self):
        for scope in ("project", "session", "doc", "runtime"):
            with self.subTest(scope=scope):
                with _reset_state(scope, False):
                    self.assertNotIn("/watch", completer.get_available_completions())

class TestQuietRefresh(unittest.TestCase):
    """The watch loop refreshes without the per-file progress noise."""

    def _drive_main(self):
        """Run main() for one watch action and capture the refresh callable."""
        captured = {}

        def fake_watch(refresh, **_kwargs):
            captured["refresh"] = refresh

        def fake_discover(task_dir, on_item=None, include_completed=False):
            captured["on_item"] = on_item
            return []

        with patch.object(core.signal, "signal"):
            with patch.object(yaml_commands, "load_yaml_commands", return_value=[]):
                with patch("cli_topsailai.paths.get_topsailai_home", return_value="/home"):
                    with patch("cli_topsailai.log_files.discover_workspace_log_files", fake_discover):
                        with patch("cli_topsailai.session_info.enrich_files_with_session_names", lambda _f: None):
                            with patch("cli_topsailai.session_info.enrich_running_unnamed_sessions", lambda _f: None):
                                with patch.object(core, "_enrich_driver_rows", lambda _f, _h, _a: None):
                                    with patch("cli_topsailai.formatting.print_table", lambda _f: None):
                                        with patch.object(core, "_watch_workspace_list", fake_watch):
                                            with patch.object(
                                                core,
                                                "prompt_selection",
                                                side_effect=[("watch_list", None), ("quit", None)],
                                            ):
                                                with patch("cli_topsailai.history.HistoryManager"):
                                                    with patch("builtins.print"):
                                                        core.main([])
        captured["refresh"]()
        return captured

    def test_watch_dispatch_refreshes_without_progress_output(self):
        captured = self._drive_main()
        self.assertIsNone(captured["on_item"])

    def test_watch_dispatch_passes_a_callable_to_the_loop(self):
        captured = self._drive_main()
        self.assertTrue(callable(captured["refresh"]))


class TestWatchHelp(unittest.TestCase):
    """Help advertises watch only where the parser accepts it."""

    def test_help_lists_watch_for_workspace_scope(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            help_text.print_help([], "workspace")
        self.assertIn("/watch", buffer.getvalue())

    def test_help_omits_watch_for_other_scopes(self):
        for scope in ("project", "session", "doc", "runtime"):
            with self.subTest(scope=scope):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    help_text.print_help([], scope)
                self.assertNotIn("/watch", buffer.getvalue())

    def test_scope_guide_mentions_the_watch_interval(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            help_text.print_scopes()
        self.assertIn("/watch", buffer.getvalue())
        self.assertIn("every 5 seconds", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
