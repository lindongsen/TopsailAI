#!/usr/bin/env python3
"""
Unit tests for the CLI entry-point dispatch layer introduced by the refactor
that renamed ``topsailai.py`` to ``topsailai_cli.py``.

Covers:
- The ``topsailai_cli.py`` shim delegating to ``cli_topsailai.core.main`` and
  its unconditional working-directory switch.
- The ``../bin/topsailai`` bash wrapper resolving ``BASE_NAME=topsailai_cli``.
- The ``../bin/topsailai_cli`` symlink pointing back to ``topsailai.cli``.
"""

import os
import runpy
import sys
import unittest
from unittest.mock import patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

import _import_topsailai  # noqa: E402
import cli_topsailai.core as cli_core  # noqa: E402


class TestEntryPointShim(unittest.TestCase):
    """Tests for the topsailai_cli.py thin shim."""

    def setUp(self):
        self.project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        self.shim_path = os.path.join(self.project_root, "topsailai_cli.py")
        self.bin_dir = os.path.normpath(os.path.join(self.project_root, "..", "bin"))

    @patch("cli_topsailai.core.main")
    def test_shim_reaches_core_main_without_args(self, mock_main):
        """Executing the shim delegates to cli_topsailai.core.main()."""
        original_argv = sys.argv
        original_cwd = os.getcwd()
        try:
            sys.argv = ["topsailai_cli.py"]
            runpy.run_path(self.shim_path, run_name="__main__")
            mock_main.assert_called_once_with([])
            # The shim unconditionally switches to PROJECT_FOLDER_BASE.
            self.assertEqual(os.getcwd(), _import_topsailai.PROJECT_FOLDER_BASE)
        finally:
            sys.argv = original_argv
            os.chdir(original_cwd)

    @patch("cli_topsailai.core.main")
    def test_shim_forwards_cli_arguments(self, mock_main):
        """CLI arguments after the program name are forwarded to main()."""
        original_argv = sys.argv
        original_cwd = os.getcwd()
        try:
            sys.argv = ["topsailai_cli.py", "--list-docs"]
            runpy.run_path(self.shim_path, run_name="__main__")
            mock_main.assert_called_once_with(["--list-docs"])
        finally:
            sys.argv = original_argv
            os.chdir(original_cwd)


class TestBinDispatchWiring(unittest.TestCase):
    """Read-only assertions on the bin/ dispatch layer."""

    def setUp(self):
        self.project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        self.bin_dir = os.path.normpath(os.path.join(self.project_root, "..", "bin"))

    def test_bin_topsailai_wrapper_resolves_base_name(self):
        """The bash wrapper must resolve BASE_NAME to the renamed entry point."""
        wrapper = os.path.join(self.bin_dir, "topsailai")
        with open(wrapper, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("BASE_NAME=topsailai_cli", content)

    def test_bin_topsailai_cli_symlink_points_back(self):
        """The topsailai_cli symlink must target topsailai.cli."""
        link = os.path.join(self.bin_dir, "topsailai_cli")
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), "topsailai.cli")


if __name__ == "__main__":
    unittest.main()