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
import time
import socket
from typing import Optional, Dict, Any, Callable

CWD = os.path.dirname(__file__)
PROJECT_FOLDER = CWD
for _ in range(4):
    if os.path.exists(f"{PROJECT_FOLDER}/topsailai"):
        break
    PROJECT_FOLDER = os.path.dirname(PROJECT_FOLDER)
if os.path.exists(f"{PROJECT_FOLDER}/topsailai"):
    sys.path.insert(0, PROJECT_FOLDER)

from topsailai.utils.thread_local_tool import set_thread_name
from topsailai_server.agent_daemon import logger


def probe_port(host: str, port: int, timeout: int = 120) -> bool:
    """Probe port availability with timeout.

    Args:
        host: Target host
        port: Target port
        timeout: Maximum time to probe in seconds (default: 120)

    Returns:
        True if port is reachable, False otherwise
    """
    start_time = time.time()
    end_time = start_time + timeout

    logger.info("Starting port probe for %s:%d (timeout: %ds)", host, port, timeout)

    while time.time() < end_time:
        try:
            with socket.create_connection((host, port), timeout=5):
                logger.info("Port %s:%d is reachable", host, port)
                return True
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            elapsed = time.time() - start_time
            remaining = end_time - time.time()
            logger.debug("Port probe attempt failed for %s:%d (elapsed: %.1fs, remaining: %.1fs): %s",
                        host, port, elapsed, remaining, e)
            time.sleep(2)  # Wait 2 seconds before next probe

    logger.warning("Port probe timed out for %s:%d after %ds", host, port, timeout)
    return False


def request_with_retry(
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    timeout: int = 30,
    **kwargs: Any
) -> Optional[requests.Response]:
    """Generic HTTP request function with retry capability.

    Args:
        method: HTTP method ('get', 'post', 'put', 'delete', 'patch')
        url: Target URL
        payload: Request body (for POST/PUT/PATCH)
        max_retries: Maximum number of retry attempts (default: 3)
        retry_delay: Delay between retries in seconds (default: 2.0, with exponential backoff)
        timeout: Request timeout in seconds (default: 30)
        **kwargs: Additional arguments passed to requests.request()

    Returns:
        Response object if successful, None if all retries failed
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                # Exponential backoff: 2s, 4s, 8s, ...
                wait_time = retry_delay * (2 ** (attempt - 1))
                logger.warning("Retry attempt %d/%d for %s %s after %.1fs delay",
                             attempt + 1, max_retries, method.upper(), url, wait_time)
                time.sleep(wait_time)

            response = requests.request(
                method=method.upper(),
                url=url,
                json=payload if method.lower() in ['post', 'put', 'patch'] else None,
                timeout=timeout,
                **kwargs
            )
            response.raise_for_status()

            if attempt > 0:
                logger.info("Request succeeded on attempt %d: %s %s", attempt + 1, method.upper(), url)

            return response

        except requests.exceptions.RequestException as e:
            last_exception = e
            if attempt < max_retries - 1:
                logger.warning("Request attempt %d/%d failed for %s %s: %s",
                             attempt + 1, max_retries, method.upper(), url, e)
            else:
                logger.exception("All %d retry attempts failed for %s %s", max_retries, method.upper(), url)

    return None


def get_env(key: str, required: bool = True) -> Optional[str]:
    """Get environment variable.

    Args:
        key: Environment variable name
        required: If True, return None when variable is missing or empty

    Returns:
        Environment variable value or None if not required or missing
    """
    value = os.environ.get(key)
    if required and not value:
        logger.error("Missing required environment variable: %s", key)
        return None
    return value


def call_set_task_result(session_id, processed_msg_id, task_id, task_result, base_url):
    """Call SetTaskResult API to report task completion."""
    url = f"{base_url}/api/v1/task"
    payload = {
        "session_id": session_id,
        "processed_msg_id": processed_msg_id,
        "task_id": task_id,
        "task_result": task_result
    }

    logger.info("Calling SetTaskResult API: %s", url)
    logger.info("Payload: %s", payload)

    response = request_with_retry(
        method="post",
        url=url,
        payload=payload,
        max_retries=3,
        retry_delay=2.0,
        timeout=30
    )

    if response:
        logger.info("SetTaskResult response: %s", response.text)
        return True
    else:
        logger.exception("SetTaskResult API call failed after retries")
        return False


def call_receive_message(session_id, processed_msg_id, message, role, base_url):
    """Call ReceiveMessage API to send direct reply."""
    url = f"{base_url}/api/v1/message"
    payload = {
        "session_id": session_id,
        "processed_msg_id": processed_msg_id,
        "message": message,
        "role": role
    }

    logger.info("Calling ReceiveMessage API: %s", url)
    logger.info("Payload: %s", payload)

    response = request_with_retry(
        method="post",
        url=url,
        payload=payload,
        max_retries=3,
        retry_delay=2.0,
        timeout=30
    )

    if response:
        logger.info("ReceiveMessage response: %s", response.text)
        return True
    else:
        logger.exception("ReceiveMessage API call failed after retries")
        return False


def main():
    """Main entry point for processor callback."""
    logger.info("Processor callback started")

    # Get required environment variables
    session_id = get_env("TOPSAILAI_SESSION_ID")
    msg_id = get_env("TOPSAILAI_MSG_ID")
    final_answer = get_env("TOPSAILAI_FINAL_ANSWER")

    # Check if any required env var is missing
    if not session_id or not msg_id or not final_answer:
        sys.exit(1)

    set_thread_name(session_id)

    # Get optional environment variables
    task_id = os.environ.get("TOPSAILAI_TASK_ID")

    # Construct base URL from host and port
    # Note: 0.0.0.0 is for listening, not for making outbound connections
    host = os.environ.get("TOPSAILAI_AGENT_DAEMON_HOST", "localhost")
    if host == "0.0.0.0":
        host = "localhost"
    port = os.environ.get("TOPSAILAI_AGENT_DAEMON_PORT", "7373")
    base_url = f"http://{host}:{port}"

    logger.info("Session ID: %s", session_id)
    logger.info("Message ID: %s", msg_id)
    logger.info("Task ID: %s", task_id)
    logger.info("Base URL: %s", base_url)

    # Probe port availability (2 minutes timeout)
    try:
        port_reachable = probe_port(host, int(port), timeout=120)
        if port_reachable:
            logger.info("Port probe successful, proceeding with API calls")
        else:
            logger.warning("Port probe failed, but continuing with task execution")
    except Exception as e:
        logger.warning("Port probe encountered an error, but continuing with task execution: %s", e)

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
