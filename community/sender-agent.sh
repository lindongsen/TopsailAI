#!/bin/bash
# Author: DawsonLin
# Email: lin_dongsen@126.com
# Created: 2026-03-28
# Purpose:

# env
EXE_FILE=${0}
ENV_FILE="${EXE_FILE%.*}.env"
. "${ENV_FILE}"

while read -r line; do
  [ -n "${line}" ] || continue
  c1=${line::1}
  if [ "${c1}" == "#" ] || [ "${c1}" == " " ] || [ "${c1}" == "\t" ]; then
    continue
  fi
  KEY="${line%%=*}"
  export ${KEY}
done < "${ENV_FILE}"


TOPSAILAI_ENABLE_SESSION_LOCK=0 \
TOPSAILAI_SESSION_LOCK_ON_SKILLS="ai-community" \
TOPSAILAI_SESSION_REFRESH_ON_SKILLS="ai-community" \
TOPSAILAI_AGENT_TYPE="react_community" \
agent_chats
