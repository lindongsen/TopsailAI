#!/usr/bin/env python3
"""Verify `workspace kill --graceful` against a real agent waiting for input.

The unit tests prove the gate and the delivery seam in isolation. This script
proves the same path end to end: a real agent process is launched inside tmux,
the script polls the real workspace listing until that process reports the
`input` state, then runs the real command and checks the real receipt.

The agent is launched with a deterministic session name and a deterministic
session ID so the tmux session and the process can be found and cleaned up
exactly. Output is written to disk and readiness is polled, never slept.

Usage:
    python3 tests/manual/verify_workspace_kill_graceful.py

Exit code 0 means every assertion held. Any other value names the failure.
"""

import json
import os
import shutil
import subprocess
import sys
import time

WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_ROOT = os.path.dirname(WORKSPACE)
BIN_DIR = os.path.join(PROJECT_ROOT, "bin")
TMP_DIR = os.path.join(WORKSPACE, ".tmp")
TIMESTAMP = time.strftime("%Y%m%dT%H%M%S")
TMUX_SESSION = f"topsailai-graceful-{TIMESTAMP}"
AGENT_SESSION_ID = f"graceful-{TIMESTAMP}"
OUTPUT_FILE = os.path.join(TMP_DIR, f"graceful-agent-{TIMESTAMP}.log")
RECEIPT_FILE = os.path.join(TMP_DIR, f"graceful-receipt-{TIMESTAMP}.json")
READY_TIMEOUT = 120.0
EXIT_TIMEOUT = 60.0


def run(argv, timeout=60):
    """Run one command and return (exit_code, stdout, stderr)."""
    completed = subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout,
        cwd=PROJECT_ROOT,
    )
    return completed.returncode, completed.stdout, completed.stderr


def workspace_rows():
    """Return the live workspace rows, or raise when the listing fails."""
    code, out, err = run(
        [os.path.join(BIN_DIR, "topsailai"), "workspace", "list", "--json",
         "--include-session-status"],
        timeout=120,
    )
    if code != 0:
        raise RuntimeError(f"workspace list failed: code={code} stderr={err[:400]}")
    document = json.loads(out)
    return document.get("items") or document.get("data") or []


def find_row(session_id):
    """Return the row for one session ID, or None when it is not listed."""
    for row in workspace_rows():
        if row.get("session_id") == session_id:
            return row
    return None


def wait_for_input_state(session_id):
    """Poll the real listing until the agent reports it is waiting for input."""
    deadline = time.monotonic() + READY_TIMEOUT
    last = None
    while time.monotonic() < deadline:
        row = find_row(session_id)
        if row is not None:
            last = (row.get("status"), row.get("process_generation"), row.get("pid"))
            if row.get("status") == "input" and row.get("process_generation"):
                return row
        time.sleep(1.0)
    raise TimeoutError(f"agent never reached input state; last observed={last}")


def launch_agent():
    """Start the interactive agent inside tmux with output captured to disk."""
    os.makedirs(TMP_DIR, exist_ok=True)
    command = (
        f"cd {PROJECT_ROOT} && "
        f"{os.path.join(BIN_DIR, 'topsailai_launch_agent')} "
        f"--non-interactive --item default --session-id {AGENT_SESSION_ID} "
        f"2>&1 | tee {OUTPUT_FILE}"
    )
    code, out, err = run(
        ["tmux", "new-session", "-d", "-s", TMUX_SESSION, command], timeout=30,
    )
    if code != 0:
        raise RuntimeError(f"tmux launch failed: code={code} stderr={err[:400]}")


def kill_graceful(session_id, generation):
    """Run the real graceful command and return (exit_code, receipt)."""
    code, out, err = run(
        [os.path.join(BIN_DIR, "topsailai"), "workspace", "kill", session_id,
         "-g", str(generation), "--graceful", "--json"],
        timeout=120,
    )
    with open(RECEIPT_FILE, "w", encoding="utf-8") as handle:
        handle.write(out)
    try:
        receipt = json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(f"receipt was not JSON: {out[:400]} stderr={err[:400]}")
    return code, receipt


def wait_for_process_exit(pid):
    """Poll until the agent PID is gone, returning whether it exited."""
    deadline = time.monotonic() + EXIT_TIMEOUT
    while time.monotonic() < deadline:
        if not os.path.exists(f"/proc/{pid}"):
            return True
        time.sleep(0.5)
    return False


def cleanup(pid):
    """Stop exactly this tmux session and this PID, never by name pattern."""
    run(["tmux", "kill-session", "-t", TMUX_SESSION], timeout=30)
    if pid and os.path.exists(f"/proc/{pid}"):
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


def main():
    """Drive the full graceful shutdown path and report each assertion."""
    if shutil.which("tmux") is None:
        print("SKIP tmux is unavailable")
        return 0
    pid = None
    try:
        launch_agent()
        print(f"launched tmux={TMUX_SESSION} session={AGENT_SESSION_ID}")
        row = wait_for_input_state(AGENT_SESSION_ID)
        pid = row.get("pid")
        generation = row.get("process_generation")
        lock_state = (row.get("session_status") or {}).get("status")
        print(f"observed status=input pid={pid} generation={generation} lock={lock_state}")
        if lock_state != "idle":
            print(f"FAIL expected an idle lock, observed {lock_state!r}")
            return 1

        code, receipt = kill_graceful(AGENT_SESSION_ID, generation)
        print(f"receipt={json.dumps(receipt, ensure_ascii=False)}")
        if code != 0:
            print(f"FAIL expected exit 0, observed {code}")
            return 1
        if receipt.get("delivery_state") != "pipe_written":
            print(f"FAIL expected pipe_written, observed {receipt.get('delivery_state')!r}")
            return 1
        response = receipt.get("response") or {}
        if response.get("exit_confirmed") is not False:
            print(f"FAIL exit must not be claimed, observed {response.get('exit_confirmed')!r}")
            return 1
        if response.get("message") != "/exit":
            print(f"FAIL expected /exit, observed {response.get('message')!r}")
            return 1
        if response.get("agent_status") != "input":
            print(f"FAIL expected agent_status=input, observed {response.get('agent_status')!r}")
            return 1
        if response.get("session_status") != "idle":
            print(f"FAIL expected session_status=idle, observed {response.get('session_status')!r}")
            return 1

        exited = wait_for_process_exit(pid)
        if not exited:
            print(f"FAIL agent PID {pid} did not exit after /exit delivery")
            return 1
        print(f"PASS agent PID {pid} exited after /exit delivery")
        return 0
    except Exception as error:
        print(f"FAIL {type(error).__name__}: {error}")
        return 1
    finally:
        cleanup(pid)
        print(f"cleaned tmux={TMUX_SESSION} pid={pid}")


if __name__ == "__main__":
    sys.exit(main())
