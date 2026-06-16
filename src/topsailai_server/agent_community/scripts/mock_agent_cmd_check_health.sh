#!/bin/bash
# Mock agent health check using curl

API_BASE="${ACS_AGENT_API_BASE:-http://127.0.0.1:18080}"
API_KEY="${ACS_AGENT_API_KEY:-}"
API_AUTH="${ACS_AGENT_API_AUTH:-bearer}"

AUTH_HEADER=""
if [ -n "$API_KEY" ]; then
    AUTH_HEADER="Authorization: Bearer ${API_KEY}"
fi

if [ -n "$AUTH_HEADER" ]; then
    RESPONSE=$(curl -sf -H "$AUTH_HEADER" "${API_BASE}/health" 2>/dev/null)
else
    RESPONSE=$(curl -sf "${API_BASE}/health" 2>/dev/null)
fi

if [ $? -eq 0 ]; then
    echo "$RESPONSE"
    exit 0
else
    echo "Health check failed"
    exit 1
fi
