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


def launch_configured_agent(folder: str, *, mode: str | None, background: bool = False, spawn=None,
                            entrypoint_base: str | None = None,
                            session_id: str | None = None,
                            driver: str | None = None,
                            prelaunch_check=None,
                            receipt: dict | None = None,
                            child_stdout=None) -> int:
    """Launch an agent and make restoration failure observable.

    When *session_id* is supplied the launch resumes that persisted identity
    instead of minting a fresh one, and *driver* selects the resume driver.

    *prelaunch_check* is an optional late revalidation invoked after
    preparation and immediately before the child is spawned or the supervisor
    is submitted; it returns ``None`` to proceed or a status code to refuse.

    *receipt* is an optional mutable mapping that the launch fills with the
    facts it actually established, so a caller can publish a machine-readable
    result without re-deriving them. *child_stdout* optionally redirects the
    directly owned foreground child's stdout, which keeps the caller's stdout
    free for a single result document.
    """
    original_cwd = os.getcwd()
    original_environment = os.environ.copy()
    result = None
    restore_errors = []
    try:
        launch_kwargs = {"mode": mode, "background": background, "spawn": spawn}
        if entrypoint_base is not None:
            launch_kwargs["entrypoint_base"] = entrypoint_base
        if session_id is not None:
            launch_kwargs["session_id"] = session_id
        if driver is not None:
            launch_kwargs["driver"] = driver
        if prelaunch_check is not None:
            launch_kwargs["prelaunch_check"] = prelaunch_check
        if receipt is not None:
            launch_kwargs["receipt"] = receipt
        if child_stdout is not None:
            launch_kwargs["child_stdout"] = child_stdout
        result = _launch_configured_agent_impl(folder, **launch_kwargs)
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
    folder: str, *, mode: str | None, background: bool = False, spawn=None,
    entrypoint_base: str | None = None,
    session_id: str | None = None,
    driver: str | None = None,
    prelaunch_check=None,
    receipt: dict | None = None,
    child_stdout=None,
) -> int:
    """Launch one configured agent and return its boundary status."""
    if spawn is None:
        spawn = _spawn_process

    def record(**facts) -> None:
        """Publish only facts this boundary actually established."""
        if receipt is not None:
            receipt.update(facts)

    def refuse_if_not_ready() -> int | None:
        """Run the caller's late revalidation at the launch boundary."""
        if prelaunch_check is None:
            return None
        return prelaunch_check()
    # A resume keeps the persisted identity; a fresh launch mints a new one.
    resumed_session = session_id
    child = None
    result = 4
    # The detached supervisor entry point is resolved against the caller's
    # invocation directory, which is captured before any folder change.
    invocation_cwd = entrypoint_base or os.getcwd()
    try:
        session_id = resumed_session or _session_id()
        record(session_id=session_id, workspace=folder, background=background,
               resumed=resumed_session is not None)
        try:
            effective_mode = (mode or "raw") if background else (mode or _detect_agent_mode())
        except (RuntimeError, ValueError, OSError) as error:
            print(f"[ERROR] Agent launch preparation failed: {error}", file=sys.stderr)
            return 4
        record(mode=effective_mode)
        if background:
            from cli_topsailai.agent_launch_background import (
                BackgroundUnconfirmed,
                launch_background,
                launch_log_identity,
            )
            from cli_topsailai.agent_launch_terminal import (
                TerminalUnavailable,
                TerminalUnconfirmed,
                resolve_mechanism,
                submit_terminal,
            )

            try:
                effective_mode = resolve_mechanism(effective_mode)
            except TerminalUnavailable as error:
                print(f"[ERROR] Agent launch preparation failed: {error}", file=sys.stderr)
                return 4
            record(mode=effective_mode)
            print(
                f"[INFO] Submitting agent: workspace={folder} mode={effective_mode} "
                f"background=yes session={session_id}"
            )

            try:
                _prepare_environment(folder, session_id)
            except (RuntimeError, ValueError, OSError) as error:
                print(f"[ERROR] Agent launch preparation failed: {error}", file=sys.stderr)
                return 4
            # Late fail-closed revalidation: the caller rechecks liveness and
            # the workspace after preparation and immediately before the
            # supervisor is submitted.
            refusal = refuse_if_not_ready()
            if refusal is not None:
                return refusal
            submit_kwargs = {
                "environment": os.environ.copy(),
                "spawn": spawn,
                "entrypoint_base": invocation_cwd,
                # A resume writes a distinct per-attempt log so an earlier
                # attempt's diagnostics are never truncated; a fresh launch
                # keeps its historical single log name.
                "log_identity": (launch_log_identity(session_id, uuid.uuid4().hex)
                                 if resumed_session else None),
                "driver": driver,
            }
            record(submission_attempted=True)
            try:
                if effective_mode == "raw":
                    background_result = launch_background(
                        folder, session_id, **submit_kwargs)
                else:
                    background_result = submit_terminal(
                        folder, session_id, mechanism=effective_mode, **submit_kwargs)
            except (BackgroundUnconfirmed, TerminalUnconfirmed) as error:
                record(effect_uncertain=True)
                print(f"[ERROR] Agent launch custody unresolved: {error}", file=sys.stderr)
                return 6
            except (OSError, ValueError, RuntimeError) as error:
                print(f"[ERROR] Agent launch failed: {error}", file=sys.stderr)
                return 5
            if background_result.get("outcome") == "cancelled":
                exit_code = background_result.get("exit_code", 6)
                if exit_code != 130 or not background_result.get("cleanup_confirmed"):
                    record(effect_uncertain=True)
                    return 6
                record(cancellation_confirmed=True)
                print(f"[INFO] Agent launch cancelled: session={session_id}")
                return 130
            launcher_pid = background_result["launcher_pid"]
            log_path = background_result["log_path"]
            record(launcher_pid=launcher_pid, log_path=log_path,
                   startup_confirmed=False, submission_confirmed=True)
            print(
                f"[INFO] Agent submitted: session={session_id} "
                f"launcher_pid={launcher_pid} mode={effective_mode} background=yes"
            )
            print(f"[INFO] Launch log: {log_path}")
            print("[INFO] Startup is not confirmed; inspect the launch log and workspace task list")
            print("[INFO] Watch: topsailai workspace")
            print(f"[INFO] Resume when idle: topsailai project resume {session_id}")
            return 0

        print(
            f"[INFO] Launching agent: workspace={folder} mode={effective_mode} "
            f"background=no session={session_id}"
        )
        command = (
            [driver] if driver
            else ["topsailai_launch_agent", "--subprocess", "--session-id", session_id]
        )
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
        if child_stdout is not None:
            # Keep the caller's stdout free for one result document; the
            # launched agent's own output stays observable on stderr.
            kwargs["stdout"] = child_stdout
        # Late fail-closed revalidation immediately before the owned child is
        # spawned, after all preparation has completed.
        refusal = refuse_if_not_ready()
        if refusal is not None:
            return refusal
        try:
            child = spawn(argv, **kwargs)
        except (OSError, ValueError) as error:
            print(f"[ERROR] Agent launch failed: {error}", file=sys.stderr)
            return 5
        record(launcher_pid=getattr(child, "pid", None), startup_confirmed=False,
               spawn_confirmed=True)
        try:
            code = child.wait()
        except KeyboardInterrupt:
            if not _stop_owned_child(child):
                record(effect_uncertain=True)
                print(f"[ERROR] Agent launch custody unresolved: session={session_id}", file=sys.stderr)
                return 6
            record(cancellation_confirmed=True)
            print(f"[ERROR] Agent launch interrupted: session={session_id}", file=sys.stderr)
            return 130
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"[ERROR] Agent launcher wait failed: {error}", file=sys.stderr)
            if not _stop_owned_child(child):
                record(effect_uncertain=True)
                print(f"[ERROR] Agent launch custody unresolved: session={session_id}", file=sys.stderr)
                return 6
            return 5
        output = (
            f"[INFO] Agent launcher exited: code={code} session={session_id}"
            if code == 0
            else f"[ERROR] Agent launcher exited: code={code} session={session_id}"
        )
        print(output, file=sys.stdout if code == 0 else sys.stderr)
        record(child_exit_code=code, launcher_exit_observed=True)
        result = code if code >= 0 else 128 + (-code)
    except KeyboardInterrupt:
        if child is not None and not _stop_owned_child(child):
            record(effect_uncertain=True)
            print(f"[ERROR] Agent launch custody unresolved: session={session_id}", file=sys.stderr)
            result = 6
        else:
            record(cancellation_confirmed=True)
            print(f"[ERROR] Agent launch interrupted: session={session_id}", file=sys.stderr)
            result = 130
    except (RuntimeError, ValueError, OSError) as error:
        if child is not None:
            print(f"[ERROR] Agent launcher failed after spawn: {error}", file=sys.stderr)
            if not _stop_owned_child(child):
                record(effect_uncertain=True)
                result = 6
            else:
                result = 5
        else:
            print(f"[ERROR] Agent launch preparation failed: {error}", file=sys.stderr)
            result = 4
    except Exception as error:
        from cli_topsailai.agent_launch_background import BackgroundUnconfirmed

        if isinstance(error, BackgroundUnconfirmed):
            record(effect_uncertain=True)
            print(f"[ERROR] Agent launch custody unresolved: {error}", file=sys.stderr)
            result = 6
        else:
            print(f"[ERROR] Agent launch failed: {error}", file=sys.stderr)
            if child is not None and not _stop_owned_child(child):
                record(effect_uncertain=True)
                result = 6
            else:
                result = 5
    return result
