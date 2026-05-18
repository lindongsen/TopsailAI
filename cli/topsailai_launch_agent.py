#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Agent Launcher Script

Parse .topsailai/settings.yaml in the current working directory,
assemble command line and environment variables based on --item argument,
and launch the subprocess via os.system (default) or subprocess.run (with --subprocess).
"""

import argparse
import os
import shlex
import subprocess
import sys


PWD = os.getenv("TOPSAILAI_PWD")
if PWD:
    os.chdir(PWD)


CONFIG_TEMPLATE = """# AI Agent Launcher Configuration Template
# Save this file as .topsailai/settings.yaml in your project root

# AI Agent driver path or command
ai_agent_driver: "ai-team-flow-dev"

# Working directory (relative paths will be resolved based on the current directory)
workspace: "."

# Context configuration: each item corresponds to a set of context files
# _default is the base context shared by all items
context:
  _default:
    - "project.yaml"
    - "docs/Environment_Variables.md"
  all_test:
    - "features/00features.md"
    - "test_all.md"
  unit_test:
    - "features/00features.md"
    - "test_unit.md"

# Environment variable configuration: each item can define its own environment variables
# _default is the base environment variables shared by all items
environment:
  _default:
    TOPSAILAI_INTERACTIVE_MODE: "1"
  all_test:
    TEST_SCOPE: "all"
  unit_test:
    TEST_SCOPE: "unit"
"""


def load_yaml(path):
    """Load a YAML file, and provide a friendly hint if PyYAML is not installed."""
    try:
        import yaml
    except ImportError as exc:
        print(
            "Error: PyYAML is required. Install it via: pip install pyyaml",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def print_available_items(context_map):
    """Print the list of available items in the configuration (excluding _default)."""
    items = [k for k in context_map.keys() if k != "_default"]
    if not items:
        print("No items configured in context section.")
        return

    print("Available items in context configuration:")
    for item in items:
        print(f"  - {item}")
    print(f"\nUse: python3 {sys.argv[0]} --item <item_name>")


def main():
    parser = argparse.ArgumentParser(
        description="Launch AI Agent Driver based on .topsailai/settings.yaml"
    )
    parser.add_argument(
        "--item",
        default=None,
        help="Item name defined in settings.yaml context/environment sections",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Only print the command line and environment variables that would be executed, without actually running",
    )
    parser.add_argument(
        "--subprocess",
        action="store_true",
        dest="use_subprocess",
        help="Use subprocess.run() to launch the command instead of os.system (default)",
    )
    args = parser.parse_args()

    # 1. Locate and parse .topsailai/settings.yaml in the current working directory
    settings_path = os.path.join(os.getcwd(), ".topsailai", "settings.yaml")
    if not os.path.isfile(settings_path):
        print(f"Error: Settings file not found: {settings_path}", file=sys.stderr)
        print("\nPlease create the configuration file first.", file=sys.stderr)
        print("\n--- Configuration Template ---\n", file=sys.stderr)
        print(CONFIG_TEMPLATE, file=sys.stderr)
        sys.exit(1)

    settings = load_yaml(settings_path)

    ai_agent_driver = settings.get("ai_agent_driver", "")
    workspace = settings.get("workspace", os.getcwd())
    context_map = settings.get("context", {})
    env_map = settings.get("environment", {})

    if not ai_agent_driver:
        print("Error: 'ai_agent_driver' is not defined in settings.yaml", file=sys.stderr)
        sys.exit(1)

    # When --item is not specified, display available items and exit
    if args.item is None:
        print_available_items(context_map)
        sys.exit(0)

    item_name = args.item

    # 2. Assemble context: _default first, then the specified item
    default_context = context_map.get("_default", [])
    item_context = context_map.get(item_name, []) if item_name != "_default" else []

    if item_name != "_default" and item_name not in context_map:
        print(f"Error: Item '{item_name}' not found in context section", file=sys.stderr)
        print("\n", file=sys.stderr)
        print_available_items(context_map)
        sys.exit(1)

    merged_context = list(default_context)
    merged_context.extend(item_context)

    # Convert relative paths to absolute paths based on workspace
    abs_context = []
    for ctx in merged_context:
        if os.path.isabs(ctx):
            abs_context.append(ctx)
        else:
            abs_context.append(os.path.join(workspace, ctx))

    # 3. Assemble environment variables: system env <- _default <- item (latter overrides former)
    default_env = env_map.get("_default", {})
    item_env = env_map.get(item_name, {}) if item_name != "_default" else {}

    merged_env = os.environ.copy()
    merged_env.update(default_env)
    merged_env.update(item_env)

    # 4. Assemble command line: ai_agent_driver + context file list
    driver_parts = shlex.split(ai_agent_driver)
    cmd = driver_parts + abs_context

    # 5. Print execution info
    print(f"[Launcher] Command: {' '.join(cmd)}")
    print(f"[Launcher] Workspace: {workspace}")
    print(
        f"[Launcher] Merged env keys: {sorted(set(list(default_env.keys()) + list(item_env.keys())))}"
    )

    # In dry-run mode, only print the details and exit without execution
    if args.dry_run:
        print("\n--- Dry Run Mode (no actual execution) ---")
        print(f"\nCommand line:\n  {' '.join(shlex.quote(c) for c in cmd)}")
        print(f"\nWorking directory:\n  {workspace}")
        print("\nEnvironment variables (merged from _default and item):")
        config_env_keys = sorted(set(list(default_env.keys()) + list(item_env.keys())))
        for key in config_env_keys:
            print(f"  {key}={merged_env.get(key, '')}")
        sys.exit(0)

    if args.use_subprocess:
        # Optional: subprocess.run mode (inherit stdin/stdout/stderr for interactive and real-time output)
        print("[Launcher] Subprocess mode (--subprocess)")
        result = subprocess.run(
            cmd,
            env=merged_env,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
            cwd=workspace,
        )
        exit_code = result.returncode
    else:
        # Default: os.system mode - build a shell command string with cd and env exports
        config_env_keys = sorted(set(list(default_env.keys()) + list(item_env.keys())))
        env_exports = []
        for key in config_env_keys:
            val = merged_env.get(key, '')
            env_exports.append(f"export {key}={shlex.quote(str(val))}")

        cmd_str = ' '.join(shlex.quote(c) for c in cmd)
        parts = [f"cd {shlex.quote(workspace)}"]
        if env_exports:
            parts.extend(env_exports)
        parts.append(cmd_str)
        full_cmd = " && ".join(parts)

        print("[Launcher] Default os.system mode")
        print(f"[Launcher] Shell command: {full_cmd}")
        ret = os.system(full_cmd)
        # Convert wait-status to exit code (Python 3.9+)
        if hasattr(os, 'waitstatus_to_exitcode'):
            exit_code = os.waitstatus_to_exitcode(ret)
        elif os.name == 'posix':
            exit_code = os.WEXITSTATUS(ret) if os.WIFEXITED(ret) else 1
        else:
            exit_code = ret

    if exit_code == 0:
        print(f"[Launcher] Task completed successfully, exit code: {exit_code}")
    else:
        print(f"[Launcher] Task failed, exit code: {exit_code}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
