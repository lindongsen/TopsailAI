#!/bin/bash
# Mock processor script for integration testing
# This script simulates the TOPSAILAI_AGENT_DAEMON_PROCESSOR
# It calls back to the API to report results

BASE_URL="${TOPSAILAI_AGENT_DAEMON_BASE_URL:-http://localhost:7373}"
SESSION_ID="$TOPSAILAI_SESSION_ID"
MSG_ID="$TOPSAILAI_MSG_ID"
TASK="$TOPSAILAI_TASK"

echo "Processor called with:"
echo "  TOPSAILAI_MSG_ID: $MSG_ID"
echo "  TOPSAILAI_TASK: $TASK"
echo "  TOPSAILAI_SESSION_ID: $SESSION_ID"
echo "  BASE_URL: $BASE_URL"

# Simulate processing time
sleep 1

# Determine behavior based on message content
# If message contains "task" keyword, generate a task result
# Otherwise, reply directly
if echo "$TASK" | grep -qi "task"; then
    # Generate a task result
    TASK_ID="task-$(date +%s)-$$"
    TASK_RESULT="Task completed for: $TASK"
    
    echo "Generating task result..."
    echo "  task_id: $TASK_ID"
    echo "  task_result: $TASK_RESULT"
    
    # Call SetTaskResult API
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/task" \
        -H "Content-Type: application/json" \
        -d "{
            \"session_id\": \"$SESSION_ID\",
            \"processed_msg_id\": \"$MSG_ID\",
            \"task_id\": \"$TASK_ID\",
            \"task_result\": \"$TASK_RESULT\"
        }")
    
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | sed '$d')
    
    echo "SetTaskResult API response:"
    echo "  HTTP Code: $HTTP_CODE"
    echo "  Body: $BODY"
else
    # Reply directly with a message
    REPLY_MESSAGE="Direct reply to: $TASK"
    
    echo "Sending direct reply..."
    echo "  reply_message: $REPLY_MESSAGE"
    
    # Call ReceiveMessage API with processed_msg_id to update the session
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/message" \
        -H "Content-Type: application/json" \
        -d "{
            \"session_id\": \"$SESSION_ID\",
            \"message\": \"$REPLY_MESSAGE\",
            \"role\": \"assistant\",
            \"processed_msg_id\": \"$MSG_ID\"
        }")
    
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | sed '$d')
    
    echo "ReceiveMessage API response:"
    echo "  HTTP Code: $HTTP_CODE"
    echo "  Body: $BODY"
fi

# Exit successfully
exit 0