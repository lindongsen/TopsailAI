#!/usr/bin/env python3
"""Unit tests for workspace environment-variable search."""

import os
import tempfile
import unittest
from unittest.mock import patch

import cli_topsailai.state as cli_state
from cli_topsailai.env_search import (
    find_environment_variables,
    get_environment_search_sources,
    parse_search_terms,
    read_environment_names,
)
from cli_topsailai.yaml_commands import (
    handle_yaml_command,
    load_yaml_commands,
    match_yaml_command,
)


class TestEnvironmentSearch(unittest.TestCase):
    """Tests for environment source parsing and precedence."""

    def test_parse_search_terms_supports_multiple_and_quoted_terms(self):
        self.assertEqual(
            parse_search_terms('OPENAI "TOOL CALL"'),
            ["openai", "tool call"],
        )

    def test_read_environment_names_includes_commented_assignments_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")
            with open(env_path, "w", encoding="utf-8") as env_file:
                env_file.write(
                    "# Optional setting follows\n"
                    "# SECRET_TOKEN=commented\n"
                    "OPENAI_API_KEY=secret-value\n"
                    "export TOPSAILAI_MODEL=visible-name-only\n"
                    "OPENAI_API_KEY=duplicate\n"
                    "INVALID-NAME=value\n"
                )

            self.assertEqual(
                read_environment_names(env_path),
                ["SECRET_TOKEN", "OPENAI_API_KEY", "TOPSAILAI_MODEL"],
            )

    def test_multiple_terms_use_case_insensitive_or_matching(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env.local")
            with open(env_path, "w", encoding="utf-8") as env_file:
                env_file.write(
                    "OPENAI_MODEL=x\n"
                    "TOPSAILAI_HISTORY_MAX_SIZE=1\n"
                    "UNRELATED=value\n"
                )

            result = find_environment_variables(
                ["openai", "history"],
                sources=[env_path],
            )

            self.assertEqual(
                result,
                (env_path, ["OPENAI_MODEL", "TOPSAILAI_HISTORY_MAX_SIZE"]),
            )

    def test_first_source_with_matches_wins(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = os.path.join(tmpdir, ".env.local")
            env_path = os.path.join(tmpdir, ".env")
            with open(local_path, "w", encoding="utf-8") as env_file:
                env_file.write("OPENAI_MODEL=local\n")
            with open(env_path, "w", encoding="utf-8") as env_file:
                env_file.write("OPENAI_API_BASE=default\n")

            result = find_environment_variables(
                ["openai"],
                sources=[local_path, env_path],
            )

            self.assertEqual(result, (local_path, ["OPENAI_MODEL"]))

    def test_source_without_matches_falls_through(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = os.path.join(tmpdir, ".env.local")
            env_path = os.path.join(tmpdir, ".env")
            template_path = os.path.join(tmpdir, "env_template")
            with open(local_path, "w", encoding="utf-8") as env_file:
                env_file.write("OTHER=value\n")
            with open(env_path, "w", encoding="utf-8") as env_file:
                env_file.write("ANOTHER=value\n")
            with open(template_path, "w", encoding="utf-8") as env_file:
                env_file.write("TOPSAILAI_USE_TOOL_CALLS=1\n")

            result = find_environment_variables(
                ["tool"],
                sources=[local_path, env_path, template_path],
            )

            self.assertEqual(
                result,
                (template_path, ["TOPSAILAI_USE_TOOL_CALLS"]),
            )

    def test_missing_sources_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "env_template")
            with open(template_path, "w", encoding="utf-8") as env_file:
                env_file.write("TOPSAILAI_MODEL=value\n")

            result = find_environment_variables(
                ["model"],
                sources=[os.path.join(tmpdir, "missing"), template_path],
            )

            self.assertEqual(result, (template_path, ["TOPSAILAI_MODEL"]))

    def test_default_sources_use_home_then_project_template(self):
        with patch.dict(os.environ, {"TOPSAILAI_HOME": "/tmp/example-home"}):
            sources = get_environment_search_sources()

        self.assertEqual(
            sources[:2],
            ["/tmp/example-home/.env.local", "/tmp/example-home/.env"],
        )
        self.assertTrue(sources[2].endswith("/src/topsailai/env_template"))


class TestEnvironmentSearchCommand(unittest.TestCase):
    """Tests for YAML registration and internal command output."""

    def setUp(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = load_yaml_commands()

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []

    def test_yaml_command_extracts_all_search_terms(self):
        matched = match_yaml_command("/env.search OPENAI HISTORY")

        self.assertIsNotNone(matched)
        instruction, variables = matched
        self.assertEqual(instruction["cmd"], "/env.search {args}")
        self.assertEqual(variables["args"], "OPENAI HISTORY")

    @patch("cli_topsailai.yaml_commands.print_info")
    @patch("cli_topsailai.completer.register_environment_completions")
    @patch("cli_topsailai.env_search.find_environment_variables")
    def test_handler_prints_source_and_registers_names_without_values(
        self, mock_find, mock_register, mock_print_info
    ):
        mock_find.return_value = (
            "/tmp/.env.local",
            ["OPENAI_API_KEY", "OPENAI_MODEL"],
        )
        instruction = {"cmd": "/env.search {args}", "shell": ""}

        action = handle_yaml_command(instruction, {"args": "OPENAI"})

        self.assertEqual(action, "yaml_handled")
        mock_register.assert_called_once_with(["OPENAI_API_KEY", "OPENAI_MODEL"])
        printed = [call.args[0] for call in mock_print_info.call_args_list]
        self.assertEqual(
            printed,
            ["Source: /tmp/.env.local", "OPENAI_API_KEY", "OPENAI_MODEL"],
        )
        self.assertNotIn("secret", "\n".join(printed))

    @patch("cli_topsailai.yaml_commands.print_error")
    def test_handler_requires_at_least_one_term(self, mock_print_error):
        instruction = {"cmd": "/env.search {args}", "shell": ""}

        action = handle_yaml_command(instruction, {"args": ""})

        self.assertEqual(action, "yaml_handled")
        mock_print_error.assert_called_once_with(
            "Usage: /env.search <term> [term...]"
        )

    @patch("cli_topsailai.yaml_commands.print_info")
    @patch("cli_topsailai.env_search.find_environment_variables", return_value=None)
    def test_handler_reports_no_matches(self, _mock_find, mock_print_info):
        instruction = {"cmd": "/env.search {args}", "shell": ""}

        handle_yaml_command(instruction, {"args": "unknown"})

        mock_print_info.assert_called_once_with(
            "No configurable environment variables matched."
        )


if __name__ == "__main__":
    unittest.main()
