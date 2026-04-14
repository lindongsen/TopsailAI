#!/bin/bash
# Mock session state checker script

echo "Session state checker called with:"
echo "  TOPSAILAI_SESSION_ID: ${TOPSAILAI_SESSION_ID:-}"
echo "  BASE_URL: ${BASE_URL:-http://localhost:7373}"

# Return idle state
echo "idle"
