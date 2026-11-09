#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-13
Purpose: Check session state (idle/processing) for agent_daemon
'''

import os
import argparse
import json
import sys

import _import_topsailai  # noqa: F401

from topsailai.workspace.lock_tool import (
    ctxm_try_session_lock,
)

STATUS_PROCESSING = "processing"
STATUS_IDLE = "idle"


def _emit_json(session_id, status, error_code=None, message=None):
    """Print one structured result so callers never parse a bare word."""
    payload = {
        "session_id": session_id,
        "status": status,
        "error_code": error_code,
        "message": message,
    }
    print(json.dumps(payload, ensure_ascii=True))
    return 0 if error_code is None else 1


def main():
    """Check if a session is idle or processing."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Check session state (idle/processing) for agent_daemon")
    parser.add_argument("-s", "--session", dest="session_id", help="Session ID to check")
    parser.add_argument("--json", action="store_true",
                        help="emit one structured JSON result instead of a bare status word")
    args = parser.parse_args()

    # Get session_id from command line or environment
    session_id = args.session_id or os.environ.get("TOPSAILAI_SESSION_ID")

    if not session_id:
        if args.json:
            sys.exit(_emit_json(None, None, "missing_session_id",
                                "TOPSAILAI_SESSION_ID not set and no --session provided"))
        print("Error: TOPSAILAI_SESSION_ID not set and no --session provided", file=sys.stderr)
        sys.exit(1)

    # Try to acquire session lock
    # If lock acquired (fp is not None), no task is working -> idle
    # If lock failed (fp is None), task is running -> processing
    try:
        with ctxm_try_session_lock(session_id=session_id, timeout=1, to_delete_lock_file=False) as data:
            if data.get("fp"):
                # Lock acquired, no task is working
                status = STATUS_IDLE
            else:
                # Lock not acquired, task is running
                status = STATUS_PROCESSING
    except Exception as e:
        if args.json:
            sys.exit(_emit_json(session_id, None, "status_unavailable",
                                f"Error checking session state: {e}"))
        print(f"Error checking session state: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        sys.exit(_emit_json(session_id, status))
    print(status)


if __name__ == "__main__":
    main()
