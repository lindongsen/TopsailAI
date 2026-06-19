#!/usr/bin/env bash
LOG_FILE="/TopsailAI/src/topsailai_server/agent_community/.tmp/mock_agent_invocations.log"
NODE_ADDR="${ACS_AGENT_API_BASE:-unknown}"
AGENT_ID="${ACS_AGENT_ID:-unknown}"
GROUP_ID="${ACS_GROUP_ID:-unknown}"
MESSAGE_ID="${ACS_MESSAGE_ID:-unknown}"
SENDER_ID="${ACS_SENDER_ID:-unknown}"
MODE="${ACS_AGENT_MODE:-unknown}"
TS=$(date -u '+%Y-%m-%dT%H:%M:%S')
echo "[$TS] NODE=$NODE_ADDR AGENT=$AGENT_ID GROUP=$GROUP_ID MSG=$MESSAGE_ID SENDER=$SENDER_ID MODE=$MODE" >> "$LOG_FILE"
echo "Mock agent $AGENT_ID on $NODE_ADDR processed message $MESSAGE_ID in group $GROUP_ID"
