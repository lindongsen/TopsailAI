#!/bin/bash
# Mock session state checker script for integration testing
# This script simulates the TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER
# It simulates both "idle" and "processing" states using a state file

# State file location - uses session ID to track per-session state
STATE_DIR="${TOPSAILAI_AGENT_DAEMON_STATE_DIR:-/tmp}"
STATE_FILE="$STATE_DIR/agent_daemon_state_${TOPSAILAI_SESSION_ID}"

echo "State checker called with:"
echo "  TOPSAILAI_SESSION_ID: $TOPSAILAI_SESSION_ID"
echo "  STATE_FILE: $STATE_FILE"

# Check if state file exists
if [ -f "$STATE_FILE" ]; then
    # Read the current state
    STATE=$(cat "$STATE_FILE")
    echo "Current state: $STATE"
    
    if [ "$STATE" = "processing" ]; then
        echo "processing"
        exit 0
    fi
fi

# If no state file or state is "idle", create it and return "idle"
echo "idle" > "$STATE_FILE"
echo "State set to: idle"

echo "idle"
exit 0