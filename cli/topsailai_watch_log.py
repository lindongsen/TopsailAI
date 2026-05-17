#!/usr/bin/env python3
"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-05-17
  Purpose: Watch log files in {TOPSAILAI_HOME}/workspace/task/ with interactive selection.
           Lists .stdout log files, shows process ownership, and streams selected file.
           Supports /refresh and /session {number} commands.
           Ensures all child processes are cleaned up on exit.
"""

import atexit
import os
import sys
import signal
import subprocess
import time
from datetime import datetime
from typing import List, Optional, Tuple


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
# File Streaming
# =============================================================================

def stream_file(filepath: str):
    """
    Stream a log file in real-time, similar to `tail -f`.
    Supports 'q' + Enter to quit, or Ctrl+C for graceful exit.
    """
    global running
    filename = os.path.basename(filepath)
    print_header(f"Streaming: {filename}")
    print(
        f"{Colors.YELLOW}[INFO] Press 'q' + Enter to quit, or Ctrl+C to exit.{Colors.RESET}\n"
    )

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)
            while running:
                try:
                    line = f.readline()
                except KeyboardInterrupt:
                    print(
                        f"\n{Colors.YELLOW}[INFO] Interrupted by user.{Colors.RESET}"
                    )
                    break

                if line:
                    print(line, end="")
                    sys.stdout.flush()
                else:
                    time.sleep(0.2)
                    try:
                        import select
                        if select.select([sys.stdin], [], [], 0)[0]:
                            char = sys.stdin.read(1)
                            if char.lower() == 'q':
                                print(
                                    f"\n{Colors.YELLOW}[INFO] Quit requested.{Colors.RESET}"
                                )
                                break
                    except Exception:
                        pass
    except FileNotFoundError:
        print(f"{Colors.RED}[ERROR] File not found: {filepath}{Colors.RESET}")
    except PermissionError:
        print(f"{Colors.RED}[ERROR] Permission denied: {filepath}{Colors.RESET}")
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
    while True:
        try:
            prompt_text = (
                f"\n{Colors.BOLD}{Colors.YELLOW}"
                f"Enter number to watch, /refresh, /session {{number}}, or 'q' to quit: "
                f"{Colors.RESET}"
            )
            user_input = input(prompt_text).strip()

            if not user_input:
                continue

            lower_input = user_input.lower()

            if lower_input in ("q", "quit", "exit"):
                return ("quit", None)

            if lower_input == "/refresh":
                return ("refresh", None)

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
                    f"Please enter a number, /refresh, /session {{number}}, or 'q'.{Colors.RESET}"
                )

        except (EOFError, KeyboardInterrupt):
            print(f"\n{Colors.YELLOW}[INFO] Exiting...{Colors.RESET}")
            cleanup_children()
            return ("quit", None)


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    global running

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    topsailai_home = get_topsailai_home()
    task_dir = os.path.join(topsailai_home, "workspace", "task")

    print_header("TopsailAI Log Watcher")
    print(f"{Colors.DIM}HOME: {topsailai_home}{Colors.RESET}")
    print(f"{Colors.DIM}DIR:  {task_dir}{Colors.RESET}")

    log_files = discover_log_files(task_dir)

    if not log_files:
        print(f"\n{Colors.YELLOW}[WARN] No .stdout log files found in:{Colors.RESET}")
        print(f"  {task_dir}")
        sys.exit(0)

    print_table(log_files)

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
