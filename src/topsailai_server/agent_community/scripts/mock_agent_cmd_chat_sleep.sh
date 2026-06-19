#!/usr/bin/env bash
# Mock agent chat command for testing
# Sleeps for MOCK_AGENT_SLEEP_MS (default 0) then echoes a canned response.
set -e
SLEEP_MS="${MOCK_AGENT_SLEEP_MS:-0}"
if [ "$SLEEP_MS" -gt 0 ]; then
  sleep "0.$SLEEP_MS" 2>/dev/null || sleep 1
fi
echo "MOCK_AGENT_RESPONSE from $ACS_AGENT_ID mode=$ACS_AGENT_MODE"
