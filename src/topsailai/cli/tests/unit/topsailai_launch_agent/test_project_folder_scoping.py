#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration tests for TOPSAILAI_PROJECT_FOLDER scoping in main()."""

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


class TestProjectFolderScoping(unittest.TestCase):
    """Verify main() passes TOPSAILAI_PROJECT_FOLDER to _scan_workspace_files."""

    def setUp(self):
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv
        self._stdout = StringIO()
        self._stderr = StringIO()

    def tearDown(self):
        os.chdir(self._original_dir)
        sys.argv = self._original_argv

    def _write_settings(self, workspace, environment=None):
        settings_dir = os.path.join(workspace, ".topsailai")
        os.makedirs(settings_dir, exist_ok=True)
        settings_path = os.path.join(settings_dir, "settings.yaml")
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write('ai_agent_driver: "test-driver"\n')
            f.write('workspace: "."\n')
            f.write('context:\n')
            f.write('  _: []\n')
            f.write('environment:\n')
            if environment:
                f.write('  _:\n')
                for key, value in environment.items():
                    f.write(f'    {key}: "{value}"\n')
            else:
                f.write('  _: {}\n')
        return settings_path

    def _run_main(self, argv):
        sys.argv = argv
        with mock.patch("sys.stdout", self._stdout), mock.patch(
            "sys.stderr", self._stderr
        ):
            with self.assertRaises(SystemExit) as cm:
                launcher.main()
        return cm.exception.code

    def test_project_folder_from_environment_scans_subfolder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            project_dir = os.path.join(tmpdir, "sub-project")
            os.makedirs(project_dir, exist_ok=True)
            self._write_settings(tmpdir, {"TOPSAILAI_PROJECT_FOLDER": project_dir})

            captured = {}

            def fake_scan(workspace, project_folder=None):
                captured["workspace"] = workspace
                captured["project_folder"] = project_folder
                return "fake-tree"

            with mock.patch.object(launcher, "_scan_workspace_files", fake_scan):
                exit_code = self._run_main(["topsailai_launch_agent.py", "--dry-run"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(captured["project_folder"], project_dir)

    def test_project_folder_from_os_environment_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            project_dir = os.path.join(tmpdir, "os-project")
            os.makedirs(project_dir, exist_ok=True)
            self._write_settings(tmpdir)

            captured = {}

            def fake_scan(workspace, project_folder=None):
                captured["workspace"] = workspace
                captured["project_folder"] = project_folder
                return "fake-tree"

            env = {"TOPSAILAI_PROJECT_FOLDER": project_dir}
            with mock.patch.object(launcher, "_scan_workspace_files", fake_scan):
                with mock.patch.dict(os.environ, env, clear=False):
                    exit_code = self._run_main(["topsailai_launch_agent.py", "--dry-run"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(captured["project_folder"], project_dir)


if __name__ == "__main__":
    unittest.main()
