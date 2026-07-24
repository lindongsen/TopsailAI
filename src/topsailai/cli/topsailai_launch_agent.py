#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Agent TopsailAI-Launcher Script

Parse .topsailai/settings.yaml in the current working directory. If the file
is missing, the launcher falls back to a built-in default configuration and
continues launching without creating a settings file.

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
import copy
import json
import dataclasses
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
# Names treated as the shared base configuration (基础配置). "_" is the preferred alias;
# "_default" is kept for backward compatibility.
BASE_ITEM_NAMES = ("_", "_default")


def _is_base_item(name):
    """Return True if the item name is a base/shared configuration key."""
    return name in BASE_ITEM_NAMES


def _get_base_context(context_map):
    """Return the merged base context file list.

    Both "_default" and "_" are treated as base keys. If both are present,
    "_default" files come first and "_" files are appended afterward.
    """
    default_context = list(context_map.get("_default", []) or [])
    underscore_context = list(context_map.get("_", []) or [])
    return default_context + underscore_context


def _get_base_env(env_map):
    """Return the merged base environment variables.

    "_default" variables are applied first, then "_" variables override them.
    """
    default_env = dict(env_map.get("_default", {}) or {})
    underscore_env = dict(env_map.get("_", {}) or {})
    merged = dict(default_env)
    merged.update(underscore_env)
    return merged


@dataclasses.dataclass(frozen=True)
class ContextSource:
    """A single context source: either a file path or a shell command."""

    type: str  # "file" or "command"
    value: str  # file path or command string
    shell: bool = True
    timeout: float = 30.0
    label: str = ""
    on_error: str = "include"  # "include", "skip", or "abort"
    cwd: str = ""
    environ: dict = dataclasses.field(default_factory=dict)


def _normalize_context_source(source, workspace=""):
    """Convert a raw context entry into a ContextSource object.

    Supports:
      - plain string -> file path
      - dict with type == "command" -> command source
      - dict with type == "file"   -> file source
    """
    if isinstance(source, str):
        return ContextSource(type="file", value=source)

    if not isinstance(source, dict):
        raise ValueError(
            f"Invalid context source type: {type(source).__name__!r}. "
            "Expected a string or a dict."
        )

    source_type = source.get("type", "file")
    if source_type not in ("file", "command"):
        raise ValueError(
            f"Invalid context source type: {source_type!r}. "
            "Expected 'file' or 'command'."
        )

    if source_type == "file":
        value = source.get("path") or source.get("value") or source.get("file")
        if not value:
            raise ValueError("File context source must specify a path.")
        return ContextSource(
            type="file",
            value=value,
            label=source.get("label", ""),
        )

    command = source.get("command") or source.get("value")
    if not command:
        raise ValueError("Command context source must specify a command.")

    timeout = source.get("timeout", 30)
    try:
        timeout = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid command timeout: {timeout!r}") from exc

    on_error = source.get("on_error", "include")
    if on_error not in ("include", "skip", "abort"):
        raise ValueError(
            f"Invalid on_error value: {on_error!r}. "
            "Expected 'include', 'skip', or 'abort'."
        )

    cwd = source.get("cwd", workspace)
    return ContextSource(
        type="command",
        value=command,
        shell=bool(source.get("shell", True)),
        timeout=timeout,
        label=source.get("label", ""),
        on_error=on_error,
        cwd=cwd,
        environ=dict(source.get("environ", {}) or {}),
    )


def _execute_context_command(source, workspace):
    """Execute a command context source and return its formatted output block."""
    command = source.value
    label = source.label or command
    cwd = source.cwd or workspace

    env = os.environ.copy()
    env.update(source.environ)

    try:
        result = subprocess.run(
            command if source.shell else shlex.split(command),
            shell=source.shell,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=source.timeout,
        )
    except subprocess.TimeoutExpired as exc:
        message = (
            f"Command timed out after {source.timeout}s:\n"
            f"  {command}\n"
            f"Partial stdout before timeout:\n{exc.stdout or ''}"
        )
        if source.on_error == "abort":
            raise RuntimeError(message) from exc
        if source.on_error == "skip":
            print(
                f"Warning: Skipping command context '{label}' due to timeout.",
                file=sys.stderr,
            )
            return ""
        return (
            f"> Command: {label} > START\n"
            f"Error: {message}\n"
            f"> Command: {label} > END"
        )
    except OSError as exc:
        message = f"Failed to execute command '{command}': {exc}"
        if source.on_error == "abort":
            raise RuntimeError(message) from exc
        if source.on_error == "skip":
            print(
                f"Warning: Skipping command context '{label}' due to execution error.",
                file=sys.stderr,
            )
            return ""
        return (
            f"> Command: {label} > START\n"
            f"Error: {message}\n"
            f"> Command: {label} > END"
        )

    if result.returncode != 0:
        if source.on_error == "abort":
            raise RuntimeError(
                f"Command '{command}' exited with code {result.returncode}.\n"
                f"stderr:\n{result.stderr}"
            )
        if source.on_error == "skip":
            print(
                f"Warning: Skipping command context '{label}' due to non-zero exit code {result.returncode}.",
                file=sys.stderr,
            )
            return ""
        output = (
            f"Warning: command exited with code {result.returncode}.\n"
            f"stderr:\n{result.stderr}\n"
            f"stdout:\n{result.stdout}"
        )
    else:
        output = result.stdout

    return f"> Command: {label} > START\n{output}\n> Command: {label} > END"


def _read_context_blocks(sources, workspace):
    """Read each context source and return formatted blocks."""
    blocks = []
    for source in sources:
        if source.type == "command":
            block = _execute_context_command(source, workspace)
            if block:
                blocks.append(block)
            continue

        # File source
        path = source.value
        if not os.path.isabs(path):
            path = os.path.join(workspace, path)
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
        "_": [],
        "default": [],
        "memo": [],
    },
    "environment": {
        "_": {
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
#   2. TOPSAILAI_AGENT_DRIVER environment variable from this file (item-specific or _)
#   3. ai_agent_driver field below
#   4. TOPSAILAI_AGENT_DRIVER from the OS environment
ai_agent_driver: "ai-team-flow-dev"

# Working directory for the launched driver.
workspace: "."

# Context configuration: each item corresponds to a set of context sources.
# Each source is either a file path (string) or a dict describing a command
# whose stdout will be captured and included as context.
#
# "_" is the 基础配置 (base configuration) shared by all items; item-specific
# sources are appended after the 基础配置 sources. File paths are relative to
# `workspace` unless they start with `/`.
#
# Command source example:
#   - type: command
#     command: "git log --oneline -10"
#     timeout: 5
#     label: "recent-commits"
#
# IMPORTANT: `context._` is currently empty. Fill it with the sources
# you want every agent run to receive (e.g. project.yaml, docs, features).
context:
  _: []
  default: []
  memo: []

# Environment variable configuration: each item can define its own variables.
# "_" variables are the 基础配置 (base configuration) and are applied first,
# then item-specific variables override them. System environment variables are
# inherited and can be overridden here.
environment:
  _:
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
    """Render a list of context sources as an inline [] or a YAML block list.

    Each item may be a plain string (file path) or a dict (command source).
    """
    if not items:
        return " []"
    spaces = " " * (base_indent + 2)
    lines = []
    for item in items:
        if isinstance(item, dict):
            lines.append(f"{spaces}- type: command")
            for key in ("command", "shell", "timeout", "label", "on_error", "cwd"):
                if key in item:
                    value = item[key]
                    if isinstance(value, bool):
                        rendered = "true" if value else "false"
                    elif isinstance(value, (int, float)):
                        rendered = str(value)
                    else:
                        rendered = _yaml_quote(value)
                    lines.append(f"{spaces}  {key}: {rendered}")
            if item.get("environ"):
                lines.append(f"{spaces}  environ:")
                env_spaces = " " * (base_indent + 4)
                for env_key, env_value in item["environ"].items():
                    lines.append(f"{env_spaces}{env_key}: {_yaml_quote(env_value)}")
        else:
            lines.append(f"{spaces}- {_yaml_quote(item)}")
    return "\n" + "\n".join(lines)


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
#   2. TOPSAILAI_AGENT_DRIVER environment variable from this file (item-specific or _)
#   3. ai_agent_driver field below
#   4. TOPSAILAI_AGENT_DRIVER from the OS environment
ai_agent_driver: {ai_agent_driver}

# Working directory for the launched driver.
workspace: {workspace}

# Context configuration: each item corresponds to a set of context sources.
# Each source is either a file path (string) or a dict describing a command
# whose stdout will be captured and included as context.
#
# "_" is the 基础配置 (base configuration) shared by all items; item-specific
# sources are appended after the 基础配置 sources. File paths are relative to
# `workspace` unless they start with `/`.
#
# Command source example:
#   - type: command
#     command: "git log --oneline -10"
#     timeout: 5
#     label: "recent-commits"
#
# IMPORTANT: `context._` is currently empty. Fill it with the sources
# you want every agent run to receive (e.g. project.yaml, docs, features).
context:
  _:{context_default}
  default: []

# Environment variable configuration: each item can define its own variables.
# "_" variables are the 基础配置 (base configuration) and are applied first,
# then item-specific variables override them. System environment variables are
# inherited and can be overridden here.
#
# TOPSAILAI_INTERACTIVE_MODE enables interactive behavior in the agent driver.
# Set to "1" to enable, "0" to disable.
environment:
  _:
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


def _prompt_context_sources(question):
    """Prompt the user for context sources until an empty line is entered.

    Lines starting with 'command:' are converted to command source dictionaries.
    Other lines are treated as file paths.
    """
    print(question)
    values = []
    while True:
        line = _prompt("", default="")
        if not line:
            break
        if line.startswith("command:"):
            values.append({
                "type": "command",
                "command": line[len("command:"):].strip(),
            })
        else:
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
        "\nContext sources are injected into every agent run. "
        "Paths are relative to the workspace unless they start with '/'. "
        "You can also add command sources by typing 'command: <shell command>'.",
        file=sys.stderr,
    )
    context_default = []
    if _prompt_yn("Would you like to add context sources for the '_' item now?", default=True):
        context_default = _prompt_context_sources(
            "Enter context file paths or 'command: <shell command>' one per line (empty line to finish):"
        )

    print(
        "\nEnvironment variables are merged before launching the driver. "
        "TOPSAILAI_INTERACTIVE_MODE is set to \"1\" by default.",
        file=sys.stderr,
    )
    extra_env = {}
    if _prompt_yn("Would you like to add extra environment variables for the '_' item now?", default=False):
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


def _handle_missing_settings(settings_path, args):
    """Decide what to do when .topsailai/settings.yaml is missing.

    - If --setup is passed, run the guided interactive setup and load the
      newly created configuration.
    - In an interactive terminal, prompt the user to choose between running
      with the default driver or entering the guided setup.
    - In a non-interactive terminal, fall back to the built-in default
      configuration without creating a file.

    Returns a tuple of (settings, settings_from_default).
    """
    if args.setup:
        print(
            f"[TopsailAI-Launcher] Settings file not found: {settings_path}",
            file=sys.stderr,
        )
        print(
            "[TopsailAI-Launcher] --setup requested, launching guided setup.",
            file=sys.stderr,
        )
        _run_interactive_setup(settings_path)
        return load_yaml(settings_path), False

    if sys.stdin.isatty():
        print(
            f"[TopsailAI-Launcher] Settings file not found: {settings_path}",
            file=sys.stderr,
        )
        print(
            "[TopsailAI-Launcher] Choose how to proceed:",
            file=sys.stderr,
        )
        print("  [r] Run with the default agent driver", file=sys.stderr)
        print(
            "  [s] Run guided setup to create .topsailai/settings.yaml",
            file=sys.stderr,
        )
        choice = _prompt("Your choice", default="r").lower()
        if choice in ("s", "setup"):
            _run_interactive_setup(settings_path)
            return load_yaml(settings_path), False

    print(
        f"[TopsailAI-Launcher] Settings file not found: {settings_path}",
        file=sys.stderr,
    )
    print(
        "[TopsailAI-Launcher] Using default configuration and continuing.",
        file=sys.stderr,
    )
    return copy.deepcopy(DEFAULT_CONFIG), True


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
    """Print the list of available items in the configuration (excluding base items)."""
    items = [k for k in context_map.keys() if not _is_base_item(k)]
    if not items:
        print("No items configured in context section.")
        return

    print("Available items in context configuration:")
    for item in items:
        print(f"  - {item}")
    print(f"\nUse: python3 {sys.argv[0]} --item <item_name>")


def _get_context_items(context_map):
    """Return non-base context item names in their configured order."""
    return [k for k in context_map.keys() if not _is_base_item(k)]


def _format_item_config(item_name, context_map, env_map):
    """Return a human-readable summary of an item's effective configuration.

    The summary merges the `_`/`_default` context sources and environment
    variables with the item-specific values so the user sees exactly what
    will be used for each option.
    """
    base_context = _get_base_context(context_map)
    item_context = list(context_map.get(item_name, []) or [])
    merged_context = base_context + item_context

    base_env = _get_base_env(env_map)
    item_env = dict(env_map.get(item_name, {}) or {})
    merged_env = dict(base_env)
    merged_env.update(item_env)

    def _source_label(source):
        if isinstance(source, dict):
            label = source.get("label") or source.get("command", "")
            return f"command: {label}"
        return str(source)

    def _is_base_source(source):
        if isinstance(source, dict):
            return any(
                source == base for base in base_context
            ) and source not in item_context
        return source in base_context and source not in item_context

    lines = [f"{item_name}"]
    if merged_context:
        lines.append("    context sources:")
        for source in merged_context:
            prefix = "      [base] " if _is_base_source(source) else "      "
            lines.append(f"{prefix}- {_source_label(source)}")
    else:
        lines.append("    context sources: (none)")
    if merged_env:
        lines.append("    environment variables:")
        for key, value in sorted(merged_env.items()):
            source = "[base]" if key in base_env and key not in item_env else "[item]"
            lines.append(f"      {source} {key}={value}")
    else:
        lines.append("    environment variables: (none)")
    return "\n".join(lines)


def _select_context_item(context_map, env_map):
    """Select a context item based on configuration and interactivity.

    - 0 non-base items: use the base item name if present, otherwise None.
    - 1 non-base item: use it automatically.
    - 2+ non-base items: prompt interactively; "default" is the default
      choice when configured. In non-interactive mode, "default" is used if
      present, otherwise the launcher exits with an error.
    """
    items = _get_context_items(context_map)
    if len(items) <= 1:
        return items[0] if items else "_"

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

    print("\nContext Items:", file=sys.stderr)
    for idx, item in enumerate(items, start=1):
        print(f"  {idx}. {item}", file=sys.stderr)

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
    if "_" not in context_map:
        context_map["_"] = []
    if "_" not in env_map:
        env_map["_"] = {"TOPSAILAI_INTERACTIVE_MODE": "1"}

    print(
        "Context files are injected into every agent run. "
        "Paths are relative to the workspace unless they start with '/'.",
        file=sys.stderr,
    )
    if _prompt_yn(
        "Would you like to add files to the '_' context now?", default=True
    ):
        context_map["_"] = _prompt_list(
            "Enter context file paths one per line (empty line to finish):"
        )

    while _prompt_yn(
        "Would you like to add another context item (e.g., 'memo', 'test')?",
        default=False,
    ):
        item_name = _prompt("Context item name")
        if not item_name or _is_base_item(item_name):
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


def _scan_folder(folder):
    """Scan a specific folder and print its tree structure.

    This reuses the same scanning logic used for agent context so that the
    output is consistent with the workspace folder tree shown to the agent.
    """
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        print(f"Error: --scan target is not a directory: {folder}", file=sys.stderr)
        sys.exit(1)
    print(_scan_workspace_files(folder, folder))


def _scan_workspace_files(workspace, project_folder=None):
    """Scan workspace and return folder structure as a tree string.

    If ``project_folder`` is provided and is a child of ``workspace`` (or
    equals it), only that folder is scanned. This lets the agent focus on the
    active project when ``TOPSAILAI_PROJECT_FOLDER`` is set.

    Symbolic links are not followed: symlinked files are listed as leaf
    entries and symlinked directories are not recursed into.
    """
    workspace = os.path.abspath(workspace)
    if project_folder:
        project_folder = os.path.abspath(project_folder)
        # Only accept the project folder if it is the workspace itself or a
        # descendant of the workspace.
        if project_folder == workspace or project_folder.startswith(
            workspace + os.sep
        ):
            scan_root = project_folder
        else:
            scan_root = workspace
    else:
        scan_root = workspace

    patterns = _load_gitignore_patterns(scan_root)

    entries = []

    def walk(current_dir, prefix=""):
        try:
            items = sorted(os.listdir(current_dir))
        except (PermissionError, OSError):
            return

        visible_items = []
        for name in items:
            # Skip hidden files and directories by default (names starting
            # with a dot). This keeps the generated context tree focused on
            # project-visible content.
            if name.startswith("."):
                continue
            full_path = os.path.join(current_dir, name)
            rel_path = os.path.relpath(full_path, scan_root).replace("\\", "/")
            is_symlink = os.path.islink(full_path)
            is_dir = os.path.isdir(full_path) and not is_symlink
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
    walk(scan_root)
    return "> " + scan_root + "\n" + "\n".join(entries)


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
    parser.add_argument(
        "--setup",
        action="store_true",
        dest="setup",
        help="Force the guided interactive setup to create .topsailai/settings.yaml when it is missing",
    )
    parser.add_argument(
        "--scan",
        default=None,
        metavar="FOLDER",
        help="Scan the specified folder and print its tree structure, then exit",
    )
    args = parser.parse_args()
    if args.scan is not None:
        _scan_folder(args.scan)
        return

    # 1. Locate and parse .topsailai/settings.yaml in the current working directory
    settings_path = os.path.join(os.getcwd(), ".topsailai", "settings.yaml")
    settings_from_default = False
    if not os.path.isfile(settings_path):
        settings, settings_from_default = _handle_missing_settings(settings_path, args)
    else:
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

        if settings_from_default:
            args.item = "_"
        elif len(non_default_items) <= 1:
            args.item = non_default_items[0] if non_default_items else "_"
        else:
            args.item = _select_context_item(
                context_map, settings.get("environment", {}) or {}
            )
    env_map = settings.get("environment", {}) or {}
    # Resolve driver with the following priority:
    # 1. --driver CLI argument
    # 2. TOPSAILAI_AGENT_DRIVER from settings.environment (item-specific or base)
    # 3. ai_agent_driver from settings.yaml
    # 4. TOPSAILAI_AGENT_DRIVER from the OS environment
    base_env = _get_base_env(env_map)
    item_env = env_map.get(args.item, {}) if not _is_base_item(args.item) else {}
    settings_env_driver = item_env.get(
        "TOPSAILAI_AGENT_DRIVER"
    ) or base_env.get("TOPSAILAI_AGENT_DRIVER")

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
    print(f"[TopsailAI-Launcher] Context item: {item_name}")

    # 2. Assemble context: base items first, then the specified item
    base_context = _get_base_context(context_map)
    item_context = context_map.get(item_name, []) if not _is_base_item(item_name) else []

    if not _is_base_item(item_name) and item_name not in context_map:
        print(f"Error: Item '{item_name}' not found in context section", file=sys.stderr)
        print("\n", file=sys.stderr)
        print_available_items(context_map)
        sys.exit(1)

    merged_context = list(base_context)
    merged_context.extend(item_context)

    # Normalize sources and resolve relative file paths against workspace.
    normalized_context = []
    for ctx in merged_context:
        source = _normalize_context_source(ctx, workspace)
        if source.type == "file" and not os.path.isabs(source.value):
            source = dataclasses.replace(
                source, value=os.path.join(workspace, source.value)
            )
        normalized_context.append(source)

    # 2.5 Read context source contents and format them (skipped in dry-run mode
    # so commands are not actually executed).
    if args.dry_run:
        context_content = ""
    else:
        context_content = _read_context_blocks(normalized_context, workspace)
    # 3. Assemble environment variables: system env <- base <- item (latter overrides former)
    base_env = _get_base_env(env_map)
    item_env = env_map.get(item_name, {}) if not _is_base_item(item_name) else {}

    os.environ["TOPSAILAI_PROJECT_WORKSPACE"] = workspace

    merged_env = os.environ.copy()
    merged_env.update(base_env)
    merged_env.update(item_env)

    # 3.5 Append context file contents and workspace folder structure to
    # TOPSAILAI_CONTEXT_USER_MESSAGE. When TOPSAILAI_PROJECT_FOLDER is set
    # (either in the OS environment or in the merged environment), restrict
    # the scanned folder tree to that project folder.
    original_user_message = merged_env.get("TOPSAILAI_CONTEXT_USER_MESSAGE", "")
    project_folder = merged_env.get("TOPSAILAI_PROJECT_FOLDER") or os.environ.get(
        "TOPSAILAI_PROJECT_FOLDER"
    )
    folder_structure = _scan_workspace_files(workspace, project_folder)

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
        f"[TopsailAI-Launcher] Merged env keys: {sorted(set(list(base_env.keys()) + list(item_env.keys())))}"
    )

    # In dry-run mode, only print the details and exit without execution
    if args.dry_run:
        print("\n--- Dry Run Mode (no actual execution) ---")
        print(f"\nCommand line:\n  {' '.join(shlex.quote(c) for c in cmd)}")
        print(f"\nWorking directory:\n  {workspace}")
        print("\nContext sources (base + selected item):")
        if normalized_context:
            for source in normalized_context:
                if source.type == "command":
                    label = source.label or source.value
                    shell_str = "true" if source.shell else "false"
                    print(
                        f"  [command] {label}\n"
                        f"    command: {source.value}\n"
                        f"    shell: {shell_str}, timeout: {source.timeout}s, "
                        f"on_error: {source.on_error}"
                    )
                else:
                    print(f"  [file] {source.value}")
        else:
            print("  (none)")
        print("\nEnvironment variables (merged from base and item):")
        config_env_keys = sorted(set(list(base_env.keys()) + list(item_env.keys())))
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
