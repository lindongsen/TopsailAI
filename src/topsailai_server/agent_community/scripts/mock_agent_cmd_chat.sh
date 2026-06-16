#!/bin/bash
# Mock agent chat using curl

API_BASE="${ACS_AGENT_API_BASE:-http://127.0.0.1:18080}"
API_KEY="${ACS_AGENT_API_KEY:-}"
API_AUTH="${ACS_AGENT_API_AUTH:-bearer}"

AUTH_HEADER=""
if [ -n "$API_KEY" ]; then
    AUTH_HEADER="Authorization: Bearer ${API_KEY}"
fi

# Build JSON payload
PAYLOAD=$(cat <<EOF
{
  "message": "${ACS_AGENT_MESSAGE}",
  "mode": "${ACS_AGENT_MODE:-agent}",
  "agent_id": "${ACS_AGENT_ID}",
  "agent_name": "${ACS_AGENT_NAME}",
  "group_id": "${ACS_GROUP_ID}",
  "sender_id": "${ACS_SENDER_ID}",
  "message_id": "${ACS_MESSAGE_ID}"
}
EOF
)

if [ -n "$AUTH_HEADER" ]; then
    RESPONSE=$(curl -sf -H "Content-Type: application/json" -H "$AUTH_HEADER" -d "$PAYLOAD" "${API_BASE}/chat" 2>/dev/null)
else
    RESPONSE=$(curl -sf -H "Content-Type: application/json" -d "$PAYLOAD" "${API_BASE}/chat" 2>/dev/null)
fi

if [ $? -eq 0 ]; then
    # Extract response text from JSON
    echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('response',''))" 2>/dev/null || echo "$RESPONSE"
    exit 0
else
    echo "Chat request failed"
    exit 1
fi
