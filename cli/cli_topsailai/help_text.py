"""Help text rendering for the TopsailAI CLI."""

from cli_topsailai.colors import Colors, colored, cprint


def print_help(yaml_commands, current_scope: str) -> None:
    """Display all available commands with descriptions and examples.

    Includes built-in commands and YAML-loaded commands for the current scope.

    Args:
        yaml_commands: List of loaded YAML command definitions.
        current_scope: The current command scope (e.g. ``"global"`` or
            ``"session"``).
    """
    width = 80
    cprint("=" * width, color=Colors.CYAN, bold=True)
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
            "cmd": "/help  or  help",
            "desc": "Display this help message with all available commands.",
            "example": "",
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

    for item in commands:
        cmd = item["cmd"]
        desc = item["desc"]
        example = item.get("example", "")

        print(f"\n  {colored(cmd, Colors.YELLOW, bold=True)}")
        print(f"      {colored(desc, Colors.WHITE)}")
        if example:
            print(f"      {colored(example, Colors.WHITE, dim=True)}")

    # Print YAML commands for current scope
    if yaml_commands:
        scope_cmds = [
            inst for inst in yaml_commands if current_scope in inst.get("scopes", [])
        ]
        if scope_cmds:
            print(f"\n  {colored('--- YAML Commands ---', Colors.CYAN, bold=True)}")
            for inst in scope_cmds:
                cmd = inst.get("cmd", "")
                aliases = inst.get("alias", [])
                if isinstance(aliases, str):
                    aliases = [aliases]
                desc = inst.get("desc", "")
                example = inst.get("example", "")

                alias_str = ""
                if aliases:
                    alias_str = f" {colored('(alias: ' + ', '.join(aliases) + ')', Colors.WHITE, dim=True)}"

                print(f"\n  {colored(cmd, Colors.YELLOW, bold=True)}{alias_str}")
                print(f"      {colored(desc, Colors.WHITE)}")
                if example:
                    print(f"      {colored(example, Colors.WHITE, dim=True)}")

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
