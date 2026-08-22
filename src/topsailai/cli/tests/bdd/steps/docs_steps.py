"""Step definitions for non-interactive documentation commands."""

from __future__ import annotations

import subprocess
from typing import Any

from pytest_bdd import parsers, then, when

from tests.bdd.steps.project_steps import (
    CLI_ENTRY_POINT,
    CommandResult,
    _resolve_python_interpreter,
)


def _run_docs_command(context: dict[str, Any], *arguments: str) -> CommandResult:
    """Run one docs subcommand in the scenario's isolated environment."""
    completed = subprocess.run(
        [_resolve_python_interpreter(), str(CLI_ENTRY_POINT), "docs", *arguments],
        cwd=context["cwd"],
        env=context["environment"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@when("I list documentation")
def list_documentation(bdd_context: dict[str, Any]) -> None:
    """List documentation through the real non-interactive CLI."""
    bdd_context["result"] = _run_docs_command(bdd_context, "list")


@when(parsers.parse('I read documentation "{name}"'))
def read_documentation(bdd_context: dict[str, Any], name: str) -> None:
    """Read one documentation file through the real non-interactive CLI."""
    bdd_context["result"] = _run_docs_command(bdd_context, "read", name)


@then(parsers.parse('the documentation list contains "{relative_path}"'))
def documentation_list_contains(
    bdd_context: dict[str, Any], relative_path: str
) -> None:
    """Require the table to contain the expected folder and file name."""
    folder, filename = relative_path.split("/", 1)
    output = bdd_context["result"].stdout
    assert folder in output
    assert filename in output


@then(parsers.parse('the documentation output contains "{marker}"'))
def documentation_output_contains(
    bdd_context: dict[str, Any], marker: str
) -> None:
    """Require a stable marker from the selected documentation file."""
    assert marker in bdd_context["result"].stdout


@then(parsers.parse('the documentation error identifies "{name}"'))
def documentation_error_identifies(
    bdd_context: dict[str, Any], name: str
) -> None:
    """Require a not-found response identifying the requested document."""
    output = bdd_context["result"].stdout
    assert f"Doc not found: {name}" in output
