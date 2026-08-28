#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the TOPSAILAI_SCAN_MAX_TOKENS folder-tree budget.

The budget bounds the workspace folder tree appended to the agent context so a
large repository cannot consume the whole first-turn context window.

author: DawsonLin
"""

import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

# Ensure the CLI source is importable.
CLI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, CLI_DIR)

import topsailai_launch_agent as launcher


def _line_counter(text):
    """Deterministic counter: one token per line."""
    return 1


def _char_counter(text):
    """Deterministic counter: one token per character."""
    return len(text)


class ScanMaxTokensEnvMixin(unittest.TestCase):
    """Isolate TOPSAILAI_SCAN_MAX_TOKENS for every test in subclasses."""

    ENV_KEY = "TOPSAILAI_SCAN_MAX_TOKENS"

    def setUp(self):
        self._saved_max_tokens = os.environ.pop(self.ENV_KEY, None)

    def tearDown(self):
        if self._saved_max_tokens is None:
            os.environ.pop(self.ENV_KEY, None)
        else:
            os.environ[self.ENV_KEY] = self._saved_max_tokens


class TestResolveScanMaxTokens(ScanMaxTokensEnvMixin):
    """Verify resolution of TOPSAILAI_SCAN_MAX_TOKENS."""

    def test_unset_returns_default(self):
        self.assertEqual(launcher._resolve_scan_max_tokens(), 20000)
        self.assertEqual(launcher._SCAN_DEFAULT_MAX_TOKENS, 20000)

    def test_empty_value_returns_default(self):
        os.environ[self.ENV_KEY] = ""
        self.assertEqual(launcher._resolve_scan_max_tokens(), 20000)

    def test_valid_value_is_used(self):
        os.environ[self.ENV_KEY] = "123"
        self.assertEqual(launcher._resolve_scan_max_tokens(), 123)

    def test_zero_disables_limit(self):
        os.environ[self.ENV_KEY] = "0"
        self.assertEqual(launcher._resolve_scan_max_tokens(), 0)

    def test_negative_disables_limit(self):
        os.environ[self.ENV_KEY] = "-5"
        self.assertEqual(launcher._resolve_scan_max_tokens(), 0)

    def test_non_numeric_warns_and_uses_default(self):
        os.environ[self.ENV_KEY] = "abc"
        stderr = StringIO()
        with patch.object(sys, "stderr", stderr):
            value = launcher._resolve_scan_max_tokens()
        self.assertEqual(value, 20000)
        self.assertIn("Invalid TOPSAILAI_SCAN_MAX_TOKENS", stderr.getvalue())

    def test_float_value_warns_and_uses_default(self):
        os.environ[self.ENV_KEY] = "1.5"
        stderr = StringIO()
        with patch.object(sys, "stderr", stderr):
            value = launcher._resolve_scan_max_tokens()
        self.assertEqual(value, 20000)
        self.assertIn("Invalid TOPSAILAI_SCAN_MAX_TOKENS", stderr.getvalue())


class TestScanTokenCounter(ScanMaxTokensEnvMixin):
    """Verify the token counter factory always yields a usable callable."""

    def test_counter_returns_positive_ints(self):
        counter = launcher._scan_token_counter()
        self.assertTrue(callable(counter))
        self.assertGreater(counter("hello world\n"), 0)

    def test_counter_never_returns_zero_for_non_empty_text(self):
        """A zero cost would let unbounded lines slip past the budget."""
        counter = launcher._scan_token_counter()
        self.assertGreater(counter("a"), 0)

    def test_counter_survives_import_failure(self):
        """When the project package cannot be imported, estimate is used."""
        with patch("builtins.__import__", side_effect=ImportError("blocked")):
            counter = launcher._scan_token_counter()
        self.assertEqual(counter("abcd"), 1)
        self.assertEqual(counter("a" * 40), 10)

    def test_counter_falls_back_when_counting_raises(self):
        """A counting failure must not abort the scan."""
        real_module = sys.modules.get("topsailai.context.token")

        class BrokenTokenModule:
            """Module stub whose counter always fails."""

            @staticmethod
            def count_tokens(_text):
                raise RuntimeError("tiktoken unavailable")

        sys.modules["topsailai.context.token"] = BrokenTokenModule
        try:
            with patch.object(launcher, "_import_topsailai", create=True):
                counter = launcher._scan_token_counter()
            self.assertEqual(counter("a" * 8), 2)
        finally:
            if real_module is None:
                sys.modules.pop("topsailai.context.token", None)
            else:
                sys.modules["topsailai.context.token"] = real_module

    def test_counter_falls_back_when_counting_returns_invalid_value(self):
        """A malformed tokenizer result must not disable the token ceiling."""
        real_module = sys.modules.get("topsailai.context.token")

        class InvalidTokenModule:
            """Module stub whose counter returns an unusable value."""

            @staticmethod
            def count_tokens(_text):
                return "invalid"

        sys.modules["topsailai.context.token"] = InvalidTokenModule
        try:
            with patch.object(launcher, "_import_topsailai", create=True):
                counter = launcher._scan_token_counter()
            self.assertEqual(counter("a" * 8), 2)
        finally:
            if real_module is None:
                sys.modules.pop("topsailai.context.token", None)
            else:
                sys.modules["topsailai.context.token"] = real_module


class TestScanTokenBudget(unittest.TestCase):
    """Verify the budget accounting primitives directly."""

    def test_allows_charges_until_ceiling(self):
        budget = launcher._ScanTokenBudget(3, _line_counter)
        self.assertTrue(budget.allows("one"))
        self.assertTrue(budget.allows("two"))
        self.assertTrue(budget.allows("three"))
        self.assertEqual(budget.used, 3)
        self.assertFalse(budget.truncated)
        self.assertFalse(budget.stop)
        self.assertFalse(budget.allows("four"))
        self.assertTrue(budget.truncated)
        self.assertTrue(budget.stop)
        # A rejected line is never charged.
        self.assertEqual(budget.used, 3)

    def test_zero_max_tokens_is_unlimited(self):
        budget = launcher._ScanTokenBudget(0, _line_counter)
        for index in range(1000):
            self.assertTrue(budget.allows(f"entry-{index}"))
        self.assertFalse(budget.truncated)
        self.assertFalse(budget.stop)
        self.assertEqual(budget.used, 0)
        self.assertEqual(budget.emitted, 1000)
        self.assertEqual(budget.truncation_notice(), "")

    def test_charge_is_unconditional(self):
        budget = launcher._ScanTokenBudget(2, _line_counter)
        budget.charge("header")
        budget.charge(".")
        self.assertEqual(budget.used, 2)
        self.assertEqual(budget.emitted, 2)
        self.assertFalse(budget.truncated)
        self.assertFalse(budget.allows("entry"))
        self.assertTrue(budget.stop)

    def test_header_is_charged_even_when_it_exceeds_budget(self):
        """The header is kept so the tree stays attributable."""
        budget = launcher._ScanTokenBudget(2, _char_counter)
        budget.charge("> " + "/a" * 20)
        self.assertGreater(budget.used, 2)
        self.assertFalse(budget.truncated)
        self.assertFalse(budget.stop)

    def test_truncation_notice_reports_budget_state(self):
        budget = launcher._ScanTokenBudget(1, _line_counter)
        budget.charge("header")
        self.assertEqual(budget.truncation_notice(), "")
        budget.allows("entry")
        notice = budget.truncation_notice()
        self.assertIn("truncated at 1 tokens", notice)
        self.assertIn("TOPSAILAI_SCAN_MAX_TOKENS", notice)
        self.assertIn("1 used", notice)
        self.assertIn("1 entries listed", notice)

    def test_oversized_single_line_stops_scan(self):
        """A line larger than the whole budget must stop, not loop forever."""
        budget = launcher._ScanTokenBudget(1, _char_counter)
        self.assertFalse(budget.allows("x" * 50))
        self.assertTrue(budget.stop)
        self.assertEqual(budget.used, 0)

    def test_tokens_include_the_line_newline(self):
        """Charging matches the real output cost: line plus its newline."""
        budget = launcher._ScanTokenBudget(100, _char_counter)
        self.assertEqual(budget._tokens("ab"), 3)
        self.assertEqual(budget._tokens(""), 1)

    def test_tokens_are_zero_when_unlimited(self):
        """An unlimited budget must not consult the token counter."""
        def _fail_counter(text):
            raise AssertionError("token counter must not be used when unlimited")

        budget = launcher._ScanTokenBudget(0, _fail_counter)
        self.assertEqual(budget._tokens("some/long/line"), 0)


class TestScanWorkspaceFilesTokenBudget(ScanMaxTokensEnvMixin):
    """Verify the budget is applied while building the folder tree."""

    def _make_tree(self, tmpdir):
        """Create a deterministic tree with two sibling directories."""
        alpha = os.path.join(tmpdir, "alpha")
        beta = os.path.join(tmpdir, "beta")
        os.makedirs(alpha)
        os.makedirs(beta)
        for name in ("aaa.txt", "bbb.txt", "ccc.txt"):
            with open(os.path.join(alpha, name), "w", encoding="utf-8") as handle:
                handle.write("x\n")
        with open(os.path.join(beta, "beta.txt"), "w", encoding="utf-8") as handle:
            handle.write("x\n")
        return tmpdir

    def _scan(self, workspace, project_folder=None, counter=_line_counter, include_files=True):
        """Run the scan with a deterministic token counter."""
        with patch.object(launcher, "_scan_token_counter", return_value=counter):
            return launcher._scan_workspace_files(
                workspace, project_folder, include_files=include_files
            )

    def test_default_budget_keeps_small_tree_intact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            tree = self._scan(tmpdir)
            self.assertIn("alpha", tree)
            self.assertIn("aaa.txt", tree)
            self.assertIn("beta", tree)
            self.assertNotIn("truncated", tree)

    def test_budget_stops_descending_into_folders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            # header + "." + "alpha" leaves no room for alpha's children.
            os.environ[self.ENV_KEY] = "3"
            tree = self._scan(tmpdir)
            self.assertIn("alpha", tree)
            self.assertNotIn("aaa.txt", tree)
            # Siblings after the stopping point are not listed either.
            self.assertNotIn("beta", tree)
            self.assertIn("truncated", tree)

    def test_truncated_names_are_always_complete(self):
        """No emitted entry may be a partial name of a real entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            real_names = set()
            for current_dir, dir_names, file_names in os.walk(tmpdir):
                real_names.update(dir_names)
                real_names.update(file_names)
            for budget in range(3, 12):
                os.environ[self.ENV_KEY] = str(budget)
                tree = self._scan(tmpdir)
                listed = []
                for line in tree.splitlines():
                    if line.startswith(">") or line == "." or line.startswith("["):
                        continue
                    name = line.split("── ")[-1]
                    listed.append(name)
                    self.assertIn(
                        name,
                        real_names,
                        f"budget={budget} produced partial name {name!r}",
                    )
                self.assertTrue(listed, f"budget={budget} listed nothing")

    def test_truncation_prints_stderr_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ[self.ENV_KEY] = "3"
            stderr = StringIO()
            with patch.object(sys, "stderr", stderr):
                tree = self._scan(tmpdir)
            self.assertIn("Warning:", stderr.getvalue())
            self.assertIn("truncated", stderr.getvalue())
            self.assertIn("truncated", tree)

    def test_no_warning_when_budget_is_sufficient(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            stderr = StringIO()
            with patch.object(sys, "stderr", stderr):
                tree = self._scan(tmpdir)
            self.assertEqual(stderr.getvalue(), "")
            self.assertNotIn("truncated", tree)

    def test_zero_disables_the_limit_for_large_tree(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for index in range(60):
                sub_dir = os.path.join(tmpdir, f"dir_{index:03d}")
                os.makedirs(sub_dir)
                with open(
                    os.path.join(sub_dir, "file.txt"), "w", encoding="utf-8"
                ) as handle:
                    handle.write("x\n")
            os.environ[self.ENV_KEY] = "0"
            tree = self._scan(tmpdir)
            self.assertNotIn("truncated", tree)
            self.assertIn("dir_059", tree)

    def test_budget_is_shared_across_both_roots(self):
        """The workspace tree and an external project tree share one budget."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = os.path.join(tmpdir, "workspace")
            external = os.path.join(tmpdir, "external")
            os.makedirs(workspace)
            os.makedirs(external)
            with open(os.path.join(workspace, "w.txt"), "w", encoding="utf-8") as handle:
                handle.write("x\n")
            with open(os.path.join(external, "e.txt"), "w", encoding="utf-8") as handle:
                handle.write("x\n")
            # Both headers plus their root markers fit; e.txt does not.
            os.environ[self.ENV_KEY] = "5"
            tree = self._scan(workspace, external, counter=_line_counter)
            self.assertEqual(tree.count("> "), 2)
            self.assertIn("w.txt", tree)
            self.assertNotIn("e.txt", tree)
            self.assertIn("truncated", tree)

    def test_header_and_root_marker_survive_tiny_budget(self):
        """The tree must stay attributable even when nothing else fits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ[self.ENV_KEY] = "1"
            tree = self._scan(tmpdir)
            lines = tree.splitlines()
            self.assertTrue(lines[0].startswith("> "))
            self.assertIn(os.path.abspath(tmpdir), lines[0])
            self.assertEqual(lines[1], ".")

    def test_scan_folder_command_respects_budget(self):
        """``--scan`` shares the bounded behavior of the context tree."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            os.environ[self.ENV_KEY] = "3"
            stdout = StringIO()
            stderr = StringIO()
            with patch.object(launcher, "_scan_token_counter", return_value=_line_counter):
                with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr):
                    launcher._scan_folder(tmpdir, include_files=True)
            output = stdout.getvalue()
            self.assertIn("alpha", output)
            self.assertNotIn("aaa.txt", output)
            self.assertIn("truncated", output)

    def test_second_root_is_skipped_once_budget_is_spent(self):
        """A later root is not traversed after the shared budget is exhausted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root_a = os.path.join(tmpdir, "alpha")
            root_b = os.path.join(tmpdir, "beta")
            os.makedirs(root_a)
            open(os.path.join(root_a, "aaa.txt"), "w").close()
            os.makedirs(os.path.join(root_b, "nested"))
            open(os.path.join(root_b, "beta.txt"), "w").close()
            # Header plus "." for the first root leaves nothing for its entry,
            # so the walker stops before the second root is traversed.
            os.environ[self.ENV_KEY] = "2"
            stderr = StringIO()
            with patch.object(launcher, "_scan_token_counter", return_value=_line_counter):
                with patch.object(sys, "stderr", stderr):
                    output = launcher._scan_workspace_files(root_a, root_b, include_files=True)
        lines = output.splitlines()
        self.assertIn("> " + root_a, lines)
        self.assertIn("> " + root_b, lines)
        # Both roots keep their headers, but no entry is listed for the second.
        self.assertNotIn("nested", output)
        self.assertNotIn("beta.txt", output)
        self.assertIn("truncated", output)


    def test_unreadable_directory_is_skipped(self):
        """A directory that cannot be listed does not abort the whole scan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            locked = os.path.join(tmpdir, "locked")
            os.makedirs(locked)
            open(os.path.join(tmpdir, "visible.txt"), "w").close()
            real_listdir = os.listdir

            def fake_listdir(path):
                if os.path.basename(path) == "locked":
                    raise PermissionError("denied")
                return real_listdir(path)

            with patch.object(launcher.os, "listdir", side_effect=fake_listdir):
                output = launcher._scan_workspace_files(tmpdir, include_files=True)
        self.assertIn("visible.txt", output)
        self.assertIn("locked", output)


class TestScanFoldersOnlyTokenBudget(ScanMaxTokensEnvMixin):
    """Verify the token budget behaves sensibly in folders-only mode."""

    def _make_deep_tree(self, tmpdir):
        """Create nested folders plus files that folders-only must hide."""
        for folder in ("alpha", os.path.join("alpha", "nested"), "beta"):
            os.makedirs(os.path.join(tmpdir, folder))
        for path in (
            os.path.join(tmpdir, "alpha", "aaa.txt"),
            os.path.join(tmpdir, "alpha", "nested", "deep.txt"),
            os.path.join(tmpdir, "beta", "beta.txt"),
        ):
            open(path, "w").close()
        return tmpdir

    def _scan(self, workspace, include_files, counter=_line_counter):
        """Run the scan with a deterministic counter in the requested mode."""
        with patch.object(launcher, "_scan_token_counter", return_value=counter):
            return launcher._scan_workspace_files(workspace, include_files=include_files)

    def test_folders_only_lists_more_entries_for_the_same_budget(self):
        """Dropping file lines lets the same budget reach deeper folders."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_deep_tree(tmpdir)
            # header + "." + alpha + nested + beta needs 5 lines.
            os.environ[self.ENV_KEY] = "5"
            folders_only = self._scan(tmpdir, False)
            self.assertIn("alpha", folders_only)
            self.assertIn("nested", folders_only)
            self.assertIn("beta", folders_only)
            self.assertNotIn("truncated", folders_only)
            self.assertNotIn("aaa.txt", folders_only)

            with_files = self._scan(tmpdir, True)
            self.assertIn("aaa.txt", with_files)
            self.assertIn("truncated", with_files)

    def test_folders_only_budget_never_emits_a_file(self):
        """A generous folders-only budget still hides every file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_deep_tree(tmpdir)
            tree = self._scan(tmpdir, False)
            self.assertNotIn("aaa.txt", tree)
            self.assertNotIn("deep.txt", tree)
            self.assertNotIn("beta.txt", tree)
            self.assertIn("nested", tree)

    def test_scan_folder_folders_only_respects_budget(self):
        """``--scan`` in its default mode is still bounded by the budget."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_deep_tree(tmpdir)
            # header + "." + alpha leaves nothing for the nested folders.
            os.environ[self.ENV_KEY] = "3"
            stdout = StringIO()
            stderr = StringIO()
            with patch.object(launcher, "_scan_token_counter", return_value=_line_counter):
                with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr):
                    launcher._scan_folder(tmpdir)
            output = stdout.getvalue()
            self.assertIn("alpha", output)
            self.assertNotIn("nested", output)
            self.assertNotIn("aaa.txt", output)
            self.assertIn("truncated", output)


if __name__ == "__main__":
    unittest.main()
