#!/bin/bash
#
# Integration Test Runner for agent_daemon
# This script sets up the environment and runs all integration tests
#

set -e

# Set integration directory
INTEGRATION_DIR="/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration"

# Set HOME environment variable for integration testing
export HOME="$INTEGRATION_DIR"

# Set environment variables for worker scripts
export TOPSAILAI_AGENT_DAEMON_PROCESSOR="$INTEGRATION_DIR/mock_processor.sh"
export TOPSAILAI_AGENT_DAEMON_SUMMARIZER="$INTEGRATION_DIR/mock_summarizer.sh"
export TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER="$INTEGRATION_DIR/mock_state_checker.sh"

echo "=========================================="
echo "  Agent Daemon Integration Test Runner"
echo "=========================================="
echo ""
echo "HOME: $HOME"
echo "PROCESSOR: $TOPSAILAI_AGENT_DAEMON_PROCESSOR"
echo "SUMMARIZER: $TOPSAILAI_AGENT_DAEMON_SUMMARIZER"
echo "STATE_CHECKER: $TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER"
echo ""

# Clean up old state files
echo "Cleaning up old state files..."
rm -f /tmp/agent_daemon_state_*

# Clean up old server logs
echo "Cleaning up old server logs..."
> "$INTEGRATION_DIR/server.log" 2>/dev/null || true

# Run the basic integration test
echo ""
echo "=========================================="
echo "  Running Basic Integration Test"
echo "=========================================="
echo ""

cd "$INTEGRATION_DIR"
python3 integration_test.py
INTEGRATION_TEST_RESULT=$?

# Run the cron integration test
echo ""
echo "=========================================="
echo "  Running Cron Integration Test"
echo "=========================================="
echo ""

python3 test_cron_integration.py
CRON_TEST_RESULT=$?

# Clean up after tests
echo ""
echo "=========================================="
echo "  Cleanup"
echo "=========================================="
echo ""

echo "Cleaning up state files..."
rm -f /tmp/agent_daemon_state_*

# Print summary
echo ""
echo "=========================================="
echo "  Test Summary"
echo "=========================================="
echo ""

if [ $INTEGRATION_TEST_RESULT -eq 0 ]; then
    echo "✓ Basic Integration Test: PASSED"
else
    echo "✗ Basic Integration Test: FAILED (exit code: $INTEGRATION_TEST_RESULT)"
fi

if [ $CRON_TEST_RESULT -eq 0 ]; then
    echo "✓ Cron Integration Test: PASSED"
else
    echo "✗ Cron Integration Test: FAILED (exit code: $CRON_TEST_RESULT)"
fi

echo ""

# Exit with appropriate code
if [ $INTEGRATION_TEST_RESULT -eq 0 ] && [ $CRON_TEST_RESULT -eq 0 ]; then
    echo "ALL TESTS PASSED!"
    exit 0
else
    echo "SOME TESTS FAILED!"
    exit 1
fi