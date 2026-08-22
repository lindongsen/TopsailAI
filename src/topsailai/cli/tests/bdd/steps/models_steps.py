"""Step definitions for non-interactive model command behavior."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from pytest_bdd import given, parsers, then, when

from tests.bdd.steps.project_steps import (
    CommandResult,
    CLI_ENTRY_POINT,
    _resolve_python_interpreter,
)


def _run_models_command(context: dict[str, Any], *arguments: str) -> CommandResult:
    """Run one models subcommand in the scenario's isolated environment."""
    completed = subprocess.run(
        [_resolve_python_interpreter(), str(CLI_ENTRY_POINT), "models", *arguments],
        cwd=context["cwd"],
        env=context["environment"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    result = CommandResult(completed.returncode, completed.stdout, completed.stderr)
    context["result"] = result
    return result


def _standard_model_arguments(name: str) -> tuple[str, ...]:
    """Return a valid model configuration using credential references."""
    return (
        "add",
        name,
        "--config",
        "provider=openai",
        "--config",
        "protocol=openai-compatible",
        "--config",
        f"model={name.lower()}-model",
        "--config",
        "api_key_env=TEST_OPENAI_API_KEY",
        "--config",
        "organization_env=TEST_OPENAI_ORG_ID",
    )


def _registry_entries(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Read model records from the isolated JSONL registry."""
    registry = context["home"] / ".models.jsonl"
    if not registry.exists():
        return []
    return [
        json.loads(line)
        for line in registry.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _json_output(context: dict[str, Any]) -> Any:
    """Parse the current command stdout as JSON."""
    return json.loads(context["result"].stdout)


@when(parsers.parse('I add model "{name}" with credential environment references'))
def add_model_with_references(bdd_context: dict[str, Any], name: str) -> None:
    """Add a valid model that references credentials by environment name."""
    _run_models_command(bdd_context, *_standard_model_arguments(name))


@given(parsers.parse('model "{name}" is already configured'))
def configured_model(bdd_context: dict[str, Any], name: str) -> None:
    """Create a valid model as scenario setup."""
    result = _run_models_command(bdd_context, *_standard_model_arguments(name))
    assert result.returncode == 0, result.stderr or result.stdout


@when("I list models as JSON")
def list_models(bdd_context: dict[str, Any]) -> None:
    """List the model registry using compact JSON output."""
    _run_models_command(bdd_context, "list", "--json")


@when(parsers.parse('I get model "{name}" as JSON'))
def get_model(bdd_context: dict[str, Any], name: str) -> None:
    """Get one named model using compact JSON output."""
    _run_models_command(bdd_context, "get", name, "--json")


@when(parsers.parse('I update model "{name}" with a new base URL'))
def update_model(bdd_context: dict[str, Any], name: str) -> None:
    """Update one field of an existing model."""
    _run_models_command(
        bdd_context,
        "update",
        name,
        "--config",
        "base_url=https://example.test/v1",
        "--json",
    )


@when(parsers.parse('I add model "{name}" with a literal API key'))
def add_model_with_literal_secret(bdd_context: dict[str, Any], name: str) -> None:
    """Attempt to store a prohibited literal credential."""
    _run_models_command(
        bdd_context,
        *_standard_model_arguments(name),
        "--config",
        "api_key=not-a-real-secret",
    )


@when(parsers.parse('I delete model "{name}" without confirmation'))
def delete_model(bdd_context: dict[str, Any], name: str) -> None:
    """Delete a model using the non-interactive confirmation bypass."""
    _run_models_command(bdd_context, "delete", name, "--yes", "--json")


@then(parsers.parse('model "{name}" appears in the JSON output'))
def model_appears_in_output(bdd_context: dict[str, Any], name: str) -> None:
    """Require a listed model with the expected safe credential references."""
    matches = [record for record in _json_output(bdd_context) if record["name"] == name]
    assert len(matches) == 1
    assert matches[0]["api_key_env"] == "TEST_OPENAI_API_KEY"
    assert "api_key" not in matches[0]


@then(parsers.parse('the JSON output contains the complete configuration for model "{name}"'))
def complete_model_output(bdd_context: dict[str, Any], name: str) -> None:
    """Require the get response to expose the configured model contract."""
    record = _json_output(bdd_context)
    assert record == {
        "id": name.lower(),
        "name": name,
        "provider": "openai",
        "protocol": "openai-compatible",
        "model": f"{name.lower()}-model",
        "api_key_env": "TEST_OPENAI_API_KEY",
        "organization_env": "TEST_OPENAI_ORG_ID",
    }


@then("the JSON output contains the updated base URL")
def updated_base_url(bdd_context: dict[str, Any]) -> None:
    """Require the update to be visible in a later get response."""
    assert _json_output(bdd_context)["base_url"] == "https://example.test/v1"


@then("the JSON output preserves the credential environment references")
def preserved_references(bdd_context: dict[str, Any]) -> None:
    """Require an update to preserve untouched credential references."""
    record = _json_output(bdd_context)
    assert record["api_key_env"] == "TEST_OPENAI_API_KEY"
    assert record["organization_env"] == "TEST_OPENAI_ORG_ID"


@then(parsers.parse('model "{name}" has exactly one registry entry'))
def one_model_entry(bdd_context: dict[str, Any], name: str) -> None:
    """Require duplicate rejection to preserve one registry record."""
    assert sum(entry.get("name") == name for entry in _registry_entries(bdd_context)) == 1


@then(parsers.parse('model "{name}" is not in the registry'))
def model_not_in_registry(bdd_context: dict[str, Any], name: str) -> None:
    """Require a model name to be absent from persistent storage."""
    assert all(entry.get("name") != name for entry in _registry_entries(bdd_context))


@then(parsers.parse('model "{name}" is in the registry'))
def model_in_registry(bdd_context: dict[str, Any], name: str) -> None:
    """Require a model name to remain in persistent storage."""
    assert any(entry.get("name") == name for entry in _registry_entries(bdd_context))
