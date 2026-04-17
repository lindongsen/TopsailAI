#!/bin/bash
#
# Mock processor script for integration testing
# This script simulates the TOPSAILAI_AGENT_DAEMON_PROCESSOR functionality
#
# It processes the message and calls the callback API to update processed_msg_id
#

echo "=== Mock Processor Started ==="
echo "Session ID: ${TOPSAILAI_SESSION_ID:-N/A}"
echo "Message ID: ${TOPSAILAI_MSG_ID:-N/A}"
echo "Task: ${TOPSAILAI_TASK:-N/A}"
echo "=== Processing Complete ==="

# Generate a mock result that matches test expectations
# The test expects "Direct reply to:" or "Direct answer to:" in the response
RESULT="Direct reply to: ${TOPSAILAI_TASK:-Task completed successfully}"

# Set the final answer for callback
export TOPSAILAI_FINAL_ANSWER="$RESULT"

# Call the processor callback script to update processed_msg_id
# The script is located at: tests/integration/mock_processor.sh
# We need to go up 2 levels: integration -> agent_daemon -> scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CALLBACK_SCRIPT="$SCRIPT_DIR/../../scripts/processor_callback.py"

if [ -f "$CALLBACK_SCRIPT" ]; then
    echo "Calling processor callback..."
    python3 "$CALLBACK_SCRIPT"
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 0 ]; then
        echo "Callback successful"
    else
        echo "Callback failed with exit code: $EXIT_CODE"
    fi
else
    echo "Callback script not found: $CALLBACK_SCRIPT"
    echo "Result: $RESULT"
fi

echo "Result: $RESULT"
exit 0
