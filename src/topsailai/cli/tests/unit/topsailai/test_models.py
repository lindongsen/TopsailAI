"""Unit tests for model registry and selection helpers.

Author: DawsonLin
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from cli_topsailai.models import (
    ModelConfigurationError,
    build_model_environment,
    clear_selected_model,
    load_models,
    load_selection,
    resolve_effective_model,
    set_selected_model,
    validate_model_record,
)


class TestModelRegistry(unittest.TestCase):
    """Verify JSONL loading and schema validation."""

    def test_loads_valid_records_in_file_order_and_reports_invalid_lines(self):
        with tempfile.TemporaryDirectory() as home:
            path = os.path.join(home, ".models.jsonl")
            records = [
                {
                    "id": "local-qwen",
                    "name": "Local Qwen",
                    "provider": "local",
                    "protocol": "openai-compatible",
                    "model": "qwen",
                    "base_url": "http://127.0.0.1:8000/v1",
                },
                "not-json",
                {
                    "id": "openai-gpt",
                    "name": "OpenAI GPT",
                    "provider": "openai",
                    "protocol": "openai-compatible",
                    "model": "gpt",
                },
            ]
            with open(path, "w", encoding="utf-8") as registry_file:
                for record in records:
                    if isinstance(record, dict):
                        registry_file.write(json.dumps(record) + "\n")
                    else:
                        registry_file.write(record + "\n")

            registry = load_models(path)

        self.assertEqual([model.id for model in registry.models], ["local-qwen", "openai-gpt"])
        self.assertEqual(len(registry.errors), 1)
        self.assertIn("Line 2", registry.errors[0])

    def test_rejects_duplicate_ids(self):
        record = {
            "id": "duplicate",
            "name": "One",
            "provider": "openai",
            "protocol": "openai-compatible",
            "model": "one",
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as registry_file:
            registry_file.write(json.dumps(record) + "\n")
            record["name"] = "Two"
            registry_file.write(json.dumps(record) + "\n")
            path = registry_file.name
        try:
            registry = load_models(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(registry.models), 1)
        self.assertIn("duplicate model id", registry.errors[0])

    def test_rejects_raw_and_additional_environment_secrets(self):
        base = {
            "id": "secure",
            "name": "Secure",
            "provider": "openai",
            "protocol": "openai-compatible",
            "model": "gpt",
        }
        with self.assertRaisesRegex(ModelConfigurationError, "raw secret fields"):
            validate_model_record({**base, "api_key": "secret"})
        with self.assertRaisesRegex(ModelConfigurationError, "cannot store secret"):
            validate_model_record(
                {**base, "environment": {"COMPANY_API_KEY": "secret"}}
            )

    def test_rejects_protected_environment_override(self):
        record = {
            "id": "bad-env",
            "name": "Bad Env",
            "provider": "openai",
            "protocol": "openai-compatible",
            "model": "gpt",
            "environment": {"TOPSAILAI_HOME": "/tmp/other"},
        }
        with self.assertRaisesRegex(ModelConfigurationError, "protected variable"):
            validate_model_record(record)


class TestModelSelection(unittest.TestCase):
    """Verify persistent scope precedence and clearing behavior."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.selection_path = os.path.join(self.temp_dir.name, ".model_selection.json")
        self.models = [
            validate_model_record(
                {
                    "id": "workspace-model",
                    "name": "Workspace",
                    "provider": "openai",
                    "protocol": "openai-compatible",
                    "model": "workspace",
                }
            ),
            validate_model_record(
                {
                    "id": "project-model",
                    "name": "Project",
                    "provider": "local",
                    "protocol": "openai-compatible",
                    "model": "project",
                }
            ),
        ]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_project_selection_overrides_workspace_and_clear_falls_back(self):
        project = os.path.join(self.temp_dir.name, "project")
        set_selected_model("workspace-model", path=self.selection_path)
        set_selected_model("project-model", project, self.selection_path)

        effective = resolve_effective_model(self.models, project, self.selection_path)
        self.assertEqual(effective.model_id, "project-model")
        self.assertEqual(effective.source, "project")

        self.assertTrue(clear_selected_model(project, self.selection_path))
        effective = resolve_effective_model(self.models, project, self.selection_path)
        self.assertEqual(effective.model_id, "workspace-model")
        self.assertEqual(effective.source, "workspace")

    def test_selection_file_preserves_other_project_entries(self):
        project_a = os.path.join(self.temp_dir.name, "a")
        project_b = os.path.join(self.temp_dir.name, "b")
        set_selected_model("workspace-model", path=self.selection_path)
        set_selected_model("project-model", project_a, self.selection_path)
        set_selected_model("workspace-model", project_b, self.selection_path)
        clear_selected_model(project_a, self.selection_path)

        state = load_selection(self.selection_path)
        self.assertEqual(state["workspace"], "workspace-model")
        self.assertEqual(len(state["projects"]), 1)
        self.assertEqual(next(iter(state["projects"].values())), "workspace-model")

    def test_missing_persisted_model_fails_without_fallback(self):
        set_selected_model("missing-model", path=self.selection_path)
        with self.assertRaisesRegex(ModelConfigurationError, "missing"):
            resolve_effective_model(self.models, selection_path=self.selection_path)


class TestModelEnvironment(unittest.TestCase):
    """Verify OpenAI-compatible child environment mapping."""

    def test_maps_openai_values_without_mutating_inherited_environment(self):
        model = validate_model_record(
            {
                "id": "company-model",
                "name": "Company",
                "provider": "custom",
                "protocol": "openai-compatible",
                "model": "company-chat",
                "base_url": "https://llm.example.test/v1",
                "api_key_env": "COMPANY_LLM_KEY",
                "organization_env": "COMPANY_ORG",
                "environment": {"OPENAI_TIMEOUT": 60},
            }
        )
        inherited = {
            "COMPANY_LLM_KEY": "secret-value",
            "COMPANY_ORG": "org-value",
            "UNCHANGED": "yes",
        }

        child = build_model_environment(model, inherited)

        self.assertEqual(child["OPENAI_MODEL"], "company-chat")
        self.assertEqual(child["OPENAI_BASE_URL"], "https://llm.example.test/v1")
        self.assertEqual(child["OPENAI_API_BASE"], "https://llm.example.test/v1")
        self.assertEqual(child["OPENAI_API_KEY"], "secret-value")
        self.assertEqual(child["OPENAI_ORG_ID"], "org-value")
        self.assertEqual(child["OPENAI_TIMEOUT"], "60")
        self.assertEqual(child["UNCHANGED"], "yes")
        self.assertNotIn("OPENAI_MODEL", inherited)

    def test_missing_secret_source_fails_without_exposing_values(self):
        model = validate_model_record(
            {
                "id": "missing-key",
                "name": "Missing Key",
                "provider": "openai",
                "protocol": "openai-compatible",
                "model": "gpt",
                "api_key_env": "MISSING_API_KEY",
            }
        )
        with self.assertRaisesRegex(ModelConfigurationError, "MISSING_API_KEY"):
            build_model_environment(model, {})


if __name__ == "__main__":
    unittest.main()
