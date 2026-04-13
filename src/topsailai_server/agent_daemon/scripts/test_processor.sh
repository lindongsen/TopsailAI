#!/bin/bash
# Test processor script - simulates message processing

echo "Processing message..."
echo "MSG_ID: $TOPSAILAI_MSG_ID"
echo "SESSION_ID: $TOPSAILAI_SESSION_ID"
echo "TASK: $TOPSAILAI_TASK"

# Simulate processing - generate a task result
# This will call processor_callback.py to report the result
export TOPSAILAI_TASK_ID="test-task-$(date +%s)"
export TOPSAILAI_FINAL_ANSWER="This is a test response from the processor"

# Call the callback to report the result
cd /root/ai/TopsailAI/src/topsailai_server/agent_daemon
python3 scripts/processor_callback.py

echo "Processor finished"