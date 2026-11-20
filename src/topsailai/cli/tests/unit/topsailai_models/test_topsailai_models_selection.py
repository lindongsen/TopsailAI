"""Unit tests for non-interactive model selection.

Covers the shared selectability validator, the ``set`` / ``current`` /
``clear`` subcommands, the shared model-argument resolver, and the
effective-model marking in ``list``.

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
from cli_topsailai.models import (
    ModelConfigurationError,
    normalize_project_workspace,
    validate_model_record,
)


def _record(model_id, name, protocol="openai-compatible", enabled=True):
    """Build one valid registry record for a test fixture."""
    return {
        "id": model_id,
        "name": name,
        "provider": "openai",
        "protocol": protocol,
        "model": f"gpt-{model_id}",
        "enabled": enabled,
    }


class _SelectionTestCase(unittest.TestCase):
    """Provide a temporary registry plus selection file for each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.models_path = os.path.join(self._tmp.name, ".models.jsonl")
        self.selection_path = os.path.join(self._tmp.name, ".model_selection.json")

        registry_patch = patch(
            "cli_topsailai.models_cli.get_models_path",
            return_value=self.models_path,
        )
        selection_patch = patch(
            "cli_topsailai.models.get_model_selection_path",
            return_value=self.selection_path,
        )
        registry_patch.start()
        selection_patch.start()
        self.addCleanup(registry_patch.stop)
        self.addCleanup(selection_patch.stop)

    def write_registry(self, *records):
        """Write the given records as the registry file."""
        with open(self.models_path, "w", encoding="utf-8") as registry_file:
            for record in records:
                registry_file.write(json.dumps(record) + "\n")

    def write_selection(self, state):
        """Write the given selection state."""
        with open(self.selection_path, "w", encoding="utf-8") as selection_file:
            json.dump(state, selection_file)

    def read_selection(self):
        """Return the persisted selection state."""
        with open(self.selection_path, "r", encoding="utf-8") as selection_file:
            return json.load(selection_file)

    def run_handler(self, handler, **kwargs):
        """Run one handler while capturing stdout and stderr separately."""
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            code = handler(argparse.Namespace(**kwargs))
        return code, stdout.getvalue(), stderr.getvalue()


class TestResolveModelArgument(unittest.TestCase):
    """Verify selector resolution order: name, then id, then row number."""

    def setUp(self):
        self.models = [
            validate_model_record(_record("alpha", "Alpha")),
            validate_model_record(_record("beta", "Beta")),
        ]

    def test_resolves_by_display_name(self):
        target = models_cli.resolve_model_argument(self.models, "Beta")
        self.assertEqual(target.id, "beta")

    def test_resolves_by_model_id(self):
        target = models_cli.resolve_model_argument(self.models, "alpha")
        self.assertEqual(target.name, "Alpha")

    def test_resolves_by_row_number(self):
        target = models_cli.resolve_model_argument(self.models, "2")
        self.assertEqual(target.id, "beta")

    def test_identity_beats_position(self):
        models = [
            validate_model_record(_record("first", "First")),
            validate_model_record(_record("second", "1")),
        ]
        target = models_cli.resolve_model_argument(models, "1")
        self.assertEqual(target.id, "second")

    def test_out_of_range_number_returns_none(self):
        self.assertIsNone(models_cli.resolve_model_argument(self.models, "9"))

    def test_unknown_selector_returns_none(self):
        self.assertIsNone(models_cli.resolve_model_argument(self.models, "nope"))

    def test_blank_selector_returns_none(self):
        self.assertIsNone(models_cli.resolve_model_argument(self.models, "   "))

    def test_surrounding_whitespace_is_ignored(self):
        target = models_cli.resolve_model_argument(self.models, "  Alpha  ")
        self.assertEqual(target.id, "alpha")


class TestValidateSelectableModel(unittest.TestCase):
    """Verify the validator shared by interactive and non-interactive paths."""

    def test_accepts_enabled_supported_model(self):
        model = validate_model_record(_record("a", "A"))
        self.assertEqual(models_cli.validate_selectable_model(model), model)

    def test_rejects_disabled_model(self):
        model = validate_model_record(_record("a", "A", enabled=False))
        with self.assertRaisesRegex(ModelConfigurationError, "Model 'a' is disabled"):
            models_cli.validate_selectable_model(model)

    def test_rejects_unsupported_protocol(self):
        model = validate_model_record(_record("a", "A", protocol="other"))
        with self.assertRaisesRegex(
            ModelConfigurationError, "Model protocol 'other' is not supported"
        ):
            models_cli.validate_selectable_model(model)

    def test_label_prefixes_the_message(self):
        model = validate_model_record(_record("a", "A", enabled=False))
        with self.assertRaisesRegex(
            ModelConfigurationError, "Selected workspace model 'a' is disabled"
        ):
            models_cli.validate_selectable_model(model, label="Selected workspace")


class TestModelsSet(_SelectionTestCase):
    """Verify ``topsailai models set``."""

    def test_sets_workspace_default_by_name(self):
        self.write_registry(_record("a", "A"), _record("b", "B"))
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_set, name="B", project=None, json=False
        )
        self.assertEqual(code, 0)
        self.assertIn("Selected workspace model", stdout)
        self.assertEqual(self.read_selection()["workspace"], "b")

    def test_sets_workspace_default_by_row_number(self):
        self.write_registry(_record("a", "A"), _record("b", "B"))
        code, _, _ = self.run_handler(
            models_cli.handle_models_set, name="2", project=None, json=False
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.read_selection()["workspace"], "b")

    def test_sets_project_override(self):
        self.write_registry(_record("a", "A"), _record("b", "B"))
        project = os.path.join(self._tmp.name, "project")
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_set, name="B", project=project, json=False
        )
        self.assertEqual(code, 0)
        self.assertIn("Selected project model", stdout)
        state = self.read_selection()
        self.assertIsNone(state["workspace"])
        self.assertEqual(
            state["projects"][normalize_project_workspace(project)], "b"
        )

    def test_rejects_disabled_model_without_persisting(self):
        self.write_registry(_record("a", "A", enabled=False))
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_set, name="A", project=None, json=False
        )
        self.assertEqual(code, 1)
        self.assertIn("is disabled", stdout)
        self.assertFalse(os.path.exists(self.selection_path))

    def test_rejects_unsupported_protocol_without_persisting(self):
        self.write_registry(_record("a", "A", protocol="other"))
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_set, name="A", project=None, json=False
        )
        self.assertEqual(code, 1)
        self.assertIn("is not supported", stdout)
        self.assertFalse(os.path.exists(self.selection_path))

    def test_unknown_model_returns_one(self):
        self.write_registry(_record("a", "A"))
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_set, name="missing", project=None, json=False
        )
        self.assertEqual(code, 1)
        self.assertIn("Model not found", stdout)

    def test_json_output_shape(self):
        self.write_registry(_record("a", "A"))
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_set, name="A", project=None, json=True
        )
        self.assertEqual(code, 0)
        document = json.loads(stdout)
        self.assertEqual(document["status"], "ok")
        self.assertEqual(document["action"], "set")
        self.assertEqual(document["scope"], "workspace")
        self.assertIsNone(document["project_workspace"])
        self.assertEqual(document["model"]["id"], "a")


class TestModelsCurrent(_SelectionTestCase):
    """Verify ``topsailai models current``."""

    def test_reports_inherited_when_nothing_selected(self):
        self.write_registry(_record("a", "A"))
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_current, project=None, json=False
        )
        self.assertEqual(code, 0)
        self.assertIn("No persisted model selection", stdout)

    def test_reports_workspace_selection(self):
        self.write_registry(_record("a", "A"), _record("b", "B"))
        self.write_selection({"workspace": "b", "projects": {}})
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_current, project=None, json=False
        )
        self.assertEqual(code, 0)
        self.assertIn("Effective model (workspace)", stdout)
        self.assertIn("B [b]", stdout)

    def test_project_override_wins(self):
        self.write_registry(_record("a", "A"), _record("b", "B"))
        project = os.path.join(self._tmp.name, "project")
        self.write_selection(
            {
                "workspace": "a",
                "projects": {normalize_project_workspace(project): "b"},
            }
        )
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_current, project=project, json=False
        )
        self.assertEqual(code, 0)
        self.assertIn("Effective model (project)", stdout)
        self.assertIn("B [b]", stdout)

    def test_missing_selected_model_fails_with_json_error(self):
        self.write_registry(_record("a", "A"))
        self.write_selection({"workspace": "gone", "projects": {}})
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_current, project=None, json=True
        )
        self.assertEqual(code, 1)
        document = json.loads(stdout)
        self.assertEqual(document["status"], "error")
        self.assertEqual(document["error_code"], "selection_invalid")
        self.assertIn("gone", document["message"])

    def test_disabled_selection_fails(self):
        self.write_registry(_record("a", "A", enabled=False))
        self.write_selection({"workspace": "a", "projects": {}})
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_current, project=None, json=False
        )
        self.assertEqual(code, 1)
        self.assertIn("is disabled", stdout)

    def test_json_reports_source_and_model(self):
        self.write_registry(_record("a", "A"))
        self.write_selection({"workspace": "a", "projects": {}})
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_current, project=None, json=True
        )
        self.assertEqual(code, 0)
        document = json.loads(stdout)
        self.assertEqual(document["source"], "workspace")
        self.assertEqual(document["model_id"], "a")
        self.assertEqual(document["model"]["id"], "a")


class TestModelsClear(_SelectionTestCase):
    """Verify ``topsailai models clear``."""

    def test_clears_workspace_selection(self):
        self.write_selection({"workspace": "a", "projects": {}})
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_clear, project=None, json=False
        )
        self.assertEqual(code, 0)
        self.assertIn("Cleared workspace model selection", stdout)
        self.assertIsNone(self.read_selection()["workspace"])

    def test_reports_nothing_to_clear(self):
        self.write_selection({"workspace": None, "projects": {}})
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_clear, project=None, json=False
        )
        self.assertEqual(code, 0)
        self.assertIn("No workspace model selection was set", stdout)

    def test_clears_project_selection(self):
        project = os.path.join(self._tmp.name, "project")
        key = normalize_project_workspace(project)
        self.write_selection({"workspace": "a", "projects": {key: "b"}})
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_clear, project=project, json=False
        )
        self.assertEqual(code, 0)
        self.assertIn("Cleared project model selection", stdout)
        state = self.read_selection()
        self.assertNotIn(key, state["projects"])
        self.assertEqual(state["workspace"], "a")

    def test_json_reports_cleared_flag(self):
        self.write_selection({"workspace": "a", "projects": {}})
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_clear, project=None, json=True
        )
        self.assertEqual(code, 0)
        document = json.loads(stdout)
        self.assertEqual(document["action"], "clear")
        self.assertTrue(document["cleared"])


class TestModelsListSelection(_SelectionTestCase):
    """Verify the effective-model marking in ``topsailai models list``."""

    def test_marks_only_the_effective_entry(self):
        self.write_registry(_record("a", "A"), _record("b", "B"))
        self.write_selection({"workspace": "b", "projects": {}})
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_list, project=None, json=False
        )
        self.assertEqual(code, 0)
        self.assertIn("  1. ", stdout)
        self.assertIn(" * 2. ", stdout)
        self.assertIn("Current model (workspace)", stdout)

    def test_reports_no_selection(self):
        self.write_registry(_record("a", "A"))
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_list, project=None, json=False
        )
        self.assertEqual(code, 0)
        self.assertIn("No workspace model selection", stdout)

    def test_json_adds_selected_boolean(self):
        self.write_registry(_record("a", "A"), _record("b", "B"))
        self.write_selection({"workspace": "b", "projects": {}})
        code, stdout, _ = self.run_handler(
            models_cli.handle_models_list, project=None, json=True
        )
        self.assertEqual(code, 0)
        records = json.loads(stdout)
        self.assertEqual([record["selected"] for record in records], [False, True])

    def test_json_stays_parseable_with_registry_errors(self):
        with open(self.models_path, "w", encoding="utf-8") as registry_file:
            registry_file.write(json.dumps(_record("a", "A")) + "\n")
            registry_file.write(json.dumps({"id": "broken"}) + "\n")
        code, stdout, stderr = self.run_handler(
            models_cli.handle_models_list, project=None, json=True
        )
        self.assertEqual(code, 0)
        records = json.loads(stdout)
        self.assertEqual(len(records), 1)
        self.assertIn("[WARN]", stderr)


class TestSelectionDispatch(_SelectionTestCase):
    """Verify the new subcommands are reachable through the dispatcher."""

    def test_set_subcommand_persists_selection(self):
        self.write_registry(_record("a", "A"))
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = models_cli.try_handle_models_subcommand(["models", "set", "A"])
        self.assertEqual(code, 0)
        self.assertEqual(self.read_selection()["workspace"], "a")

    def test_current_subcommand_reports_selection(self):
        self.write_registry(_record("a", "A"))
        self.write_selection({"workspace": "a", "projects": {}})
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = models_cli.try_handle_models_subcommand(["models", "current"])
        self.assertEqual(code, 0)
        self.assertIn("Effective model (workspace)", stdout.getvalue())

    def test_clear_subcommand_removes_selection(self):
        self.write_selection({"workspace": "a", "projects": {}})
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = models_cli.try_handle_models_subcommand(["models", "clear"])
        self.assertEqual(code, 0)
        self.assertIsNone(self.read_selection()["workspace"])

    def test_set_subcommand_accepts_project_option(self):
        self.write_registry(_record("a", "A"))
        project = os.path.join(self._tmp.name, "project")
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = models_cli.try_handle_models_subcommand(
                ["models", "set", "A", "--project", project]
            )
        self.assertEqual(code, 0)
        state = self.read_selection()
        self.assertEqual(
            state["projects"][normalize_project_workspace(project)], "a"
        )


if __name__ == "__main__":
    unittest.main()
