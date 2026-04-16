#!/usr/bin/env python3
"""
Mock Processor Script for Live Integration Tests

This script simulates the TOPSAILAI_AGENT_DAEMON_PROCESSOR behavior.
It reads environment variables and simulates processing a message.

Usage:
    This script is called by the agent_daemon when processing messages.
    It should be configured via the --processor CLI argument.

Environment Variables:
    TOPSAILAI_MSG_ID: The message ID being processed
    TOPSAILAI_TASK: The message content/task to process
    TOPSAILAI_SESSION_ID: The session ID
"""

import os
import sys
import time
import json

def main():
    """Mock processor main function"""
    msg_id = os.environ.get('TOPSAILAI_MSG_ID', '')
    task = os.environ.get('TOPSAILAI_TASK', '')
    session_id = os.environ.get('TOPSAILAI_SESSION_ID', '')
    
    print(f"Mock Processor started")
    print(f"  msg_id: {msg_id}")
    print(f"  session_id: {session_id}")
    print(f"  task: {task[:100]}..." if len(task) > 100 else f"  task: {task}")
    
    # Simulate some processing time
    time.sleep(0.5)
    
    # Generate a mock task result
    task_result = f"Processed: {task[:50]}..." if len(task) > 50 else f"Processed: {task}"
    
    print(f"Mock Processor completed")
    print(f"  result: {task_result}")
    
    # Exit successfully
    return 0

if __name__ == '__main__':
    sys.exit(main())
