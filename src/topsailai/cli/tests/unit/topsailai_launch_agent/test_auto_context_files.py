#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for automatic workspace context files in topsailai_launch_agent.

``AGENTS.md``, ``LEARN.md``, and ``MEMORY.md`` are injected into the default
context when they exist in the workspace (or in ``TOPSAILAI_PROJECT_FOLDER``),
and a file already configured in ``settings.yaml`` is never injected twice.
"""

import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest import mock

CLI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, CLI_DIR)

import topsailai_launch_agent as launcher


def _write(path, content):
    """Write ``content`` to ``path``, creating parent directories."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


class TestAutoContextRoots(unittest.TestCase):
    """Verify which directories are searched for instruction files."""

    def test_workspace_only_when_project_folder_is_absent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roots = launcher._auto_context_roots(tmpdir)

        self.assertEqual(roots, [os.path.realpath(tmpdir)])

    def test_project_folder_is_searched_after_the_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = os.path.join(tmpdir, "ws")
            project = os.path.join(tmpdir, "ws", "proj")
            os.makedirs(project)

            roots = launcher._auto_context_roots(workspace, project)

        self.assertEqual(
            roots, [os.path.realpath(workspace), os.path.realpath(project)]
        )

    def test_identical_project_folder_is_not_searched_twice(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roots = launcher._auto_context_roots(tmpdir, tmpdir)

        self.assertEqual(roots, [os.path.realpath(tmpdir)])

    def test_symlinked_project_folder_is_not_searched_twice(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = os.path.join(tmpdir, "ws")
            os.makedirs(workspace)
            link = os.path.join(tmpdir, "ws-link")
            os.symlink(workspace, link)

            roots = launcher._auto_context_roots(workspace, link)

        self.assertEqual(roots, [os.path.realpath(workspace)])


class TestDiscoverAutoContextFiles(unittest.TestCase):
    """Verify discovery, ordering, and deduplication."""

    def test_all_three_files_are_discovered_in_fixed_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("MEMORY.md", "LEARN.md", "AGENTS.md"):
                _write(os.path.join(tmpdir, name), name)

            discovered = launcher._discover_auto_context_files(tmpdir)

        self.assertEqual(
            [os.path.basename(source.value) for source in discovered],
            ["AGENTS.md", "LEARN.md", "MEMORY.md"],
        )
        self.assertTrue(all(source.type == "file" for source in discovered))

    def test_missing_files_are_not_discovered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(os.path.join(tmpdir, "LEARN.md"), "learn")

            discovered = launcher._discover_auto_context_files(tmpdir)

        self.assertEqual(
            [os.path.basename(source.value) for source in discovered], ["LEARN.md"]
        )

    def test_directory_with_a_matching_name_is_not_a_context_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "AGENTS.md"))

            discovered = launcher._discover_auto_context_files(tmpdir)

        self.assertEqual(discovered, [])

    def test_relative_configured_path_is_not_injected_twice(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(os.path.join(tmpdir, "LEARN.md"), "learn")
            existing = [launcher.ContextSource(type="file", value="LEARN.md")]

            discovered = launcher._discover_auto_context_files(
                tmpdir, existing_sources=existing
            )

        self.assertEqual(discovered, [])

    def test_absolute_configured_path_is_not_injected_twice(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "MEMORY.md")
            _write(path, "memory")
            existing = [launcher.ContextSource(type="file", value=path)]

            discovered = launcher._discover_auto_context_files(
                tmpdir, existing_sources=existing
            )

        self.assertEqual(discovered, [])

    def test_symlinked_configured_path_is_not_injected_twice(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "real-memory.md")
            _write(target, "memory")
            link = os.path.join(tmpdir, "MEMORY.md")
            os.symlink(target, link)
            existing = [launcher.ContextSource(type="file", value=target)]

            discovered = launcher._discover_auto_context_files(
                tmpdir, existing_sources=existing
            )

        self.assertEqual(discovered, [])

    def test_command_sources_do_not_suppress_a_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(os.path.join(tmpdir, "AGENTS.md"), "agents")
            existing = [
                launcher.ContextSource(type="command", value="cat AGENTS.md")
            ]

            discovered = launcher._discover_auto_context_files(
                tmpdir, existing_sources=existing
            )

        self.assertEqual(
            [os.path.basename(source.value) for source in discovered], ["AGENTS.md"]
        )

    def test_project_folder_file_is_discovered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = os.path.join(tmpdir, "proj")
            _write(os.path.join(project, "LEARN.md"), "project learn")

            discovered = launcher._discover_auto_context_files(tmpdir, project)

        self.assertEqual(
            [source.value for source in discovered],
            [os.path.join(os.path.realpath(project), "LEARN.md")],
        )

    def test_same_file_reachable_from_both_roots_is_injected_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = os.path.join(tmpdir, "proj")
            os.makedirs(project)
            _write(os.path.join(tmpdir, "AGENTS.md"), "agents")
            os.symlink(
                os.path.join(tmpdir, "AGENTS.md"),
                os.path.join(project, "AGENTS.md"),
            )

            discovered = launcher._discover_auto_context_files(tmpdir, project)

        self.assertEqual(len(discovered), 1)
        self.assertEqual(
            os.path.realpath(discovered[0].value),
            os.path.realpath(os.path.join(tmpdir, "AGENTS.md")),
        )


class TestMergeAutoContextSources(unittest.TestCase):
    """Verify the merge helper reports only the newly added sources."""

    def test_merge_appends_and_reports_only_new_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(os.path.join(tmpdir, "AGENTS.md"), "agents")
            _write(os.path.join(tmpdir, "LEARN.md"), "learn")
            existing = [launcher.ContextSource(type="file", value="LEARN.md")]

            merged, added = launcher._merge_auto_context_sources(existing, tmpdir)

        self.assertEqual(len(merged), 2)
        self.assertEqual(
            [os.path.basename(source.value) for source in added], ["AGENTS.md"]
        )

    def test_merge_does_not_mutate_the_input_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(os.path.join(tmpdir, "AGENTS.md"), "agents")
            existing = []

            launcher._merge_auto_context_sources(existing, tmpdir)

        self.assertEqual(existing, [])


class TestMainAutoContext(unittest.TestCase):
    """Verify main() injects the files into the assembled context message."""

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

    def tearDown(self):
        launcher._cleanup_message_files()
        launcher._CONTEXT_MESSAGE_FILE = self._original_context_file
        launcher._TASK_MESSAGE_FILE = self._original_task_file
        os.chdir(self._original_dir)
        sys.argv = self._original_argv
        self._workspace.cleanup()

    def _write_settings(self, context_sources, environment=None):
        """Write a settings file with the given base context sources."""
        lines = [
            'ai_agent_driver: "/bin/true"',
            'workspace: "."',
            "context:",
        ]
        if context_sources:
            lines.append("  _:")
            for source in context_sources:
                lines.append(f'    - "{source}"')
        else:
            lines.append("  _: []")
        lines.append("  default: []")
        lines.append("environment:")
        if environment:
            lines.append("  _:")
            for key, value in environment.items():
                lines.append(f'    {key}: "{value}"')
        else:
            lines.append("  _: {}")
        _write(
            os.path.join(self.workspace, ".topsailai", "settings.yaml"),
            "\n".join(lines) + "\n",
        )

    def _run_main(self, argv):
        """Run main() and return (exit_code, stdout, stderr)."""
        stdout = StringIO()
        stderr = StringIO()
        sys.argv = argv
        with mock.patch.object(launcher, "_scan_workspace_files", return_value=""), \
                mock.patch.object(launcher, "_driver_exists", return_value=True), \
                mock.patch("sys.stdout", stdout), \
                mock.patch("sys.stderr", stderr):
            with self.assertRaises(SystemExit) as raised:
                launcher.main()
        return raised.exception.code, stdout.getvalue(), stderr.getvalue()

    def test_dry_run_reports_auto_files(self):
        _write(os.path.join(self.workspace, "AGENTS.md"), "agents")
        _write(os.path.join(self.workspace, "MEMORY.md"), "memory")
        self._write_settings([])

        exit_code, output, _ = self._run_main(
            ["topsailai_launch_agent.py", "--dry-run"]
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Auto context files:", output)
        self.assertIn("AGENTS.md", output)
        self.assertIn("MEMORY.md", output)
        self.assertIn("auto: AGENTS.md, MEMORY.md", output)

    def test_configured_file_is_listed_once(self):
        _write(os.path.join(self.workspace, "LEARN.md"), "learn")
        _write(os.path.join(self.workspace, "AGENTS.md"), "agents")
        self._write_settings(["LEARN.md"])

        exit_code, output, _ = self._run_main(
            ["topsailai_launch_agent.py", "--dry-run"]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.count("[file]"), 2)
        self.assertIn("auto: AGENTS.md", output)
        self.assertNotIn("auto: AGENTS.md, LEARN.md", output)

    def test_no_base_context_suppresses_auto_files(self):
        _write(os.path.join(self.workspace, "AGENTS.md"), "agents")
        self._write_settings([])

        exit_code, output, _ = self._run_main(
            ["topsailai_launch_agent.py", "--dry-run", "--no-base-context"]
        )

        self.assertEqual(exit_code, 0)
        self.assertNotIn("Auto context files:", output)
        self.assertNotIn("[file]", output)

    def test_auto_files_are_read_into_the_context_message(self):
        _write(os.path.join(self.workspace, "AGENTS.md"), "AGENTS BODY")
        _write(os.path.join(self.workspace, "LEARN.md"), "LEARN BODY")
        _write(os.path.join(self.workspace, "MEMORY.md"), "MEMORY BODY")
        self._write_settings(["LEARN.md"])

        observed = {}

        def observe(environment):
            context_path = environment["TOPSAILAI_CONTEXT_USER_MESSAGE"]
            with open(context_path, encoding="utf-8") as handle:
                observed["context"] = handle.read()

        with mock.patch.object(
            launcher.subprocess,
            "run",
            side_effect=lambda *a, **k: (
                observe(k["env"]),
                mock.Mock(returncode=0),
            )[1],
        ):
            exit_code, _, _ = self._run_main(
                ["topsailai_launch_agent.py", "--subprocess"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(observed["context"].count("AGENTS BODY"), 1)
        self.assertEqual(observed["context"].count("LEARN BODY"), 1)
        self.assertEqual(observed["context"].count("MEMORY BODY"), 1)

    def test_project_folder_instruction_file_is_injected(self):
        project = os.path.join(self.workspace, "proj")
        _write(os.path.join(project, "LEARN.md"), "PROJECT LEARN BODY")
        self._write_settings(
            [], environment={"TOPSAILAI_PROJECT_FOLDER": "./proj"}
        )

        observed = {}

        def observe(environment):
            context_path = environment["TOPSAILAI_CONTEXT_USER_MESSAGE"]
            with open(context_path, encoding="utf-8") as handle:
                observed["context"] = handle.read()

        with mock.patch.object(
            launcher.subprocess,
            "run",
            side_effect=lambda *a, **k: (
                observe(k["env"]),
                mock.Mock(returncode=0),
            )[1],
        ):
            exit_code, _, _ = self._run_main(
                ["topsailai_launch_agent.py", "--subprocess"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(observed["context"].count("PROJECT LEARN BODY"), 1)


if __name__ == "__main__":
    unittest.main()
