"""Fixtures for future isolated Hooks module-discovery contracts."""

from __future__ import annotations

import importlib.machinery
import shutil
import subprocess
import sysconfig
from pathlib import Path
from typing import Any, Callable


def require_discovery_contract() -> Callable[..., Any]:
    """Return the future production discovery API or fail inside the test body."""
    try:
        from topsailai.hooks.module_discovery import build_module_manifest
    except (ImportError, ModuleNotFoundError) as exc:
        raise AssertionError(
            "R4 module-discovery contract missing: "
            "build_module_manifest(module_folder, hook_point)"
        ) from exc
    assert callable(build_module_manifest), "build_module_manifest must be callable"
    return build_module_manifest


def write_module(folder: Path, name: str, body: str = "def main(*args, **kwargs):\n    return None\n") -> Path:
    """Write one direct source-module fixture."""
    path = folder / f"{name}.py"
    path.write_text(body, encoding="utf-8")
    return path


def compile_extension(folder: Path, name: str, suffix: str | None = None) -> Path:
    """Build one real loadable CPython extension with a callable main entry."""
    compiler = shutil.which("cc")
    include_directory = sysconfig.get_paths().get("include")
    assert compiler, "fixture requires an available C compiler"
    assert include_directory, "fixture requires Python development headers"
    target_suffix = suffix or importlib.machinery.EXTENSION_SUFFIXES[0]
    assert target_suffix in importlib.machinery.EXTENSION_SUFFIXES
    source = folder / f"{name}.c"
    output = folder / f"{name}{target_suffix}"
    source.write_text(
        "#include <Python.h>\n"
        "static PyObject *main_entry(PyObject *self, PyObject *args, PyObject *kwargs) {\n"
        "    Py_RETURN_NONE;\n"
        "}\n"
        "static PyMethodDef methods[] = {\n"
        "    {\"main\", (PyCFunction)(void(*)(void))main_entry, METH_VARARGS | METH_KEYWORDS, NULL},\n"
        "    {NULL, NULL, 0, NULL}\n"
        "};\n"
        "static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, \"fixture\", NULL, -1, methods};\n"
        f"PyMODINIT_FUNC PyInit_{name}(void) {{ return PyModule_Create(&module); }}\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            compiler,
            "-shared",
            "-fPIC",
            f"-I{include_directory}",
            str(source),
            "-o",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return output


def manifest_entries(result: Any) -> tuple[Any, ...]:
    """Require the immutable result entry collection from the future API."""
    assert hasattr(result, "entries"), "discovery result must expose entries"
    entries = result.entries
    assert type(entries) is tuple, "discovery entries must be an immutable tuple"
    return entries
