"""Shared configured-agent launch boundary."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid

from cli_topsailai.core import _detect_agent_mode
from cli_topsailai.project_scope import (
    _apply_selected_model_environment,
    _wrap_command_for_agent_mode,
)


def _spawn_process(*args, **kwargs):
    """Create the directly owned production child process."""
    return subprocess.Popen(*args, **kwargs)


def _session_id() -> str:
    """Create an explicit identity for a fresh workspace launch."""
    return f"workspace-agent-{uuid.uuid4().hex}"


def _prepare_environment(folder: str, session_id: str):
    """Apply launch identity and selected model environment."""
    keys = ("TOPSAILAI_PWD", "PWD", "TOPSAILAI_SESSION_ID", "SESSION_ID")
    original = {key: os.environ.get(key) for key in keys}
    os.chdir(folder)
    os.environ.update({
        "TOPSAILAI_PWD": folder,
        "PWD": folder,
        "TOPSAILAI_SESSION_ID": session_id,
        "SESSION_ID": session_id,
    })
    model = _apply_selected_model_environment(folder)
    if model is None:
        raise RuntimeError("selected model configuration could not be applied")
    model_original, forwarded = model
    return keys, original, model_original, forwarded


def _stop_owned_child(child) -> bool:
    """Terminate and reap the directly owned child after interruption."""
    try:
        if child.poll() is not None:
            return True
        # Give a child that received the terminal interrupt a bounded grace
        # period before escalating; only this directly owned child is touched.
        try:
            child.wait(timeout=1.0)
            return True
        except subprocess.TimeoutExpired:
            pass
        child.terminate()
        try:
            child.wait(timeout=1.0)
            return True
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=1.0)
            return True
    except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
        return False


def launch_configured_agent(folder: str, *, mode: str | None, background: bool = False, spawn=None) -> int:
    """Launch an agent and make restoration failure observable."""
    original_cwd = os.getcwd()
    original_environment = os.environ.copy()
    result = None
    restore_errors = []
    try:
        result = _launch_configured_agent_impl(folder, mode=mode, background=background, spawn=spawn)
    finally:
        try:
            os.chdir(original_cwd)
        except OSError as error:
            restore_errors.append(f"cwd: {error}")
        try:
            os.environ.clear()
            os.environ.update(original_environment)
        except OSError as error:
            restore_errors.append(f"environment: {error}")
        if restore_errors:
            print(
                "[ERROR] Failed to restore launch environment: " + "; ".join(restore_errors),
                file=sys.stderr,
            )
            result = 6
    return result

def _launch_configured_agent_impl(
    folder: str, *, mode: str | None, background: bool = False, spawn=None
) -> int:
    """Launch one configured agent and return its boundary status."""
    if background:
        print("[ERROR] --background is not yet available", file=sys.stderr)
        return 2
    if spawn is None:
        spawn = _spawn_process

    original_cwd = os.getcwd()
    original_environment = os.environ.copy()
    session_id = None
    child = None
    result = 4
    try:
        session_id = _session_id()
        effective_mode = mode or _detect_agent_mode()
        print(
            f"[INFO] Launching agent: workspace={folder} mode={effective_mode} "
            f"background=no session={session_id}"
        )
        command = ["topsailai_launch_agent", "--subprocess", "--session-id", session_id]
        try:
            forwarded = _prepare_environment(folder, session_id)[3]
            if effective_mode == "raw":
                argv = command
                kwargs = {"cwd": folder, "env": os.environ.copy()}
            else:
                argv = _wrap_command_for_agent_mode(" ".join(command), effective_mode, forwarded)
                kwargs = {"cwd": folder, "env": os.environ.copy(), "shell": True}
        except (RuntimeError, ValueError, OSError) as error:
            print(f"[ERROR] Agent launch preparation failed: {error}", file=sys.stderr)
            return 4
        try:
            child = spawn(argv, **kwargs)
        except (OSError, ValueError) as error:
            print(f"[ERROR] Agent launch failed: {error}", file=sys.stderr)
            return 5
        try:
            code = child.wait()
        except KeyboardInterrupt:
            if not _stop_owned_child(child):
                print(f"[ERROR] Agent launch custody unresolved: session={session_id}", file=sys.stderr)
                return 6
            print(f"[ERROR] Agent launch interrupted: session={session_id}", file=sys.stderr)
            return 130
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"[ERROR] Agent launcher wait failed: {error}", file=sys.stderr)
            if not _stop_owned_child(child):
                print(f"[ERROR] Agent launch custody unresolved: session={session_id}", file=sys.stderr)
                return 6
            return 5
        output = (
            f"[INFO] Agent launcher exited: code={code} session={session_id}"
            if code == 0
            else f"[ERROR] Agent launcher exited: code={code} session={session_id}"
        )
        print(output, file=sys.stdout if code == 0 else sys.stderr)
        result = code if code >= 0 else 128 + (-code)
    except KeyboardInterrupt:
        if child is not None and not _stop_owned_child(child):
            print(f"[ERROR] Agent launch custody unresolved: session={session_id}", file=sys.stderr)
            result = 6
        else:
            print(f"[ERROR] Agent launch interrupted: session={session_id}", file=sys.stderr)
            result = 130
    except (RuntimeError, ValueError, OSError) as error:
        if child is not None:
            print(f"[ERROR] Agent launcher failed after spawn: {error}", file=sys.stderr)
            result = 6 if not _stop_owned_child(child) else 5
        else:
            print(f"[ERROR] Agent launch preparation failed: {error}", file=sys.stderr)
            result = 4
    return result

