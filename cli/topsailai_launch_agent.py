#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Agent TopsailAI-Launcher Script

Parse .topsailai/settings.yaml in the current working directory,
assemble environment variables based on --item argument,
read configured context files into TOPSAILAI_CONTEXT_USER_MESSAGE,
and launch the subprocess via os.system (default) or subprocess.run (with --subprocess).
"""

import argparse
import os
import shlex
import subprocess
import sys

# DONOT REMOVE THIS
import readline


PWD = os.getenv("TOPSAILAI_PWD")
if PWD:
    os.chdir(PWD)


CONFIG_TEMPLATE = """# AI Agent TopsailAI-Launcher Configuration Template
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



def _load_gitignore_patterns(workspace):
    """Load .gitignore patterns from workspace root."""
    gitignore_path = os.path.join(workspace, ".gitignore")
    patterns = [
        ".git", ".venv", "__pycache__",
        ".log", ".db", ".env", ".env.*",
        ".tmp", ".task",
        ".DS_Store", ".cache", ".pnp",
        "node_modules", "__mocks__",
    ]
    if not os.path.isfile(gitignore_path):
        return patterns

    with open(gitignore_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n\r")
            # Remove inline comments, but not escaped #
            cleaned = []
            escape = False
            for ch in line:
                if escape:
                    cleaned.append(ch)
                    escape = False
                elif ch == "\\":
                    escape = True
                    cleaned.append(ch)
                elif ch == "#":
                    break
                else:
                    cleaned.append(ch)
            line = "".join(cleaned).rstrip()
            if not line:
                continue
            patterns.append(line)
    return patterns


def _match_gitignore_pattern(rel_path, name, is_dir, pattern):
    """Check if a path matches a single gitignore pattern."""
    import fnmatch

    negation = False
    if pattern.startswith("!"):
        negation = True
        pattern = pattern[1:]

    if not pattern:
        return False, negation

    dir_only = pattern.endswith("/")
    if dir_only:
        pattern = pattern[:-1]
        if not is_dir:
            return False, negation

    pattern = pattern.replace("\\", "/")

    if "/" in pattern:
        # Anchored pattern: match against relative path
        if pattern.startswith("/"):
            pattern = pattern[1:]
        if fnmatch.fnmatch(rel_path, pattern):
            return True, negation
        if is_dir and fnmatch.fnmatch(rel_path, pattern + "/*"):
            return True, negation
    else:
        # Unanchored pattern: match basename anywhere
        if fnmatch.fnmatch(name, pattern):
            return True, negation

    return False, negation


def _is_ignored(rel_path, name, is_dir, patterns):
    """Check if a path is ignored by gitignore patterns."""
    ignored = False
    for pattern in patterns:
        matched, negation = _match_gitignore_pattern(rel_path, name, is_dir, pattern)
        if matched:
            ignored = not negation
    return ignored


def _scan_workspace_files(workspace):
    """Scan workspace and return folder structure as a tree string."""
    workspace = os.path.abspath(workspace)
    patterns = _load_gitignore_patterns(workspace)

    entries = []

    def walk(current_dir, prefix=""):
        try:
            items = sorted(os.listdir(current_dir))
        except (PermissionError, OSError):
            return

        visible_items = []
        for name in items:
            if name == ".git":
                continue
            full_path = os.path.join(current_dir, name)
            rel_path = os.path.relpath(full_path, workspace).replace("\\", "/")
            is_dir = os.path.isdir(full_path)
            if _is_ignored(rel_path, name, is_dir, patterns):
                continue
            visible_items.append((name, full_path, is_dir))

        count = len(visible_items)
        for idx, (name, full_path, is_dir) in enumerate(visible_items):
            is_last = idx == count - 1
            connector = "└── " if is_last else "├── "
            entries.append(f"{prefix}{connector}{name}")
            if is_dir:
                extension = "    " if is_last else "│   "
                walk(full_path, prefix + extension)

    entries.append(".")
    walk(workspace)
    return "> " + workspace + "\n" + "\n".join(entries)

def _read_context_file_blocks(context_paths):
    """Read each context file and return formatted blocks."""
    blocks = []
    for path in context_paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            print(
                f"Warning: Failed to read context file '{path}': {exc}",
                file=sys.stderr,
            )
            continue
        blocks.append(f"> File: {path} > START\n{content}\n> File: {path} > END")
    return "\n\n".join(blocks)

def main():
    parser = argparse.ArgumentParser(
        description="Launch AI Agent Driver based on .topsailai/settings.yaml"
    )
    parser.add_argument(
        "--item",
        default="default",
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
    parser.add_argument(
        "--driver",
        default=None,
        help="Override the ai_agent_driver defined in settings.yaml",
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

    ai_agent_driver = args.driver if args.driver else settings.get("ai_agent_driver", "")
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

    # 2.5 Read context file contents and format them
    context_content = _read_context_file_blocks(abs_context)

    # 3. Assemble environment variables: system env <- _default <- item (latter overrides former)
    default_env = env_map.get("_default", {})
    item_env = env_map.get(item_name, {}) if item_name != "_default" else {}

    os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = workspace

    merged_env = os.environ.copy()
    merged_env.update(default_env)
    merged_env.update(item_env)

    # 3.5 Append context file contents and workspace folder structure to TOPSAILAI_CONTEXT_USER_MESSAGE
    original_user_message = merged_env.get("TOPSAILAI_CONTEXT_USER_MESSAGE", "")
    folder_structure = _scan_workspace_files(workspace)

    message_parts = []
    if context_content:
        message_parts.append(context_content)
    if folder_structure:
        message_parts.append(f"# Workspace Folder Structure\n{folder_structure}")

    if original_user_message:
        if message_parts:
            merged_env["TOPSAILAI_CONTEXT_USER_MESSAGE"] = (
                f"{original_user_message}\n\n---\n\n"
                + "\n\n---\n\n".join(message_parts)
            )
        else:
            merged_env["TOPSAILAI_CONTEXT_USER_MESSAGE"] = original_user_message
    else:
        merged_env["TOPSAILAI_CONTEXT_USER_MESSAGE"] = "\n\n---\n\n".join(
            message_parts
        )

    # 4. Assemble command line: ai_agent_driver only (context is passed via env)
    driver_parts = shlex.split(ai_agent_driver)
    cmd = driver_parts

    # 5. Print execution info
    print(f"[TopsailAI-Launcher] Command: {' '.join(cmd)}")
    print(f"[TopsailAI-Launcher] Workspace: {workspace}")
    print(
        f"[TopsailAI-Launcher] Merged env keys: {sorted(set(list(default_env.keys()) + list(item_env.keys())))}"
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
        print("[TopsailAI-Launcher] Subprocess mode (--subprocess)")
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
        # Default: os.system mode - set environment variables via os.environ,
        # then build a minimal shell command string (cd + command).
        for key, val in merged_env.items():
            os.environ[key] = str(val)

        cmd_str = ' '.join(shlex.quote(c) for c in cmd)
        full_cmd = f"cd {shlex.quote(workspace)} && {cmd_str}"

        print("[TopsailAI-Launcher] Default os.system mode")
        print(f"[TopsailAI-Launcher] Shell command: {full_cmd}")
        ret = os.system(full_cmd)
        # Convert wait-status to exit code (Python 3.9+)
        if hasattr(os, 'waitstatus_to_exitcode'):
            exit_code = os.waitstatus_to_exitcode(ret)
        elif os.name == 'posix':
            exit_code = os.WEXITSTATUS(ret) if os.WIFEXITED(ret) else 1
        else:
            exit_code = ret

    if exit_code == 0:
        print(f"[TopsailAI-Launcher] Task completed successfully, exit code: {exit_code}")
    else:
        print(f"[TopsailAI-Launcher] Task failed, exit code: {exit_code}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
