#!/usr/bin/env python3
"""
Mock processor script for E2E integration testing.

This script simulates the TOPSAILAI_AGENT_DAEMON_PROCESSOR behavior for testing.
It reads environment variables and calls the appropriate callback based on test mode.

Environment Variables:
    TOPSAILAI_MSG_ID: The message ID being processed
    TOPSAILAI_TASK: The message content/task
    TOPSAILAI_SESSION_ID: The session ID
    TOPSAILAI_TEST_MODE: "direct_answer" or "task_mode"
    TOPSAILAI_AGENT_DAEMON_HOST: Host for API calls (default: localhost)
    TOPSAILAI_AGENT_DAEMON_PORT: Port for API calls (default: 7373)

Usage:
    export TOPSAILAI_MSG_ID=xxx
    export TOPSAILAI_TASK="test task"
    export TOPSAILAI_SESSION_ID=xxx
    export TOPSAILAI_TEST_MODE=direct_answer  # or task_mode
    python mock_processor_e2e.py
"""

import os
import sys
import argparse
import requests

# Add the parent directory to the path for imports
sys.path.insert(0, '/root/ai/TopsailAI/src')

from topsailai_server.agent_daemon import logger


def get_env(key, default=None):
    """Get environment variable with optional default"""
    return os.environ.get(key, default)


def call_processor_callback(final_answer, task_id=None):
    """
    Call the processor_callback.py script to report results.
    
    Args:
        final_answer: The result message or task result
        task_id: Optional task ID for task mode
        
    Returns:
        bool: True if successful, False otherwise
    """
    # Set environment variables for the callback script
    env = os.environ.copy()
    env['TOPSAILAI_FINAL_ANSWER'] = final_answer
    env['TOPSAILAI_SESSION_ID'] = get_env('TOPSAILAI_SESSION_ID')
    env['TOPSAILAI_MSG_ID'] = get_env('TOPSAILAI_MSG_ID')
    
    if task_id:
        env['TOPSAILAI_TASK_ID'] = task_id
    
    # Import and run the callback function directly
    try:
        from scripts.processor_callback import call_set_task_result, call_receive_message
        
        host = get_env('TOPSAILAI_AGENT_DAEMON_HOST', 'localhost')
        port = get_env('TOPSAILAI_AGENT_DAEMON_PORT', '7373')
        base_url = f"http://{host}:{port}"
        
        session_id = env['TOPSAILAI_SESSION_ID']
        msg_id = env['TOPSAILAI_MSG_ID']
        
        if task_id:
            logger.info("Calling SetTaskResult API with task_id: %s", task_id)
            return call_set_task_result(
                session_id=session_id,
                processed_msg_id=msg_id,
                task_id=task_id,
                task_result=final_answer,
                base_url=base_url
            )
        else:
            logger.info("Calling ReceiveMessage API for direct answer")
            return call_receive_message(
                session_id=session_id,
                processed_msg_id=msg_id,
                message=final_answer,
                role="assistant",
                base_url=base_url
            )
    except Exception as e:
        logger.exception("Failed to call processor callback: %s", e)
        return False


def process_direct_answer(task_content):
    """
    Process a message with direct answer mode.
    Simulates a processor that generates an immediate response.
    
    Args:
        task_content: The original message content
        
    Returns:
        bool: True if successful
    """
    logger.info("Processing in DIRECT ANSWER mode")
    logger.info("Task content: %s", task_content)
    
    # Generate a direct answer
    answer = f"Direct answer to: {task_content}"
    
    return call_processor_callback(final_answer=answer, task_id=None)


def process_task_mode(task_content):
    """
    Process a message with task mode.
    Simulates a processor that generates a task and reports result.
    
    Args:
        task_content: The original message content
        
    Returns:
        bool: True if successful
    """
    logger.info("Processing in TASK MODE")
    logger.info("Task content: %s", task_content)
    
    # Generate a task ID
    import uuid
    task_id = f"task-{uuid.uuid4().hex[:8]}"
    
    # Generate task result
    task_result = f"Task completed for: {task_content}"
    
    logger.info("Generated task_id: %s", task_id)
    
    return call_processor_callback(final_answer=task_result, task_id=task_id)


def main():
    """Main entry point for mock processor"""
    parser = argparse.ArgumentParser(
        description='Mock processor for E2E integration testing'
    )
    parser.add_argument(
        '--mode',
        choices=['direct_answer', 'task_mode'],
        help='Test mode: direct_answer or task_mode'
    )
    parser.add_argument(
        '--task',
        help='Task content to process'
    )
    
    args = parser.parse_args()
    
    # Get environment variables
    test_mode = args.mode or get_env('TOPSAILAI_TEST_MODE', 'direct_answer')
    task_content = args.task or get_env('TOPSAILAI_TASK', 'Default test task')
    session_id = get_env('TOPSAILAI_SESSION_ID', 'unknown-session')
    msg_id = get_env('TOPSAILAI_MSG_ID', 'unknown-msg')
    
    logger.info("=" * 50)
    logger.info("Mock Processor E2E Started")
    logger.info("=" * 50)
    logger.info("Session ID: %s", session_id)
    logger.info("Message ID: %s", msg_id)
    logger.info("Test Mode: %s", test_mode)
    logger.info("Task Content: %s", task_content)
    logger.info("=" * 50)
    
    # Process based on mode
    if test_mode == 'direct_answer':
        success = process_direct_answer(task_content)
    elif test_mode == 'task_mode':
        success = process_task_mode(task_content)
    else:
        logger.error("Unknown test mode: %s", test_mode)
        sys.exit(1)
    
    logger.info("=" * 50)
    if success:
        logger.info("Mock Processor E2E Completed Successfully")
        sys.exit(0)
    else:
        logger.error("Mock Processor E2E Failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
