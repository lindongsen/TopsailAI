"""Help text rendering for the TopsailAI CLI."""

from typing import Any, Dict, List, Optional

from cli_topsailai.colors import Colors, colored, cprint


def _command_matches(item: Dict[str, Any], keyword_lower: str) -> bool:
    """Check whether a command definition matches a keyword."""
    texts = [str(item.get("cmd", ""))]

    desc = item.get("desc", "")
    if isinstance(desc, str):
        texts.append(desc)

    example = item.get("example", "")
    if isinstance(example, str):
        texts.append(example)

    aliases = item.get("alias", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    for alias in aliases:
        texts.append(str(alias))

    return any(keyword_lower in t.lower() for t in texts)


def _render_command(item: Dict[str, Any], is_yaml: bool = False) -> None:
    """Render a single command definition to the terminal."""
    cmd = item.get("cmd", "")
    desc = item.get("desc", "")
    example = item.get("example", "")

    alias_str = ""
    if is_yaml:
        aliases = item.get("alias", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        if aliases:
            alias_str = (
                " "
                + colored(
                    "(alias: " + ", ".join(str(a) for a in aliases) + ")",
                    Colors.WHITE,
                    dim=True,
                )
            )

    print(f"\n  {colored(cmd, Colors.YELLOW, bold=True)}{alias_str}")
    print(f"      {colored(desc, Colors.WHITE)}")
    if example:
        print(f"      {colored(example, Colors.WHITE, dim=True)}")


def print_instruction_help(instruction: Dict[str, Any]) -> None:
    """Display detailed help for a single YAML instruction.

    Args:
        instruction: YAML instruction dictionary.
    """
    width = 80
    cprint("=" * width, color=Colors.CYAN, bold=True)
    cprint("  TopsailAI - Command Help", color=Colors.CYAN, bold=True)
    cprint("=" * width, color=Colors.CYAN, bold=True)

    _render_command(instruction, is_yaml=True)

    cprint("=" * width, color=Colors.CYAN)
    print()


def print_help(
    yaml_commands: Optional[List[Dict[str, Any]]],
    current_scope: str,
    keyword: Optional[str] = None,
) -> None:
    """Display available commands with descriptions and examples.

    Includes built-in commands and YAML-loaded commands for the current scope.
    When ``keyword`` is provided, only commands whose cmd/alias/desc/example
    contain the keyword (case-insensitive) are shown.

    Args:
        yaml_commands: List of loaded YAML command definitions.
        current_scope: The current command scope (e.g. ``"global"`` or
            ``"session"``).
        keyword: Optional search keyword for fuzzy filtering.
    """
    width = 80
    cprint("=" * width, color=Colors.CYAN, bold=True)
    if keyword:
        cprint(
            f"  TopsailAI - Commands matching '{keyword}'",
            color=Colors.CYAN,
            bold=True,
        )
    else:
        cprint("  TopsailAI - Available Commands", color=Colors.CYAN, bold=True)
    cprint("=" * width, color=Colors.CYAN, bold=True)

    commands = [
        {
            "cmd": "<number>",
            "desc": "Select a log file by its number to stream output in real-time.",
            "example": "Example: 3",
        },
        {
            "cmd": "/refresh",
            "desc": "Re-scan the task directory and refresh the file list.",
            "example": "",
        },
        {
            "cmd": "/session <number>",
            "desc": "Retrieve detailed messages for the session ID of the selected file.",
            "example": "Example: /session 3",
        },
        {
            "cmd": "/clean [<number> [<number>...]]",
            "desc": "Clean up .stdout files. Without arguments: deletes idle files older than 3 days. With numbers: deletes the specified files by their list number.",
            "example": "Example: /clean 3 5 7",
        },
        {
            "cmd": "/send [session_id_or_index] [message...]",
            "desc": "Send a message to a running session through its named pipe. In session scope, omit the session id. If no message is provided, enter multi-line input mode (finish with EOF). While streaming a log, /send defaults to the watched session.",
            "example": "Example: /send 1 hello  or  /send my-session hello  or  while streaming: /send hello",
        },
        {
            "cmd": "/help [<keyword>]",
            "desc": "Display this help message with all available commands. Use /help <keyword> to search commands by name, alias, or description.",
            "example": "Example: /help ctx",
        },
        {
            "cmd": "q  or  quit",
            "desc": "Exit the log watcher gracefully.",
            "example": "",
        },
        {
            "cmd": "Ctrl+C",
            "desc": "Interrupt and exit gracefully, cleaning up all child processes.",
            "example": "",
        },
    ]

    keyword_lower = keyword.lower() if keyword else None
    if keyword_lower:
        builtin_matches = [c for c in commands if _command_matches(c, keyword_lower)]
    else:
        builtin_matches = commands

    for item in builtin_matches:
        _render_command(item)

    yaml_matches: List[Dict[str, Any]] = []
    if yaml_commands:
        # When searching, look across all scopes so users can discover
        # commands that are not available in the current scope.
        scope_cmds = [
            inst
            for inst in yaml_commands
            if keyword_lower or current_scope in inst.get("scopes", [])
        ]
        if keyword_lower:
            yaml_matches = [
                inst for inst in scope_cmds if _command_matches(inst, keyword_lower)
            ]
        else:
            yaml_matches = scope_cmds

        if yaml_matches and not keyword:
            print(f"\n  {colored('--- YAML Commands ---', Colors.CYAN, bold=True)}")

        for inst in yaml_matches:
            _render_command(inst, is_yaml=True)

    if keyword_lower and not builtin_matches and not yaml_matches:
        message = f"No commands found matching '{keyword}'."
        print(f"\n  {colored(message, Colors.YELLOW)}")

    cprint("-" * width, color=Colors.CYAN)
    print(
        f"  {colored('Tip: Running processes are shown in ', Colors.WHITE, dim=True)}"
        f"{colored('green', Colors.GREEN)}"
        f"{colored(', idle files in ', Colors.WHITE, dim=True)}"
        f"{colored('gray', Colors.GRAY)}"
        f"{colored('.', Colors.WHITE, dim=True)}"
    )
    cprint("=" * width, color=Colors.CYAN)
    print()
