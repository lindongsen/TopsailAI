"""BDD steps for discovery from a Cython-compiled packaged tree."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib.machinery
import json
import os
from pathlib import Path
import shutil
import subprocess
import sysconfig
import tempfile
from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when

from scripts.packaged_discovery_smoke import (
    CONTROL_PROBE,
    EXPECTED_ACTIONS,
    EXPECTED_HOOKS,
    HOOK_PROBE,
)
from topsailai.utils.env_tool import resolve_python_interpreter


WORKSPACE = Path(__file__).resolve().parents[3]
SOURCE_IMPORT_ROOT = WORKSPACE.parent
DEFAULT_PACKAGED_ROOT = Path(
    "/TopsailAI/build/output/.deb/topsailai/TopsailAI/src"
)
EXPECTED_CORRECTION = [
    {
        "step_name": "action",
        "tool_call": "cmd_tool-exec_cmd",
        "tool_args": {"cmd": "echo ok"},
    }
]
CONTROL_MODULES = ("instruction", "interrupt", "message")
SHARED_MODULE_ALLOWLISTS = {
    "topsailai.tools": {
        "agent_tool",
        "bigfile_tool",
        "cmd_tool",
        "collaboration_tool",
        "ctx_tool",
        "file_readonly_tool",
        "file_tool",
        "git_tool",
        "human_tool",
        "jev_tool",
        "multimodal_readonly_tool",
        "sandbox_tool",
        "skill_tool",
        "ssh_tool",
        "story_memory_tool",
        "story_tool",
        "subagent_tool",
        "time_tool",
    },
    "topsailai.workspace.plugin_instruction": {
        "agent",
        "env",
        "git",
        "skill",
        "skill_repo",
        "stat",
    },
    "topsailai.workspace.agent.hooks": {
        "post_final_answer",
        "pre_run_agent2llm_source",
        "pre_run_input",
    },
    "topsailai.context.chat_history_manager": {"sql"},
}

CONTROL_ORIGIN_PROBE = r'''
import importlib.util
import json
from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
from topsailai.workspace.control_handlers import register_control_handlers

registry = ControlHandlerRegistry()
register_control_handlers(registry)
print(json.dumps({
    "actions": sorted(registry.list_actions()),
    "origins": {
        name: importlib.util.find_spec(
            "topsailai.workspace.control_handlers." + name
        ).origin
        for name in ("instruction", "interrupt", "message")
    },
}))
'''

SHARED_DISCOVERY_PROBE = r'''
import importlib
import importlib.util
import json
import sys
from topsailai.utils.module_tool import list_sub_mods_name

package_name = sys.argv[1]
package = importlib.import_module(package_name)
names = list_sub_mods_name(package_name)
print(json.dumps({
    "names": names,
    "package_origin": package.__file__,
    "origins": {
        name: importlib.util.find_spec(package_name + "." + name).origin
        for name in names
    },
    "sys_path": sys.path,
}))
'''

EXTERNAL_FUNCTION_MAP_PROBE = r'''
import json
import os
import sys
from topsailai.utils.module_tool import get_external_function_map

plugin_path = os.path.realpath(sys.argv[1])
sys.path[:] = [
    entry for entry in sys.path
    if not entry or not plugin_path.startswith(os.path.realpath(entry) + os.sep)
]
result = get_external_function_map(plugin_path, key="TOOLS")
print(json.dumps({
    "keys": sorted(result or {}),
    "module_names": sorted(
        function.__module__ for function in (result or {}).values()
    ),
}))
'''

PACKAGE_INITIALIZER_C = r'''
#include <Python.h>

static struct PyModuleDef module_definition = {
    PyModuleDef_HEAD_INIT,
    "PACKAGE_NAME",
    NULL,
    -1,
    NULL,
};

PyMODINIT_FUNC PyInit_PACKAGE_NAME(void) {
    return PyModule_Create(&module_definition);
}
'''

PLUGIN_MODULE_C = r'''
#include <Python.h>

static PyObject *compiled_plugin(PyObject *self, PyObject *args) {
    return PyUnicode_FromString("compiled-plugin");
}

static PyMethodDef methods[] = {
    {"compiled_plugin", compiled_plugin, METH_NOARGS, NULL},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef module_definition = {
    PyModuleDef_HEAD_INIT,
    "plugin",
    NULL,
    -1,
    methods,
};

PyMODINIT_FUNC PyInit_plugin(void) {
    PyObject *module;
    PyObject *parent = PyImport_ImportModule("compiled_outer.compiled_inner");
    PyObject *tools;
    PyObject *function;
    if (parent == NULL) {
        return NULL;
    }
    Py_DECREF(parent);
    module = PyModule_Create(&module_definition);
    if (module == NULL) {
        return NULL;
    }
    tools = PyDict_New();
    function = PyObject_GetAttrString(module, "compiled_plugin");
    if (tools == NULL || function == NULL ||
            PyDict_SetItemString(tools, "run", function) < 0 ||
            PyModule_AddObject(module, "TOOLS", tools) < 0) {
        Py_XDECREF(tools);
        Py_XDECREF(function);
        Py_DECREF(module);
        return NULL;
    }
    Py_DECREF(function);
    return module;
}
'''


@dataclass
class CompiledDiscoveryContext:
    """Hold paths and isolated probe results for one BDD scenario."""

    packaged_root: Path
    source_root: Path = SOURCE_IMPORT_ROOT
    source_actions: list[str] = field(default_factory=list)
    packaged_actions: list[str] = field(default_factory=list)
    control_origins: dict[str, str] = field(default_factory=dict)
    hook_result: dict[str, Any] = field(default_factory=dict)
    shared_result: dict[str, Any] = field(default_factory=dict)
    package_name: str = ""
    external_fixture_root: Path | None = None
    external_package_path: Path | None = None
    external_result: dict[str, Any] = field(default_factory=dict)


def _package_directory(root: Path, package_name: str) -> Path:
    """Return the filesystem directory for one dotted package name."""
    return root.joinpath(*package_name.split("."))


def _extension_artifacts(directory: Path, module_name: str) -> list[Path]:
    """Return valid extension artifacts for one module without hardcoding `.so`."""
    return [
        directory / f"{module_name}{suffix}"
        for suffix in importlib.machinery.EXTENSION_SUFFIXES
        if (directory / f"{module_name}{suffix}").is_file()
    ]


def _assert_compiled_only(directory: Path, module_names: set[str] | tuple[str, ...]) -> None:
    """Require extension artifacts and reject sibling source modules."""
    for module_name in module_names:
        assert _extension_artifacts(directory, module_name), (
            f"missing extension artifact for {module_name} in {directory}"
        )
        assert not (directory / f"{module_name}.py").exists(), (
            f"source sibling masks extension discovery: {module_name}.py"
        )


def _compile_extension(source_path: Path, output_path: Path) -> None:
    """Compile one CPython extension module into the scenario fixture."""
    compiler = shutil.which("cc")
    include_directory = sysconfig.get_paths().get("include")
    assert compiler, "C compiler is required for compiled-module BDD"
    assert include_directory, "Python include directory is unavailable"
    completed = subprocess.run(
        [
            compiler,
            "-shared",
            "-fPIC",
            f"-I{include_directory}",
            str(source_path),
            "-o",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr


def _run_probe(root: Path, code: str, *arguments: str) -> Any:
    """Run a JSON probe with the selected tree as the only PYTHONPATH entry."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [resolve_python_interpreter(), "-c", code, *arguments],
        cwd=str(root),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        pytest.fail(f"probe returned non-JSON stdout: {completed.stdout!r}: {error}")


def _assert_packaged_origin(packaged_root: Path, origin: str) -> None:
    """Require one resolved module origin to remain inside the packaged tree."""
    resolved_origin = Path(origin).resolve()
    assert resolved_origin.is_relative_to(packaged_root), (
        f"module escaped packaged root: {resolved_origin}"
    )


def _require_packaged_root(context: CompiledDiscoveryContext) -> None:
    """Fail clearly when a packaged-gate scenario lacks real build artifacts."""
    assert context.packaged_root.is_dir(), (
        f"packaged root does not exist: {context.packaged_root}"
    )
    assert (context.packaged_root / "topsailai" / "__init__.py").is_file(), (
        f"packaged root does not contain topsailai: {context.packaged_root}"
    )


@pytest.fixture
def compiled_discovery_ctx() -> CompiledDiscoveryContext:
    """Provide scenario state and clean any owned compiled fixture afterward."""
    configured = os.environ.get("TOPSAILAI_PACKAGED_ROOT", "").strip()
    packaged_root = Path(configured) if configured else DEFAULT_PACKAGED_ROOT
    context = CompiledDiscoveryContext(packaged_root=packaged_root.resolve())
    yield context
    if context.external_fixture_root is not None:
        print(f"deleting compiled fixture: {context.external_fixture_root}")
        shutil.rmtree(context.external_fixture_root)


@given("a source TopsailAI tree using import-system module discovery")
def given_source_discovery(compiled_discovery_ctx: CompiledDiscoveryContext) -> None:
    """Select the source tree without requiring packaged artifacts."""
    assert (compiled_discovery_ctx.source_root / "topsailai" / "__init__.py").is_file()


@when("source module discovery enumerates the representative registries and hooks")
def when_source_discovery(compiled_discovery_ctx: CompiledDiscoveryContext) -> None:
    """Enumerate source registries through the same public discovery helpers."""
    compiled_discovery_ctx.source_actions = _run_probe(
        compiled_discovery_ctx.source_root,
        CONTROL_PROBE,
    )
    compiled_discovery_ctx.shared_result = {
        package: _run_probe(
            compiled_discovery_ctx.source_root,
            SHARED_DISCOVERY_PROBE,
            package,
        )["names"]
        for package in SHARED_MODULE_ALLOWLISTS
    }
    hook_directory = _package_directory(
        compiled_discovery_ctx.source_root,
        "topsailai.ai_base.llm_control.llm_mistakes.deepseek_hook_scripts",
    )
    response_path = (
        WORKSPACE / "tests" / "mistakes" / "response" / "deepseek" / "dsml-3.txt"
    )
    compiled_discovery_ctx.hook_result = _run_probe(
        compiled_discovery_ctx.source_root,
        HOOK_PROBE,
        str(hook_directory),
        str(response_path),
    )


@then("source discovery exposes the expected modules and control actions")
def then_source_discovery_contract(compiled_discovery_ctx: CompiledDiscoveryContext) -> None:
    """Require source behavior to satisfy the same discovery contracts."""
    assert set(compiled_discovery_ctx.source_actions) == EXPECTED_ACTIONS
    for package, expected in SHARED_MODULE_ALLOWLISTS.items():
        assert set(compiled_discovery_ctx.shared_result[package]) >= expected
    discovered = compiled_discovery_ctx.hook_result["discovered"]
    assert [item["module_name"] for item in discovered] == EXPECTED_HOOKS
    assert all(item["kind"] == "source" for item in discovered)


@given(
    "a packaged TopsailAI tree containing compiled control-handler modules without sibling source modules"
)
def given_compiled_control_handlers(compiled_discovery_ctx: CompiledDiscoveryContext) -> None:
    """Require a real compiled-only control-handler inventory."""
    _require_packaged_root(compiled_discovery_ctx)
    directory = _package_directory(
        compiled_discovery_ctx.packaged_root,
        "topsailai.workspace.control_handlers",
    )
    _assert_compiled_only(directory, CONTROL_MODULES)


@when("control handlers are registered from the source and packaged trees")
def when_register_control_handlers(compiled_discovery_ctx: CompiledDiscoveryContext) -> None:
    """Register handlers in separate source and packaged interpreters."""
    compiled_discovery_ctx.source_actions = _run_probe(
        compiled_discovery_ctx.source_root,
        CONTROL_PROBE,
    )
    package_result = _run_probe(
        compiled_discovery_ctx.packaged_root,
        CONTROL_ORIGIN_PROBE,
    )
    compiled_discovery_ctx.packaged_actions = package_result["actions"]
    compiled_discovery_ctx.control_origins = package_result["origins"]


@then("both trees expose the same control-handler action set")
def then_control_actions_match(compiled_discovery_ctx: CompiledDiscoveryContext) -> None:
    """Require exact source and packaged registry parity."""
    assert compiled_discovery_ctx.source_actions == compiled_discovery_ctx.packaged_actions


@then("the packaged tree exposes every expected send-control action")
def then_expected_control_actions(compiled_discovery_ctx: CompiledDiscoveryContext) -> None:
    """Require the authoritative send-control action contract."""
    assert set(compiled_discovery_ctx.packaged_actions) == EXPECTED_ACTIONS


@then("the packaged control-handler modules originate from the packaged tree")
def then_control_origins_are_packaged(
    compiled_discovery_ctx: CompiledDiscoveryContext,
) -> None:
    """Require every handler spec to resolve under the selected packaged root."""
    assert set(compiled_discovery_ctx.control_origins) == set(CONTROL_MODULES)
    for origin in compiled_discovery_ctx.control_origins.values():
        _assert_packaged_origin(compiled_discovery_ctx.packaged_root, origin)


@given(
    "a packaged TopsailAI tree containing compiled mistake hooks without sibling source modules"
)
def given_compiled_mistake_hooks(compiled_discovery_ctx: CompiledDiscoveryContext) -> None:
    """Require both packaged DeepSeek wrappers to be extension-only modules."""
    _require_packaged_root(compiled_discovery_ctx)
    directory = _package_directory(
        compiled_discovery_ctx.packaged_root,
        "topsailai.ai_base.llm_control.llm_mistakes.deepseek_hook_scripts",
    )
    _assert_compiled_only(directory, set(EXPECTED_HOOKS))


@when(parsers.parse('the packaged hook runner processes the DeepSeek response fixture "{fixture}"'))
def when_run_packaged_hook(
    compiled_discovery_ctx: CompiledDiscoveryContext,
    fixture: str,
) -> None:
    """Run the authoritative hook probe against one malformed response fixture."""
    hook_directory = _package_directory(
        compiled_discovery_ctx.packaged_root,
        "topsailai.ai_base.llm_control.llm_mistakes.deepseek_hook_scripts",
    )
    response_path = WORKSPACE / "tests" / "mistakes" / "response" / "deepseek" / fixture
    assert response_path.is_file(), f"response fixture does not exist: {response_path}"
    compiled_discovery_ctx.hook_result = _run_probe(
        compiled_discovery_ctx.packaged_root,
        HOOK_PROBE,
        str(hook_directory),
        str(response_path),
    )


@then("both expected compiled wrapper hooks are discovered in stable order")
def then_expected_hooks_discovered(compiled_discovery_ctx: CompiledDiscoveryContext) -> None:
    """Require the authoritative ordered wrapper list and extension classification."""
    discovered = compiled_discovery_ctx.hook_result["discovered"]
    assert [item["module_name"] for item in discovered] == EXPECTED_HOOKS
    assert all(item["kind"] == "extension" for item in discovered)


@then("the expected corrective action is returned")
def then_expected_correction(compiled_discovery_ctx: CompiledDiscoveryContext) -> None:
    """Require the authoritative corrective command payload."""
    assert compiled_discovery_ctx.hook_result["result"] == EXPECTED_CORRECTION


@given(
    parsers.parse(
        'the packaged TopsailAI package "{package}" contains extension modules without sibling source modules'
    )
)
def given_compiled_shared_package(
    compiled_discovery_ctx: CompiledDiscoveryContext,
    package: str,
) -> None:
    """Require each independently allowlisted module to be extension-only."""
    _require_packaged_root(compiled_discovery_ctx)
    assert package in SHARED_MODULE_ALLOWLISTS
    compiled_discovery_ctx.package_name = package
    directory = _package_directory(compiled_discovery_ctx.packaged_root, package)
    _assert_compiled_only(directory, SHARED_MODULE_ALLOWLISTS[package])


@when("shared module discovery enumerates that package")
def when_shared_discovery(compiled_discovery_ctx: CompiledDiscoveryContext) -> None:
    """Enumerate one packaged registry through the shared production helper."""
    compiled_discovery_ctx.shared_result = _run_probe(
        compiled_discovery_ctx.packaged_root,
        SHARED_DISCOVERY_PROBE,
        compiled_discovery_ctx.package_name,
    )


@then(parsers.parse('every expected compiled module for "{package}" is returned'))
def then_shared_modules_returned(
    compiled_discovery_ctx: CompiledDiscoveryContext,
    package: str,
) -> None:
    """Require the independent acceptance allowlist in discovery results."""
    assert package == compiled_discovery_ctx.package_name
    assert set(compiled_discovery_ctx.shared_result["names"]) >= SHARED_MODULE_ALLOWLISTS[package]


@then("every discovered module originates from the packaged tree")
def then_shared_origins_are_packaged(
    compiled_discovery_ctx: CompiledDiscoveryContext,
) -> None:
    """Require package and discovered module specs to remain in the packaged tree."""
    result = compiled_discovery_ctx.shared_result
    _assert_packaged_origin(compiled_discovery_ctx.packaged_root, result["package_origin"])
    for origin in result["origins"].values():
        _assert_packaged_origin(compiled_discovery_ctx.packaged_root, origin)
    forbidden = str(WORKSPACE.resolve())
    assert all(forbidden not in entry for entry in result["sys_path"])


@given(
    "a nested external plugin package whose package initializers and plugin modules are extension artifacts only"
)
def given_compiled_only_external_package(
    compiled_discovery_ctx: CompiledDiscoveryContext,
) -> None:
    """Build a real nested extension-only package under the task temp directory."""
    temp_parent = WORKSPACE / ".tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    fixture_root = Path(
        tempfile.mkdtemp(prefix="compiled-external-plugin-", dir=temp_parent)
    )
    compiled_discovery_ctx.external_fixture_root = fixture_root
    outer = fixture_root / "compiled_outer"
    inner = outer / "compiled_inner"
    inner.mkdir(parents=True)
    extension_suffix = sysconfig.get_config_var("EXT_SUFFIX")
    assert extension_suffix in importlib.machinery.EXTENSION_SUFFIXES

    for package_name, directory in (
        ("compiled_outer", outer),
        ("compiled_inner", inner),
    ):
        source_path = fixture_root / f"{package_name}_init.c"
        source_path.write_text(
            PACKAGE_INITIALIZER_C.replace("PACKAGE_NAME", package_name),
            encoding="utf-8",
        )
        _compile_extension(
            source_path,
            directory / f"__init__{extension_suffix}",
        )

    plugin_source = fixture_root / "plugin.c"
    plugin_source.write_text(PLUGIN_MODULE_C, encoding="utf-8")
    _compile_extension(plugin_source, inner / f"plugin{extension_suffix}")
    for directory in (outer, inner):
        assert not (directory / "__init__.py").exists()
        assert not (directory / "__init__.pyc").exists()
        assert _extension_artifacts(directory, "__init__")
    _assert_compiled_only(inner, {"plugin"})
    compiled_discovery_ctx.external_package_path = inner


@when("its external function map is loaded by filesystem path")
def when_external_function_map_loaded(
    compiled_discovery_ctx: CompiledDiscoveryContext,
) -> None:
    """Load the compiled-only nested package through the public external loader."""
    assert compiled_discovery_ctx.external_fixture_root is not None
    assert compiled_discovery_ctx.external_package_path is not None
    compiled_discovery_ctx.external_result = _run_probe(
        compiled_discovery_ctx.source_root,
        EXTERNAL_FUNCTION_MAP_PROBE,
        str(compiled_discovery_ctx.external_package_path),
    )


@then("the nested package path is resolved through the Python import system")
def then_external_package_path_resolved(
    compiled_discovery_ctx: CompiledDiscoveryContext,
) -> None:
    """Require the plugin to retain its complete nested package identity."""
    assert compiled_discovery_ctx.external_result["module_names"] == [
        "compiled_outer.compiled_inner.plugin"
    ]


@then("its declared plugin functions are discovered")
def then_external_functions_discovered(
    compiled_discovery_ctx: CompiledDiscoveryContext,
) -> None:
    """Require the compiled plugin's declared function to enter the map."""
    assert compiled_discovery_ctx.external_result["keys"] == ["plugin.run"]
