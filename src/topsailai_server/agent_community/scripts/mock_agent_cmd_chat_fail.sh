#!/usr/bin/env bash
# Mock agent chat command that always fails
>&2 echo "MOCK_AGENT_FAILURE from $ACS_AGENT_ID mode=$ACS_AGENT_MODE"
exit 1
