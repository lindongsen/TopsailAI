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
    get_usage_docs_dir,
    print_doc_table,
    read_doc_file,
)

__version__ = "0.1.0"

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
                if target in ("doc", "docs", "usage"):
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

def main(argv: Optional[List[str]] = None) -> None:
    """Main entry point for the TopsailAI CLI."""
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
        "-r", "--runtime-raw",
        action="store_true",
        dest="runtime_raw",
        help="use raw curses-free mode when entering the runtime scope (default)",
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
        "--list-docs",
        action="store_true",
        dest="list_docs",
        help="list usage documentation files and exit",
    )
    parser.add_argument(
        "--read-doc",
        type=str,
        default=None,
        dest="read_doc",
        metavar="NAME",
        help="read a usage documentation file by name and exit",
    )

    # Be tolerant of unknown arguments so tests that invoke main() with
    # arbitrary fake argv do not crash. Only help/version trigger an exit.
    args, _ = parser.parse_known_args(argv)
    if args.help:
        parser.print_help()
        sys.exit(0)
    if args.version:
        print(f"{parser.prog} {__version__}")
        sys.exit(0)
    if args.list_docs:
        docs = build_doc_list()
        print_doc_table(docs)
        sys.exit(0)
    if args.read_doc:
        content = read_doc_file(args.read_doc)
        if content is None:
            print(f"Usage doc not found: {args.read_doc}")
            sys.exit(1)
        print(content)
        sys.exit(0)

    # Heavy imports are deferred until after --help / --version are handled.
    from cli_topsailai.cleaning import clean_by_numbers, clean_expired_files
    from cli_topsailai.completer import setup_tab_completion
    from cli_topsailai.formatting import print_header, print_table
    from cli_topsailai.help_text import print_help, print_instruction_help
    from cli_topsailai.history import HistoryManager, load_readline_history
    from cli_topsailai.log_files import discover_log_files
    from cli_topsailai.paths import get_topsailai_home
    from cli_topsailai.process import cleanup_children
    from cli_topsailai.project_scope import (
        build_project_list,
        launch_agent_in_folder,
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

    def _refresh_workspace() -> None:
        nonlocal log_files
        print(f"{Colors.DIM}Refreshing list...{Colors.RESET}")
        sys.stdout.flush()
        log_files = discover_log_files(task_dir, on_item=_print_refresh_item)
        enrich_files_with_session_names(log_files)
        print_table(log_files)

    def _refresh_project() -> None:
        nonlocal project_entries
        project_entries = build_project_list(limit=10)
        if project_entries:
            print_project_table(project_entries)
        else:
            print(
                f"\n{Colors.YELLOW}[WARN] No sessions with project_workspace found.{Colors.RESET}"
            )

    doc_entries: List[Dict[str, Any]] = []

    def _refresh_doc() -> None:
        nonlocal doc_entries
        doc_entries = build_doc_list()
        if doc_entries:
            print_doc_table(doc_entries)
        else:
            print(
                f"\n{Colors.YELLOW}[WARN] No usage documentation files found.{Colors.RESET}"
            )

    if state.current_scope == "project":
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
                active_items = project_entries
            elif state.current_scope == "doc":
                active_items = doc_entries
            else:
                active_items = log_files
            previous_scope = state.current_scope
            action, value = prompt_selection(active_items, task_dir)

            if action == "yaml_handled":
                if state.current_scope != previous_scope:
                    if state.current_scope == "project":
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
                    _refresh_project()
                elif state.current_scope == "doc":
                    _refresh_doc()
                else:
                    _refresh_workspace()
                continue

            if action == "help":
                print_help(state.yaml_commands, state.current_scope, keyword=value)
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
                active_entries = (
                    project_entries
                    if state.current_scope == "project"
                    else log_files
                )
                folder = resolve_agent_folder(value, active_entries)
                if folder is None:
                    print(
                        f"\n{Colors.RED}[ERROR] Invalid number or folder: '{value}'. "
                        f"Use /agent {{number}} or /agent {{folder}}.{Colors.RESET}"
                    )
                    continue
                launch_agent_in_folder(folder)
                continue

            if action == "resume":
                if state.current_scope != "project":
                    print(
                        f"\n{Colors.RED}[ERROR] /resume is only available in project scope.{Colors.RESET}"
                    )
                    continue
                resume_session(value, project_entries)
                continue

            if action == "session":
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
                    f"\n{Colors.GREEN}[INFO] Entered doc scope. Usage docs under {get_usage_docs_dir()}{Colors.RESET}"
                )
                _refresh_doc()
                continue

            if action == "read_doc":
                selected_doc = doc_entries[value]
                filename = selected_doc["filename"]
                state.current_doc_filename = filename
                content = read_doc_file(filename)
                if content is None:
                    print(
                        f"\n{Colors.RED}[ERROR] Could not read usage doc: {filename}{Colors.RESET}"
                    )
                else:
                    print(f"\n{Colors.CYAN}{'=' * 80}{Colors.RESET}")
                    print(f"{Colors.BOLD}{Colors.CYAN}  {filename}{Colors.RESET}")
                    print(f"{Colors.CYAN}{'=' * 80}{Colors.RESET}")
                    print(content)
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
                active_entries = (
                    project_entries
                    if state.current_scope == "project"
                    else log_files
                )
                selected_file = active_entries[value]
                session_id = selected_file.get("session_id")
                stdout_path = selected_file.get("path")
                if session_id == "(temp)":
                    session_id = "topsailai"
                runtime_raw = not args.runtime_tui
                stream_file(
                    selected_file["path"],
                    task_dir=task_dir,
                    log_files=log_files,
                    default_session_id=session_id,
                    default_stdout_path=stdout_path,
                    runtime_raw=runtime_raw,
                    tail_lines=args.tail_lines,
                )
                print(f"\n{Colors.DIM}Refreshing list...{Colors.RESET}")
                if state.current_scope == "project":
                    _refresh_project()
                else:
                    _refresh_workspace()
                continue
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}[INFO] Interrupted by user.{Colors.RESET}")
    finally:
        cleanup_children()

    print(f"\n{Colors.CYAN}Goodbye!{Colors.RESET}\n")
