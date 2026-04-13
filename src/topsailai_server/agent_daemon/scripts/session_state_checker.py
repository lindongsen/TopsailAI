#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-13
  Purpose: Check session state (idle/processing) for agent_daemon
'''

import os
import sys

from topsailai.workspace.lock_tool import (
    ctxm_try_session_lock,
)

STATUS_PROCESSING = "processing"
STATUS_IDLE = "idle"


def main():
    """Check if a session is idle or processing."""
    # Get session_id from environment
    session_id = os.environ.get("TOPSAILAI_SESSION_ID")
    
    if not session_id:
        print("Error: TOPSAILAI_SESSION_ID not set", file=sys.stderr)
        sys.exit(1)
    
    # Try to acquire session lock
    # If lock acquired (fp is not None), no task is working -> idle
    # If lock failed (fp is None), task is running -> processing
    try:
        with ctxm_try_session_lock(session_id=session_id, timeout=1) as data:
            if data.get("fp"):
                # Lock acquired, no task is working
                print(STATUS_IDLE)
            else:
                # Lock not acquired, task is running
                print(STATUS_PROCESSING)
    except Exception as e:
        print(f"Error checking session state: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()