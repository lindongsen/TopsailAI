"""Shared machine-readable receipt boundary for workspace commands.

Author: DawsonLin
"""

from __future__ import annotations

import json

# The stable public field set is shared with the runtime and workspace-driver
# envelopes so one consumer can parse every non-interactive receipt.
RECEIPT_FIELDS = (
    "ok", "exit_code", "action", "session_id", "pid", "delivery_state",
    "error_code", "message", "bytes_written", "request_id", "response",
    "delivery_unknown",
)

# Exit codes that mean "the command itself failed" rather than "an observed
# child exited with this status". Foreground launches preserve child statuses
# 0..255, so only these documented codes carry a receipt error classification.
KILL_ERROR_CODES = {
    2: "usage_error",
    3: "target_error",
    4: "signal_failed",
}

AGENT_ERROR_CODES = {
    2: "usage_error",
    3: "invalid_folder",
    4: "preparation_failed",
    5: "spawn_failed",
    6: "custody_unresolved",
    130: "cancelled",
}

RESUME_ERROR_CODES = {
    2: "usage_error",
    3: "session_not_found",
    4: "resume_refused",
    5: "spawn_failed",
    6: "custody_unresolved",
    130: "cancelled",
}

# Options that consume the following token, so a value such as ``-m --json``
# is never mistaken for the JSON flag itself.
_VALUE_FLAGS = frozenset({
    "-m", "--agent-mode", "-s", "--session", "-d", "--driver",
})


def json_requested(argv) -> bool:
    """Recognize ``--json`` without mistaking a consumed value for the flag."""
    index = 0
    tokens = list(argv)
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return False
        if token == "--json":
            return True
        index += 2 if token in _VALUE_FLAGS else 1
    return False


def new_receipt(action: str, *, session_id=None, pid=None) -> dict:
    """Create one receipt carrying the complete stable field set."""
    return {
        "ok": False,
        "exit_code": 2,
        "action": action,
        "session_id": session_id,
        "pid": pid,
        "delivery_state": None,
        "error_code": None,
        "message": "",
        "bytes_written": None,
        "request_id": None,
        "response": None,
        "delivery_unknown": False,
    }


def settle(receipt: dict, exit_code: int, error_codes: dict, *, message: str = "") -> dict:
    """Classify one exit code into the receipt without overstating delivery.

    A zero exit code is the only success. Documented failure codes map to their
    named error. Any other non-zero code is an observed child status, except a
    negative or out-of-range value, which is treated as a generic command error.
    """
    receipt["exit_code"] = exit_code
    receipt["ok"] = exit_code == 0
    if exit_code == 0:
        receipt["error_code"] = None
        receipt["message"] = message
        return receipt
    if exit_code in error_codes:
        error_code = error_codes[exit_code]
    elif isinstance(exit_code, int) and 1 <= exit_code <= 255:
        error_code = "child_exit_status"
    else:
        error_code = "command_failed"
    receipt["error_code"] = error_code
    receipt["message"] = message or error_code
    receipt["delivery_unknown"] = exit_code == 6
    return receipt


def emit_receipt(receipt: dict) -> None:
    """Write exactly one JSON document to stdout."""
    payload = {name: receipt.get(name) for name in RECEIPT_FIELDS}
    print(json.dumps(payload, ensure_ascii=True))


def emit_failure(action: str, exit_code: int, error_code: str, message: str,
                 *, session_id=None, pid=None) -> None:
    """Emit one failure receipt for a request that never reached execution."""
    receipt = new_receipt(action, session_id=session_id, pid=pid)
    receipt.update(
        exit_code=exit_code, ok=False, error_code=error_code,
        message=message, delivery_state="not_delivered",
        delivery_unknown=exit_code == 6,
    )
    emit_receipt(receipt)
