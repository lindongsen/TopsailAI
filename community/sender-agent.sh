#!/bin/bash
# Author: DawsonLin
# Email: lin_dongsen@126.com
# Created: 2026-03-28
# Purpose:

# env
EXE_FILE=${0}
ENV_FILE="${EXE_FILE%.*}.env"

if [ -e "${ENV_FILE}" ]; then
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
fi

[ -n "${SESSION_ID}" ] || {
    echo "please give a SESSION_ID to environ"
    exit 1
}

TOPSAILAI_ENABLE_SESSION_LOCK=0 \
TOPSAILAI_SESSION_LOCK_ON_SKILLS="ai-community" \
TOPSAILAI_SESSION_REFRESH_ON_SKILLS="ai-community" \
TOPSAILAI_CALL_SKILL_TIMEOUT_MAP="ai-community=600" \
TOPSAILAI_AGENT_TYPE="react_community" \
agent_chats
