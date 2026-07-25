"""Thin interactive loop for the TopsailAI CLI.

The implementation logic has been split into sibling modules under
``cli_topsailai/``.  This module contains only the interactive prompt,
command dispatch loop, and ``main()`` entry point.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, List, Optional, Tuple

import cli_topsailai.state as state
from cli_topsailai.colors import Colors
from cli_topsailai.doc_scope import (
    build_doc_list,
    get_docs_dir,
    print_doc_table,
    resolve_doc,
)
from cli_topsailai.projects import (
    add_project,
    build_managed_project_list,
    delete_project_by_index,
    delete_project_by_path,
    load_projects,
    print_project_table,
)

__version__ = "0.1.0"

# Tracks whether the project scope is showing session-based projects
# ("sessions") or the managed project list ("managed").
_project_scope_mode: str = "sessions"


def _try_handle_project_subcommand(argv: Optional[List[str]]) -> Optional[int]:
    """Handle non-interactive ``project add|del|list`` CLI invocations.

    Returns an exit code when the subcommand is recognized and processed,
    otherwise ``None`` so normal interactive startup continues.
    """
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) < 1 or argv[0].lower() != "project":
        return None
    subcmd = argv[1].lower() if len(argv) > 1 else ""
    if subcmd == "list":
        projects = build_managed_project_list()
        if not projects:
            print(
                f"{Colors.YELLOW}[WARN] No managed projects found.{Colors.RESET}"
            )
            return 0
        print_project_table(projects)
        return 0
    if subcmd not in ("add", "del"):
        print(
            f"{Colors.RED}[ERROR] Unknown project subcommand: {subcmd!r}. "
            f"Use: topsailai project add <path> [name], "
            f"topsailai project del <path>, or topsailai project list{Colors.RESET}"
        )
        return 1
    if len(argv) < 3:
        print(
            f"{Colors.RED}[ERROR] Usage: topsailai project {subcmd} <path>{Colors.RESET}"
        )
        return 1
    raw_path = argv[2]
    if subcmd == "add":
        name = " ".join(argv[3:]).strip() or None
        if add_project(raw_path, name=name):
            print(f"{Colors.GREEN}[INFO] Project added: {raw_path}{Colors.RESET}")
            return 0
        return 1
    if delete_project_by_path(raw_path):
        return 0
    return 1


def _warn_deprecated(old_flag: str, new_cmd: str) -> None:
    """Print a deprecation warning for a legacy CLI option."""
    print(
        f"{Colors.YELLOW}[WARN] {old_flag} is deprecated and will be removed in a future release. "
        f"Use '{new_cmd}' instead.{Colors.RESET}",
        file=sys.stderr,
    )


def _handle_workspace_subcommand(_args: argparse.Namespace) -> int:
    """Handle the non-interactive ``workspace`` subcommand."""
    _print_workspace_table()
    return 0


def _handle_docs_list_subcommand(_args: argparse.Namespace) -> int:
    """Handle the non-interactive ``docs list`` subcommand."""
    docs = build_doc_list()
    print_doc_table(docs)
    return 0


def _handle_docs_read_subcommand(args: argparse.Namespace) -> int:
    """Handle the non-interactive ``docs read <name>`` subcommand."""
    name = args.name
    result = resolve_doc(name)
    if result["status"] == "not_found":
        print(f"Doc not found: {name}")
        return 1
    if result["status"] == "conflict":
        print(f"Ambiguous doc name: {name}")
        print("Please use the precise folder/document.md format:")
        for option in result["options"]:
            print(f"  {option}")
        return 1
    print(result["content"])
    return 0


def _handle_project_subcommand(args: argparse.Namespace) -> int:
    """Delegate project subcommands to the existing handler."""
    argv = ["project", args.project_subcommand]
    if args.project_path is not None:
        argv.append(args.project_path)
    if args.project_name is not None:
        argv.append(args.project_name)
    code = _try_handle_project_subcommand(argv)
    return 0 if code is None else code


def setup_signal_handlers() -> None:
    """Register SIGINT/SIGTERM handlers for graceful shutdown."""
    from cli_topsailai.process import signal_handler

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def get_prompt() -> str:
    """Generate dynamic prompt based on current scope."""
    if state.current_scope == "project":
        return f"\n{Colors.GREEN}[project]{Colors.RESET}> "
    if state.current_scope == "session" and state.current_session_id:
        return (
            f"\n{Colors.GREEN}[session:{state.current_session_id}]{Colors.RESET}> "
        )
    if state.current_scope == "doc" and state.current_doc_filename:
        return f"\n{Colors.GREEN}[doc:{state.current_doc_filename}]{Colors.RESET}> "
    if state.current_scope == "doc":
        return f"\n{Colors.GREEN}[doc]{Colors.RESET}> "
    return f"\n{Colors.GREEN}[workspace]{Colors.RESET}> "


def prompt_selection(
    files: List[dict], task_dir: str
) -> Tuple[str, Optional[Any]]:
    """
    Prompt user to select a file by number or enter a command.
    Returns (action, value).
    """
    from cli_topsailai.process import cleanup_children
    from cli_topsailai.yaml_commands import (
        find_yaml_command_for_help,
        handle_yaml_command,
        match_yaml_command,
    )
    from cli_topsailai.help_text import print_instruction_help

    _MAX_CONSECUTIVE_UNRECOGNIZED = 10
    _MAX_PROMPT_ITERATIONS = 100
    _consecutive_unrecognized = 0
    _iterations = 0

    while True:
        _iterations += 1
        if _iterations > _MAX_PROMPT_ITERATIONS:
            print(
                f"{Colors.RED}[ERROR] Maximum prompt iterations exceeded; "
                f"exiting to prevent an infinite loop.{Colors.RESET}"
            )
            return ("quit", None)
        try:
            prompt_text = get_prompt()
            # Some execution wrappers (e.g. uv run) strip ANSI escape
            # sequences from the prompt argument passed to input(), which
            # causes literal [32m/[0m markers to be displayed. Print the
            # colored prompt directly via stdout and call input() with an
            # empty prompt so the escapes are preserved.
            sys.stdout.write(prompt_text)
            sys.stdout.flush()
            user_input = input("").strip()
            if user_input:
                try:
                    import readline

                    readline.add_history(user_input)
                except (NameError, AttributeError, ImportError):
                    pass
                if state.history_manager is not None:
                    state.history_manager.append(
                        state.current_scope,
                        state.current_session_id or "",
                        user_input,
                    )

            if not user_input:
                continue
            lower_input = user_input.lower()

            if lower_input in ("q", "quit", "exit"):
                if state.current_scope == "doc":
                    return ("leave_scope", None)
                return ("quit", None)

            # Project scope: r/recent shows recent session/project history.
            # This must be checked before the global r/refresh binding.
            if state.current_scope == "project" and lower_input in ("r", "recent"):
                return ("show_recent_projects", None)

            if lower_input in ("r", "refresh", "/refresh"):
                return ("refresh", None)
            if lower_input.startswith("/clean") or lower_input.startswith("clean"):
                parts = user_input.split()
                if len(parts) == 1:
                    return ("clean", None)
                try:
                    indices = [int(p) - 1 for p in parts[1:]]
                    return ("clean_numbers", indices)
                except ValueError:
                    print(
                        f"{Colors.RED}[ERROR] Usage: /clean or /clean {{number}} "
                        f"[{{number}} ...]{Colors.RESET}"
                    )
                    continue

            if lower_input.startswith("/send") or lower_input.startswith("send"):
                return ("send", user_input)

            if lower_input in ("/retrieve", "retrieve"):
                return ("retrieve", None)

            if lower_input in ("/stream", "stream"):
                return ("stream", None)

            if state.current_scope == "workspace" and lower_input == "scopes":
                return ("scopes", None)

            if lower_input in ("/help", "help"):
                return ("help", None)

            if lower_input.startswith("/help "):
                keyword = user_input[6:].strip()
                return ("help", keyword)

            if lower_input.startswith("help "):
                keyword = user_input[5:].strip()
                return ("help", keyword)

            # Per-command help: /cmd -h or /cmd --help
            help_match = re.match(r"^(.*?)\s+(-h|--help)$", user_input)
            if help_match:
                base_cmd = help_match.group(1).strip()
                instruction = find_yaml_command_for_help(base_cmd)
                if instruction:
                    # Only treat as help when the command does not consume
                    # arbitrary args, otherwise --help may be intended for the
                    # underlying external command.
                    if "{args}" not in instruction.get("cmd", ""):
                        return ("help_cmd", instruction)

            # Scope switching: cd doc enters the documentation scope.
            cd_match = re.match(r"^/?cd\s+(.+)$", user_input)
            if cd_match:
                target = cd_match.group(1).strip().lower()
                if target in ("doc", "docs", "usage", "memo"):
                    return ("enter_doc", None)

            # Bare cd returns to workspace scope from doc scope.
            if state.current_scope == "doc" and lower_input in ("cd", "/cd"):
                return ("leave_scope", None)
            # Project scope: cd {session_id|number} enters session scope using
            # the displayed entries, matching the behavior of bare numbers.
            if state.current_scope == "project":
                cd_match = re.match(r"^/?cd\s+(.+)$", user_input)
                if cd_match:
                    arg = cd_match.group(1).strip()
                    if arg.isdigit():
                        idx = int(arg) - 1
                        if 0 <= idx < len(files):
                            session_id = files[idx].get("session_id")
                            if not session_id:
                                print(
                                    f"{Colors.RED}[ERROR] Selected entry has no "
                                    f"session ID.{Colors.RESET}"
                                )
                                continue
                            if session_id == "(temp)":
                                print(
                                    f"{Colors.RED}[ERROR] No session ID available "
                                    f"for entry {idx + 1}.{Colors.RESET}"
                                )
                                continue
                            return ("enter_session", session_id)
                        print(
                            f"{Colors.RED}[ERROR] Invalid number. "
                            f"Please enter 1-{len(files)}.{Colors.RESET}"
                        )
                        continue
                    # Non-numeric argument is treated as a literal session ID.
                    return ("enter_session", arg)

            # Managed project list commands (project scope only).
            if state.current_scope == "project":
                if lower_input in ("p", "projects"):
                    return ("show_managed_projects", None)
                if lower_input in ("r", "recent"):
                    return ("show_recent_projects", None)
                if lower_input.startswith("p ") or lower_input.startswith("/p "):
                    parts = user_input.split(None, 2)
                    subcmd = parts[1].lower() if len(parts) > 1 else ""
                    if subcmd == "add":
                        args = parts[2] if len(parts) > 2 else ""
                        return ("add_managed_project", args)
                    if subcmd == "del":
                        if len(parts) < 3:
                            print(
                                f"{Colors.RED}[ERROR] Usage: p del <number>{Colors.RESET}"
                            )
                            continue
                        return ("delete_managed_project", parts[2].strip())
                    print(
                        f"{Colors.RED}[ERROR] Unknown project sub-command: "
                        f"'{subcmd}'. Use p add or p del.{Colors.RESET}"
                    )
                    continue

            # Try YAML command matching first
            yaml_match = match_yaml_command(user_input, task_dir)
            if yaml_match:
                instruction, variables = yaml_match
                action = handle_yaml_command(instruction, variables)
                return (action, None)

            if (
                lower_input in ("/session", "session")
                or lower_input.startswith("/session ")
                or lower_input.startswith("session ")
            ):
                parts = user_input.split(None, 1)
                if len(parts) < 2:
                    print(
                        f"{Colors.RED}[ERROR] Usage: /session {{number|session_id}}{Colors.RESET}"
                    )
                    continue
                arg = parts[1].strip()
                if arg.isdigit():
                    num = int(arg)
                    if 1 <= num <= len(files):
                        return ("session", num - 1)
                    print(
                        f"{Colors.RED}[ERROR] Invalid number. "
                        f"Please enter 1-{len(files)}.{Colors.RESET}"
                    )
                else:
                    # Literal session ID: resolve (temp) marker and retrieve.
                    from cli_topsailai.log_files import _resolve_literal_session_id

                    session_id = _resolve_literal_session_id(arg)
                    if not session_id:
                        print(
                            f"{Colors.RED}[ERROR] Invalid session ID.{Colors.RESET}"
                        )
                        continue
                    return ("session_id", session_id)
                continue

            if (
                lower_input == "/agent"
                or lower_input.startswith("/agent ")
                or lower_input.startswith("agent ")
                or (state.current_scope == "project" and lower_input == "agent")
            ):
                parts = user_input.split(None, 1)
                if len(parts) < 2:
                    print(
                        f"{Colors.RED}[ERROR] Usage: /agent {{number}} or /agent {{folder}}{Colors.RESET}"
                    )
                    continue
                return ("agent", parts[1].strip())

            if (
                lower_input == "/resume"
                or lower_input.startswith("/resume ")
                or lower_input.startswith("resume ")
                or (state.current_scope == "project" and lower_input == "resume")
            ):
                parts = user_input.split(None, 1)
                if len(parts) < 2:
                    print(
                        f"{Colors.RED}[ERROR] Usage: /resume {{number}}{Colors.RESET}"
                    )
                    continue
                return ("resume", parts[1].strip())
            try:
                selected = int(user_input)
                if state.current_scope == "doc":
                    if 1 <= selected <= len(files):
                        return ("read_doc", selected - 1)
                    print(
                        f"{Colors.RED}[ERROR] Invalid number. "
                        f"Please enter 1-{len(files)}.{Colors.RESET}"
                    )
                    continue
                if 1 <= selected <= len(files):
                    if state.current_scope == "project":
                        session_id = files[selected - 1].get("session_id")
                        if not session_id:
                            print(
                                f"{Colors.RED}[ERROR] Selected entry has no "
                                f"session ID.{Colors.RESET}"
                            )
                            continue
                        return ("enter_session", session_id)
                    return ("watch", selected - 1)
                print(
                    f"{Colors.RED}[ERROR] Invalid number. "
                    f"Please enter 1-{len(files)}.{Colors.RESET}"
                )
            except ValueError:
                print(
                    f"{Colors.RED}[ERROR] Unknown command: '{user_input}'. "
                    f"Please enter a number, /refresh, /session {{number}}, "
                    f"/agent {{number|folder}}, /resume {{number}}, /clean, /send, /help, or 'q'.{Colors.RESET}"
                )
                _consecutive_unrecognized += 1
                if _consecutive_unrecognized >= _MAX_CONSECUTIVE_UNRECOGNIZED:
                    print(
                        f"{Colors.RED}[ERROR] Too many unrecognized commands; "
                        f"exiting to prevent an infinite loop.{Colors.RESET}"
                    )
                    return ("quit", None)

        except (EOFError, KeyboardInterrupt):
            print(f"\n{Colors.YELLOW}[INFO] Exiting...{Colors.RESET}")
            cleanup_children()
            return ("quit", None)


def _print_workspace_table() -> None:
    """Print the workspace task list and return.

    This helper is used by the ``-w`` / ``--workspace`` flag to display the
    same table that normally appears at the ``[workspace]>`` prompt without
    entering interactive mode.
    """
    from cli_topsailai.formatting import print_header, print_table
    from cli_topsailai.log_files import discover_log_files
    from cli_topsailai.paths import get_topsailai_home
    from cli_topsailai.session_info import enrich_files_with_session_names

    topsailai_home = get_topsailai_home()
    task_dir = os.path.join(topsailai_home, "workspace", "task")

    print_header("TopsailAI Task Watcher")
    print(f"{Colors.DIM}HOME: {topsailai_home}{Colors.RESET}")
    print(f"{Colors.DIM}DIR:  {task_dir}{Colors.RESET}")

    log_files = discover_log_files(task_dir)
    enrich_files_with_session_names(log_files)
    if log_files:
        print_table(log_files)
    else:
        print(f"\n{Colors.YELLOW}[WARN] No .stdout log files found in:{Colors.RESET}")
        print(f"  {task_dir}")


def main(argv: Optional[List[str]] = None) -> None:
    """Main entry point for the TopsailAI CLI."""
    global _project_scope_mode
    parser = argparse.ArgumentParser(
        prog="topsailai.py",
        description="TopsailAI interactive CLI",
        add_help=False,
    )
    parser.add_argument(
        "-h", "--help",
        action="store_true",
        dest="help",
        help="show this help message and exit",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        dest="version",
        help="show program's version number and exit",
    )
    parser.add_argument(
        "--tui", "--runtime-tui",
        action="store_true",
        dest="runtime_tui",
        help="use the two-pane curses UI when entering the runtime scope",
    )
    parser.add_argument(
        "--tail-lines",
        type=int,
        default=100,
        dest="tail_lines",
        metavar="N",
        help="number of recent log lines to echo on startup in runtime mode (default: 100)",
    )
    parser.add_argument(
        "--agent-mode",
        type=str,
        choices=["raw", "dtach", "tmux"],
        default="dtach",
        dest="agent_mode",
        metavar="MODE",
        help="how to launch agent processes: raw (direct), dtach, or tmux (default: dtach)",
    )
    # Deprecated non-interactive options. They are kept for backward
    # compatibility and route to the new subcommand behavior with a warning.
    parser.add_argument(
        "-w", "--workspace",
        action="store_true",
        dest="workspace",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--list-docs",
        action="store_true",
        dest="list_docs",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--read-doc",
        type=str,
        default=None,
        dest="read_doc",
        metavar="NAME",
        help=argparse.SUPPRESS,
    )

    subparsers = parser.add_subparsers(dest="command", help="non-interactive commands")

    workspace_parser = subparsers.add_parser(
        "workspace",
        help="display the workspace task list and exit",
        add_help=False,
    )
    workspace_parser.set_defaults(func=_handle_workspace_subcommand)

    docs_parser = subparsers.add_parser(
        "docs",
        help="documentation commands",
        add_help=False,
    )
    docs_subparsers = docs_parser.add_subparsers(dest="docs_command")
    docs_list_parser = docs_subparsers.add_parser(
        "list",
        help="list documentation files and exit",
        add_help=False,
    )
    docs_list_parser.set_defaults(func=_handle_docs_list_subcommand)
    docs_read_parser = docs_subparsers.add_parser(
        "read",
        help="read a documentation file by folder/name.md or name and exit",
        add_help=False,
    )
    docs_read_parser.add_argument("name", help="documentation file name")
    docs_read_parser.set_defaults(func=_handle_docs_read_subcommand)

    project_parser = subparsers.add_parser(
        "project",
        help="manage the project list",
        add_help=False,
    )
    project_subparsers = project_parser.add_subparsers(dest="project_subcommand")
    project_list_parser = project_subparsers.add_parser(
        "list",
        help="list managed projects",
        add_help=False,
    )
    project_list_parser.set_defaults(func=_handle_project_subcommand)
    project_add_parser = project_subparsers.add_parser(
        "add",
        help="add a project to the managed list",
        add_help=False,
    )
    project_add_parser.add_argument("project_path", help="project path")
    project_add_parser.add_argument(
        "project_name",
        nargs="?",
        default=None,
        help="optional project name",
    )
    project_add_parser.set_defaults(func=_handle_project_subcommand)
    project_del_parser = project_subparsers.add_parser(
        "del",
        help="remove a project from the managed list",
        add_help=False,
    )
    project_del_parser.add_argument("project_path", help="project path")
    project_del_parser.set_defaults(func=_handle_project_subcommand)

    # Be tolerant of unknown arguments so tests that invoke main() with
    # arbitrary fake argv do not crash. Only help/version trigger an exit.
    try:
        args, remainder = parser.parse_known_args(argv)
    except SystemExit:
        # argparse may exit on invalid subcommand choices when pytest passes
        # its own positional arguments. Treat this as an interactive run.
        args = argparse.Namespace(
            help=False,
            version=False,
            runtime_tui=False,
            tail_lines=100,
            agent_mode="dtach",
            workspace=False,
            list_docs=False,
            read_doc=None,
            command=None,
            docs_command=None,
            project_subcommand=None,
        )
        remainder = []
    if args.help:
        parser.print_help()
        print("\nGlobal options:")
        print("  --tui, --runtime-tui     Use the two-pane curses UI in runtime scope")
        print("  --tail-lines N           Number of recent log lines on runtime startup")
        print("  --agent-mode MODE        raw | dtach | tmux")
        sys.exit(0)
    if args.version:
        print(f"{parser.prog} {__version__}")
        sys.exit(0)

    # Backward-compatible deprecated options.
    if args.workspace:
        _warn_deprecated("--workspace", "topsailai workspace")
        sys.exit(_handle_workspace_subcommand(args))
    if args.list_docs:
        _warn_deprecated("--list-docs", "topsailai docs list")
        sys.exit(_handle_docs_list_subcommand(args))
    if args.read_doc:
        _warn_deprecated("--read-doc", "topsailai docs read <name>")
        sys.exit(_handle_docs_read_subcommand(args))

    # Non-interactive subcommand dispatch.
    if getattr(args, "func", None):
        sys.exit(args.func(args))

    # No recognized subcommand: ignore any unknown positional arguments and
    # start the interactive session. This preserves the pre-refactor behavior
    # where pytest-injected sys.argv identifiers did not cause a crash.
    _ = remainder
    # Heavy imports are deferred until after --help / --version are handled.
    from cli_topsailai.cleaning import clean_by_numbers, clean_expired_files
    from cli_topsailai.completer import setup_tab_completion
    from cli_topsailai.formatting import print_header, print_table
    from cli_topsailai.help_text import print_help, print_instruction_help, print_scopes
    from cli_topsailai.history import HistoryManager, load_readline_history
    from cli_topsailai.log_files import discover_log_files
    from cli_topsailai.paths import get_topsailai_home
    from cli_topsailai.process import cleanup_children
    from cli_topsailai.project_scope import (
        build_managed_project_list,
        build_project_list,
        launch_agent_in_folder,
        print_managed_project_table,
        print_project_table,
        resolve_agent_folder,
        resume_session,
    )
    from cli_topsailai.retrieve import retrieve_session
    from cli_topsailai.session_info import enrich_files_with_session_names
    from cli_topsailai.streaming import handle_send_command, stream_file
    from cli_topsailai.yaml_commands import load_yaml_commands

    setup_signal_handlers()

    # Load YAML commands
    state.yaml_commands = load_yaml_commands()

    topsailai_home = get_topsailai_home()
    task_dir = os.path.join(topsailai_home, "workspace", "task")

    # Initialize command history
    history_path = os.path.join(topsailai_home, ".history.jsonl")
    state.history_manager = HistoryManager(history_path)
    state.history_manager.load_all()
    load_readline_history(
        state.history_manager, state.current_scope, state.current_session_id
    )
    setup_tab_completion()

    print_header("TopsailAI Task Watcher")
    print(f"{Colors.DIM}HOME: {topsailai_home}{Colors.RESET}")
    print(f"{Colors.DIM}DIR:  {task_dir}{Colors.RESET}")

    def _print_refresh_item(file_info: dict) -> None:
        """Print a single file as it is discovered during refresh."""
        session = file_info.get("session_id") or "-"
        filename = file_info.get("filename", "")
        print(
            f"{Colors.DIM}  Found {Colors.RESET}{session}"
            f"{Colors.DIM} {filename}{Colors.RESET}"
        )
        sys.stdout.flush()

    print(f"{Colors.DIM}Refreshing list...{Colors.RESET}")
    sys.stdout.flush()
    log_files = discover_log_files(task_dir, on_item=_print_refresh_item)
    enrich_files_with_session_names(log_files)
    project_entries: List[Dict[str, Any]] = []
    managed_project_entries: List[Dict[str, Any]] = []
    doc_entries: List[Dict[str, Any]] = []

    def _refresh_workspace() -> None:
        nonlocal log_files
        print(f"{Colors.DIM}Refreshing list...{Colors.RESET}")
        sys.stdout.flush()
        log_files = discover_log_files(task_dir, on_item=_print_refresh_item)
        enrich_files_with_session_names(log_files)
        print_table(log_files)

    def _refresh_managed_projects() -> None:
        nonlocal managed_project_entries
        managed_project_entries = build_managed_project_list()
        print_managed_project_table(managed_project_entries)

    def _refresh_project() -> None:
        nonlocal project_entries
        project_entries = build_project_list(limit=10)
        if project_entries:
            print_project_table(project_entries)
        else:
            print(
                f"\n{Colors.YELLOW}[WARN] No sessions with project_workspace found.{Colors.RESET}"
            )

    def _refresh_project_scope() -> None:
        """Refresh whichever project-scope view is currently active."""
        if _project_scope_mode == "managed":
            _refresh_managed_projects()
        else:
            _refresh_project()

    def _handle_add_managed_project(args_str: str) -> None:
        """Parse arguments and add a managed project, prompting when needed."""
        global _project_scope_mode
        parts = args_str.strip().split(None, 1)
        if not parts:
            raw_path = input("Project path: ").strip()
        else:
            raw_path = parts[0].strip()
        if not raw_path:
            print(f"{Colors.RED}[ERROR] Project path is required.{Colors.RESET}")
            return
        name = parts[1].strip() if len(parts) > 1 else None
        if not name:
            name = input("Project name (optional): ").strip() or None
        if add_project(raw_path, name=name):
            print(f"{Colors.GREEN}[INFO] Project added.{Colors.RESET}")
            _project_scope_mode = "managed"
            _refresh_managed_projects()
        else:
            print(f"{Colors.RED}[ERROR] Failed to add project.{Colors.RESET}")

    def _handle_delete_managed_project(args_str: str) -> None:
        """Delete a managed project by its displayed row number."""
        global _project_scope_mode
        args_str = args_str.strip()
        if not args_str:
            print(
                f"{Colors.RED}[ERROR] Missing project number. Usage: p del <number>{Colors.RESET}"
            )
            return
        try:
            index = int(args_str)
        except ValueError:
            print(
                f"{Colors.RED}[ERROR] Invalid project number: '{args_str}'.{Colors.RESET}"
            )
            return
        if delete_project_by_index(index):
            print(f"{Colors.GREEN}[INFO] Project deleted.{Colors.RESET}")
            _project_scope_mode = "managed"
            _refresh_managed_projects()
        else:
            print(f"{Colors.RED}[ERROR] Failed to delete project.{Colors.RESET}")

    def _refresh_doc() -> None:
        nonlocal doc_entries
        doc_entries = build_doc_list()
        print_doc_table(doc_entries)

    if state.current_scope == "project":
        _project_scope_mode = "sessions"
        _refresh_project()
    elif state.current_scope == "doc":
        _refresh_doc()
    else:
        if log_files:
            print_table(log_files)
        else:
            print(f"\n{Colors.YELLOW}[WARN] No .stdout log files found in:{Colors.RESET}")
            print(f"  {task_dir}")
    try:
        while state.running:
            if state.current_scope == "project":
                active_items = (
                    managed_project_entries
                    if _project_scope_mode == "managed"
                    else project_entries
                )
            elif state.current_scope == "doc":
                active_items = doc_entries
            else:
                active_items = log_files
            previous_scope = state.current_scope
            action, value = prompt_selection(active_items, task_dir)

            if action == "yaml_handled":
                if state.current_scope != previous_scope:
                    if state.current_scope == "project":
                        _project_scope_mode = "sessions"
                        _refresh_project()
                    elif state.current_scope == "doc":
                        _refresh_doc()
                    elif state.current_scope == "workspace":
                        _refresh_workspace()
                continue

            if action == "quit":
                break

            if action == "refresh":
                if state.current_scope == "project":
                    _refresh_project_scope()
                elif state.current_scope == "doc":
                    _refresh_doc()
                else:
                    _refresh_workspace()
                continue

            if action == "help":
                print_help(state.yaml_commands, state.current_scope, keyword=value)
                continue

            if action == "scopes":
                print_scopes()
                continue

            if action == "help_cmd":
                print_instruction_help(value)
                continue

            if action == "clean":
                if state.current_scope == "project":
                    print(
                        f"\n{Colors.YELLOW}[INFO] /clean is not available in project scope.{Colors.RESET}"
                    )
                else:
                    clean_expired_files(task_dir, log_files)
                    print(f"\n{Colors.DIM}Refreshing file list...{Colors.RESET}")
                    _refresh_workspace()
                continue

            if action == "clean_numbers":
                if state.current_scope == "project":
                    print(
                        f"\n{Colors.YELLOW}[INFO] /clean is not available in project scope.{Colors.RESET}"
                    )
                else:
                    clean_by_numbers(task_dir, log_files, value)
                    print(f"\n{Colors.DIM}Refreshing file list...{Colors.RESET}")
                    _refresh_workspace()
                continue

            if action == "send":
                # /send operates on discovered log files. In project scope refresh
                # workspace files first so numeric targets resolve correctly.
                if state.current_scope == "project":
                    _refresh_workspace()
                handle_send_command(value, task_dir, log_files)
                continue

            if action == "agent":
                if state.current_scope == "project":
                    active_entries = (
                        managed_project_entries
                        if _project_scope_mode == "managed"
                        else project_entries
                    )
                else:
                    active_entries = log_files
                folder = resolve_agent_folder(value, active_entries)
                if folder is None:
                    print(
                        f"\n{Colors.RED}[ERROR] Invalid number or folder: '{value}'. "
                        f"Use /agent {{number}} or /agent {{folder}}.{Colors.RESET}"
                    )
                    continue
                launch_agent_in_folder(folder, agent_mode=args.agent_mode)
                continue

            if action == "resume":
                if state.current_scope != "project":
                    print(
                        f"\n{Colors.RED}[ERROR] /resume is only available in project scope.{Colors.RESET}"
                    )
                    continue
                resume_session(value, project_entries, agent_mode=args.agent_mode)
                continue

            if action == "session":
                if state.current_scope == "project" and _project_scope_mode == "managed":
                    print(
                        f"\n{Colors.YELLOW}[INFO] /session is not available for managed projects. "
                        f"Use /agent {{number}} to launch an agent.{Colors.RESET}"
                    )
                    continue
                active_entries = (
                    project_entries
                    if state.current_scope == "project"
                    else log_files
                )
                selected_file = active_entries[value]
                session_id = selected_file.get("session_id")
                if not session_id or session_id == "(temp)":
                    print(
                        f"{Colors.RED}[ERROR] No session ID available for this file.{Colors.RESET}"
                    )
                    continue
                retrieve_session(session_id, max_chars=1000)
                continue

            if action == "session_id":
                retrieve_session(value, max_chars=1000)
                continue

            if action == "enter_session":
                state.current_scope = "session"
                state.current_session_id = value
                print(
                    f"\n{Colors.GREEN}[INFO] Entered session scope: {value}{Colors.RESET}"
                )
                continue

            if action == "enter_doc":
                state.current_scope = "doc"
                state.current_doc_filename = None
                print(
                    f"\n{Colors.GREEN}[INFO] Entered doc scope. Docs under {get_docs_dir()}{Colors.RESET}"
                )
                _refresh_doc()
                continue

            if action == "read_doc":
                selected_doc = doc_entries[value]
                rel_path = selected_doc["rel_path"]
                state.current_doc_filename = rel_path
                result = resolve_doc(rel_path)
                if result["status"] == "ok":
                    print(f"\n{Colors.CYAN}{'=' * 80}{Colors.RESET}")
                    print(f"{Colors.BOLD}{Colors.CYAN}  {result['rel_path']}{Colors.RESET}")
                    print(f"{Colors.CYAN}{'=' * 80}{Colors.RESET}")
                    print(result["content"])
                elif result["status"] == "conflict":
                    print(
                        f"\n{Colors.YELLOW}[WARN] '{rel_path}' matches multiple docs. "
                        f"Please use the exact folder/document.md format:{Colors.RESET}"
                    )
                    for option in result["options"]:
                        print(f"  - {option}")
                else:
                    print(
                        f"\n{Colors.RED}[ERROR] Doc not found: {rel_path}{Colors.RESET}"
                    )
                continue

            if action == "leave_scope":
                if state.current_scope == "doc":
                    state.current_scope = "workspace"
                    state.current_doc_filename = None
                    print(
                        f"\n{Colors.GREEN}[INFO] Returned to workspace scope.{Colors.RESET}"
                    )
                    _refresh_workspace()
                continue

            if action == "watch":
                if state.current_scope == "project" and _project_scope_mode == "managed":
                    print(
                        f"\n{Colors.YELLOW}[INFO] Watching a log file is not available for managed projects. "
                        f"Use /agent {{number}} to launch an agent.{Colors.RESET}"
                    )
                    continue
                active_entries = (
                    project_entries
                    if state.current_scope == "project"
                    else log_files
                )
                selected_file = active_entries[value]
                session_id = selected_file.get("session_id")
                stdout_path = selected_file.get("path")
                file_pid = selected_file.get("pid")
                if session_id == "(temp)":
                    session_id = "topsailai"
                stream_file(
                    selected_file["path"],
                    task_dir=task_dir,
                    log_files=log_files,
                    default_session_id=session_id,
                    default_stdout_path=stdout_path,
                    default_pid=file_pid,
                    runtime_raw=not args.runtime_tui,
                    tail_lines=args.tail_lines,
                )
                if state.current_scope == "project":
                    _refresh_project_scope()
                else:
                    _refresh_workspace()
                continue

            if action == "show_managed_projects":
                _project_scope_mode = "managed"
                _refresh_managed_projects()
                continue

            if action == "show_recent_projects":
                _project_scope_mode = "sessions"
                _refresh_project()
                continue

            if action == "add_managed_project":
                _handle_add_managed_project(value)
                continue

            if action == "delete_managed_project":
                _handle_delete_managed_project(value)
                continue
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}[INFO] Interrupted by user.{Colors.RESET}")
    finally:
        cleanup_children()

    print(f"\n{Colors.CYAN}Goodbye!{Colors.RESET}\n")
