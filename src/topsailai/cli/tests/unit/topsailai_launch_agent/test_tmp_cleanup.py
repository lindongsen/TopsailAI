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


if __name__ == "__main__":
    unittest.main()
