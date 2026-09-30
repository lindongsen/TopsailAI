"""Verify compiled package discovery for control handlers and LLM mistake hooks.

Author: DawsonLin

The smoke gate compares source and packaged control-handler actions, then
loads the packaged hook runner in an isolated interpreter and verifies the
compiled p010/p020 hooks handle representative DeepSeek responses.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


EXPECTED_ACTIONS = {
    "call_instruction",
    "clear_interrupt",
    "get_runtime_messages",
    "get_session_messages",
    "hard_interrupt",
    "soft_interrupt",
}
EXPECTED_HOOKS = ["p010_dsml_singular_wrapper", "p020_dsml_mismatched_wrapper"]


CONTROL_PROBE = r'''
import json
from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
from topsailai.workspace.control_handlers import register_control_handlers

registry = ControlHandlerRegistry()
register_control_handlers(registry)
print(json.dumps(sorted(registry.list_actions())))
'''

HOOK_PROBE = r'''
import json
import sys
from topsailai.ai_base.llm_control.llm_mistakes import hook_script_runner

script_dir, response_path = sys.argv[1:]
with open(response_path, "r", encoding="utf-8") as response_file:
    response = response_file.read()

discovered = hook_script_runner._discover_scripts(script_dir)
result = hook_script_runner.run_hook_scripts(script_dir, "deepseek", response)
print(json.dumps({
    "discovered": [
        {"module_name": item.module_name, "kind": item.kind}
        for item in discovered
    ],
    "result": result,
}))
'''


def _parse_args() -> argparse.Namespace:
    """Parse smoke-gate paths and optional response fixtures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-root",
        type=Path,
        required=True,
        help="Packaged TopsailAI source root containing the compiled modules.",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Source TopsailAI root used for the control-handler comparison.",
    )
    parser.add_argument(
        "--response-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "tests"
        / "mistakes"
        / "response"
        / "deepseek",
        help="Directory containing dsml-3.txt and dsml-4.txt.",
    )
    return parser.parse_args()


def _run_probe(root: Path, code: str, *args: str) -> Any:
    """Run one probe with only the selected package root importable."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    completed = subprocess.run(
        [sys.executable, "-c", code, *args],
        cwd=str(root),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"probe returned non-JSON output for {root}: {completed.stdout!r}"
        ) from error


def _require_directory(path: Path, description: str) -> Path:
    """Return an existing directory or raise a clear smoke-gate error."""
    path = path.resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"{description} does not exist: {path}")
    return path


def _check_control_handlers(source_root: Path, package_root: Path) -> None:
    """Require source and packaged control-handler actions to match exactly."""
    source_actions = _run_probe(source_root, CONTROL_PROBE)
    package_actions = _run_probe(package_root, CONTROL_PROBE)
    if set(source_actions) != EXPECTED_ACTIONS:
        raise AssertionError(f"unexpected source actions: {source_actions}")
    if set(package_actions) != EXPECTED_ACTIONS:
        raise AssertionError(f"unexpected packaged actions: {package_actions}")
    if source_actions != package_actions:
        raise AssertionError(
            f"source/package action mismatch: {source_actions} != {package_actions}"
        )
    print(f"control handlers: {package_actions}")


def _check_hook_runner(package_root: Path, response_dir: Path) -> None:
    """Require packaged discovery and execution of both compiled hooks."""
    hook_dir = _require_directory(
        package_root
        / "topsailai"
        / "ai_base"
        / "llm_control"
        / "llm_mistakes"
        / "deepseek_hook_scripts",
        "packaged hook directory",
    )
    discovered_names = None
    for fixture_name in ("dsml-3.txt", "dsml-4.txt"):
        fixture = response_dir / fixture_name
        if not fixture.is_file():
            raise FileNotFoundError(f"response fixture does not exist: {fixture}")
        result = _run_probe(package_root, HOOK_PROBE, str(hook_dir), str(fixture))
        names = [item["module_name"] for item in result["discovered"]]
        if names != EXPECTED_HOOKS:
            raise AssertionError(f"unexpected packaged hooks: {names}")
        if discovered_names is None:
            discovered_names = names
        elif names != discovered_names:
            raise AssertionError("packaged hook discovery is not stable")
        action = result["result"]
        if action != [
            {
                "step_name": "action",
                "tool_call": "cmd_tool-exec_cmd",
                "tool_args": {"cmd": "echo ok"},
            }
        ]:
            raise AssertionError(f"unexpected result for {fixture_name}: {action}")
        print(f"hook runner {fixture_name}: {action}")


def main() -> int:
    """Run both packaged discovery smoke gates."""
    args = _parse_args()
    source_root = _require_directory(args.source_root, "source root")
    package_root = _require_directory(args.package_root, "package root")
    response_dir = _require_directory(args.response_dir, "response directory")
    _check_control_handlers(source_root, package_root)
    _check_hook_runner(package_root, response_dir)
    print("packaged discovery smoke gates: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
