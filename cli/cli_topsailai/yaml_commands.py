"""YAML-based command instruction parsing for the TopsailAI CLI."""

from __future__ import annotations

import os
import re
import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional, Tuple

from cli_topsailai.colors import print_error, print_info, print_success, print_warning
from cli_topsailai.constants import (
    DEFAULT_TIMEOUT,
    DEFAULT_TOPSAILAI_YAML,
    ENV_VAR_PATTERN,
)
from cli_topsailai.history import load_readline_history
import cli_topsailai.state as state


def resolve_env_value(value: Any) -> Any:
    """Resolve environment variable references inside a string value."""
    if not isinstance(value, str):
        return value
    matches = list(ENV_VAR_PATTERN.finditer(value))
    if not matches:
        return value

    result = value
    for match in reversed(matches):
        full = match.group(0)
        inner = match.group(1)
        if inner.startswith("{") and inner.endswith("}"):
            var_name = inner[1:-1]
            default_sep = var_name.find(":-")
            if default_sep != -1:
                var_name, default_val = var_name[:default_sep], var_name[default_sep + 2 :]
            else:
                default_val = ""
            env_val = os.environ.get(var_name, default_val)
            result = result[: match.start()] + env_val + result[match.end() :]
        else:
            var_name = inner
            env_val = os.environ.get(var_name, "")
            result = result[: match.start()] + env_val + result[match.end() :]
    return result


def resolve_dict_env_values(data: Any) -> Any:
    """Recursively resolve environment variable references in dict/list values."""
    if isinstance(data, dict):
        return {k: resolve_dict_env_values(v) for k, v in data.items()}
    if isinstance(data, list):
        return [resolve_dict_env_values(item) for item in data]
    return resolve_env_value(data)


def load_yaml_commands(
    yaml_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Load command instructions from a YAML file.

    The file is expected to contain an ``instructions`` list at the root.
    Returns a list of instruction dictionaries.  If the file is missing,
    PyYAML is not installed, or parsing fails, an empty list is returned.

    Args:
        yaml_path: Path to the YAML file.  Defaults to ``topsailai.yaml`` in
            the same directory as this module.

    Returns:
        List of instruction dictionaries.
    """
    if yaml_path is None:
        module_dir = os.path.dirname(os.path.abspath(__file__))
        yaml_path = os.path.join(module_dir, "topsailai.yaml")
    if not os.path.isfile(yaml_path):
        return []

    try:
        import yaml
    except ImportError:
        print_warning("PyYAML not installed. YAML commands unavailable.")
        return []

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print_warning(f"Failed to load topsailai.yaml: {e}")
        return []

    if not data or not isinstance(data, dict):
        return []

    instructions = data.get("instructions", [])
    if not isinstance(instructions, list):
        return []

    return instructions


def get_all_command_names(instruction: Dict[str, Any]) -> List[str]:
    """
    Get all command names for an instruction, including cmd and aliases.

    Returns a list of names without leading '/'.

    Args:
        instruction: YAML instruction dictionary.

    Returns:
        List of command name strings.
    """
    names = []
    cmd = instruction.get("cmd", "")
    if cmd:
        names.append(cmd.lstrip("/"))

    aliases = instruction.get("alias", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    for alias in aliases:
        if alias:
            names.append(alias.lstrip("/"))

    return names


def match_yaml_command(
    user_input: str, task_dir: str = ""
) -> Optional[Tuple[Dict[str, Any], Dict[str, str]]]:
    """
    Match user input against YAML commands.

    Returns ``(instruction, variables)`` or ``None``.  Supports exact match
    (with or without leading '/'), variable extraction from cmd templates like
    ``/cd {session_id}``, alias matching, and scope filtering.

    Args:
        user_input: Raw command string entered by the user.
        task_dir: Task directory used when resolving directory variables.

    Returns:
        Matched instruction and extracted variables, or ``None``.
    """
    # Special handling for /cd without arguments: available in all scopes
    if user_input in ("/cd", "cd"):
        for instruction in state.yaml_commands:
            cmd_template = instruction.get("cmd", "")
            if cmd_template.startswith("/cd"):
                return instruction, {"session_id": "", "task_dir": task_dir}

    for instruction in state.yaml_commands:
        scopes = instruction.get("scopes", [])
        if state.current_scope not in scopes:
            continue

        cmd_template = instruction.get("cmd", "")
        if not cmd_template:
            continue

        var_pattern = re.compile(r"\{(\w+)\}")
        var_names = var_pattern.findall(cmd_template)

        pattern = re.escape(cmd_template.lstrip("/"))
        for var_name in var_names:
            if var_name == "args":
                pattern = pattern.replace(
                    f"\\{{{var_name}\\}}", f"(?P<{var_name}>.*)"
                )
            else:
                pattern = pattern.replace(
                    f"\\{{{var_name}\\}}", f"(?P<{var_name}>\\S+)"
                )

        pattern = f"^/?{pattern}(?:\\s+.*)?$"
        flags = re.DOTALL if cmd_template.startswith(("/ctx.add_msg", "/ctx.btw", "/agent2llm.add_msg")) else 0
        match = re.match(pattern, user_input, flags)
        if match:
            variables = match.groupdict()
            variables.setdefault("session_id", state.current_session_id or "")
            variables["task_dir"] = task_dir
            if cmd_template.startswith(("/ctx.add_msg", "/ctx.btw", "/agent2llm.add_msg")):
                msg_match = re.match(
                    rf"^/?{re.escape(cmd_template.lstrip('/'))}(?:\s+(.*))?$/",
                    user_input,
                    re.DOTALL,
                )
                variables["message"] = (
                    msg_match.group(1) if msg_match and msg_match.group(1) is not None else ""
                )
            return instruction, variables

        aliases = instruction.get("alias", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        for alias in aliases:
            if not alias:
                continue
            alias_pattern = re.escape(alias)
            for var_name in var_names:
                if var_name == "args":
                    alias_pattern = alias_pattern.replace(
                        f"\\{{{var_name}\\}}", f"(?P<{var_name}>.*)"
                    )
                else:
                    alias_pattern = alias_pattern.replace(
                        f"\\{{{var_name}\\}}", f"(?P<{var_name}>\\S+)"
                    )
            alias_pattern = f"^/?{alias_pattern}(?:\\s+.*)?$"
            alias_match = re.match(alias_pattern, user_input)
            if alias_match:
                variables = alias_match.groupdict()
                variables.setdefault("session_id", state.current_session_id or "")
                variables["task_dir"] = task_dir
                return instruction, variables

    return None


def build_command_env(
    instruction: Dict[str, Any], variables: Dict[str, str]
) -> Dict[str, str]:
    """
    Build environment variables for a shell command.

    Defaults:
      - TOPSAILAI_SESSION_ID={session_id}
      - TOPSAILAI_INTERACTIVE_MODE="0"

    Instruction-level ``environ`` overrides and extends defaults.  Variable
    placeholders like ``{session_id}`` are resolved from ``variables``.

    Args:
        instruction: YAML instruction dictionary.
        variables: Extracted variable values from command matching.

    Returns:
        Merged environment dictionary.
    """
    env = os.environ.copy()

    defaults = {
        "TOPSAILAI_SESSION_ID": variables.get("session_id", ""),
        "TOPSAILAI_INTERACTIVE_MODE": "0",
    }
    env.update(defaults)

    instruction_env = instruction.get("environ")
    if isinstance(instruction_env, dict):
        for key, value in instruction_env.items():
            if not isinstance(value, str):
                continue
            resolved = value
            for var_name, var_value in variables.items():
                resolved = resolved.replace(f"{{{var_name}}}", var_value)
            env[key] = resolved

    return env


def handle_yaml_command(
    instruction: Dict[str, Any], variables: Dict[str, str]
) -> str:
    """
    Handle a matched YAML command.

    Returns ``"yaml_handled"`` so the main loop knows the input was processed.

    Args:
        instruction: Matched YAML instruction dictionary.
        variables: Extracted variable values.

    Returns:
        Action string for the main loop.
    """
    from cli_topsailai.log_files import (
        _display_session_id,
        _resolve_literal_session_id,
        discover_log_files,
    )
    from cli_topsailai.process import (
        is_async_command,
        is_independent_process,
        is_use_os_system,
        run_external_command,
    )

    cmd = instruction.get("cmd", "")
    shell = instruction.get("shell", "")

    if cmd.startswith(("/ctx.add_msg", "/ctx.btw", "/agent2llm.add_msg")):
        initial = variables.get("message", "")
        if len(initial) >= 2 and initial[0] in ('"', "'") and initial[-1] == initial[0]:
            initial = initial[1:-1]
        lines: List[str] = []
        if initial:
            lines.append(initial)
        else:
            print_info("Enter message (Ctrl+D to finish):")
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    print_warning("Cancelled.")
                    return "yaml_handled"
                lines.append(line)
        message = "\n".join(lines).strip()
        if not message:
            print_error("Message cannot be empty.")
            return "yaml_handled"
        shell_cmd = shell
        shell_cmd = shell_cmd.replace(
            "'{session_id}'", shlex.quote(state.current_session_id or "")
        )
        shell_cmd = shell_cmd.replace("'{message}'", shlex.quote(message))
        try:
            cmd_list = shlex.split(shell_cmd)
            cmd_env = build_command_env(instruction, variables)
            run_external_command(
                cmd_list,
                cmd_env,
                is_independent_process(instruction),
                is_async_command(instruction),
                is_use_os_system(instruction),
            )
        except Exception as e:
            print_error(f"Failed to execute command: {e}")
        return "yaml_handled"

    if not shell:
        if cmd.startswith("/cd"):
            session_id = variables.get("session_id", "").strip()
            if session_id:
                if session_id.isdigit():
                    resolved_task_dir = variables.get("task_dir", "")
                    if resolved_task_dir:
                        log_files = discover_log_files(resolved_task_dir)
                        idx = int(session_id) - 1
                        if 0 <= idx < len(log_files):
                            resolved = log_files[idx].get("session_id")
                            if resolved:
                                if resolved == "(temp)":
                                    print_error(
                                        f"No session ID available for entry {idx + 1}."
                                    )
                                    return "yaml_handled"
                                session_id = resolved
                            else:
                                print_error(f"Entry {idx + 1} has no session ID.")
                                return "yaml_handled"
                        else:
                            print_error(
                                f"Invalid number. Please enter 1-{len(log_files)}."
                            )
                            return "yaml_handled"
                else:
                    session_id = _resolve_literal_session_id(session_id)
                state.current_scope = "session"
                state.current_session_id = session_id
                print_success(
                    f"Entered session scope: {_display_session_id(session_id)}"
                )
            else:
                state.current_scope = "workspace"
                state.current_session_id = None
                print_success("Switched to workspace scope.")
            if state.history_manager is not None:
                load_readline_history(state.history_manager, state.current_scope, state.current_session_id)
            return "yaml_handled"

        if cmd.startswith("/env.get"):
            key = variables.get("key", "").strip()
            if key:
                value = os.environ.get(key, "")
                print_info(f"{key}={value}")
            else:
                print_error("Usage: /env.get {key}")
            return "yaml_handled"

        if cmd.startswith("/env.set"):
            key = variables.get("key", "").strip()
            value = variables.get("value", "").strip()
            if key:
                os.environ[key] = value
                print_success(f"Set {key}={value}")
            else:
                print_error("Usage: /env.set {key} {value}")
            return "yaml_handled"

        print_warning(f"Internal command not implemented: {cmd}")
        return "yaml_handled"

    try:
        shell_cmd = shell
        for var_name, var_value in variables.items():
            if var_name == "args":
                shell_cmd = shell_cmd.replace(f"'{{{var_name}}}'", var_value)
                shell_cmd = shell_cmd.replace(f"{{{var_name}}}", var_value)
            else:
                quoted_placeholder = f"'{{{var_name}}}'"
                if quoted_placeholder in shell_cmd:
                    shell_cmd = shell_cmd.replace(quoted_placeholder, shlex.quote(var_value))
                else:
                    shell_cmd = shell_cmd.replace(f"{{{var_name}}}", shlex.quote(var_value))

        cmd_list = shlex.split(shell_cmd)
        cmd_env = build_command_env(instruction, variables)
        run_external_command(
            cmd_list,
            cmd_env,
            is_independent_process(instruction),
            is_async_command(instruction),
            is_use_os_system(instruction),
        )
    except Exception as e:
        print_error(f"Failed to execute command: {e}")

    return "yaml_handled"


def parse_command_string(
    raw_cmd: str, env: Optional[Dict[str, str]] = None
) -> List[str]:
    """
    Parse a command string using shell-like rules, then resolve any remaining
    environment variable references.
    """
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)

    expanded = os.path.expandvars(raw_cmd)
    expanded = re.sub(
        r"\$\{([^}:]+):-([^}]*)\}",
        lambda m: merged_env.get(m.group(1), m.group(2)),
        expanded,
    )
    try:
        return shlex.split(expanded)
    except ValueError:
        return raw_cmd.split()


def build_command_list(
    instruction: Dict[str, Any], env: Optional[Dict[str, str]] = None
) -> List[str]:
    """Build a command list from 'cmd' (string or list) inside an instruction."""
    raw_cmd = instruction.get("cmd")
    if raw_cmd is None:
        return []
    if isinstance(raw_cmd, list):
        merged_env = dict(os.environ)
        if env:
            merged_env.update(env)
        resolved = []
        for item in raw_cmd:
            if isinstance(item, str):
                expanded = os.path.expandvars(item)
                expanded = re.sub(
                    r"\$\{([^}:]+):-([^}]*)\}",
                    lambda m: merged_env.get(m.group(1), m.group(2)),
                    expanded,
                )
                resolved.extend(shlex.split(expanded))
            else:
                resolved.append(str(item))
        return resolved
    return parse_command_string(raw_cmd, env)


def execute_yaml_instruction(
    instruction: Dict[str, Any],
    env: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> bool:
    """
    Execute a single YAML instruction.
    Returns True if execution succeeded, False otherwise.
    """
    from cli_topsailai.process import (
        is_async_command,
        is_independent_process,
        is_use_os_system,
        run_external_command,
    )

    instruction = resolve_dict_env_values(instruction)
    cmd_list = build_command_list(instruction, env)
    if not cmd_list:
        print_error("Instruction has no 'cmd' field.")
        return False

    cmd_env = dict(os.environ)
    if env:
        cmd_env.update(env)
    instruction_env = instruction.get("env")
    if isinstance(instruction_env, dict):
        cmd_env.update(instruction_env)

    independent = is_independent_process(instruction)
    async_cmd = is_async_command(instruction)
    use_os_system = is_use_os_system(instruction)

    description = instruction.get("description")
    if description:
        print_info(f"[{description}]")

    try:
        run_external_command(
            cmd_list,
            cmd_env,
            independent=independent,
            async_cmd=async_cmd,
            use_os_system=use_os_system,
            timeout=timeout,
        )
    except Exception as exc:
        print_error(f"Execution failed: {exc}")
        return False
    return True


def execute_command_by_name(
    commands: Dict[str, Any],
    name: str,
    env: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> bool:
    """Execute a named command from the YAML command dictionary."""
    instruction = commands.get(name)
    if instruction is None:
        print_error(f"Unknown command: {name}")
        return False
    return execute_yaml_instruction(instruction, env, timeout)


def list_command_names(commands: Dict[str, Any]) -> List[str]:
    """Return a sorted list of available command names."""
    return sorted(commands.keys())
