#!/usr/bin/env bash
# Mock agent chat command for testing
# Sleeps for 30 seconds then echoes a canned response.
set -e
sleep 30
echo "MOCK_AGENT_RESPONSE from $ACS_AGENT_ID mode=$ACS_AGENT_MODE after 30s sleep"
