#!/usr/bin/env bash
set -e
SLEEP_MS="${MOCK_AGENT_SLEEP_MS:-120000}"
if [ "$SLEEP_MS" -gt 0 ]; then
  sleep "$(awk "BEGIN {print $SLEEP_MS/1000}")" 2>/dev/null || sleep 120
fi
echo "MOCK_AGENT_RESPONSE from $ACS_AGENT_ID mode=$ACS_AGENT_MODE"
