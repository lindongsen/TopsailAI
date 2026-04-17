#!/usr/bin/env python3
"""
Mock Processor Script for Live Integration Tests

This script simulates the TOPSAILAI_AGENT_DAEMON_PROCESSOR behavior.
It reads environment variables, simulates processing a message, and calls
the callback API to update the processed_msg_id.

Usage:
    This script is called by the agent_daemon when processing messages.
    It should be configured via the --processor CLI argument.

Environment Variables:
    TOPSAILAI_MSG_ID: The message ID being processed
    TOPSAILAI_TASK: The message content/task to process
    TOPSAILAI_SESSION_ID: The session ID
    TOPSAILAI_AGENT_DAEMON_URL: The base URL of the agent daemon (default: http://localhost:7373)
"""

import os
import sys
import time
import urllib.request
import urllib.error
import json


def call_api(endpoint, data):
    """
    Call the agent daemon API endpoint.
    
    Args:
        endpoint: API endpoint path (e.g., '/api/v1/message/receive')
        data: Dictionary of data to send
        
    Returns:
        tuple: (success: bool, response_data: dict)
    """
    base_url = os.environ.get('TOPSAILAI_AGENT_DAEMON_URL', 'http://localhost:7373')
    url = f"{base_url}{endpoint}"
    
    json_data = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=json_data,
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('code', 0) == 0, result
    except urllib.error.URLError as e:
        print(f"API call failed: {e}", file=sys.stderr)
        return False, {}
    except Exception as e:
        print(f"API call error: {e}", file=sys.stderr)
        return False, {}


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
    
    # Call the callback API to update processed_msg_id
    # According to the spec, processor should call ReceiveMessage API
    # with the processed_msg_id to mark the message as processed
    success, response = call_api('/api/v1/message/receive', {
        'session_id': session_id,
        'message': task_result,
        'role': 'assistant',
        'processed_msg_id': msg_id
    })
    
    if success:
        print(f"Callback API called successfully")
    else:
        print(f"Callback API call failed, but continuing...")
    
    # Exit successfully
    return 0


if __name__ == '__main__':
    sys.exit(main())
