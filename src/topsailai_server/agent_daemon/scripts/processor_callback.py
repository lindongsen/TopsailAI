#!/usr/bin/env python3
'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-13
  Purpose:
    Callback script for processor to report results back to agent_daemon.
    - If TOPSAILAI_TASK_ID exists: call SetTaskResult API
    - Otherwise: call ReceiveMessage API
'''

import os
import sys
import requests

from topsailai.utils.thread_local_tool import set_thread_name
from topsailai_server.agent_daemon import logger


def get_env(key, required=True):
    """Get environment variable, optionally required"""
    value = os.environ.get(key)
    if required and not value:
        logger.error("Missing required environment variable: %s", key)
        sys.exit(1)
    return value


def call_set_task_result(session_id, processed_msg_id, task_id, task_result, base_url):
    """Call SetTaskResult API to report task completion"""
    url = f"{base_url}/api/v1/task"
    payload = {
        "session_id": session_id,
        "processed_msg_id": processed_msg_id,
        "task_id": task_id,
        "task_result": task_result
    }

    logger.info("Calling SetTaskResult API: %s", url)
    logger.info("Payload: %s", payload)

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        logger.info("SetTaskResult response: %s", response.text)
        return True
    except requests.exceptions.RequestException as e:
        logger.exception("Failed to call SetTaskResult API: %s", e)
        return False


def call_receive_message(session_id, processed_msg_id, message, role, base_url):
    """Call ReceiveMessage API to send direct reply"""
    url = f"{base_url}/api/v1/message"
    payload = {
        "session_id": session_id,
        "processed_msg_id": processed_msg_id,
        "message": message,
        "role": role
    }

    logger.info("Calling ReceiveMessage API: %s", url)
    logger.info("Payload: %s", payload)

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        logger.info("ReceiveMessage response: %s", response.text)
        return True
    except requests.exceptions.RequestException as e:
        logger.exception("Failed to call ReceiveMessage API: %s", e)
        return False


def main():
    """Main entry point for processor callback"""
    logger.info("Processor callback started")

    # Get required environment variables
    session_id = get_env("TOPSAILAI_SESSION_ID")
    set_thread_name(session_id)
    msg_id = get_env("TOPSAILAI_MSG_ID")
    final_answer = get_env("TOPSAILAI_FINAL_ANSWER")

    # Get optional environment variables
    task_id = os.environ.get("TOPSAILAI_TASK_ID")

    # Construct base URL from host and port
    host = os.environ.get("TOPSAILAI_AGENT_DAEMON_HOST", "localhost")
    port = os.environ.get("TOPSAILAI_AGENT_DAEMON_PORT", "7373")
    base_url = f"http://{host}:{port}"

    logger.info("Session ID: %s", session_id)
    logger.info("Message ID: %s", msg_id)
    logger.info("Task ID: %s", task_id)
    logger.info("Base URL: %s", base_url)

    # Determine which API to call based on task_id
    if task_id:
        # Task was generated, report task result
        logger.info("Task ID found, calling SetTaskResult API")
        success = call_set_task_result(
            session_id=session_id,
            processed_msg_id=msg_id,
            task_id=task_id,
            task_result=final_answer,
            base_url=base_url
        )
    else:
        # No task, send direct reply
        logger.info("No Task ID, calling ReceiveMessage API")
        success = call_receive_message(
            session_id=session_id,
            processed_msg_id=msg_id,
            message=final_answer,
            role="assistant",
            base_url=base_url
        )

    if success:
        logger.info("Processor callback completed successfully")
        sys.exit(0)
    else:
        logger.error("Processor callback failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
