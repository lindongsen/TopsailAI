#!/bin/bash
# Mock agent chat command that echoes back the received ACS_AGENT_MESSAGE.
# This allows deterministic verification of agent triggers without requiring an HTTP endpoint.

# Optional: log invocation for debugging
LOG_FILE="/tmp/mock_agent_cmd_chat.log"
{
  echo "=== $(date -Iseconds) ==="
  echo "ACS_AGENT_ID=$ACS_AGENT_ID"
  echo "ACS_AGENT_NAME=$ACS_AGENT_NAME"
  echo "ACS_AGENT_TYPE=$ACS_AGENT_TYPE"
  echo "ACS_AGENT_MODE=$ACS_AGENT_MODE"
  echo "ACS_GROUP_ID=$ACS_GROUP_ID"
  echo "ACS_MESSAGE_ID=$ACS_MESSAGE_ID"
  echo "ACS_SENDER_ID=$ACS_SENDER_ID"
  echo "ACS_AGENT_MESSAGE=$ACS_AGENT_MESSAGE"
} >> "$LOG_FILE"

# Echo a deterministic response that includes the agent name and a snippet of the message.
printf 'Mock agent "%s" received your message and is responding. Original message length: %d characters.\n' \
  "$ACS_AGENT_NAME" "${#ACS_AGENT_MESSAGE}"

exit 0
