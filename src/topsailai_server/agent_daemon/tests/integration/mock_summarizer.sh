#!/bin/bash
# Mock summarizer script for integration testing
# This script simulates the TOPSAILAI_AGENT_DAEMON_SUMMARIZER

echo "Summarizer called with:"
echo "  TOPSAILAI_SESSION_ID: $TOPSAILAI_SESSION_ID"
echo "  TOPSAILAI_TASK: $TOPSAILAI_TASK"

# Simulate processing time
sleep 0.5

# Exit successfully
exit 0
