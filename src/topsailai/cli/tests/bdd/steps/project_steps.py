"""Step definitions for non-interactive project command behavior."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when


CLI_WORKSPACE = Path(__file__).resolve().parents[3]
CLI_ENTRY_POINT = CLI_WORKSPACE / "topsailai_cli.py"


@dataclass(frozen=True)
class CommandResult:
    """Captured result of one non-interactive CLI invocation."""

    returncode: int
    stdout: str
    stderr: str


def _resolve_python_interpreter() -> str:
    """Resolve a usable Python interpreter for CLI subprocesses."""
    candidates = (getattr(sys, "executable", ""), getattr(sys, "_base_executable", ""))
    for candidate in candidates:
        path = Path(candidate) if candidate else None
        if path and path.exists() and path.name.lower().startswith("python"):
            return str(path)
    for name in ("python3", "python"):
        candidate = shutil.which(name)
        if candidate:
            return candidate
    raise RuntimeError("No usable Python interpreter found")


@pytest.fixture
def bdd_context(tmp_path: Path) -> dict[str, Any]:
    """Provide scenario-local paths, environment, and command state."""
    home = tmp_path / "topsailai-home"
    cwd = tmp_path / "working-directory"
    home.mkdir()
    cwd.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(tmp_path / "user-home"),
            "PWD": str(cwd),
            "TOPSAILAI_HOME": str(home),
        }
    )
    Path(environment["HOME"]).mkdir()
    return {
        "home": home,
        "cwd": cwd,
        "environment": environment,
        "projects": {},
        "result": None,
    }


def _run_project_command(context: dict[str, Any], *arguments: str) -> CommandResult:
    """Run one project subcommand in the scenario's isolated environment."""
    completed = subprocess.run(
        [_resolve_python_interpreter(), str(CLI_ENTRY_POINT), "project", *arguments],
        cwd=context["cwd"],
        env=context["environment"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _registry_entries(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Read valid records from the scenario-local project registry."""
    registry = context["home"] / ".projects.jsonl"
    if not registry.exists():
        return []
    return [json.loads(line) for line in registry.read_text(encoding="utf-8").splitlines() if line]


@given("an isolated TopsailAI home and working directory")
def isolated_environment(bdd_context: dict[str, Any]) -> None:
    """Confirm that the scenario uses isolated home and working directories."""
    assert bdd_context["home"] != Path.home()
    assert bdd_context["cwd"].is_dir()


@given(parsers.parse('an existing project directory named "{name}"'))
def existing_project(bdd_context: dict[str, Any], name: str) -> None:
    """Create and remember an existing project directory."""
    project = bdd_context["cwd"] / name
    project.mkdir()
    bdd_context["projects"][name] = project


@given(parsers.parse('a missing project directory named "{name}"'))
def missing_project(bdd_context: dict[str, Any], name: str) -> None:
    """Remember a project path without creating it."""
    bdd_context["projects"][name] = bdd_context["cwd"] / name


@given(parsers.parse('project "{name}" is already registered'))
def registered_project(bdd_context: dict[str, Any], name: str) -> None:
    """Register a project as scenario setup and require success."""
    result = _run_project_command(bdd_context, "add", str(bdd_context["projects"][name]))
    assert result.returncode == 0, result.stderr or result.stdout


@when(parsers.parse('I add project "{name}"'))
def add_project(bdd_context: dict[str, Any], name: str) -> None:
    """Run the non-interactive project-add command."""
    bdd_context["result"] = _run_project_command(
        bdd_context, "add", str(bdd_context["projects"][name])
    )


@when(parsers.parse('I delete project "{name}"'))
def delete_project(bdd_context: dict[str, Any], name: str) -> None:
    """Run the non-interactive project-delete command."""
    bdd_context["result"] = _run_project_command(
        bdd_context, "del", str(bdd_context["projects"][name])
    )


@then("the command succeeds")
def command_succeeds(bdd_context: dict[str, Any]) -> None:
    """Require a successful CLI exit status."""
    result = bdd_context["result"]
    assert result.returncode == 0, result.stderr or result.stdout


@then("the command fails")
def command_fails(bdd_context: dict[str, Any]) -> None:
    """Require a nonzero CLI exit status."""
    result = bdd_context["result"]
    assert result.returncode != 0, result.stdout


@then(parsers.parse('project "{name}" is registered'))
def project_is_registered(bdd_context: dict[str, Any], name: str) -> None:
    """Require the resolved project path in the registry."""
    expected = str(bdd_context["projects"][name].resolve())
    assert any(entry.get("path") == expected for entry in _registry_entries(bdd_context))


@then(parsers.parse('project "{name}" is not registered'))
def project_is_not_registered(bdd_context: dict[str, Any], name: str) -> None:
    """Require the resolved project path to be absent from the registry."""
    expected = str(bdd_context["projects"][name].resolve())
    assert all(entry.get("path") != expected for entry in _registry_entries(bdd_context))


@then(parsers.parse('project "{name}" has exactly one registry entry'))
def project_has_one_entry(bdd_context: dict[str, Any], name: str) -> None:
    """Require duplicate rejection to leave one registry record."""
    expected = str(bdd_context["projects"][name].resolve())
    matches = [entry for entry in _registry_entries(bdd_context) if entry.get("path") == expected]
    assert len(matches) == 1


@then(parsers.parse('project directory "{name}" still exists'))
def project_directory_exists(bdd_context: dict[str, Any], name: str) -> None:
    """Require registry deletion to preserve the project directory."""
    assert bdd_context["projects"][name].is_dir()
