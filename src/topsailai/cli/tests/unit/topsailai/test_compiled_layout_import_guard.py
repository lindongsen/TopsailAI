"""Regression guards for the compiled CLI import boundary.

The packager turns shebang-bearing top-level scripts into standalone
executables. Package modules must therefore remain importable when those script
module names are unavailable.

Author: DawsonLin
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys


CLI_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = CLI_ROOT.parent.parent
PACKAGE_ROOT = CLI_ROOT / "cli_topsailai"


def _has_source_module(name: str) -> bool:
    """Return whether the source root provides a real module with *name*."""
    return (SOURCE_ROOT / f"{name}.py").is_file() or (
        SOURCE_ROOT / name / "__init__.py"
    ).is_file()


def _standalone_script_names() -> frozenset[str]:
    """Return top-level script names that disappear as modules after build."""
    names = set()
    for path in CLI_ROOT.glob("*.py"):
        with path.open("r", encoding="utf-8") as stream:
            first_line = stream.readline()
        if first_line.startswith("#!") and not _has_source_module(path.stem):
            names.add(path.stem)
    return frozenset(names)


def _production_python_files() -> list[Path]:
    """Return production Python files governed by the compiled-layout rule."""
    return sorted(CLI_ROOT.glob("*.py")) + sorted(PACKAGE_ROOT.rglob("*.py"))


def _forbidden_imports(path: Path, blocked: frozenset[str]) -> list[str]:
    """Return static imports in *path* that target standalone scripts."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    try:
        display_path = path.relative_to(CLI_ROOT)
    except ValueError:
        display_path = path
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name.split(".", 1)[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module.split(".", 1)[0]]
        else:
            continue
        for name in names:
            if name in blocked:
                violations.append(f"{display_path}:{node.lineno}: {name}")
    return violations


def _run_compiled_layout_probe() -> subprocess.CompletedProcess[str]:
    """Import every package module while standalone script names are blocked."""
    probe = r'''
import importlib
import importlib.abc
import json
from pathlib import Path
import sys

cli_root = Path(sys.argv[1])
source_root = Path(sys.argv[2])


def has_source_module(name):
    return (source_root / (name + ".py")).is_file() or (
        source_root / name / "__init__.py"
    ).is_file()


blocked = set()
for path in cli_root.glob("*.py"):
    with path.open("r", encoding="utf-8") as stream:
        first_line = stream.readline()
    if first_line.startswith("#!") and not has_source_module(path.stem):
        blocked.add(path.stem)


class StandaloneScriptBlocker(importlib.abc.MetaPathFinder):
    """Reject imports that only work before scripts become executables."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in blocked:
            raise ModuleNotFoundError("standalone script is not importable: " + fullname)
        return None


sys.meta_path.insert(0, StandaloneScriptBlocker())
sensitivity_name = sorted(blocked)[0]
sensitive = False
try:
    importlib.import_module(sensitivity_name)
except ModuleNotFoundError:
    sensitive = True

failures = []
modules = sorted(
    path.stem
    for path in (cli_root / "cli_topsailai").glob("*.py")
    if path.stem != "__init__"
)
for name in modules:
    try:
        importlib.import_module("cli_topsailai." + name)
    except Exception as error:
        failures.append([name, type(error).__name__, str(error)])

print(json.dumps({
    "blocked_count": len(blocked),
    "module_count": len(modules),
    "sensitivity_name": sensitivity_name,
    "sensitive": sensitive,
    "failures": failures,
}))
'''
    environment = os.environ.copy()
    python_path = [str(SOURCE_ROOT), str(CLI_ROOT)]
    if environment.get("PYTHONPATH"):
        python_path.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_path)
    return subprocess.run(
        [sys.executable, "-c", probe, str(CLI_ROOT), str(SOURCE_ROOT)],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )


def test_production_code_does_not_import_standalone_scripts():
    """Static imports must not depend on modules absent from the artifact."""
    blocked = _standalone_script_names()
    assert blocked, "the guard discovered no standalone scripts"
    violations = []
    for path in _production_python_files():
        violations.extend(_forbidden_imports(path, blocked))
    assert violations == []


def test_static_guard_detects_a_standalone_script_import(tmp_path):
    """The static guard must fail on the dependency it is designed to ban."""
    blocked = _standalone_script_names()
    target = "topsailai_session_info"
    assert target in blocked
    source = tmp_path / "bad_import.py"
    source.write_text(f"import {target}\n", encoding="utf-8")
    assert _forbidden_imports(source, blocked) == [
        f"{source}:{1}: {target}"
    ]


def test_package_imports_survive_compiled_layout():
    """Every package module must import when script module names are blocked."""
    completed = _run_compiled_layout_probe()
    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert document["blocked_count"] > 0
    assert document["module_count"] > 0
    assert document["sensitive"] is True, document
    assert document["failures"] == [], document
