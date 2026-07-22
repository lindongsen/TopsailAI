"""Process management helpers for the TopsailAI CLI."""

import atexit
import os
import shlex
import subprocess
import sys
import time
from typing import Any, Dict, List

import cli_topsailai.state as cli_state
from cli_topsailai.colors import print_error, print_info, print_success, print_warning


def register_process(proc: subprocess.Popen) -> None:
    """Register a subprocess for cleanup tracking."""
    if proc is not None:
        cli_state._child_processes.add(proc)


def unregister_process(proc: subprocess.Popen) -> None:
    """Unregister a subprocess after it completes."""
    cli_state._child_processes.discard(proc)


def is_independent_process(instruction: Dict[str, Any]) -> bool:
    """Check if the instruction should run as an independent process."""
    independent = instruction.get("independent_process")
    if isinstance(independent, str):
        return independent.lower() in ("1", "true", "yes")
    return bool(independent)


def is_async_command(instruction: Dict[str, Any]) -> bool:
    """Check if the instruction should be executed asynchronously."""
    async_val = instruction.get("async")
    if isinstance(async_val, str):
        return async_val.lower() in ("1", "true", "yes")
    return bool(async_val)


def is_use_os_system(instruction: Dict[str, Any]) -> bool:
    """Check if the instruction should use os.system() to execute shell."""
    use_os = instruction.get("use_os_system")
    if isinstance(use_os, str):
        return use_os.lower() in ("1", "true", "yes")
    return bool(use_os)


def launch_independent_process(cmd_list: List[str], **kwargs: Any) -> subprocess.Popen:
    """
    Start an independent child process that is logically separated from the
    current process: the child process's parent-process-id is not the
    current-process-id.
    """
    popen_kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": kwargs.get("stdout", subprocess.PIPE),
        "stderr": kwargs.get("stderr", subprocess.PIPE),
        "text": kwargs.get("text", True),
        "env": kwargs.get("env"),
    }
    if sys.platform == "win32":
        # Windows
        popen_kwargs["creationflags"] = subprocess.DETACHED_PROCESS
    else:
        # Linux/macOS: start_new_session already calls os.setsid() internally
        popen_kwargs["start_new_session"] = True
    return subprocess.Popen(cmd_list, **popen_kwargs)


def run_os_system_command(shell_cmd: str, cmd_env: Dict[str, str]) -> int:
    """Execute a shell command via os.system with temporary environment overrides.

    Temporarily applies ``cmd_env`` values to ``os.environ`` so the shell
    command sees the requested environment, then restores the original values.

    Args:
        shell_cmd: The shell command string to execute.
        cmd_env: Environment variables to apply during execution.

    Returns:
        The exit code returned by ``os.system``.
    """
    old_env: Dict[str, Optional[str]] = {}
    try:
        for key, value in cmd_env.items():
            old_env[key] = os.environ.get(key)
            os.environ[key] = value
        exit_code = os.system(shell_cmd)
    finally:
        for key, old_value in old_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value
    return exit_code


def run_external_command(
    cmd_list: List[str],
    cmd_env: Dict[str, str],
    independent: bool,
    async_cmd: bool = False,
    use_os_system: bool = False,
    timeout: int = 30,
) -> None:
    """
    Run an external command, either as a tracked child process or as an
    independent process.  Independent processes are not registered for cleanup
    and run in a new session.  Async commands are launched in the background
    and return immediately.  When use_os_system is True, the command is
    executed via os.system() instead of subprocess.
    """
    # When use_os_system is True, execute via os.system() with environment variables
    if use_os_system:
        shell_cmd = " ".join(shlex.quote(arg) for arg in cmd_list)
        print_info(f"Executing (os.system): {shell_cmd} ...")
        exit_code = run_os_system_command(shell_cmd, cmd_env)
        if exit_code != 0:
            print_error(f"Command exited with code {exit_code}.")
        print_success("Execution completed.")
        return

    print_info(f"Executing: {' '.join(cmd_list)} ...")
    if async_cmd:
        # Async commands run as independent background processes
        proc = launch_independent_process(
            cmd_list,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            env=cmd_env,
        )
        print_success(f"Async process started (pid={proc.pid}).")
        return

    if independent:
        proc = launch_independent_process(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=cmd_env,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            if stdout:
                print(stdout, end="")
            if stderr:
                print_error(stderr, end="")
        finally:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass
    else:
        proc = subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=cmd_env,
        )
        register_process(proc)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            if stdout:
                print(stdout, end="")
            if stderr:
                print_error(stderr, end="")
        finally:
            unregister_process(proc)
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass
    print_success("Execution completed.")


def cleanup_children() -> None:
    """
    Terminate and kill all tracked child processes.
    First sends SIGTERM, waits 0.5s, then sends SIGKILL to survivors.
    """
    if not cli_state._child_processes:
        return

    print_warning(
        f"\nCleaning up {len(cli_state._child_processes)} child process(es)..."
    )

    # Phase 1: graceful terminate
    for proc in list(cli_state._child_processes):
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass

    # Wait briefly for graceful shutdown
    time.sleep(0.5)

    # Phase 2: force kill survivors
    for proc in list(cli_state._child_processes):
        try:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=1)
        except Exception:
            pass
        finally:
            unregister_process(proc)

    print_success("All child processes cleaned up.")


# Register cleanup on normal interpreter exit
atexit.register(cleanup_children)


def signal_handler(signum: int, frame: Any) -> None:
    """Handle Ctrl+C / SIGTERM gracefully with child cleanup."""
    print_warning(f"\nReceived signal {signum}. Exiting...")
    cli_state.running = False
    cleanup_children()
    sys.exit(0)


# Backward-compatible alias used by older tests and callers.
cleanup_child_processes = cleanup_children
