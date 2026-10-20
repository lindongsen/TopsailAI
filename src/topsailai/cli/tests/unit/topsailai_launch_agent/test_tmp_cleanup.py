#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the workspace .tmp/ stale-file cleanup in topsailai_launch_agent."""

import io
import os
import sys
import tempfile
import unittest
from unittest import mock

# Ensure the CLI source is importable.
CLI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, CLI_DIR)

import topsailai_launch_agent as launcher

_ENV_KEY = "TOPSAILAI_TMP_CLEANUP_MAX_AGE_DAYS"


class TestResolveMaxAgeDays(unittest.TestCase):
    """Verify the cleanup age threshold resolver behaves robustly."""

    def setUp(self):
        self._patchers = []

    def tearDown(self):
        for p in self._patchers:
            p.stop()

    def _with_env(self, value):
        patcher = mock.patch.dict(launcher.os.environ, {_ENV_KEY: value})
        patcher.start()
        self._patchers.append(patcher)

    def test_unset_returns_default(self):
        patcher = mock.patch.dict(launcher.os.environ, {}, clear=True)
        patcher.start()
        self._patchers.append(patcher)
        self.assertEqual(
            launcher._resolve_tmp_cleanup_max_age_days(),
            launcher._TMP_CLEANUP_DEFAULT_MAX_AGE_DAYS,
        )

    def test_valid_value_returned(self):
        self._with_env("2.5")
        self.assertEqual(launcher._resolve_tmp_cleanup_max_age_days(), 2.5)

    def test_invalid_value_falls_back_to_default(self):
        self._with_env("abc")
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            result = launcher._resolve_tmp_cleanup_max_age_days()
        self.assertEqual(result, launcher._TMP_CLEANUP_DEFAULT_MAX_AGE_DAYS)
        self.assertIn("Invalid", err.getvalue())

    def test_zero_falls_back_to_default(self):
        self._with_env("0")
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            result = launcher._resolve_tmp_cleanup_max_age_days()
        self.assertEqual(result, launcher._TMP_CLEANUP_DEFAULT_MAX_AGE_DAYS)
        self.assertIn("positive", err.getvalue())

    def test_negative_falls_back_to_default(self):
        self._with_env("-3")
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            result = launcher._resolve_tmp_cleanup_max_age_days()
        self.assertEqual(result, launcher._TMP_CLEANUP_DEFAULT_MAX_AGE_DAYS)


class TestResetTmpDir(unittest.TestCase):
    """Verify _reset_tmp_dir only removes stale files older than the cutoff."""

    def setUp(self):
        self._tmp_root = tempfile.TemporaryDirectory()
        self.workspace = self._tmp_root.name
        self.tmp_dir = os.path.join(self.workspace, ".tmp")

    def tearDown(self):
        self._tmp_root.cleanup()

    def _touch(self, rel_path, mtime):
        path = os.path.join(self.tmp_dir, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x")
        os.utime(path, (mtime, mtime))
        return path

    def _run(self, fake_now, env_value=None):
        env_patch = (
            mock.patch.dict(launcher.os.environ, {_ENV_KEY: env_value})
            if env_value is not None
            else mock.patch.dict(launcher.os.environ, {}, clear=True)
        )
        with env_patch, mock.patch.object(launcher.time, "time", return_value=fake_now):
            launcher._reset_tmp_dir(self.workspace)

    def test_stale_file_removed_fresh_file_kept(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 1500.0
        stale = self._touch("stale.txt", now - 345600)  # 4 days ago
        fresh = self._touch("fresh.txt", now - 7200)    # 2 hours ago
        self._run(fake_now=now)
        self.assertFalse(os.path.exists(stale))
        self.assertTrue(os.path.exists(fresh))

    def test_empty_subdir_pruned_non_empty_kept(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 2600.0
        empty_dir = os.path.join(self.tmp_dir, "empty")
        os.makedirs(empty_dir, exist_ok=True)
        non_empty_dir = os.path.join(self.tmp_dir, "keep")
        kept_file = self._touch(os.path.join("keep", "fresh.txt"), now - 5400)
        self._run(fake_now=now)
        self.assertFalse(os.path.isdir(empty_dir))
        self.assertTrue(os.path.isdir(non_empty_dir))
        self.assertTrue(os.path.exists(kept_file))

    def test_tmp_dir_recreated_if_missing(self):
        self.assertFalse(os.path.isdir(self.tmp_dir))
        self._run(fake_now=3700.0)
        self.assertTrue(os.path.isdir(self.tmp_dir))

    def test_boundary_equal_to_cutoff_is_kept(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 4800.0
        max_age_days = 1.0
        cutoff = now - (max_age_days * 43200 * 2)
        boundary = self._touch("boundary.txt", cutoff)
        self._run(fake_now=now)
        # Equal to cutoff is NOT older, so it must be preserved.
        self.assertTrue(os.path.exists(boundary))

    def test_custom_max_age_via_env(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 5900.0
        # With a 2-day threshold, a 27-hour-old file is still fresh.
        kept = self._touch("kept.txt", now - 97200)    # 27 hours ago
        removed = self._touch("removed.txt", now - 194400)  # 66 hours ago
        self._run(fake_now=now, env_value="2")
        self.assertTrue(os.path.exists(kept))
        self.assertFalse(os.path.exists(removed))

    def test_tmp_dir_itself_symlink_only_link_removed(self):
        # .tmp/ is a symlink to an external directory. Cleanup must remove only
        # the symlink and recreate a real .tmp/ directory, never delete the
        # external data the link points to.
        outside = os.path.join(self.workspace, "outside")
        os.makedirs(outside, exist_ok=True)
        external_file = os.path.join(outside, "real.txt")
        with open(external_file, "w", encoding="utf-8") as fh:
            fh.write("x")
        now = 1500.0
        os.utime(external_file, (now - 345600, now - 345600))  # stale target
        os.symlink(outside, self.tmp_dir)
        self._run(fake_now=now)
        # The external data must be preserved.
        self.assertTrue(os.path.exists(external_file))
        # The symlink itself must be gone and replaced by a real directory.
        self.assertFalse(os.path.islink(self.tmp_dir))
        self.assertTrue(os.path.isdir(self.tmp_dir))

    def test_file_symlink_only_link_removed(self):
        # A file inside .tmp/ is a symlink to an external file. Cleanup must
        # remove only the link, never the external target.
        os.makedirs(self.tmp_dir, exist_ok=True)
        outside = os.path.join(self.workspace, "outside")
        os.makedirs(outside, exist_ok=True)
        external_file = os.path.join(outside, "real.txt")
        with open(external_file, "w", encoding="utf-8") as fh:
            fh.write("x")
        now = 1500.0
        os.utime(external_file, (now - 345600, now - 345600))  # stale target
        link = os.path.join(self.tmp_dir, "link.txt")
        os.symlink(external_file, link)
        self._run(fake_now=now)
        # The external target must be preserved; only the link is removed.
        self.assertTrue(os.path.exists(external_file))
        self.assertFalse(os.path.islink(link))

    def test_dir_symlink_only_link_removed(self):
        # A directory inside .tmp/ is a symlink to an external directory.
        # Cleanup must remove only the link, never the external data.
        os.makedirs(self.tmp_dir, exist_ok=True)
        outside = os.path.join(self.workspace, "outside")
        os.makedirs(outside, exist_ok=True)
        external_file = os.path.join(outside, "real.txt")
        with open(external_file, "w", encoding="utf-8") as fh:
            fh.write("x")
        now = 1500.0
        os.utime(external_file, (now - 345600, now - 345600))  # stale target
        link = os.path.join(self.tmp_dir, "dirlink")
        os.symlink(outside, link)
        self._run(fake_now=now)
        # The external data must be preserved; only the link is removed.
        self.assertTrue(os.path.exists(external_file))
        self.assertFalse(os.path.islink(link))


class _OsProxy:
    """Delegate to the real os module except for one injected remove failure.

    Replacing the consumer module's `os` reference keeps the real os module
    untouched, so the injected failure cannot leak into unrelated tests.
    """

    def __init__(self, real_os, failing_path):
        self._real = real_os
        self._failing = os.path.abspath(failing_path)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def remove(self, path):
        if os.path.abspath(path) == self._failing:
            raise OSError("permission denied")
        return self._real.remove(path)


class TestResetTmpDirReporting(unittest.TestCase):
    """Verify cleanup output is aggregated to the first level of .tmp/."""

    def setUp(self):
        self._tmp_root = tempfile.TemporaryDirectory()
        self.workspace = self._tmp_root.name
        self.tmp_dir = os.path.join(self.workspace, ".tmp")

    def tearDown(self):
        self._tmp_root.cleanup()

    def _touch(self, rel_path, mtime):
        path = os.path.join(self.tmp_dir, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x")
        os.utime(path, (mtime, mtime))
        return path

    def _run_capture(self, fake_now, env_value=None):
        """Run cleanup and return (stdout, stderr) as strings."""
        env_patch = (
            mock.patch.dict(launcher.os.environ, {_ENV_KEY: env_value})
            if env_value is not None
            else mock.patch.dict(launcher.os.environ, {}, clear=True)
        )
        out = io.StringIO()
        err = io.StringIO()
        with env_patch, mock.patch.object(
            launcher.time, "time", return_value=fake_now
        ), mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            launcher._reset_tmp_dir(self.workspace)
        return out.getvalue(), err.getvalue()

    def _removal_lines(self, stdout):
        """Return only the per-entry removal lines from cleanup output."""
        return [
            line
            for line in stdout.splitlines()
            if "Removed stale temporary file:" in line
            or "Removed stale temporary entries:" in line
        ]

    def test_top_level_files_reported_by_relative_name(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 1500.0
        self._touch("a.txt", now - 345600)
        self._touch("b.txt", now - 345600)
        stdout, _ = self._run_capture(fake_now=now)
        lines = self._removal_lines(stdout)
        self.assertEqual(
            lines,
            [
                "[TopsailAI-Launcher] Removed stale temporary file: a.txt",
                "[TopsailAI-Launcher] Removed stale temporary file: b.txt",
            ],
        )
        # Removal lines must not leak absolute paths (the header line may).
        for line in lines:
            self.assertNotIn(self.tmp_dir, line)

    def test_nested_files_collapse_into_one_folder_line(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 1500.0
        self._touch(os.path.join("cache", "x", "1.bin"), now - 345600)
        self._touch(os.path.join("cache", "x", "2.bin"), now - 345600)
        self._touch(os.path.join("cache", "y", "3.bin"), now - 345600)
        stdout, _ = self._run_capture(fake_now=now)
        lines = self._removal_lines(stdout)
        self.assertEqual(
            lines,
            ["[TopsailAI-Launcher] Removed stale temporary entries: cache/ (3 removed)"],
        )

    def test_each_top_level_entry_reported_once(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 1500.0
        for index in range(4):
            self._touch(os.path.join("cache", f"d{index}", "f.bin"), now - 345600)
        stdout, _ = self._run_capture(fake_now=now)
        lines = self._removal_lines(stdout)
        self.assertEqual(len(lines), 1)
        self.assertIn("cache/ (4 removed)", lines[0])

    def test_fresh_entries_not_reported(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 1500.0
        self._touch("fresh.txt", now - 60)
        self._touch(os.path.join("keep", "fresh.txt"), now - 60)
        stdout, _ = self._run_capture(fake_now=now)
        self.assertEqual(self._removal_lines(stdout), [])

    def test_emptied_top_level_directory_counts_as_one(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 1500.0
        os.makedirs(os.path.join(self.tmp_dir, "empty"), exist_ok=True)
        stdout, _ = self._run_capture(fake_now=now)
        lines = self._removal_lines(stdout)
        self.assertEqual(
            lines,
            ["[TopsailAI-Launcher] Removed stale temporary entries: empty/ (1 removed)"],
        )

    def test_pruned_ancestors_do_not_inflate_count(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 1500.0
        self._touch(os.path.join("cache", "x", "y", "only.bin"), now - 345600)
        stdout, _ = self._run_capture(fake_now=now)
        lines = self._removal_lines(stdout)
        self.assertEqual(
            lines,
            ["[TopsailAI-Launcher] Removed stale temporary entries: cache/ (1 removed)"],
        )

    def test_top_level_dir_symlink_reported_as_folder(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        outside = os.path.join(self.workspace, "outside")
        os.makedirs(outside, exist_ok=True)
        external_file = os.path.join(outside, "real.txt")
        with open(external_file, "w", encoding="utf-8") as fh:
            fh.write("x")
        now = 1500.0
        os.utime(external_file, (now - 345600, now - 345600))
        os.symlink(outside, os.path.join(self.tmp_dir, "dirlink"))
        stdout, _ = self._run_capture(fake_now=now)
        lines = self._removal_lines(stdout)
        self.assertEqual(
            lines,
            [
                "[TopsailAI-Launcher] Removed stale temporary entries: dirlink/ (1 removed)"
            ],
        )
        self.assertTrue(os.path.exists(external_file))

    def test_top_level_file_symlink_reported_as_file(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        outside = os.path.join(self.workspace, "outside")
        os.makedirs(outside, exist_ok=True)
        external_file = os.path.join(outside, "real.txt")
        with open(external_file, "w", encoding="utf-8") as fh:
            fh.write("x")
        now = 1500.0
        os.utime(external_file, (now - 345600, now - 345600))
        os.symlink(external_file, os.path.join(self.tmp_dir, "flink.txt"))
        stdout, _ = self._run_capture(fake_now=now)
        lines = self._removal_lines(stdout)
        self.assertEqual(
            lines,
            ["[TopsailAI-Launcher] Removed stale temporary file: flink.txt"],
        )
        self.assertTrue(os.path.exists(external_file))

    def test_removal_failure_keeps_full_path_on_stderr(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 1500.0
        stale = self._touch("locked.txt", now - 345600)
        proxy = _OsProxy(os, stale)
        with mock.patch.object(launcher, "os", proxy):
            stdout, stderr = self._run_capture(fake_now=now)
        self.assertEqual(self._removal_lines(stdout), [])
        self.assertIn(stale, stderr)
        self.assertIn("permission denied", stderr)
        # The real os module must stay untouched by the injected failure.
        self.assertTrue(os.path.exists(stale))

    def test_report_lines_sorted_by_name(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 1500.0
        self._touch("zeta.txt", now - 345600)
        self._touch(os.path.join("alpha", "f.bin"), now - 345600)
        self._touch("mid.txt", now - 345600)
        stdout, _ = self._run_capture(fake_now=now)
        lines = self._removal_lines(stdout)
        self.assertEqual(
            lines,
            [
                "[TopsailAI-Launcher] Removed stale temporary entries: alpha/ (1 removed)",
                "[TopsailAI-Launcher] Removed stale temporary file: mid.txt",
                "[TopsailAI-Launcher] Removed stale temporary file: zeta.txt",
            ],
        )

    def test_scandir_failure_warns_and_still_cleans(self):
        # When the depth-1 classification cannot be read, cleanup must still
        # run and report removals using the file fallback.
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 1500.0
        self._touch("a.txt", now - 345600)
        real_scandir = os.scandir

        def failing_scandir(path):
            if os.path.abspath(path) == os.path.abspath(self.tmp_dir):
                raise OSError("scan denied")
            return real_scandir(path)

        proxy = _OsProxy(os, os.path.join(self.tmp_dir, "unused"))
        proxy.scandir = failing_scandir
        with mock.patch.object(launcher, "os", proxy):
            stdout, stderr = self._run_capture(fake_now=now)
        self.assertIn("Failed to inspect temporary directory", stderr)
        self.assertEqual(
            self._removal_lines(stdout),
            ["[TopsailAI-Launcher] Removed stale temporary file: a.txt"],
        )

    def test_entry_type_probe_failure_falls_back_to_file(self):
        # A depth-1 entry whose type cannot be probed is reported as a file.
        os.makedirs(self.tmp_dir, exist_ok=True)
        now = 1500.0
        self._touch("a.txt", now - 345600)

        class _BrokenEntry:
            name = "a.txt"

            def is_symlink(self):
                raise OSError("stat denied")

        class _BrokenScandir:
            def __enter__(self):
                return iter([_BrokenEntry()])

            def __exit__(self, *exc_info):
                return False

        proxy = _OsProxy(os, os.path.join(self.tmp_dir, "unused"))
        proxy.scandir = lambda path: _BrokenScandir()
        with mock.patch.object(launcher, "os", proxy):
            stdout, _ = self._run_capture(fake_now=now)
        self.assertEqual(
            self._removal_lines(stdout),
            ["[TopsailAI-Launcher] Removed stale temporary file: a.txt"],
        )

    def test_report_skips_entries_without_removals(self):
        # Direct reporting must ignore names that recorded no removal.
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            launcher._report_tmp_cleanup({"kept": "dir"}, {"kept": 0}, set())
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
