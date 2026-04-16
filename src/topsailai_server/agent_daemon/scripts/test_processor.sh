#!/bin/bash
# Test processor script - simulates message processing

CWD=$(dirname $(readlink -f "$0"))

echo "Processing message..."
echo "MSG_ID: $TOPSAILAI_MSG_ID"
echo "SESSION_ID: $TOPSAILAI_SESSION_ID"
echo "TASK: $TOPSAILAI_TASK"

# wait a short moment (0.1-0.5 seconds)
min=1
max=5
random_number=$((RANDOM % (max - min + 1) + min))
sleep 0.${random_number}

# Simulate processing - generate a task result
# This will call processor_callback.py to report the result
export TOPSAILAI_TASK_ID="test-task-$(date +%s)"
export TOPSAILAI_FINAL_ANSWER="This is a test response from the processor"

# Call the callback to report the result
"${CWD}/processor_callback.py"

echo "Processor finished"
