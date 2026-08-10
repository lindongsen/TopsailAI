"""Unit tests for the ``topsailai models`` CLI subcommand.

Author: DawsonLin
"""

import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from cli_topsailai import models_cli
from cli_topsailai.models import validate_model_record


class TestSlugifyId(unittest.TestCase):
    """Verify id generation from display names."""

    def test_lowercases_and_replaces_spaces(self):
        self.assertEqual(models_cli._slugify_id("GPT-4o"), "gpt-4o")

    def test_trims_leading_trailing_separators(self):
        self.assertEqual(models_cli._slugify_id("  OpenAI GPT-4  "), "openai-gpt-4")

    def test_keeps_allowed_special_characters(self):
        self.assertEqual(models_cli._slugify_id("local:qwen_7b"), "local:qwen_7b")

    def test_collapses_consecutive_separators(self):
        self.assertEqual(models_cli._slugify_id("a  b"), "a-b")

    def test_fallback_when_name_is_only_separators(self):
        self.assertEqual(models_cli._slugify_id(" - "), "model")


class TestParseConfigPairs(unittest.TestCase):
    """Verify ``--config KEY=VALUE`` parsing."""

    def test_parses_string_values(self):
        record = models_cli._parse_config_pairs(
            ["provider=openai", "model=gpt-4o"]
        )
        self.assertEqual(record, {"provider": "openai", "model": "gpt-4o"})

    def test_parses_json_values(self):
        record = models_cli._parse_config_pairs(
            ["enabled=true", "tags=[\"a\",\"b\"]"]
        )
        self.assertEqual(record, {"enabled": True, "tags": ["a", "b"]})

    def test_rejects_missing_equals(self):
        with self.assertRaisesRegex(Exception, "KEY=VALUE"):
            models_cli._parse_config_pairs(["provider"])

    def test_rejects_empty_key(self):
        with self.assertRaisesRegex(Exception, "Empty key"):
            models_cli._parse_config_pairs(["=value"])


class TestBuildAddRecord(unittest.TestCase):
    """Verify record construction for ``add``."""

    def test_generates_id_from_name(self):
        record = models_cli._build_add_record("GPT-4o", ["provider=openai", "model=gpt-4o"])
        self.assertEqual(record["id"], "gpt-4o")
        self.assertEqual(record["name"], "GPT-4o")

    def test_preserves_explicit_id(self):
        record = models_cli._build_add_record(
            "GPT-4o", ["id=custom", "provider=openai", "model=gpt-4o"]
        )
        self.assertEqual(record["id"], "custom")

    def test_rejects_empty_name(self):
        with self.assertRaisesRegex(Exception, "model name is required"):
            models_cli._build_add_record("", [])

class TestExpandEnvironmentEntries(unittest.TestCase):
    """Verify ``environment.KEY`` expansion into the environment mapping."""

    def test_expands_environment_key(self):
        record = models_cli._expand_environment_entries(
            {"environment.TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "300"}
        )
        self.assertEqual(
            record,
            {"environment": {"TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "300"}},
        )

    def test_merges_with_existing_environment(self):
        record = models_cli._expand_environment_entries(
            {
                "environment": {"EXISTING": "1"},
                "environment.NEW": "2",
            }
        )
        self.assertEqual(record["environment"], {"EXISTING": "1", "NEW": "2"})

    def test_empty_value_removes_key(self):
        record = models_cli._expand_environment_entries(
            {
                "environment": {"TO_REMOVE": "1"},
                "environment.TO_REMOVE": "",
            }
        )
        self.assertEqual(record["environment"], {})

    def test_stringifies_values(self):
        record = models_cli._expand_environment_entries(
            {"environment.TIMEOUT": 300}
        )
        self.assertEqual(record["environment"], {"TIMEOUT": "300"})

    def test_rejects_missing_env_name(self):
        with self.assertRaisesRegex(Exception, "environment key name is required"):
            models_cli._expand_environment_entries({"environment.": "x"})


class TestBuildAddRecordEnvironment(unittest.TestCase):
    """Verify ``add`` supports environment entries."""

    def test_add_with_environment_entries(self):
        record = models_cli._build_add_record(
            "GPT-4o",
            [
                "provider=openai",
                "model=gpt-4o",
                "environment.TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT=300",
            ],
        )
        self.assertEqual(
            record["environment"],
            {"TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "300"},
        )


class TestBuildUpdateRecordEnvironment(unittest.TestCase):
    """Verify ``update`` supports environment entries with merge semantics."""

    def _make_model(self, environment=None):
        record = {
            "id": "gpt-4o",
            "name": "GPT-4o",
            "provider": "openai",
            "protocol": "openai-compatible",
            "model": "gpt-4o",
        }
        if environment:
            record["environment"] = environment
        return validate_model_record(record)

    def test_update_sets_environment_entry(self):
        model = self._make_model()
        record = models_cli._build_update_record(
            model,
            ["environment.TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT=300"],
        )
        self.assertEqual(
            record["environment"],
            {"TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "300"},
        )

    def test_update_merges_with_existing_environment(self):
        model = self._make_model({"EXISTING": "1"})
        record = models_cli._build_update_record(
            model,
            ["environment.NEW=2"],
        )
        self.assertEqual(record["environment"], {"EXISTING": "1", "NEW": "2"})

    def test_update_removes_environment_entry(self):
        model = self._make_model({"TO_REMOVE": "1", "KEEP": "2"})
        record = models_cli._build_update_record(
            model,
            ["environment.TO_REMOVE="],
        )
        self.assertEqual(record["environment"], {"KEEP": "2"})


class TestModelsList(unittest.TestCase):
    """Verify ``topsailai models list``."""

    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_empty_registry(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            mock_path.return_value = os.path.join(tmp, ".models.jsonl")
            code = models_cli.handle_models_list(argparse.Namespace(json=False))
        self.assertEqual(code, 0)
        self.assertIn("No model configurations found", mock_stdout.getvalue())

    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_lists_entries_with_row_numbers(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".models.jsonl")
            mock_path.return_value = path
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "id": "a",
                            "name": "A",
                            "provider": "openai",
                            "protocol": "openai-compatible",
                            "model": "gpt-a",
                        }
                    )
                    + "\n"
                )
                fh.write(
                    json.dumps(
                        {
                            "id": "b",
                            "name": "B",
                            "provider": "local",
                            "protocol": "openai-compatible",
                            "model": "gpt-b",
                        }
                    )
                    + "\n"
                )
            code = models_cli.handle_models_list(argparse.Namespace(json=False))
        self.assertEqual(code, 0)
        output = mock_stdout.getvalue()
        self.assertIn("1.", output)
        self.assertIn("2.", output)
        self.assertIn("\"name\": \"A\"", output)
        self.assertIn("\"name\": \"B\"", output)

    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_compact_json_output(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".models.jsonl")
            mock_path.return_value = path
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "id": "a",
                            "name": "A",
                            "provider": "openai",
                            "protocol": "openai-compatible",
                            "model": "gpt-a",
                        }
                    )
                    + "\n"
                )
            code = models_cli.handle_models_list(argparse.Namespace(json=True))
        self.assertEqual(code, 0)
        output = mock_stdout.getvalue().strip()
        self.assertTrue(output.startswith("["))
        self.assertIn("\"id\":\"a\"", output)


class TestModelsAdd(unittest.TestCase):
    """Verify ``topsailai models add``."""

    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_add_with_config_pairs(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".models.jsonl")
            mock_path.return_value = path
            args = argparse.Namespace(
                name="GPT-4o",
                config=[
                    "provider=openai",
                    "protocol=openai-compatible",
                    "model=gpt-4o",
                    "api_key_env=OPENAI_API_KEY",
                ],
                json=False,
            )
            code = models_cli.handle_models_add(args)
            self.assertEqual(code, 0)
            with open(path, "r", encoding="utf-8") as fh:
                records = [json.loads(line) for line in fh]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["id"], "gpt-4o")
            self.assertEqual(records[0]["name"], "GPT-4o")
            self.assertEqual(records[0]["api_key_env"], "OPENAI_API_KEY")

    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_add_rejects_duplicate_name(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".models.jsonl")
            mock_path.return_value = path
            record = {
                "id": "a",
                "name": "A",
                "provider": "openai",
                "protocol": "openai-compatible",
                "model": "gpt-a",
            }
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
            args = argparse.Namespace(
                name="A",
                config=["provider=openai", "protocol=openai-compatible", "model=gpt-a"],
                json=False,
            )
            code = models_cli.handle_models_add(args)
            self.assertEqual(code, 1)
            self.assertIn("already exists", mock_stdout.getvalue())

    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_add_rejects_raw_api_key(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".models.jsonl")
            mock_path.return_value = path
            args = argparse.Namespace(
                name="Bad",
                config=[
                    "provider=openai",
                    "protocol=openai-compatible",
                    "model=gpt",
                    "api_key=secret",
                ],
                json=False,
            )
            code = models_cli.handle_models_add(args)
            self.assertEqual(code, 1)
            self.assertIn("raw secret fields", mock_stdout.getvalue())


class TestModelsUpdate(unittest.TestCase):
    """Verify ``topsailai models update``."""

    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_update_by_name(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".models.jsonl")
            mock_path.return_value = path
            record = {
                "id": "a",
                "name": "A",
                "provider": "openai",
                "protocol": "openai-compatible",
                "model": "gpt-a",
            }
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
            args = argparse.Namespace(
                name="A",
                config=["base_url=https://example.test/v1"],
                json=False,
            )
            code = models_cli.handle_models_update(args)
            self.assertEqual(code, 0)
            with open(path, "r", encoding="utf-8") as fh:
                updated = json.loads(fh.read().strip())
            self.assertEqual(updated["base_url"], "https://example.test/v1")
            self.assertEqual(updated["id"], "a")

    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_update_rejects_missing_model(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".models.jsonl")
            mock_path.return_value = path
            args = argparse.Namespace(
                name="Missing",
                config=["base_url=https://example.test/v1"],
                json=False,
            )
            code = models_cli.handle_models_update(args)
            self.assertEqual(code, 1)
            self.assertIn("Model not found", mock_stdout.getvalue())


class TestModelsGet(unittest.TestCase):
    """Verify ``topsailai models get``."""

    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_get_prints_pretty_json(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".models.jsonl")
            mock_path.return_value = path
            record = {
                "id": "a",
                "name": "A",
                "provider": "openai",
                "protocol": "openai-compatible",
                "model": "gpt-a",
            }
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
            args = argparse.Namespace(name="A", json=False)
            code = models_cli.handle_models_get(args)
            self.assertEqual(code, 0)
            output = mock_stdout.getvalue()
            self.assertIn('"id": "a"', output)
            self.assertIn('"name": "A"', output)

    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_get_compact_json(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".models.jsonl")
            mock_path.return_value = path
            record = {
                "id": "a",
                "name": "A",
                "provider": "openai",
                "protocol": "openai-compatible",
                "model": "gpt-a",
            }
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
            args = argparse.Namespace(name="A", json=True)
            code = models_cli.handle_models_get(args)
            self.assertEqual(code, 0)
            output = mock_stdout.getvalue().strip()
            self.assertIn('"id":"a"', output)


class TestModelsDelete(unittest.TestCase):
    """Verify ``topsailai models delete``."""

    @patch("cli_topsailai.models_cli._confirm_deletion", return_value=True)
    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_delete_confirmed_interactively(self, mock_stdout, mock_path, _mock_confirm):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".models.jsonl")
            mock_path.return_value = path
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "id": "a",
                            "name": "A",
                            "provider": "openai",
                            "protocol": "openai-compatible",
                            "model": "gpt-a",
                        }
                    )
                    + "\n"
                )
            args = argparse.Namespace(name="A", yes=False, json=False)
            code = models_cli.handle_models_delete(args)
            self.assertEqual(code, 0)
            self.assertEqual(os.path.getsize(path), 0)

    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_delete_with_yes_flag(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".models.jsonl")
            mock_path.return_value = path
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "id": "a",
                            "name": "A",
                            "provider": "openai",
                            "protocol": "openai-compatible",
                            "model": "gpt-a",
                        }
                    )
                    + "\n"
                )
            args = argparse.Namespace(name="A", yes=True, json=False)
            code = models_cli.handle_models_delete(args)
            self.assertEqual(code, 0)
            self.assertEqual(os.path.getsize(path), 0)

    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("cli_topsailai.models_cli.get_model_selection_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_delete_clears_workspace_selection(
        self, mock_stdout, mock_selection_path, mock_models_path
    ):
        with tempfile.TemporaryDirectory() as tmp:
            models_path = os.path.join(tmp, ".models.jsonl")
            selection_path = os.path.join(tmp, ".model_selection.json")
            mock_models_path.return_value = models_path
            mock_selection_path.return_value = selection_path
            with open(models_path, "w", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "id": "a",
                            "name": "A",
                            "provider": "openai",
                            "protocol": "openai-compatible",
                            "model": "gpt-a",
                        }
                    )
                    + "\n"
                )
            with open(selection_path, "w", encoding="utf-8") as fh:
                json.dump({"workspace": "a", "projects": {}}, fh)

            args = argparse.Namespace(name="A", yes=True, json=False)
            code = models_cli.handle_models_delete(args)
            self.assertEqual(code, 0)
            with open(selection_path, "r", encoding="utf-8") as fh:
                state = json.load(fh)
            self.assertIsNone(state.get("workspace"))


class TestDispatch(unittest.TestCase):
    """Verify top-level dispatch into the models subcommand."""

    @patch("cli_topsailai.models_cli.get_models_path")
    def test_unknown_subcommand_returns_non_zero(self, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            mock_path.return_value = os.path.join(tmp, ".models.jsonl")
            code = models_cli.try_handle_models_subcommand(["models", "nope"])
            self.assertEqual(code, 2)

    @patch("cli_topsailai.models_cli.get_models_path")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_non_models_argv_is_ignored(self, mock_stdout, mock_path):
        with tempfile.TemporaryDirectory() as tmp:
            mock_path.return_value = os.path.join(tmp, ".models.jsonl")
            code = models_cli.try_handle_models_subcommand(["project", "list"])
            self.assertIsNone(code)


if __name__ == "__main__":
    unittest.main()
