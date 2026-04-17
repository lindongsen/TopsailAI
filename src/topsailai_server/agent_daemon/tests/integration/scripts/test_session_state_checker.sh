#!/bin/bash
#
# test_session_state_checker.sh - Mock session state checker for integration testing
#
# This script simulates the TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER functionality.
# It checks the state of a session (idle/processing) based on the session ID.
#
# Environment Variables:
#   - TOPSAILAI_SESSION_ID: The session ID to check
#
# Output:
#   Prints either "idle" or "processing" to stdout
#
# Exit Codes:
#   0 - Success
#   1 - Error (session not found, etc.)
#
# Usage:
#   Used by integration tests to verify session state checking workflow.
#   This is a mock implementation that always returns "idle" for testing.
#

# Log the received session ID for debugging
echo "[test_session_state_checker] Received state check request"
echo "[test_session_state_checker] TOPSAILAI_SESSION_ID: ${TOPSAILAI_SESSION_ID:-NOT_SET}"

# Check if session ID is provided
if [ -z "$TOPSAILAI_SESSION_ID" ]; then
    echo "[test_session_state_checker] Error: TOPSAILAI_SESSION_ID not provided"
    exit 1
fi

# For testing purposes, always return "idle"
# In a real implementation, this would check actual session state
echo "[test_session_state_checker] Session ${TOPSAILAI_SESSION_ID} state: idle"

# Print the state to stdout (this is what the daemon reads)
echo "idle"

# Exit with success code
exit 0
