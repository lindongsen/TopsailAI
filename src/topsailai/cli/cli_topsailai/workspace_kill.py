"""Confirmed termination of exactly one displayed workspace PID.

Author: DawsonLin
"""

import os
import signal


def kill_workspace_row(rows, index, *, read_input):
    """Confirm and submit SIGTERM for a displayed row; never infer another PID."""
    if type(index) is not int or not 0 <= index < len(rows):
        print("[ERROR] Invalid workspace row number.")
        return False
    row = rows[index]
    pid = row.get("workspace_pid")
    session = row.get("session_id") or "(temp)"
    if type(pid) is not int or pid <= 0 or pid > 2147483647:
        print(f"[ERROR] Row {index + 1}, session={session}: no valid displayed PID.")
        return False
    if pid == 1 or pid == os.getpid():
        print(f"[ERROR] Refusing protected PID={pid}, session={session}.")
        return False
    target = f"row {index + 1}, session={session}, PID={pid}"
    previous_handler = signal.getsignal(signal.SIGINT)
    try:
        # Confirmation interrupts must not enter the CLI's global child cleanup.
        signal.signal(signal.SIGINT, signal.default_int_handler)
        answer = read_input(
            f"[WARN] Terminate {target} with SIGTERM? Unsaved work may be lost. [y/N] "
        )
    except (EOFError, KeyboardInterrupt):
        print(f"\n[INFO] Cancelled termination of {target}.")
        return False
    finally:
        signal.signal(signal.SIGINT, previous_handler)
    if answer.strip().lower() not in ("y", "yes"):
        print(f"[INFO] Cancelled termination of {target}.")
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"[ERROR] SIGTERM failed for {target}: {type(exc).__name__}: {exc}")
        return False
    print(f"[INFO] SIGTERM sent to {target}; process exit is not confirmed.")
    return True
