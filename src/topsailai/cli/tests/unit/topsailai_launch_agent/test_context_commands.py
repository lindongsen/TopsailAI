#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for command context sources in topsailai_launch_agent."""

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


class TestNormalizeContextSource(unittest.TestCase):
    """Verify _normalize_context_source handles files and commands."""

    def test_plain_string_becomes_file_source(self):
        source = launcher._normalize_context_source("README.md")
        self.assertEqual(source.type, "file")
        self.assertEqual(source.value, "README.md")

    def test_file_dict_with_path(self):
        source = launcher._normalize_context_source({"type": "file", "path": "x.md"})
        self.assertEqual(source.type, "file")
        self.assertEqual(source.value, "x.md")

    def test_file_dict_without_path_raises(self):
        with self.assertRaises(ValueError):
            launcher._normalize_context_source({"type": "file"})

    def test_command_dict_minimal(self):
        source = launcher._normalize_context_source({"type": "command", "command": "echo hi"})
        self.assertEqual(source.type, "command")
        self.assertEqual(source.value, "echo hi")
        self.assertTrue(source.shell)
        self.assertEqual(source.timeout, 30.0)
        self.assertEqual(source.on_error, "abort")

    def test_command_dict_all_fields(self):
        source = launcher._normalize_context_source({
            "type": "command",
            "command": "python run.py",
            "shell": False,
            "timeout": 60,
            "label": "runner",
            "on_error": "skip",
            "cwd": "/tmp",
            "environ": {"FOO": "bar"},
        })
        self.assertEqual(source.type, "command")
        self.assertEqual(source.value, "python run.py")
        self.assertFalse(source.shell)
        self.assertEqual(source.timeout, 60.0)
        self.assertEqual(source.label, "runner")
        self.assertEqual(source.on_error, "skip")
        self.assertEqual(source.cwd, "/tmp")
        self.assertEqual(source.environ, {"FOO": "bar"})

    def test_invalid_source_type(self):
        with self.assertRaises(ValueError):
            launcher._normalize_context_source({"type": "unknown"})

    def test_invalid_top_level_type(self):
        with self.assertRaises(ValueError):
            launcher._normalize_context_source(123)

    def test_invalid_timeout(self):
        with self.assertRaises(ValueError):
            launcher._normalize_context_source({"type": "command", "command": "x", "timeout": "abc"})

    def test_invalid_on_error(self):
        with self.assertRaises(ValueError):
            launcher._normalize_context_source({"type": "command", "command": "x", "on_error": "bad"})


class TestExecuteContextCommand(unittest.TestCase):
    """Verify _execute_context_command behavior."""

    def test_successful_command_returns_formatted_block(self):
        source = launcher.ContextSource(type="command", value="echo hello", shell=True)
        block = launcher._execute_context_command(source, "/tmp")
        self.assertIn("> Command: echo hello > START", block)
        self.assertIn("hello", block)
        self.assertIn("> Command: echo hello > END", block)

    def test_non_shell_command_splits_args(self):
        source = launcher.ContextSource(type="command", value="echo hello", shell=False)
        block = launcher._execute_context_command(source, "/tmp")
        self.assertIn("hello", block)

    def test_label_replaces_command_in_header(self):
        source = launcher.ContextSource(type="command", value="echo hello", label="greeting")
        block = launcher._execute_context_command(source, "/tmp")
        self.assertIn("> Command: greeting > START", block)

    def test_command_failure_include_adds_warning(self):
        source = launcher.ContextSource(type="command", value="exit 1", shell=True, on_error="include")
        block = launcher._execute_context_command(source, "/tmp")
        self.assertIn("Warning: command exited with code 1", block)

    def test_command_failure_skip_returns_empty(self):
        source = launcher.ContextSource(type="command", value="exit 1", shell=True, on_error="skip")
        block = launcher._execute_context_command(source, "/tmp")
        self.assertEqual(block, "")

    def test_command_failure_abort_raises(self):
        source = launcher.ContextSource(type="command", value="exit 1", shell=True, on_error="abort")
        with self.assertRaises(RuntimeError):
            launcher._execute_context_command(source, "/tmp")

    def test_command_timeout_include_adds_error(self):
        source = launcher.ContextSource(type="command", value="sleep 10", shell=True, timeout=0.01, on_error="include")
        block = launcher._execute_context_command(source, "/tmp")
        self.assertIn("Command timed out", block)

    def test_command_timeout_skip_returns_empty(self):
        source = launcher.ContextSource(type="command", value="sleep 10", shell=True, timeout=0.01, on_error="skip")
        block = launcher._execute_context_command(source, "/tmp")
        self.assertEqual(block, "")

    def test_command_timeout_abort_raises(self):
        source = launcher.ContextSource(type="command", value="sleep 10", shell=True, timeout=0.01, on_error="abort")
        with self.assertRaises(RuntimeError):
            launcher._execute_context_command(source, "/tmp")

    def test_command_uses_custom_cwd(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = launcher.ContextSource(type="command", value="pwd", shell=True, cwd=tmpdir)
            block = launcher._execute_context_command(source, "/tmp")
            self.assertIn(tmpdir, block)

    def test_command_uses_custom_environ(self):
        source = launcher.ContextSource(
            type="command",
            value="echo $MY_VAR",
            shell=True,
            environ={"MY_VAR": "custom_value"},
        )
        block = launcher._execute_context_command(source, "/tmp")
        self.assertIn("custom_value", block)


class TestReadContextBlocks(unittest.TestCase):
    """Verify _read_context_blocks handles mixed file and command sources."""

    def test_file_and_command_sources_combined(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "sample.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("file content\n")

            sources = [
                launcher.ContextSource(type="file", value=file_path),
                launcher.ContextSource(type="command", value="echo command content", shell=True),
            ]
            blocks = launcher._read_context_blocks(sources, tmpdir)
            self.assertIn("file content", blocks)
            self.assertIn("command content", blocks)
            self.assertIn("> File:", blocks)
            self.assertIn("> Command:", blocks)

    def test_missing_file_is_skipped_with_warning(self):
        sources = [launcher.ContextSource(type="file", value="/nonexistent/path.txt")]
        with mock.patch("sys.stderr", new=StringIO()):
            blocks = launcher._read_context_blocks(sources, "/tmp")
        self.assertEqual(blocks, "")


class TestIntegrationCommandContext(unittest.TestCase):
    """End-to-end tests for command context sources via main()."""

    def setUp(self):
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv
        self._stdout = StringIO()
        self._stderr = StringIO()

    def tearDown(self):
        os.chdir(self._original_dir)
        sys.argv = self._original_argv

    def _write_settings(self, workspace, context):
        settings_dir = os.path.join(workspace, ".topsailai")
        os.makedirs(settings_dir, exist_ok=True)
        settings_path = os.path.join(settings_dir, "settings.yaml")
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write('ai_agent_driver: "test-driver"\n')
            f.write('workspace: "."\n')
            f.write('context:\n')
            for key, value in context.items():
                if not value:
                    f.write(f'  {key}: []\n')
                else:
                    f.write(f'  {key}:\n')
                    for item in value:
                        if isinstance(item, dict):
                            f.write('    - type: command\n')
                            for k, v in item.items():
                                if k == "type":
                                    continue
                                if isinstance(v, bool):
                                    rendered = "true" if v else "false"
                                elif isinstance(v, (int, float)):
                                    rendered = str(v)
                                else:
                                    rendered = f'"{v}"'
                                f.write(f'      {k}: {rendered}\n')
                        else:
                            f.write(f'    - "{item}"\n')
            f.write('environment:\n')
            f.write('  _default: {}\n')
        return settings_path

    def _run_main(self, argv):
        sys.argv = argv
        with mock.patch("sys.stdout", self._stdout), mock.patch(
            "sys.stderr", self._stderr
        ):
            with self.assertRaises(SystemExit) as cm:
                launcher.main()
        return cm.exception.code

    def test_dry_run_lists_command_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(tmpdir, {
                "_default": ["project.yaml"],
                "default": [{"type": "command", "command": "echo hi"}],
            })
            project_path = os.path.join(tmpdir, "project.yaml")
            with open(project_path, "w", encoding="utf-8") as f:
                f.write("# project\n")

            exit_code = self._run_main(["topsailai_launch_agent.py", "--dry-run"])

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn("[command]", stdout_output)
            self.assertIn("echo hi", stdout_output)
            self.assertIn("[file]", stdout_output)

    def test_command_source_generates_context_message_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(tmpdir, {
                "_default": [{"type": "command", "command": "echo context-line"}],
            })

            exit_code = self._run_main(["topsailai_launch_agent.py", "--dry-run"])

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn("[command]", stdout_output)
            self.assertIn("echo context-line", stdout_output)

    def test_command_source_with_non_shell_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(tmpdir, {
                "_default": [{"type": "command", "command": "echo hi", "shell": False}],
            })

            exit_code = self._run_main(["topsailai_launch_agent.py", "--dry-run"])

            self.assertEqual(exit_code, 0)
            stdout_output = self._stdout.getvalue()
            self.assertIn("[command]", stdout_output)
            self.assertIn("shell: false", stdout_output)


if __name__ == "__main__":
    unittest.main()
