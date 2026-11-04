#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for launcher-provided initial user tasks."""

import os
import sys
import tempfile
import unittest
from io import StringIO
from types import SimpleNamespace
from unittest import mock

CLI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, CLI_DIR)

import topsailai_launch_agent as launcher


class TestInitialTask(unittest.TestCase):
    """Verify --task delivery, precedence, validation, and cleanup."""

    def setUp(self):
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv
        self._original_context_file = launcher._CONTEXT_MESSAGE_FILE
        self._original_task_file = launcher._TASK_MESSAGE_FILE
        temporary_root = os.path.join(CLI_DIR, ".tmp")
        os.makedirs(temporary_root, exist_ok=True)
        self._workspace = tempfile.TemporaryDirectory(dir=temporary_root)
        self.workspace = self._workspace.name
        os.chdir(self.workspace)
        settings_dir = os.path.join(self.workspace, ".topsailai")
        os.makedirs(settings_dir, exist_ok=True)
        with open(
            os.path.join(settings_dir, "settings.yaml"), "w", encoding="utf-8"
        ) as settings_file:
            settings_file.write(
                'ai_agent_driver: "/bin/true"\n'
                'workspace: "."\n'
                'context:\n'
                '  _: []\n'
                'environment:\n'
                '  _: {}\n'
            )

    def tearDown(self):
        launcher._cleanup_message_files()
        launcher._CONTEXT_MESSAGE_FILE = self._original_context_file
        launcher._TASK_MESSAGE_FILE = self._original_task_file
        os.chdir(self._original_dir)
        sys.argv = self._original_argv
        self._workspace.cleanup()

    def _run_main(self, argv, child_return_code=0, child_observer=None):
        stdout = StringIO()
        stderr = StringIO()

        def run_child(*args, **kwargs):
            if child_observer:
                child_observer(kwargs["env"])
            return SimpleNamespace(returncode=child_return_code)

        sys.argv = argv
        with mock.patch.object(launcher, "_scan_workspace_files", return_value=""), \
                mock.patch.object(launcher.subprocess, "run", side_effect=run_child), \
                mock.patch("sys.stdout", stdout), \
                mock.patch("sys.stderr", stderr):
            with self.assertRaises(SystemExit) as raised:
                launcher.main()
        return raised.exception.code, stdout.getvalue(), stderr.getvalue()

    def test_task_overrides_existing_value_and_preserves_exact_content(self):
        task = '修复测试失败\n保留 "引号" 和 emoji 🚀\n'
        observed = {}

        def observe(environment):
            task_path = environment["TOPSAILAI_TASK"]
            observed["path"] = task_path
            observed["exists_during_run"] = os.path.isfile(task_path)
            with open(task_path, encoding="utf-8") as task_file:
                observed["content"] = task_file.read()
            context_value = environment.get("TOPSAILAI_CONTEXT_USER_MESSAGE", "")
            observed["context"] = context_value

        with mock.patch.dict(os.environ, {"TOPSAILAI_TASK": "older task"}, clear=False):
            exit_code, output, _ = self._run_main(
                [
                    "topsailai_launch_agent.py",
                    "--item",
                    "_",
                    "--subprocess",
                    "--task",
                    task,
                ],
                child_observer=observe,
            )

        self.assertEqual(exit_code, 0)
        self.assertTrue(observed["exists_during_run"])
        self.assertEqual(observed["content"], task)
        self.assertNotEqual(observed["path"], "older task")
        self.assertNotIn(task, observed["context"])
        self.assertFalse(os.path.exists(observed["path"]))
        self.assertIn(f"Initial task: configured ({len(task)} characters)", output)
        self.assertNotIn(task, output)

    def test_existing_task_is_preserved_when_option_is_omitted(self):
        observed = {}

        def observe(environment):
            observed["task"] = environment["TOPSAILAI_TASK"]

        with mock.patch.dict(
            os.environ, {"TOPSAILAI_TASK": "existing startup task"}, clear=False
        ):
            exit_code, _, _ = self._run_main(
                ["topsailai_launch_agent.py", "--item", "_", "--subprocess"],
                child_observer=observe,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(observed["task"], "existing startup task")

    def test_task_file_is_removed_after_child_failure(self):
        observed = {}

        def observe(environment):
            observed["path"] = environment["TOPSAILAI_TASK"]
            self.assertTrue(os.path.isfile(observed["path"]))

        exit_code, _, _ = self._run_main(
            [
                "topsailai_launch_agent.py",
                "--item",
                "_",
                "--subprocess",
                "--task",
                "failing task",
            ],
            child_return_code=7,
            child_observer=observe,
        )

        self.assertEqual(exit_code, 7)
        self.assertFalse(os.path.exists(observed["path"]))

    def test_dry_run_redacts_task_and_creates_no_task_file(self):
        task = "secret task body that must not appear"
        sys.argv = [
            "topsailai_launch_agent.py",
            "--item",
            "_",
            "--dry-run",
            "--task",
            task,
        ]
        stdout = StringIO()
        with mock.patch.dict(
            os.environ, {"TOPSAILAI_TASK": "inherited task body"}, clear=False
        ), mock.patch.object(
            launcher, "_scan_workspace_files", return_value=""
        ), mock.patch.object(
            launcher, "_write_task_message_file"
        ) as writer, mock.patch(
            "sys.stdout", stdout
        ):
            with self.assertRaises(SystemExit) as raised:
                launcher.main()

        output = stdout.getvalue()
        self.assertEqual(raised.exception.code, 0)
        writer.assert_not_called()
        self.assertIn(f"Initial task: configured ({len(task)} characters)", output)
        self.assertIn("TOPSAILAI_TASK=<configured>", output)
        self.assertNotIn(task, output)
        self.assertNotIn("inherited task body", output)

    def test_empty_task_is_rejected(self):
        for value in ("", "  \n\t"):
            with self.subTest(value=value):
                sys.argv = ["topsailai_launch_agent.py", "--task", value]
                with mock.patch("sys.stderr", StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        launcher.main()
                self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
