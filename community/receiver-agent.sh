#!/bin/bash
# Author: DawsonLin
# Email: lin_dongsen@126.com
# Created: 2026-03-27
# Purpose:
# Env:
#   MESSENGER_MESSAGE, message content
#   MESSENGER_MODE, sync or async
#   MESSENGER_SENDER, the sender name
#   MESSENGER_RECEIVER, me

# check
[ -n "${MESSENGER_MESSAGE}" ] || exit 1
[ -n "${MESSENGER_SENDER}" ] || exit 1
[ "$MESSENGER_MESSAGE" == "ping" ] && echo "${MESSENGER_SENDER}: pong" && exit 0
[ "$MESSENGER_MESSAGE" == "health check" ] && echo "${MESSENGER_SENDER}: healthy" && exit 0

# env
EXE_FILE=$(readlink -f "$0")
ENV_FILE="${EXE_FILE%.*}.env"
. "${ENV_FILE}"

[ "${MESSENGER_RECEIVER}" == "${TOPSAILAI_AGENT_NAME}" ] || exit 1

export SESSION_ID="${MESSENGER_RECEIVER}+${MESSENGER_SENDER}"
export SYSTEM_PROMPT="${SYSTEM_PROMPT}\n\n---\nYour name is ${TOPSAILAI_AGENT_NAME}\n---\n\n"

while read -r line; do
  [ -n "${line}" ] || continue
  c1=${line::1}
  if [ "${c1}" == "#" ] || [ "${c1}" == " " ] || [ "${c1}" == "\t" ]; then
    continue
  fi
  KEY=$(echo "${line}" | cut -d '=' -f 1)
  export ${KEY}
done < "${ENV_FILE}"

# lock
LOCK_DIR=/topsailai/lock/
mkdir -p "${LOCK_DIR}"

# start
flock -E 203 -w 0 -x "${LOCK_DIR}/receiver_${MESSENGER_MODE:-sync}.lock" agent_chat "'${MESSENGER_SENDER}' Say: " "${MESSENGER_MESSAGE}"
RET_CODE=$?
[ ${RET_CODE} -eq 203 ] && {
    echo "(${TOPSAILAI_AGENT_NAME}) is busy"
    exit 0
}
exit ${RET_CODE}
