#!/bin/bash
# Mock failing agent chat command for failure-handling tests.
# Simulates an agent that is healthy but fails to produce a response.
echo "Mock agent chat command failed intentionally" >&2
exit 1
