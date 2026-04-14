#!/bin/bash
# Author: DawsonLin
# Email: lin_dongsen@126.com
# Created: 2026-04-13
# Purpose:

CWD=$(dirname $(readlink -f "$0"))

function help() {
  echo "
Environ provided to this script:
  - TOPSAILAI_MSG_ID: Latest unprocessed msg_id from message table
  - TOPSAILAI_TASK: Message content to process
  - TOPSAILAI_SESSION_ID: Session identifier
"
  echo ""
  echo $*
  exit 1
}

[ -n "${TOPSAILAI_MSG_ID}" ] || help "ERROR: missing TOPSAILAI_MSG_ID"
[ -n "${TOPSAILAI_TASK}" ] || help "ERROR: missing TOPSAILAI_TASK"
[ -n "${TOPSAILAI_SESSION_ID}" ] || help "ERROR: TOPSAILAI_SESSION_ID"

TOPSAILAI_ENABLE_SESSION_LOCK=1 TOPSAILAI_SESSION_LOCK_WAIT_TIMEOUT=1 TOPSAILAI_SESSION_LOCK_FILE_NEED_DELETE=0 \
TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER="${CWD}/processor_callback.py env_keys=TOPSAILAI_AGENT_DAEMON_HOST,TOPSAILAI_AGENT_DAEMON_PORT,TOPSAILAI_MSG_ID" \
topsailai_agent_plan_task
