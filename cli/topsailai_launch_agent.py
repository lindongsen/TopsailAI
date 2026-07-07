#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Agent TopsailAI-Launcher Script

Parse .topsailai/settings.yaml in the current working directory. If the file
is missing, create it from a default configuration template, prompt the user
to fill context._default, and continue launching.

When no --item is provided, the launcher inspects the context section and
auto-selects the item: a single item is used directly, multiple items prompt
for selection (with "default" as the default choice), and an empty context
enters an interactive setup guide.

Assemble environment variables based on --item argument, read configured
context files into TOPSAILAI_CONTEXT_USER_MESSAGE, and launch the subprocess
via os.system (default) or subprocess.run (with --subprocess).
"""

import argparse
import atexit
import json
import os
import shlex
import signal
import subprocess
import sys
import time

# DONOT REMOVE THIS
import readline


PWD = os.getenv("TOPSAILAI_PWD")
if PWD:
    os.chdir(PWD)

# Global reference to the temporary context message file, used for cleanup on exit.
_CONTEXT_MESSAGE_FILE = None


def _cleanup_context_file():
    """Remove the temporary context message file if it exists."""
    global _CONTEXT_MESSAGE_FILE
    path = _CONTEXT_MESSAGE_FILE
    if path and os.path.isfile(path):
        try:
            os.remove(path)
            print(
                f"[TopsailAI-Launcher] Removed temporary context file: {path}"
            )
        except OSError as exc:
            print(
                f"[TopsailAI-Launcher] Warning: Failed to remove temporary context file '{path}': {exc}",
                file=sys.stderr,
            )
    _CONTEXT_MESSAGE_FILE = None


def _signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM by cleaning up the temporary file and exiting."""
    print(
        f"\n[TopsailAI-Launcher] Received signal {signum}, cleaning up and exiting...",
        file=sys.stderr,
    )
    _cleanup_context_file()
    sys.exit(128 + signum)


# Register cleanup hooks so the temporary file is removed on normal exit,
# uncaught exceptions, and common termination signals.
atexit.register(_cleanup_context_file)
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


DEFAULT_CONFIG = {
    "ai_agent_driver": "ai-team-flow-dev",
    "workspace": ".",
    "context": {
        "_default": [],
        "default": [],
        "memo": [],
    },
    "environment": {
        "_default": {
            "TOPSAILAI_INTERACTIVE_MODE": "1",
        },
        "default": {},
        "memo": {
            "TOPSAILAI_AGENT_DRIVER": "topsailai_agent_chats",
        },
    },
}


CONFIG_TEMPLATE = """# AI Agent TopsailAI-Launcher Configuration
# This file tells topsailai_launch_agent.py which driver to run, which files
# to inject into the agent context, and which environment variables to set.

# AI Agent driver path or command.
# Resolution order (first match wins):
#   1. --driver CLI argument
#   2. TOPSAILAI_AGENT_DRIVER environment variable from this file (item-specific or _default)
#   3. ai_agent_driver field below
#   4. TOPSAILAI_AGENT_DRIVER from the OS environment
ai_agent_driver: "ai-team-flow-dev"

# Working directory for the launched driver.
workspace: "."

# Context configuration: each item corresponds to a set of context files.
# _default is the base context shared by all items; item-specific files are
# appended after _default files. Paths are relative to `workspace` unless
# they start with `/`.
#
# IMPORTANT: `context._default` is currently empty. Fill it with the files
# you want every agent run to receive (e.g. project.yaml, docs, features).
context:
  _default: []
  default: []
  memo: []

# Environment variable configuration: each item can define its own variables.
# _default variables are applied first, then item-specific variables override
# them. System environment variables are inherited and can be overridden here.
environment:
  _default:
    TOPSAILAI_INTERACTIVE_MODE: "1"
  default: {}
  memo:
    TOPSAILAI_AGENT_DRIVER: "topsailai_agent_chats"
"""


def _write_default_settings(path):
    """Write the commented default configuration to .topsailai/settings.yaml.

    The generated file includes detailed comments so users can understand each
    section without reading external documentation.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(CONFIG_TEMPLATE)


def _yaml_quote(value):
    """Return a YAML-safe quoted string using JSON-style escaping."""
    return json.dumps(str(value))


def _render_yaml_list(items, base_indent=2):
    """Render a list of strings as an inline [] or a YAML block list."""
    if not items:
        return " []"
    spaces = " " * (base_indent + 2)
    return "\n" + "\n".join(f"{spaces}- {_yaml_quote(item)}" for item in items)

def _render_env_lines(env_vars, base_indent=2):
    """Render extra environment variables as indented YAML lines.

    TOPSAILAI_INTERACTIVE_MODE is always written by the caller, so it is
    skipped here to avoid duplication.
    """
    if not env_vars:
        return ""
    spaces = " " * (base_indent + 2)
    lines = []
    for key, value in sorted(env_vars.items()):
        if key == "TOPSAILAI_INTERACTIVE_MODE":
            continue
        lines.append(f"{spaces}{key}: {_yaml_quote(value)}")
    if not lines:
        return ""
    return "\n" + "\n".join(lines) + "\n"


INTERACTIVE_CONFIG_TEMPLATE = """# AI Agent TopsailAI-Launcher Configuration
# This file tells topsailai_launch_agent.py which driver to run, which files
# to inject into the agent context, and which environment variables to set.

# AI Agent driver path or command.
# Resolution order (first match wins):
#   1. --driver CLI argument
#   2. TOPSAILAI_AGENT_DRIVER environment variable from this file (item-specific or _default)
#   3. ai_agent_driver field below
#   4. TOPSAILAI_AGENT_DRIVER from the OS environment
ai_agent_driver: {ai_agent_driver}

# Working directory for the launched driver.
workspace: {workspace}

# Context configuration: each item corresponds to a set of context files.
# _default is the base context shared by all items; item-specific files are
# appended after _default files. Paths are relative to `workspace` unless
# they start with `/`.
#
# IMPORTANT: `context._default` is currently empty. Fill it with the files
# you want every agent run to receive (e.g. project.yaml, docs, features).
context:
  _default:{context_default}
  default: []

# Environment variable configuration: each item can define its own variables.
# _default variables are applied first, then item-specific variables override
# them. System environment variables are inherited and can be overridden here.
#
# TOPSAILAI_INTERACTIVE_MODE enables interactive behavior in the agent driver.
# Set to "1" to enable, "0" to disable.
environment:
  _default:
    TOPSAILAI_INTERACTIVE_MODE: "1"
{extra_env}  default: {{}}
"""


def _prompt(question, default=""):
    """Prompt the user for a single line of input."""
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{suffix}: ")
    except EOFError:
        answer = ""
    return answer.strip() or default


def _prompt_yn(question, default=True):
    """Prompt the user for a yes/no answer."""
    default_text = "Y/n" if default else "y/N"
    answer = _prompt(question, default_text).lower()
    if answer in ("y", "yes"):
        return True
    if answer in ("n", "no"):
        return False
    return default


def _prompt_list(question):
    """Prompt the user for a list of values until an empty line is entered."""
    print(question)
    values = []
    while True:
        line = _prompt("", default="")
        if not line:
            break
        values.append(line)
    return values

def _run_interactive_setup(settings_path):
    """Guide the user through creating a minimal settings.yaml interactively."""
    print(
        "\n=== TopsailAI Launcher Interactive Setup ===",
        file=sys.stderr,
    )
    print(
        "The settings file is missing. Let's create one together.\n",
        file=sys.stderr,
    )

    ai_agent_driver = _prompt(
        "AI agent driver command",
        default=DEFAULT_CONFIG["ai_agent_driver"],
    )

    workspace = _prompt(
        "Working directory for the driver",
        default=DEFAULT_CONFIG["workspace"],
    )

    print(
        "\nContext files are injected into every agent run. "
        "Paths are relative to the workspace unless they start with '/'.",
        file=sys.stderr,
    )
    context_default = []
    if _prompt_yn("Would you like to add context files for the '_default' item now?", default=True):
        context_default = _prompt_list(
            "Enter context file paths one per line (empty line to finish):"
        )

    print(
        "\nEnvironment variables are merged before launching the driver. "
        "TOPSAILAI_INTERACTIVE_MODE is set to \"1\" by default.",
        file=sys.stderr,
    )
    extra_env = {}
    if _prompt_yn("Would you like to add extra environment variables for the '_default' item now?", default=False):
        extra_env = {}
        print("Enter KEY=VALUE pairs one per line (empty line to finish):")
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if not line:
                break
            if "=" not in line:
                print(
                    f"Warning: Ignoring invalid env line (expected KEY=VALUE): {line}",
                    file=sys.stderr,
                )
                continue
            key, value = line.split("=", 1)
            extra_env[key.strip()] = value.strip()

    content = INTERACTIVE_CONFIG_TEMPLATE.format(
        ai_agent_driver=_yaml_quote(ai_agent_driver),
        workspace=_yaml_quote(workspace),
        context_default=_render_yaml_list(context_default, base_indent=2),
        extra_env=_render_env_lines(extra_env, base_indent=2),
    )
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(
        f"\nConfiguration saved to: {settings_path}",
        file=sys.stderr,
    )
    print(
        "You can edit this file later or re-run this setup by deleting it.\n",
        file=sys.stderr,
    )


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


def _get_context_items(context_map):
    """Return non-_default context item names in their configured order."""
    return [k for k in context_map.keys() if k != "_default"]


def _format_item_config(item_name, context_map, env_map):
    """Return a human-readable summary of an item's effective configuration.

    The summary merges the `_default` context files and environment variables
    with the item-specific values so the user sees exactly what will be used
    for each option.
    """
    default_context = list(context_map.get("_default", []) or [])
    item_context = list(context_map.get(item_name, []) or [])
    merged_context = default_context + item_context

    default_env = dict(env_map.get("_default", {}) or {})
    item_env = dict(env_map.get(item_name, {}) or {})
    merged_env = dict(default_env)
    merged_env.update(item_env)

    lines = [f"{item_name}"]
    if merged_context:
        lines.append("    context files:")
        for path in merged_context:
            prefix = "      [default] " if path in default_context and path not in item_context else "      "
            lines.append(f"{prefix}- {path}")
    else:
        lines.append("    context files: (none)")
    if merged_env:
        lines.append("    environment variables:")
        for key, value in sorted(merged_env.items()):
            source = "[default]" if key in default_env and key not in item_env else "[item]"
            lines.append(f"      {source} {key}={value}")
    else:
        lines.append("    environment variables: (none)")
    return "\n".join(lines)


def _select_context_item(context_map, env_map):
    """Select a context item based on configuration and interactivity.

    - 0 non-_default items: use _default.
    - 1 non-_default item: use it automatically.
    - 2+ non-_default items: prompt interactively; "default" is the default
      choice when configured. In non-interactive mode, "default" is used if
      present, otherwise the launcher exits with an error.
    """
    items = _get_context_items(context_map)
    if len(items) <= 1:
        return items[0] if items else "_default"

    if not sys.stdin.isatty():
        if "default" in items:
            return "default"
        print(
            "Error: Multiple context items are configured but no default is set. "
            "Use --item to select one of the following:",
            file=sys.stderr,
        )
        for item in items:
            print(f"  - {item}", file=sys.stderr)
        sys.exit(1)

    print(
        "\nMultiple context items are configured. Please select one:",
        file=sys.stderr,
    )
    for idx, item in enumerate(items, start=1):
        print(
            f"\n  {idx}. {_format_item_config(item, context_map, env_map)}",
            file=sys.stderr,
        )

    print(flush=True)
    default_item = "default" if "default" in items else None
    prompt_text = (
        f"Select context item (1-{len(items)}, default: {default_item})"
        if default_item
        else f"Select context item (1-{len(items)})"
    )

    while True:
        answer = _prompt(prompt_text, default=default_item or "")
        if answer in items:
            return answer
        try:
            idx = int(answer)
            if 1 <= idx <= len(items):
                return items[idx - 1]
        except ValueError:
            pass
        print(
            f"Invalid selection. Please enter a number 1-{len(items)} or an item name.",
            file=sys.stderr,
        )


def _run_context_setup(settings_path, settings):
    """Guide the user through configuring context when it is empty."""
    print(
        "\n=== TopsailAI Launcher Context Setup ===",
        file=sys.stderr,
    )
    print(
        "No context is configured. Context files help the agent understand your project.\n",
        file=sys.stderr,
    )

    workspace = settings.get("workspace", ".")
    settings["context"] = settings.get("context") or {}
    settings["environment"] = settings.get("environment") or {}
    context_map = settings["context"]
    env_map = settings["environment"]
    if "_default" not in context_map:
        context_map["_default"] = []
    if "_default" not in env_map:
        env_map["_default"] = {"TOPSAILAI_INTERACTIVE_MODE": "1"}

    print(
        "Context files are injected into every agent run. "
        "Paths are relative to the workspace unless they start with '/'.",
        file=sys.stderr,
    )
    if _prompt_yn(
        "Would you like to add files to the '_default' context now?", default=True
    ):
        context_map["_default"] = _prompt_list(
            "Enter context file paths one per line (empty line to finish):"
        )

    while _prompt_yn(
        "Would you like to add another context item (e.g., 'memo', 'test')?",
        default=False,
    ):
        item_name = _prompt("Context item name")
        if not item_name or item_name == "_default":
            print("Invalid item name. Skipping.", file=sys.stderr)
            continue
        context_map[item_name] = _prompt_list(
            f"Enter context file paths for '{item_name}' one per line (empty line to finish):"
        )
        if _prompt_yn(
            f"Would you like to add environment variables for '{item_name}'?",
            default=False,
        ):
            env_vars = {}
            print("Enter KEY=VALUE pairs one per line (empty line to finish):")
            while True:
                try:
                    line = input("> ").strip()
                except EOFError:
                    break
                if not line:
                    break
                if "=" not in line:
                    print(
                        f"Warning: Ignoring invalid env line (expected KEY=VALUE): {line}",
                        file=sys.stderr,
                    )
                    continue
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip()
            env_map[item_name] = env_vars

    try:
        import yaml
    except ImportError as exc:
        print(
            "Error: PyYAML is required. Install it via: pip install pyyaml",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    with open(settings_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(settings, f, sort_keys=False, allow_unicode=True)
    print(
        f"\nConfiguration saved to: {settings_path}",
        file=sys.stderr,
    )



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
        default=None,
        help=(
            "Item name defined in settings.yaml context/environment sections. "
            "If omitted, the launcher auto-selects based on context configuration."
        ),
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
        print(
            f"[TopsailAI-Launcher] Settings file not found: {settings_path}",
            file=sys.stderr,
        )
        if not sys.stdin.isatty():
            print(
                "[TopsailAI-Launcher] Non-interactive mode detected. "
                "Creating a default configuration file for you.",
                file=sys.stderr,
            )
            _write_default_settings(settings_path)
            print(
                "\nIMPORTANT: `context._default` is currently empty. "
                "Fill it with the files you want every agent run to receive "
                "(e.g. project.yaml, docs, features).",
                file=sys.stderr,
            )
            print(
                "\n--- Generated Configuration Template ---\n",
                file=sys.stderr,
            )
            print(CONFIG_TEMPLATE, file=sys.stderr)
        else:
            _run_interactive_setup(settings_path)

    settings = load_yaml(settings_path)

    workspace = settings.get("workspace", os.getcwd()) or "."
    if workspace[0] != "/":
        workspace = os.path.abspath(workspace)

    # Resolve the context item to use when --item is not provided.
    if args.item is None:
        context_map = settings.get("context", {}) or {}
        non_default_items = _get_context_items(context_map)

        if not context_map:
            if sys.stdin.isatty():
                if _prompt_yn(
                    "No context is configured. Would you like to configure context now?",
                    default=True,
                ):
                    _run_context_setup(settings_path, settings)
                    settings = load_yaml(settings_path)
                    context_map = settings.get("context", {}) or {}
                    non_default_items = _get_context_items(context_map)
            else:
                print(
                    "[TopsailAI-Launcher] Warning: context is empty. "
                    "Continuing without context files.",
                    file=sys.stderr,
                )

        if len(non_default_items) <= 1:
            args.item = non_default_items[0] if non_default_items else "_default"
        else:
            args.item = _select_context_item(
                context_map, settings.get("environment", {}) or {}
            )

    env_map = settings.get("environment", {}) or {}
    # Resolve driver with the following priority:
    # 1. --driver CLI argument
    # 2. TOPSAILAI_AGENT_DRIVER from settings.environment (item-specific or _default)
    # 3. ai_agent_driver from settings.yaml
    # 4. TOPSAILAI_AGENT_DRIVER from the OS environment
    default_env = env_map.get("_default", {})
    item_env = env_map.get(args.item, {}) if args.item != "_default" else {}
    settings_env_driver = item_env.get(
        "TOPSAILAI_AGENT_DRIVER"
    ) or default_env.get("TOPSAILAI_AGENT_DRIVER")

    ai_agent_driver = (
        args.driver
        if args.driver
        else (
            settings_env_driver
            or settings.get("ai_agent_driver", "")
            or os.getenv("TOPSAILAI_AGENT_DRIVER", "")
        )
    )
    context_map = settings.get("context", {}) or {}

    if not ai_agent_driver:
        print("Error: 'ai_agent_driver' is not defined in settings.yaml", file=sys.stderr)
        sys.exit(1)

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
            context_message = (
                f"{original_user_message}\n\n---\n\n"
                + "\n\n---\n\n".join(message_parts)
            )
        else:
            context_message = original_user_message
    else:
        context_message = "\n\n---\n\n".join(message_parts)

    # Write large context message to a file to avoid exceeding environment variable size limits.
    global _CONTEXT_MESSAGE_FILE
    _CONTEXT_MESSAGE_FILE = None
    if context_message:
        tmp_dir = os.path.join(workspace, ".tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d%H%M%S", time.localtime())
        _CONTEXT_MESSAGE_FILE = os.path.join(
            tmp_dir, f"TOPSAILAI_CONTEXT_USER_MESSAGE.{timestamp}.data"
        )
        with open(_CONTEXT_MESSAGE_FILE, "w", encoding="utf-8") as f:
            f.write(context_message)
        merged_env["TOPSAILAI_CONTEXT_USER_MESSAGE"] = _CONTEXT_MESSAGE_FILE
    else:
        merged_env["TOPSAILAI_CONTEXT_USER_MESSAGE"] = ""

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

    try:
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
            # then launch the driver directly without changing directory.
            for key, val in merged_env.items():
                os.environ[key] = str(val)

            cmd_str = ' '.join(shlex.quote(c) for c in cmd)

            print("[TopsailAI-Launcher] Default os.system mode")
            print(f"[TopsailAI-Launcher] Shell command: {cmd_str}")
            ret = os.system(cmd_str)
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
    finally:
        # Clean up the temporary context message file after the driver exits.
        _cleanup_context_file()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
