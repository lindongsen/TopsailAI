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


def print_scopes() -> None:
    """Display detailed introductions for every interactive CLI scope."""
    width = 80
    scopes = [
        (
            "workspace",
            "The default task-watcher scope. It lists discovered session and task log files so you can monitor and manage work across the current TopsailAI home.",
            "Select a numbered log, retrieve session context, refresh or clean the task list, send messages, launch agents, enter project or doc scope, and show help.",
        ),
        (
            "runtime",
            "The live log-streaming scope entered after selecting a workspace log file. It follows output for the watched session or task while keeping session messaging available.",
            "Send process messages with /send, inject agent2llm context with /ctx.btw, print session metadata with /meta, send control requests with /control, recall previous and next runtime messages with the Up/Down arrow keys, show help, or leave the stream with q or quit.",
        ),
        (
            "project",
            "A navigation scope that lists recent sessions with recorded project workspaces, including their running or idle status. It also supports an independently managed project list via the p command.",
            "Select or cd to a session, retrieve session context, refresh the list, launch or resume an agent in a project workspace, switch between recent sessions (r) and managed projects (p), manage projects with p/p add/p del, show help, or use cd to return to workspace scope.",
        ),
        (
            "session",
            "A focused scope for one session ID, used to inspect its context and interact with that session without selecting it repeatedly.",
            "Retrieve or stream session data, send runtime messages, add agent2llm or persistent context messages, use configured session commands, show help, or use cd to return to workspace scope.",
        ),
        (
            "doc",
            "A documentation browser for Markdown files grouped under the single-level folders in docs/.",
            "Select a numbered document to read it, refresh the documentation list, show help, or use q, quit, or cd to return to workspace scope.",
        ),
    ]

    cprint("=" * width, color=Colors.CYAN, bold=True)
    cprint("  TopsailAI - Scope Guide", color=Colors.CYAN, bold=True)
    cprint("=" * width, color=Colors.CYAN, bold=True)
    for name, introduction, actions in scopes:
        print(f"\n  {colored(name, Colors.YELLOW, bold=True)}")
        print(f"      {colored(introduction, Colors.WHITE)}")
        print(f"      {colored('Available actions: ' + actions, Colors.WHITE, dim=True)}")
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
            "cmd": "!<command>",
            "desc": "Execute a shell command line (like /git).",
            "example": "Example: !git status",
            "scopes": ["workspace", "runtime", "project", "session", "doc"],
        },
        {
            "cmd": "<number>",
            "desc": "Select a log file by its number to stream output in real-time.",
            "example": "Example: 3",
            "scopes": ["workspace"],
        },
        {
            "cmd": "<number>",
            "desc": "Enter the selected session by its number.",
            "example": "Example: 3",
            "scopes": ["project"],
        },
        {
            "cmd": "<number>",
            "desc": "Read the selected documentation file.",
            "example": "Example: 3",
            "scopes": ["doc"],
        },
        {
            "cmd": "/refresh",
            "desc": "Re-scan the task directory and refresh the file list.",
            "example": "",
            "scopes": ["workspace", "project", "doc"],
        },
        {
            "cmd": "/session <number>",
            "desc": "Retrieve detailed messages for the session ID of the selected file.",
            "example": "Example: /session 3",
            "scopes": ["workspace"],
        },
        {
            "cmd": "/git.status",
            "desc": "Alias for '/git status'. Show git status for the project workspace of the current session.",
            "example": "",
            "scopes": ["session", "runtime"],
        },
        {
            "cmd": "/git.diff",
            "desc": "Alias for '/git diff'. Show git diff for the project workspace of the current session.",
            "example": "",
            "scopes": ["session", "runtime"],
        },
        {
            "cmd": "/resume <number>",
            "desc": "Resume an idle session in its project workspace. In workspace scope the number refers to the task list; in project scope it refers to the project session list. The selected session must not be running. You will be prompted to choose an agent driver (default: topsailai_agent_plan_tasks). Use `--agent-mode raw|dtach|tmux` to control how the resumed agent process is launched (default: dtach).",
            "example": "Example: /resume 3  or  topsailai --agent-mode tmux",
            "scopes": ["workspace", "project"],
        },
        {
            "cmd": "/git <subcommand> [args...]",
            "desc": "Run an arbitrary git command in the project workspace of the current session.",
            "example": "Example: /git status  or  /git diff --cached  or  /git log --oneline -10",
            "scopes": ["session", "runtime"],
        },
        {
            "cmd": "/clean [<number> [<number>...]]",
            "desc": "Clean up .stdout files. Without arguments: deletes idle files older than 3 days. With numbers: deletes the specified files by their list number.",
            "example": "Example: /clean 3 5 7",
            "scopes": ["workspace"],
        },
        {
            "cmd": "/agent <number|folder>",
            "desc": "Launch an agent. In workspace scope, `agent` or `/agent` (no arguments) runs the YAML-configured agent command. `agent <number|folder>` or `/agent <number|folder>` changes to the selected project workspace folder and launches topsailai_launch_agent; the number refers to the log file list in workspace scope or the project session list in project scope. An absolute/relative folder path can also be used. Use `--agent-mode raw|dtach|tmux` to control how the agent process is launched (default: dtach).",
            "example": "Example: agent  or  /agent  or  /agent 3  or  /agent /path/to/project  or  topsailai --agent-mode tmux",
            "scopes": ["workspace", "project"],
        },
        {
            "cmd": "/models [current|clear]",
            "desc": "List and select model configurations, show the effective selection, or clear the selection for the current workspace or project scope. Project selections override the workspace default for subsequent agent launches and resumes.",
            "example": "Example: /models  or  /models current  or  /models clear",
            "scopes": ["workspace", "project"],
        },
        {
            "cmd": "p  or  projects",
            "desc": "Switch to the managed project list. The list is stored in .projects.jsonl under TOPSAILAI_HOME and is sorted oldest-first. In workspace scope this view only accepts r (return to task list), p (refresh list), q (quit), cd (return to task list), and p agent <number>.",
            "example": "Example: p",
            "scopes": ["workspace", "project"],
        },
        {
            "cmd": "r [limit]  or  recent [limit]",
            "desc": "Refresh the recent project session list. If `[limit]` is provided, update the maximum number of records shown (default 30).",
            "example": "Example: r  or  r 30",
            "scopes": ["project"],
        },
        {
            "cmd": "p add [path] [name]",
            "desc": "Add a project to the managed project list. The path must exist and be a directory. If path or name is omitted, you will be prompted interactively.",
            "example": "Example: p add /work/my-project my-project",
            "scopes": ["workspace", "project"],
        },
        {
            "cmd": "p del <number>",
            "desc": "Delete the managed project at the displayed row number. You will be asked for y/N confirmation. Only the registry entry is removed; the project folder on disk is not deleted.",
            "example": "Example: p del 2",
            "scopes": ["workspace", "project"],
        },
        {
            "cmd": "p agent <number>",
            "desc": "Launch an agent in the managed project at the displayed row number. This command is only available when the workspace is showing the managed project list (after typing `p` or `projects`). The number is the 1-based row number shown in the managed project table. Use `--agent-mode raw|dtach|tmux` to control how the agent process is launched (default: dtach).",
            "example": "Example: p agent 2  or  topsailai --agent-mode tmux",
            "scopes": ["workspace"],
        },
        {
            "cmd": "project add <path> [name]",
            "desc": "Non-interactive: add a project path to the managed project list stored in .projects.jsonl under TOPSAILAI_HOME. Duplicate paths are rejected.",
            "example": "Example: topsailai project add /work/my-project my-project",
            "scopes": ["cli"],
        },
        {
            "cmd": "project del <path>",
            "desc": "Non-interactive: remove a project path from the managed project list. Only the registry entry is removed; the project folder on disk is not deleted.",
            "example": "Example: topsailai project del /work/my-project",
            "scopes": ["cli"],
        },
        {
            "cmd": "project list",
            "desc": "Non-interactive: list all managed projects stored in .projects.jsonl under TOPSAILAI_HOME. Output includes row number, name, path, and creation time.",
            "example": "Example: topsailai project list",
            "scopes": ["cli"],
        },
        {
            "cmd": "/send [session_id_or_index] [message...]",
            "desc": "Send a message to a running session through its named pipe. In session scope, omit the session id. If no message is provided, enter multi-line input mode (finish with EOF). While streaming a log, /send defaults to the watched session.",
            "example": "Example: /send 1 hello  or  /send my-session hello  or  while streaming: /send hello",
            "scopes": ["session", "runtime"],
        },
        {
            "cmd": "/ctx.btw [message...]",
            "desc": "Inject a by-the-way message into the agent2llm runtime context of the watched session. In session scope, omit the session id. If no message is provided, enter multi-line input mode (finish with EOF). While streaming a log, /ctx.btw defaults to the watched session.",
            "example": "Example: /ctx.btw remember to check the logs  or  while streaming: /ctx.btw hello",
            "scopes": ["session", "runtime"],
        },
        {
            "cmd": "/meta",
            "desc": "Print the metadata file for the watched parent session. Task logs use their parent session PID rather than the child task PID.",
            "example": "Example: /meta",
            "scopes": ["runtime"],
        },
        {
            "cmd": "/control <command> [args_json]  |  /control.<subcommand>",
            "desc": "Send a control request to the current session through its UDS control socket. Supported commands: call_instruction, hard_interrupt, soft_interrupt, clear_interrupt, get_runtime_messages. args_json is an optional JSON object; defaults to {}. Fixed actions can be invoked without JSON via /control.hard_interrupt, /control.soft_interrupt [reason], /control.clear_interrupt, /control.get_runtime_messages. /control.call_instruction without a JSON payload starts an interactive wizard that prompts for instruction, args, and kwargs.",
            "example": "Example: /control.hard_interrupt  or  /control.soft_interrupt timeout  or  /control.call_instruction  or  /control call_instruction {\"instruction\":\"ctx.history\",\"args\":[\"arg1\"],\"kwargs\":{\"key\":\"value\"}}",
            "scopes": ["session", "runtime"],
        },
        {
            "cmd": "<free-form text>",
            "desc": "While streaming a log, any input that is not a recognized command prompts 'Send as message? [y/N]'. Answering yes sends the input to the watched session via /send.",
            "example": "Example: hello  (then answer y to send it)",
            "scopes": ["runtime"],
        },
        {
            "cmd": "Up / Down arrows",
            "desc": "While streaming a log, press Up to recall the previous runtime message and Down to move to the next newer message. When at the newest end, Down returns to an empty prompt.",
            "example": "",
            "scopes": ["runtime"],
        },
        {
            "cmd": "/help [<keyword>]",
            "desc": "Display this help message with all available commands. Use /help <keyword> to search commands by name, alias, or description.",
            "example": "Example: /help ctx",
        },
        {
            "cmd": "scopes",
            "desc": "Display detailed introductions and available actions for all CLI scopes.",
            "example": "",
            "scopes": ["workspace"],
        },
        {
            "cmd": "cd project",
            "desc": "Enter project scope to show recent records (default limit 30).",
            "example": "",
            "scopes": ["workspace"],
        },
        {
            "cmd": "cd doc  or  cd docs  or  cd <folder>",
            "desc": "Enter doc scope to list documentation files under docs/ (grouped by single-level subfolders such as usage/ and memo/). The folder name can also be used as a shortcut (e.g., cd usage or cd memo).",
            "example": "",
            "scopes": ["workspace"],
        },
        {
            "cmd": "q  or  quit  or  cd",
            "desc": "Exit the current scope. From session, runtime, project, or doc scope, return to workspace scope.",
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
        builtin_matches = [
            c
            for c in commands
            if current_scope
            in c.get("scopes", ["workspace", "project", "session", "runtime"])
        ]

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
