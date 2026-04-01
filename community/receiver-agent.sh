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

# env
EXE_FILE=${0}
ENV_FILE="${EXE_FILE%.*}.env"
. "${ENV_FILE}"

# hook
[ "$MESSENGER_MESSAGE" == "ping" ] && echo "${TOPSAILAI_AGENT_NAME}: pong" && exit 0
[ "$MESSENGER_MESSAGE" == "health check" ] && echo "${TOPSAILAI_AGENT_NAME}: healthy" && exit 0

# only for debug
[ "$MESSENGER_MESSAGE" == "debug" ] && {
  echo "${TOPSAILAI_AGENT_NAME}: debug"

  echo ""
  echo "Environ:"
  echo "---"
  env
  echo "---"

  echo ""
  echo "EnvFile: ${ENV_FILE}"
  echo "---"
  cat "${ENV_FILE}"
  echo "---"

  exit 0
}

[ "${MESSENGER_RECEIVER}" == "${TOPSAILAI_AGENT_NAME}" ] || exit 1

export SESSION_ID="${MESSENGER_RECEIVER}+${MESSENGER_SENDER}"
export SYSTEM_PROMPT="${SYSTEM_PROMPT}\n\n---\nYour name is ${TOPSAILAI_AGENT_NAME}\n---\n\n"

export DEBUG=0
export TOPSAILAI_INTERACTIVE_MODE=0
export TOPSAILAI_NEED_SYMBOL_FOR_ANSWER=1
export TOPSAILAI_ENABLE_SESSION_LOCK=1


while read -r line; do
  [ -n "${line}" ] || continue
  c1=${line::1}
  if [ "${c1}" == "#" ] || [ "${c1}" == " " ] || [ "${c1}" == "\t" ]; then
    continue
  fi
  KEY="${line%%=*}"
  export ${KEY}
done < "${ENV_FILE}"

# lock
LOCK_DIR=/topsailai/lock/
mkdir -p "${LOCK_DIR}"

# start
_HEAD_MSG="
# AI-Community
'${MESSENGER_SENDER}' Say: "
flock -E 203 -w 0 -x "${LOCK_DIR}/receiver_${MESSENGER_MODE:-sync}.lock" agent_chat "${_HEAD_MSG}" "${MESSENGER_MESSAGE}"
RET_CODE=$?
[ ${RET_CODE} -eq 203 ] && {
    echo "(${TOPSAILAI_AGENT_NAME}) is busy"
    exit 0
}
exit ${RET_CODE}
