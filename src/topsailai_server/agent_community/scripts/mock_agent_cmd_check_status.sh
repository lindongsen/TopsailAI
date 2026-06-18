#!/bin/bash
# Mock agent status check command.
# Returns idle/processing based on a simple deterministic rule.

if [ -n "$ACS_AGENT_MESSAGE" ]; then
  echo "processing"
else
  echo "idle"
fi

exit 0
