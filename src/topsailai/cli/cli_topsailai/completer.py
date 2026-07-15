"""Tab-completion helpers for the TopsailAI CLI."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional

import cli_topsailai.state as cli_state
from cli_topsailai.paths import expand_path


def get_all_command_names(yaml_commands: Optional[Any] = None) -> List[str]:
    """Return all command names from the loaded YAML instructions.

    Args:
        yaml_commands: Optional list of YAML command dictionaries, or a single
            instruction dictionary.  When omitted, the globally loaded
            ``state.yaml_commands`` is used.
    """
    if yaml_commands is None:
        commands = cli_state.yaml_commands
    elif isinstance(yaml_commands, dict):
        commands = [yaml_commands]
    else:
        commands = yaml_commands

    names: List[str] = []
    for instruction in commands:
        if not isinstance(instruction, dict):
            continue
        # Support both "cmd" (YAML command field) and "name" variants.
        name = instruction.get("name") or instruction.get("cmd")
        if name:
            names.append(name.lstrip("/"))
        # Support both "aliases" and "alias" keys, and string-or-list values.
        aliases = instruction.get("aliases") or instruction.get("alias") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        for alias in aliases:
            if alias:
                names.append(alias.lstrip("/"))
    return names


def get_available_completions() -> List[str]:
    """Return all available command completions for the current scope."""
    completions: List[str] = []

    # Built-in commands (always available)
    builtins = ["/refresh", "/clean", "/help", "/session", "/send"]
    completions.extend(builtins)

    # YAML commands filtered by current scope
    for instruction in cli_state.yaml_commands:
        scopes = instruction.get("scopes", [])
        if cli_state.current_scope not in scopes:
            continue
        cmd = instruction.get("cmd", "")
        if cmd:
            completions.append(cmd.split()[0])
        aliases = instruction.get("alias", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        for alias in aliases:
            if alias:
                if not alias.startswith("/"):
                    alias = "/" + alias
                completions.append(alias)

    # Remove duplicates and sort
    seen = set()
    unique = []
    for c in completions:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return sorted(unique)


def _get_file_completions(prefix: str) -> List[str]:
    """Return file-system completion candidates for *prefix*."""
    expanded = expand_path(prefix)
    if os.path.isdir(expanded):
        directory = expanded
        base = ""
    else:
        directory = os.path.dirname(expanded) or "."
        base = os.path.basename(expanded)
    try:
        entries = os.listdir(directory)
    except OSError:
        return []
    matches = []
    for entry in entries:
        if entry.startswith(base):
            full = os.path.join(directory, entry)
            if os.path.isdir(full):
                entry += "/"
            matches.append(entry)
    return matches


def get_completions(text: str, state_index: int) -> Optional[str]:
    """readline completion entry point."""
    if state_index == 0:
        line = text.lstrip()
        candidates: List[str] = []
        if line.startswith("/"):
            candidates = get_available_completions()
        else:
            candidates = _get_file_completions(line)
        cli_state._completion_matches = [c for c in candidates if c.startswith(text)]
    try:
        return cli_state._completion_matches[state_index]
    except (AttributeError, IndexError):
        return None


def tab_completer(text: str, state: int) -> Optional[str]:
    """readline tab completion callback."""
    try:
        import readline

        line = readline.get_line_buffer()
        if line.strip() and not line.startswith(text):
            parts = line[: readline.get_begidx()].strip().split()
            if parts:
                return None

        candidates = get_available_completions()
        matches = []
        for c in candidates:
            if c.startswith(text):
                matches.append(c)
            elif not text.startswith("/") and c.lstrip("/").startswith(text):
                matches.append(c.lstrip("/"))
        if state < len(matches):
            return matches[state]
    except (NameError, AttributeError, ImportError):
        pass
    return None


def setup_tab_completion() -> None:
    """Configure readline for TAB command completion."""
    try:
        import readline

        readline.set_completer(tab_completer)
        readline.set_completer_delims(" \t\n")
        readline.parse_and_bind("tab: complete")
    except (NameError, AttributeError, ImportError):
        pass
