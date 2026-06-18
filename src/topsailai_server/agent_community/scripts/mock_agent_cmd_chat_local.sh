#!/usr/bin/env bash
set -euo pipefail
# Local offline mock agent chat script for manual testing.
# Prints a deterministic response based on ACS_AGENT_MESSAGE.

MSG="${ACS_AGENT_MESSAGE:-}"
SENDER="${ACS_SENDER_NAME:-unknown}"
GROUP="${ACS_GROUP_NAME:-unknown}"

echo "Mock agent received message from ${SENDER} in group ${GROUP}."
echo ""
echo "Original context:"
printf '%s\n' "${MSG}"
echo ""
echo "---"
echo "response: This is a mock agent response."
