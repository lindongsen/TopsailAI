#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-13
  Purpose:
'''

from topsailai.workspace.lock_tool import (
    ctxm_try_session_lock,
)

STATUS_PROCESSING = "processing"
STATUS_IDLE = "idle"

with ctxm_try_session_lock(timeout=1) as data:
    if data.get("fp"):
        # lock ok, no task is working
        print(STATUS_IDLE)
    else:
        print(STATUS_PROCESSING)
