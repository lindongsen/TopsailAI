#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for ai_agent_driver resolution priority."""

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


class TestAgentDriverResolution(unittest.TestCase):
    """Verify driver selection priority:
    --driver > settings.environment > settings.ai_agent_driver > os.getenv.
    """

    def setUp(self):
        self._original_dir = os.getcwd()
        self._original_argv = sys.argv
        self._original_pwd = os.environ.get("TOPSAILAI_PWD")
        self._original_env_driver = os.environ.get("TOPSAILAI_AGENT_DRIVER")
        self._stdout = StringIO()
        self._stderr = StringIO()

    def tearDown(self):
        os.chdir(self._original_dir)
        sys.argv = self._original_argv
        if self._original_pwd is not None:
            os.environ["TOPSAILAI_PWD"] = self._original_pwd
        elif "TOPSAILAI_PWD" in os.environ:
            del os.environ["TOPSAILAI_PWD"]
        if self._original_env_driver is not None:
            os.environ["TOPSAILAI_AGENT_DRIVER"] = self._original_env_driver
        elif "TOPSAILAI_AGENT_DRIVER" in os.environ:
            del os.environ["TOPSAILAI_AGENT_DRIVER"]

    def _write_settings(
        self,
        workspace,
        driver="default-driver",
        default_env_driver=None,
        item_env_driver=None,
    ):
        settings_dir = os.path.join(workspace, ".topsailai")
        os.makedirs(settings_dir, exist_ok=True)
        settings_path = os.path.join(settings_dir, "settings.yaml")
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write(f'ai_agent_driver: "{driver}"\n')
            f.write('workspace: "."\n')
            f.write('context:\n')
            f.write('  _default:\n')
            f.write('    - "project.yaml"\n')
            f.write('  default:\n')
            f.write('    - "project.yaml"\n')
            f.write('environment:\n')
            f.write('  _default:\n')
            if default_env_driver:
                f.write(f'    TOPSAILAI_AGENT_DRIVER: "{default_env_driver}"\n')
            else:
                f.write('    DUMMY: "1"\n')
            f.write('  default:\n')
            if item_env_driver:
                f.write(f'    TOPSAILAI_AGENT_DRIVER: "{item_env_driver}"\n')
            else:
                f.write('    DUMMY: "1"\n')
        project_path = os.path.join(workspace, "project.yaml")
        with open(project_path, "w", encoding="utf-8") as f:
            f.write("# dummy project file\n")

    def _run_main(self, argv):
        sys.argv = argv
        with mock.patch("sys.stdout", self._stdout), mock.patch(
            "sys.stderr", self._stderr
        ):
            with self.assertRaises(SystemExit) as cm:
                launcher.main()
        return cm.exception.code

    def _command_line_section(self, output):
        """Return only the 'Command line:' section from dry-run output."""
        marker = "\nCommand line:\n"
        env_marker = "\nEnvironment variables (merged from _default and item):"
        start = output.find(marker)
        if start == -1:
            return ""
        start += len(marker)
        end = output.find(env_marker, start)
        if end == -1:
            return output[start:]
        return output[start:end]

    def test_cli_argument_overrides_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                driver="settings-driver",
                default_env_driver="default-env-driver",
                item_env_driver="item-env-driver",
            )
            os.environ["TOPSAILAI_AGENT_DRIVER"] = "os-env-driver"

            exit_code = self._run_main(
                [
                    "topsailai_launch_agent.py",
                    "--driver",
                    "cli-driver",
                    "--dry-run",
                ]
            )

            self.assertEqual(exit_code, 0)
            cmd_section = self._command_line_section(self._stdout.getvalue())
            self.assertIn("cli-driver", cmd_section)
            self.assertNotIn("item-env-driver", cmd_section)
            self.assertNotIn("default-env-driver", cmd_section)
            self.assertNotIn("settings-driver", cmd_section)
            self.assertNotIn("os-env-driver", cmd_section)

    def test_settings_environment_item_overrides_ai_agent_driver_and_os_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                driver="settings-driver",
                default_env_driver="default-env-driver",
                item_env_driver="item-env-driver",
            )
            os.environ["TOPSAILAI_AGENT_DRIVER"] = "os-env-driver"

            exit_code = self._run_main(["topsailai_launch_agent.py", "--dry-run"])

            self.assertEqual(exit_code, 0)
            cmd_section = self._command_line_section(self._stdout.getvalue())
            self.assertIn("item-env-driver", cmd_section)
            self.assertNotIn("default-env-driver", cmd_section)
            self.assertNotIn("settings-driver", cmd_section)
            self.assertNotIn("os-env-driver", cmd_section)

    def test_settings_environment_default_overrides_ai_agent_driver_and_os_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(
                tmpdir,
                driver="settings-driver",
                default_env_driver="default-env-driver",
            )
            os.environ["TOPSAILAI_AGENT_DRIVER"] = "os-env-driver"

            exit_code = self._run_main(["topsailai_launch_agent.py", "--dry-run"])

            self.assertEqual(exit_code, 0)
            cmd_section = self._command_line_section(self._stdout.getvalue())
            self.assertIn("default-env-driver", cmd_section)
            self.assertNotIn("settings-driver", cmd_section)
            self.assertNotIn("os-env-driver", cmd_section)

    def test_ai_agent_driver_overrides_os_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(tmpdir, driver="settings-driver")
            os.environ["TOPSAILAI_AGENT_DRIVER"] = "os-env-driver"

            exit_code = self._run_main(["topsailai_launch_agent.py", "--dry-run"])

            self.assertEqual(exit_code, 0)
            cmd_section = self._command_line_section(self._stdout.getvalue())
            self.assertIn("settings-driver", cmd_section)
            self.assertNotIn("os-env-driver", cmd_section)

    def test_os_env_used_as_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            self._write_settings(tmpdir, driver="")
            os.environ["TOPSAILAI_AGENT_DRIVER"] = "os-env-driver"

            exit_code = self._run_main(["topsailai_launch_agent.py", "--dry-run"])

            self.assertEqual(exit_code, 0)
            cmd_section = self._command_line_section(self._stdout.getvalue())
            self.assertIn("os-env-driver", cmd_section)


if __name__ == "__main__":
    unittest.main()
