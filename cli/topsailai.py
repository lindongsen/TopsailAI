#!/usr/bin/env python3
"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-05-17
  Purpose: Watch log files in {TOPSAILAI_HOME}/workspace/task/ with interactive selection.
           Lists .stdout log files, shows process ownership, and streams selected file.
           Supports /refresh, /session {number}, /clean, and /help commands.
           Supports loading additional commands from topsailai.yaml with scope awareness.
           Ensures all child processes are cleaned up on exit.
"""

import atexit
import os
import re
import select
import sys
import signal
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
try:
    import readline
except ImportError:
    pass


# =============================================================================
# ANSI Color Constants
# =============================================================================
class Colors:
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"
    BG_BLUE = "\033[44m"
    BG_GREEN = "\033[42m"


# =============================================================================
# Global state
# =============================================================================
running = True
_child_processes: List[subprocess.Popen] = []

# YAML command support
current_scope = "workspace"
current_session_id: Optional[str] = None
yaml_commands: List[Dict[str, Any]] = []


def register_process(proc: subprocess.Popen):
    """Register a subprocess for cleanup tracking."""
    if proc is not None:
        _child_processes.append(proc)


def unregister_process(proc: subprocess.Popen):
    """Unregister a subprocess after it completes."""
    try:
        _child_processes.remove(proc)
    except ValueError:
        pass


def cleanup_children():
    """
    Terminate and kill all tracked child processes.
    First sends SIGTERM, waits 0.5s, then sends SIGKILL to survivors.
    """
    if not _child_processes:
        return

    print(
        f"\n{Colors.YELLOW}[INFO] Cleaning up {len(_child_processes)} child process(es)...{Colors.RESET}"
    )

    # Phase 1: graceful terminate
    for proc in list(_child_processes):
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass

    # Wait briefly for graceful shutdown
    time.sleep(0.5)

    # Phase 2: force kill survivors
    for proc in list(_child_processes):
        try:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=1)
        except Exception:
            pass
        finally:
            unregister_process(proc)

    print(f"{Colors.GREEN}[INFO] All child processes cleaned up.{Colors.RESET}")


# Register cleanup on normal interpreter exit
atexit.register(cleanup_children)


def signal_handler(signum, frame):
    """Handle Ctrl+C / SIGTERM gracefully with child cleanup."""
    global running
    print(
        f"\n{Colors.YELLOW}[INFO] Received signal {signum}. Exiting...{Colors.RESET}"
    )
    running = False
    cleanup_children()
    sys.exit(0)


# =============================================================================
# YAML Command Loading
# =============================================================================

def load_yaml_commands() -> List[Dict[str, Any]]:
    """
    Load commands from topsailai.yaml in the same directory as this script.
    Returns a list of instruction dictionaries.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    yaml_path = os.path.join(script_dir, "topsailai.yaml")

    if not os.path.isfile(yaml_path):
        return []

    try:
        import yaml
    except ImportError:
        print(
            f"{Colors.YELLOW}[WARN] PyYAML not installed. "
            f"YAML commands will not be loaded.{Colors.RESET}"
        )
        return []

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(
            f"{Colors.YELLOW}[WARN] Failed to load topsailai.yaml: {e}{Colors.RESET}"
        )
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
    """
    names = []
    cmd = instruction.get("cmd", "")
    if cmd:
        # Strip leading '/' for matching
        names.append(cmd.lstrip("/"))

    aliases = instruction.get("alias", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    for alias in aliases:
        if alias:
            names.append(alias.lstrip("/"))

    return names


def match_yaml_command(user_input: str) -> Optional[Tuple[Dict[str, Any], Dict[str, str]]]:
    """
    Match user input against YAML commands.
    Returns (instruction, variables) or None.

    Supports:
    - Exact match (with or without leading '/')
    - Variable extraction from cmd template like "/cd {session_id}"
    - Alias matching
    - Scope filtering
    """
    global current_scope, current_session_id

    # Special handling for /cd without arguments: available in all scopes
    if user_input in ("/cd", "cd"):
        for instruction in yaml_commands:
            cmd_template = instruction.get("cmd", "")
            if cmd_template.startswith("/cd"):
                return instruction, {"session_id": ""}

    for instruction in yaml_commands:
        scopes = instruction.get("scopes", [])
        if current_scope not in scopes:
            continue

        cmd_template = instruction.get("cmd", "")
        if not cmd_template:
            continue

        # Build regex pattern from cmd template
        # Strip leading '/' so commands work with or without it
        cmd_stripped = cmd_template.lstrip('/')
        # Escape special regex chars, then replace {var} with capture groups
        pattern = re.escape(cmd_stripped)
        var_names = re.findall(r"\\\{(\w+)\\\}", pattern)
        for var_name in var_names:
            pattern = pattern.replace(
                f"\\{{{var_name}\\}}", f"(?P<{var_name}>\\S+)"
            )

        # Allow optional leading '/' and optional trailing arguments
        pattern = f"^/?{pattern}(?:\\s+.*)?$"
        match = re.match(pattern, user_input)
        if match:
            variables = match.groupdict()
            variables.setdefault("session_id", current_session_id or "")
            return instruction, variables

        # Also check aliases
        aliases = instruction.get("alias", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        for alias in aliases:
            alias_stripped = alias.lstrip('/')
            alias_pattern = re.escape(alias_stripped)
            alias_vars = re.findall(r"\\\{(\w+)\\\}", alias_pattern)
            for var_name in alias_vars:
                alias_pattern = alias_pattern.replace(
                    f"\\{{{var_name}\\}}", f"(?P<{var_name}>\\S+)"
                )
            alias_pattern = f"^/?{alias_pattern}(?:\\s+.*)?$"
            alias_match = re.match(alias_pattern, user_input)
            if alias_match:
                variables = alias_match.groupdict()
                variables.setdefault("session_id", current_session_id or "")
                return instruction, variables

    return None


def handle_yaml_command(instruction: Dict[str, Any], variables: Dict[str, str]) -> str:
    """
    Handle a matched YAML command.
    Returns action string for main loop.
    """
    global current_scope, current_session_id

    cmd = instruction.get("cmd", "")
    shell = instruction.get("shell", "")

    # Internal commands (shell is empty)
    if not shell:
        if cmd.startswith("/cd"):
            session_id = variables.get("session_id", "").strip()
            if session_id:
                current_scope = "session"
                current_session_id = session_id
                print(
                    f"{Colors.GREEN}[INFO] Entered session scope: {session_id}{Colors.RESET}"
                )
            else:
                current_scope = "workspace"
                current_session_id = None
                print(
                    f"{Colors.GREEN}[INFO] Switched to workspace scope.{Colors.RESET}"
                )
            return "yaml_handled"

        if cmd.startswith("/env.get"):
            key = variables.get("key", "").strip()
            if key:
                value = os.environ.get(key, "")
                print(f"{Colors.CYAN}{key}={value}{Colors.RESET}")
            else:
                print(f"{Colors.RED}[ERROR] Usage: /env.get {{key}}{Colors.RESET}")
            return "yaml_handled"

        if cmd.startswith("/env.set"):
            key = variables.get("key", "").strip()
            value = variables.get("value", "").strip()
            if key:
                os.environ[key] = value
                print(f"{Colors.GREEN}[INFO] Set {key}={value}{Colors.RESET}")
            else:
                print(f"{Colors.RED}[ERROR] Usage: /env.set {{key}} {{value}}{Colors.RESET}")
            return "yaml_handled"

        print(f"{Colors.YELLOW}[WARN] Internal command not implemented: {cmd}{Colors.RESET}")
        return "yaml_handled"

    # External shell command
    try:
        # Replace variables in shell template
        shell_cmd = shell
        for var_name, var_value in variables.items():
            shell_cmd = shell_cmd.replace(f"{{{var_name}}}", var_value)

        proc = subprocess.Popen(
            shell_cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        register_process(proc)
        try:
            stdout, stderr = proc.communicate(timeout=30)
            if stdout:
                print(stdout, end="")
            if stderr:
                print(f"{Colors.RED}{stderr}{Colors.RESET}", end="")
        finally:
            unregister_process(proc)
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to execute command: {e}{Colors.RESET}")

    return "yaml_handled"


def get_prompt() -> str:
    """Generate dynamic prompt based on current scope."""
    if current_scope == "session" and current_session_id:
        return (
            f"\n{Colors.GREEN}[session:{current_session_id}]{Colors.RESET}> "
        )
    return f"\n{Colors.GREEN}[workspace]{Colors.RESET}> "


# =============================================================================
# TOPSAILAI_HOME Resolution
# =============================================================================

def get_topsailai_home() -> str:
    """
    Resolve TOPSAILAI_HOME with the following priority:
    1. Environment variable TOPSAILAI_HOME
    2. System home's .topsailai/.env file
    3. Default: /topsailai
    """
    env_home = os.environ.get("TOPSAILAI_HOME")
    if env_home and os.path.isdir(env_home):
        return env_home

    system_home = os.path.expanduser("~")
    env_file = os.path.join(system_home, ".topsailai", ".env")
    if os.path.isfile(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TOPSAILAI_HOME="):
                        value = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if value and os.path.isdir(value):
                            return value
        except Exception:
            pass

    default_home = "/topsailai"
    if os.path.isdir(default_home):
        return default_home
    return default_home


# =============================================================================
# Log File Discovery
# =============================================================================

def discover_log_files(task_dir: str) -> List[dict]:
    """
    Discover all .stdout log files in the task directory.
    """
    log_files = []
    if not os.path.isdir(task_dir):
        return log_files

    for entry in os.listdir(task_dir):
        if not entry.endswith(".stdout"):
            continue
        full_path = os.path.join(task_dir, entry)
        if not os.path.isfile(full_path):
            continue

        session_id = None
        if entry == "session.stdout":
            session_id = "(temp)"
        elif entry.endswith(".session.stdout"):
            session_id = entry.replace(".session.stdout", "")

        stat_info = os.stat(full_path)
        log_files.append({
            "filename": entry,
            "path": full_path,
            "session_id": session_id,
            "size": stat_info.st_size,
            "mtime": stat_info.st_mtime,
        })

    log_files.sort(key=lambda x: x["mtime"], reverse=True)
    return log_files


# =============================================================================
# Process Detection
# =============================================================================

def get_file_pid(filepath: str) -> Optional[int]:
    """
    Check if a file is currently being used by any process.
    Uses lsof first, then falls back to fuser.
    All spawned subprocesses are tracked and cleaned up on exit.
    """
    # Try lsof
    try:
        proc = subprocess.Popen(
            ["lsof", "-t", filepath],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        register_process(proc)
        try:
            stdout, _ = proc.communicate(timeout=3)
            if proc.returncode == 0 and stdout.strip():
                pids = stdout.strip().splitlines()
                if pids:
                    return int(pids[0])
        finally:
            unregister_process(proc)
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=1)
    except Exception:
        pass

    # Fallback to fuser
    try:
        proc = subprocess.Popen(
            ["fuser", filepath],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        register_process(proc)
        try:
            stdout, _ = proc.communicate(timeout=3)
            if proc.returncode == 0 and stdout.strip():
                parts = stdout.strip().split(":")
                if len(parts) >= 2:
                    pids = parts[1].strip().split()
                    if pids:
                        return int(pids[0])
        finally:
            unregister_process(proc)
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=1)
    except Exception:
        pass

    return None


# =============================================================================
# Formatting Helpers
# =============================================================================

def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}K"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}M"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f}G"


def format_timestamp(ts: float) -> str:
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%m-%d %H:%M")


def format_timestamp_full(ts: float) -> str:
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def print_header(title: str):
    width = 80
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * width}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {title}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * width}{Colors.RESET}")


def print_table(files: List[dict]):
    if not files:
        print(f"{Colors.YELLOW}[WARN] No .stdout log files found.{Colors.RESET}")
        return

    w_no = 4
    w_name = 28
    w_session = 22
    w_pid = 8
    w_size = 10
    w_time = 14

    header = (
        f"{Colors.BOLD}{Colors.BG_BLUE}{Colors.WHITE}"
        f" {'No':^{w_no}} |"
        f" {'Filename':^{w_name}} |"
        f" {'Session ID':^{w_session}} |"
        f" {'PID':^{w_pid}} |"
        f" {'Size':^{w_size}} |"
        f" {'Modified':^{w_time}} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_name + 2)}+"
        f"{'-' * (w_session + 2)}+"
        f"{'-' * (w_pid + 2)}+"
        f"{'-' * (w_size + 2)}+"
        f"{'-' * (w_time + 1)}"
        f"{Colors.RESET}"
    )

    print(header)
    print(sep)

    for idx, f in enumerate(files, start=1):
        pid = get_file_pid(f["path"])
        f["pid"] = pid

        name = f["filename"]
        if len(name) > w_name:
            name = name[:w_name - 3] + "..."

        session = f["session_id"] or "-"
        if len(session) > w_session:
            session = session[:w_session - 3] + "..."

        pid_str = str(pid) if pid else "-"
        size_str = format_size(f["size"])
        time_str = format_timestamp(f["mtime"])
        color = Colors.GREEN if pid else Colors.GRAY

        row = (
            f"{color}"
            f" {idx:^{w_no}} |"
            f" {name:<{w_name}} |"
            f" {session:<{w_session}} |"
            f" {pid_str:^{w_pid}} |"
            f" {size_str:>{w_size}} |"
            f" {time_str:^{w_time}} "
            f"{Colors.RESET}"
        )
        print(row)

    print(sep)
    print(
        f"{Colors.GREEN}● Running{Colors.RESET}  "
        f"{Colors.GRAY}○ Idle{Colors.RESET}  "
        f"{Colors.DIM}(Total: {len(files)} files){Colors.RESET}"
    )


# =============================================================================
# Help Display
# =============================================================================

def print_help():
    """
    Display all available commands with descriptions and examples.
    Includes built-in commands and YAML-loaded commands for current scope.
    """
    width = 80
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * width}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  Available Commands{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * width}{Colors.RESET}")

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

        print(f"\n  {Colors.BOLD}{Colors.YELLOW}{cmd}{Colors.RESET}")
        print(f"      {Colors.WHITE}{desc}{Colors.RESET}")
        if example:
            print(f"      {Colors.DIM}{example}{Colors.RESET}")

    # Print YAML commands for current scope
    if yaml_commands:
        scope_cmds = [
            inst for inst in yaml_commands
            if current_scope in inst.get("scopes", [])
        ]
        if scope_cmds:
            print(f"\n  {Colors.BOLD}{Colors.CYAN}--- YAML Commands ---{Colors.RESET}")
            for inst in scope_cmds:
                cmd = inst.get("cmd", "")
                aliases = inst.get("alias", [])
                if isinstance(aliases, str):
                    aliases = [aliases]
                desc = inst.get("desc", "")
                example = inst.get("example", "")

                alias_str = ""
                if aliases:
                    alias_str = f" {Colors.DIM}(alias: {', '.join(aliases)}){Colors.RESET}"

                print(f"\n  {Colors.BOLD}{Colors.YELLOW}{cmd}{Colors.RESET}{alias_str}")
                print(f"      {Colors.WHITE}{desc}{Colors.RESET}")
                if example:
                    print(f"      {Colors.DIM}{example}{Colors.RESET}")

    print(f"\n{Colors.CYAN}{'-' * width}{Colors.RESET}")
    print(
        f"  {Colors.DIM}Tip: Running processes are shown in {Colors.GREEN}green"
        f"{Colors.DIM}, idle files in {Colors.GRAY}gray"
        f"{Colors.DIM}.{Colors.RESET}"
    )
    print(f"{Colors.CYAN}{'=' * width}{Colors.RESET}\n")


# =============================================================================
# Clean Expired Files
# =============================================================================

def clean_expired_files(task_dir: str, files: List[dict]) -> int:
    """
    Clean up .stdout log files that are:
    - Not being used by any process (PID is None)
    - Older than 3 days (72 hours)

    Shows a confirmation prompt before deletion.
    Returns the number of files deleted.
    """
    now = time.time()
    threshold_seconds = 3 * 24 * 60 * 60  # 72 hours

    expired_files = []
    for f in files:
        # Check if file is still on disk and get fresh stat
        if not os.path.isfile(f["path"]):
            continue

        # Refresh mtime in case it changed
        try:
            mtime = os.path.getmtime(f["path"])
        except OSError:
            continue

        age = now - mtime
        if age <= threshold_seconds:
            continue

        # Check process ownership (fresh check)
        pid = get_file_pid(f["path"])
        if pid is not None:
            continue

        expired_files.append({
            "filename": f["filename"],
            "path": f["path"],
            "size": os.path.getsize(f["path"]),
            "mtime": mtime,
            "age_hours": age / 3600,
        })

    if not expired_files:
        print(
            f"\n{Colors.GREEN}[INFO] No expired .stdout files found. "
            f"(Files must be idle and older than 3 days){Colors.RESET}"
        )
        return 0

    # Show confirmation table
    print_header("Clean Expired Log Files")
    print(
        f"{Colors.YELLOW}[WARN] The following {len(expired_files)} file(s) are idle "
        f"and older than 3 days:{Colors.RESET}\n"
    )

    w_no = 4
    w_name = 32
    w_size = 10
    w_time = 20
    w_age = 12

    header = (
        f"{Colors.BOLD}{Colors.BG_BLUE}{Colors.WHITE}"
        f" {'No':^{w_no}} |"
        f" {'Filename':^{w_name}} |"
        f" {'Size':^{w_size}} |"
        f" {'Modified':^{w_time}} |"
        f" {'Age':^{w_age}} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_name + 2)}+"
        f"{'-' * (w_size + 2)}+"
        f"{'-' * (w_time + 2)}+"
        f"{'-' * (w_age + 1)}"
        f"{Colors.RESET}"
    )

    print(header)
    print(sep)

    for idx, ef in enumerate(expired_files, start=1):
        name = ef["filename"]
        if len(name) > w_name:
            name = name[:w_name - 3] + "..."

        size_str = format_size(ef["size"])
        time_str = format_timestamp_full(ef["mtime"])
        age_str = f"{ef['age_hours']:.1f}h"

        row = (
            f"{Colors.GRAY}"
            f" {idx:^{w_no}} |"
            f" {name:<{w_name}} |"
            f" {size_str:>{w_size}} |"
            f" {time_str:^{w_time}} |"
            f" {age_str:>{w_age}} "
            f"{Colors.RESET}"
        )
        print(row)

    print(sep)

    # Confirmation prompt
    confirm_prompt = (
        f"\n{Colors.BOLD}{Colors.YELLOW}"
        f"Are you sure you want to delete these {len(expired_files)} file(s)? [y/N]: "
        f"{Colors.RESET}"
    )
    try:
        confirm = input(confirm_prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(f"\n{Colors.YELLOW}[INFO] Clean cancelled.{Colors.RESET}")
        return 0

    if confirm not in ("y", "yes"):
        print(f"{Colors.YELLOW}[INFO] Clean cancelled.{Colors.RESET}")
        return 0

    # Perform deletion
    deleted_count = 0
    failed_files = []

    for ef in expired_files:
        try:
            os.remove(ef["path"])
            deleted_count += 1
            print(
                f"{Colors.GREEN}[OK] Deleted: {ef['filename']}{Colors.RESET}"
            )
        except OSError as e:
            failed_files.append((ef["filename"], str(e)))
            print(
                f"{Colors.RED}[ERROR] Failed to delete {ef['filename']}: {e}{Colors.RESET}"
            )

    print(
        f"\n{Colors.GREEN}[INFO] Clean complete: "
        f"{deleted_count} deleted, {len(failed_files)} failed.{Colors.RESET}"
    )
    return deleted_count


def clean_by_numbers(task_dir: str, files: List[dict], indices: List[int]) -> int:
    """
    Clean up specific .stdout log files by their list numbers.

    Validates each index, shows a confirmation prompt, then deletes the files.
    Returns the number of files deleted.
    """
    valid_files = []
    invalid_indices = []

    for idx in indices:
        if 0 <= idx < len(files):
            f = files[idx]
            if os.path.isfile(f["path"]):
                valid_files.append(f)
            else:
                invalid_indices.append(idx + 1)
        else:
            invalid_indices.append(idx + 1)

    if invalid_indices:
        print(
            f"{Colors.YELLOW}[WARN] Invalid or out-of-range number(s): "
            f"{', '.join(str(i) for i in invalid_indices)}{Colors.RESET}"
        )

    if not valid_files:
        print(
            f"{Colors.YELLOW}[INFO] No valid files to delete.{Colors.RESET}"
        )
        return 0

    # Show confirmation table
    print_header("Clean Selected Log Files")
    print(
        f"{Colors.YELLOW}[WARN] The following {len(valid_files)} file(s) will be deleted:{Colors.RESET}\n"
    )

    w_no = 4
    w_name = 32
    w_size = 10
    w_time = 20

    header = (
        f"{Colors.BOLD}{Colors.BG_BLUE}{Colors.WHITE}"
        f" {'No':^{w_no}} |"
        f" {'Filename':^{w_name}} |"
        f" {'Size':^{w_size}} |"
        f" {'Modified':^{w_time}} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_name + 2)}+"
        f"{'-' * (w_size + 2)}+"
        f"{'-' * (w_time + 1)}"
        f"{Colors.RESET}"
    )

    print(header)
    print(sep)

    for idx, f in enumerate(valid_files, start=1):
        name = f["filename"]
        if len(name) > w_name:
            name = name[:w_name - 3] + "..."

        size_str = format_size(f["size"])
        time_str = format_timestamp_full(f["mtime"])

        row = (
            f"{Colors.GRAY}"
            f" {idx:^{w_no}} |"
            f" {name:<{w_name}} |"
            f" {size_str:>{w_size}} |"
            f" {time_str:^{w_time}} "
            f"{Colors.RESET}"
        )
        print(row)

    print(sep)

    # Confirmation prompt
    confirm_prompt = (
        f"\n{Colors.BOLD}{Colors.YELLOW}"
        f"Are you sure you want to delete these {len(valid_files)} file(s)? [y/N]: "
        f"{Colors.RESET}"
    )
    try:
        confirm = input(confirm_prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(f"\n{Colors.YELLOW}[INFO] Clean cancelled.{Colors.RESET}")
        return 0

    if confirm not in ("y", "yes"):
        print(f"{Colors.YELLOW}[INFO] Clean cancelled.{Colors.RESET}")
        return 0

    # Perform deletion
    deleted_count = 0
    failed_files = []

    for f in valid_files:
        try:
            os.remove(f["path"])
            deleted_count += 1
            print(
                f"{Colors.GREEN}[OK] Deleted: {f['filename']}{Colors.RESET}"
            )
        except OSError as e:
            failed_files.append((f["filename"], str(e)))
            print(
                f"{Colors.RED}[ERROR] Failed to delete {f['filename']}: {e}{Colors.RESET}"
            )

    print(
        f"\n{Colors.GREEN}[INFO] Clean complete: "
        f"{deleted_count} deleted, {len(failed_files)} failed.{Colors.RESET}"
    )
    return deleted_count


# =============================================================================
# File Streaming
# =============================================================================

def stream_file(filepath: str):
    """
    Stream a log file in real-time, similar to `tail -f`.

    Strategy:
    1. Show the last 20 lines via `tail -n 20` (one-shot subprocess).
    2. Open the file directly in binary mode, seek to end, and read new data
       in a tight loop. This avoids pipe buffering issues from `tail -f`.
    3. Use select() with a short timeout (0.05s) to check for 'q' keypress.

    Supports 'q' to quit, or Ctrl+C for graceful exit.
    """
    global running
    filename = os.path.basename(filepath)
    print_header(f"Streaming: {filename}")
    print(
        f"{Colors.YELLOW}[INFO] Press 'q' to quit, or Ctrl+C to exit.{Colors.RESET}\n"
    )

    # Step 1: Show last 20 lines using a one-shot tail command.
    try:
        subprocess.run(["tail", "-n", "20", filepath], check=False)
    except Exception:
        pass

    # Step 2: Open file directly and follow new writes.
    # Using binary mode for minimal overhead; write raw bytes to stdout.buffer.
    try:
        with open(filepath, "rb") as f:
            f.seek(0, 2)  # Jump to end
            while running:
                chunk = f.read(4096)
                if chunk:
                    if hasattr(sys.stdout, "buffer"):
                        sys.stdout.buffer.write(chunk)
                        sys.stdout.buffer.flush()
                    else:
                        print(chunk.decode("utf-8", errors="replace"), end="")
                        sys.stdout.flush()
                else:
                    # No new data; check for 'q' key with a short timeout.
                    if sys.stdin.isatty():
                        readable, _, _ = select.select([sys.stdin], [], [], 0.05)
                        if readable:
                            char = sys.stdin.read(1)
                            if char and char.lower() == 'q':
                                print(
                                    f"\n{Colors.YELLOW}[INFO] Quit requested.{Colors.RESET}"
                                )
                                break
                    else:
                        time.sleep(0.05)
    except FileNotFoundError:
        print(f"{Colors.RED}[ERROR] File not found: {filepath}{Colors.RESET}")
    except PermissionError:
        print(f"{Colors.RED}[ERROR] Permission denied: {filepath}{Colors.RESET}")
    except KeyboardInterrupt:
        print(
            f"\n{Colors.YELLOW}[INFO] Interrupted by user.{Colors.RESET}"
        )
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to stream file: {e}{Colors.RESET}")

    print(f"\n{Colors.CYAN}[INFO] Streaming stopped.{Colors.RESET}")


# =============================================================================
# Session Retrieval
# =============================================================================

def retrieve_session(session_id: str):
    """
    Retrieve session content via topsailai_retrieve_messages command.
    The subprocess is tracked and will be cleaned up on script exit.
    """
    print_header(f"Session Content: {session_id}")
    proc = None
    try:
        proc = subprocess.Popen(
            ["topsailai_retrieve_messages", session_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        register_process(proc)
        stdout, stderr = proc.communicate(timeout=30)
        if proc.returncode == 0:
            print(f"{Colors.WHITE}{stdout}{Colors.RESET}")
        else:
            print(
                f"{Colors.RED}[ERROR] topsailai_retrieve_messages failed: "
                f"{stderr.strip()}{Colors.RESET}"
            )
    except FileNotFoundError:
        print(
            f"{Colors.RED}[ERROR] Command 'topsailai_retrieve_messages' not found. "
            f"Please ensure it is installed and in PATH.{Colors.RESET}"
        )
    except subprocess.TimeoutExpired:
        print(f"{Colors.RED}[ERROR] Command timed out after 30s.{Colors.RESET}")
        if proc and proc.poll() is None:
            proc.kill()
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to retrieve session: {e}{Colors.RESET}")
    finally:
        if proc:
            unregister_process(proc)
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass


# =============================================================================
# Interactive Selection
# =============================================================================

def prompt_selection(files: List[dict]) -> Tuple[str, Optional[int]]:
    """
    Prompt user to select a file by number or enter a command.
    Returns (action, value).
    """
    global current_scope, current_session_id

    while True:
        try:
            prompt_text = get_prompt()
            user_input = input(prompt_text).strip()
            try:
                readline.add_history(user_input)
            except NameError:
                pass

            if not user_input:
                continue

            lower_input = user_input.lower()

            if lower_input in ("q", "quit", "exit"):
                return ("quit", None)

            if lower_input == "/refresh":
                return ("refresh", None)

            if lower_input.startswith("/clean"):
                parts = user_input.split()
                if len(parts) == 1:
                    return ("clean", None)
                try:
                    indices = [int(p) - 1 for p in parts[1:]]
                    return ("clean_numbers", indices)
                except ValueError:
                    print(
                        f"{Colors.RED}[ERROR] Usage: /clean or /clean {{number}} [{{number}} ...]{Colors.RESET}"
                    )
                    continue

            if lower_input in ("/help", "help"):
                return ("help", None)

            # Try YAML command matching first
            yaml_match = match_yaml_command(user_input)
            if yaml_match:
                instruction, variables = yaml_match
                action = handle_yaml_command(instruction, variables)
                return (action, None)

            if lower_input.startswith("/session "):
                parts = user_input.split(None, 1)
                if len(parts) < 2:
                    print(
                        f"{Colors.RED}[ERROR] Usage: /session {{number}}{Colors.RESET}"
                    )
                    continue
                try:
                    num = int(parts[1].strip())
                    if 1 <= num <= len(files):
                        return ("session", num - 1)
                    else:
                        print(
                            f"{Colors.RED}[ERROR] Invalid number. "
                            f"Please enter 1-{len(files)}.{Colors.RESET}"
                        )
                except ValueError:
                    print(
                        f"{Colors.RED}[ERROR] Invalid number. "
                        f"Usage: /session {{number}}{Colors.RESET}"
                    )
                continue

            try:
                selected = int(user_input)
                if 1 <= selected <= len(files):
                    return ("watch", selected - 1)
                else:
                    print(
                        f"{Colors.RED}[ERROR] Invalid number. "
                        f"Please enter 1-{len(files)}.{Colors.RESET}"
                    )
            except ValueError:
                print(
                    f"{Colors.RED}[ERROR] Unknown command: '{user_input}'. "
                    f"Please enter a number, /refresh, /session {{number}}, /clean, /help, or 'q'.{Colors.RESET}"
                )

        except (EOFError, KeyboardInterrupt):
            print(f"\n{Colors.YELLOW}[INFO] Exiting...{Colors.RESET}")
            cleanup_children()
            return ("quit", None)

# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    global running, yaml_commands

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Load YAML commands
    yaml_commands = load_yaml_commands()

    topsailai_home = get_topsailai_home()
    task_dir = os.path.join(topsailai_home, "workspace", "task")

    print_header("TopsailAI Task Watcher")
    print(f"{Colors.DIM}HOME: {topsailai_home}{Colors.RESET}")
    print(f"{Colors.DIM}DIR:  {task_dir}{Colors.RESET}")

    log_files = discover_log_files(task_dir)

    if not log_files:
        print(f"\n{Colors.YELLOW}[WARN] No .stdout log files found in:{Colors.RESET}")
        print(f"  {task_dir}")
        sys.exit(0)

    print_table(log_files)
    print(
        f"\n  {Colors.DIM}Type {Colors.YELLOW}/help{Colors.DIM} for available commands{Colors.RESET}"
    )

    try:
        while running:
            action, value = prompt_selection(log_files)

            if action == "quit":
                break

            if action == "refresh":
                print(f"\n{Colors.DIM}Refreshing file list...{Colors.RESET}")
                log_files = discover_log_files(task_dir)
                print_table(log_files)
                continue

            if action == "help":
                print_help()
                continue

            if action == "clean":
                clean_expired_files(task_dir, log_files)
                print(f"\n{Colors.DIM}Refreshing file list...{Colors.RESET}")
                log_files = discover_log_files(task_dir)
                print_table(log_files)
                continue

            if action == "clean_numbers":
                clean_by_numbers(task_dir, log_files, value)
                print(f"\n{Colors.DIM}Refreshing file list...{Colors.RESET}")
                log_files = discover_log_files(task_dir)
                print_table(log_files)
                continue

            if action == "session":
                selected_file = log_files[value]
                session_id = selected_file.get("session_id")
                if not session_id or session_id == "(temp)":
                    print(
                        f"{Colors.RED}[ERROR] No session ID available for this file.{Colors.RESET}"
                    )
                    continue
                retrieve_session(session_id)
                continue

            if action == "watch":
                selected_file = log_files[value]
                stream_file(selected_file["path"])
                print(f"\n{Colors.DIM}Refreshing file list...{Colors.RESET}")
                log_files = discover_log_files(task_dir)
                print_table(log_files)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}[INFO] Interrupted by user.{Colors.RESET}")
    finally:
        cleanup_children()

    print(f"\n{Colors.CYAN}Goodbye!{Colors.RESET}\n")


if __name__ == "__main__":
    main()
