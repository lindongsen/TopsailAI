#!/usr/bin/env python3
"""
Wait for Message Result Script

This script sends a new message to a session and then loops waiting for the
processing result by querying messages with processed_msg_id=new_msg_id.

Usage:
    python wait_for_message_result.py --session-id SESSION_ID --message "Hello" --host localhost --port 7373

Environment Variables:
    TOPSAILAI_AGENT_DAEMON_HOST: Server host (default: localhost)
    TOPSAILAI_AGENT_DAEMON_PORT: Server port (default: 7373)
    WAIT_INTERVAL: Polling interval in seconds (default: 2)
    MAX_WAIT_TIME: Maximum wait time in seconds (default: 300)
"""

import argparse
import os
import sys
import time
from typing import Optional, List, Dict, Any

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.client.message import MessageClient


def wait_for_message_result(
    client: MessageClient,
    session_id: str,
    new_msg_id: str,
    wait_interval: int = 2,
    max_wait_time: int = 300,
    verbose: bool = False
) -> Optional[List[Dict[str, Any]]]:
    """
    Wait for message processing result by polling with processed_msg_id filter.

    Args:
        client: MessageClient instance
        session_id: The session ID
        new_msg_id: The new message ID to wait for
        wait_interval: Polling interval in seconds
        max_wait_time: Maximum wait time in seconds
        verbose: Print verbose output

    Returns:
        List of messages with processed_msg_id=new_msg_id, or None if timeout
    """
    start_time = time.time()
    elapsed = 0

    logger.info("Waiting for message result: session_id=%s, new_msg_id=%s", session_id, new_msg_id)
    print(f"Waiting for message result...")
    print(f"  Session ID: {session_id}")
    print(f"  New Message ID: {new_msg_id}")
    print(f"  Polling interval: {wait_interval}s")
    print(f"  Max wait time: {max_wait_time}s")
    print()

    while elapsed < max_wait_time:
        # Query messages with processed_msg_id=new_msg_id
        messages = client.list_messages(
            session_id=session_id,
            processed_msg_id=new_msg_id,
            sort_key="create_time",
            order_by="asc",
            verbose=False
        )

        if messages:
            logger.info("Found %d message(s) with processed_msg_id=%s", len(messages), new_msg_id)
            print(f"\nFound {len(messages)} message(s) with processed_msg_id={new_msg_id}")
            return messages

        # Print progress
        remaining = max_wait_time - elapsed
        print(f"\rTime elapsed: {int(elapsed)}s / {max_wait_time}s (remaining: {int(remaining)}s)", end="", flush=True)

        # Wait before next poll
        time.sleep(wait_interval)
        elapsed = time.time() - start_time

    # Timeout
    logger.warning("Timeout waiting for message result: session_id=%s, new_msg_id=%s", session_id, new_msg_id)
    print(f"\n\nTimeout! No messages found with processed_msg_id={new_msg_id} after {max_wait_time}s")
    return None


def send_and_wait(
    session_id: str,
    message: str,
    role: str = "user",
    host: str = "localhost",
    port: int = 7373,
    wait_interval: int = 2,
    max_wait_time: int = 300,
    verbose: bool = False
) -> Optional[List[Dict[str, Any]]]:
    """
    Send a message and wait for the processing result.

    Args:
        session_id: The session ID
        message: The message content
        role: Message role (user/assistant)
        host: Server host
        port: Server port
        wait_interval: Polling interval in seconds
        max_wait_time: Maximum wait time in seconds
        verbose: Print verbose output

    Returns:
        List of messages with processed_msg_id=new_msg_id, or None if timeout/error
    """
    client = MessageClient(base_url=f"http://{host}:{port}")

    try:
        # Send the message
        logger.info("Sending message to session %s", session_id)
        print(f"Sending message to session: {session_id}")
        print(f"Message: {message[:100]}{'...' if len(message) > 100 else ''}")

        result = client.send_message(
            session_id=session_id,
            message=message,
            role=role,
            verbose=verbose
        )

        # Extract the new message ID from the result
        # Note: client.send_message() returns the 'data' field from API response,
        # which is already {"msg_id": "..."}, not {"data": {"msg_id": "..."}}
        new_msg_id = None
        if result and isinstance(result, dict):
            new_msg_id = result.get('msg_id')

        if not new_msg_id:
            logger.error("Failed to get new message ID from response")
            print("Error: Failed to get new message ID from response")
            return None

        logger.info("New message created: msg_id=%s", new_msg_id)
        print(f"\nNew message created: {new_msg_id}")
        print("-" * 60)

        # Wait for the result
        return wait_for_message_result(
            client=client,
            session_id=session_id,
            new_msg_id=new_msg_id,
            wait_interval=wait_interval,
            max_wait_time=max_wait_time,
            verbose=verbose
        )

    except Exception as e:
        logger.exception("Error sending message: %s", e)
        print(f"Error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Send a message and wait for the processing result',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Send a message and wait for result
  python wait_for_message_result.py --session-id test-session --message "Hello world"

  # With custom host and port
  python wait_for_message_result.py --session-id test-session --message "Hello" --host localhost --port 7373

  # With verbose output
  python wait_for_message_result.py --session-id test-session --message "Hello" --verbose

  # With custom polling interval and timeout
  python wait_for_message_result.py --session-id test-session --message "Hello" --wait-interval 5 --max-wait-time 600
        """
    )

    parser.add_argument('--session-id', type=str, required=True,
                        help='Session ID to send message to')
    parser.add_argument('--message', type=str, required=True,
                        help='Message content')
    parser.add_argument('--role', type=str, default='user',
                        choices=['user', 'assistant'],
                        help='Message role (default: user)')
    parser.add_argument('--host', type=str,
                        default=os.environ.get('TOPSAILAI_AGENT_DAEMON_HOST', 'localhost'),
                        help='Server host (default: localhost)')
    parser.add_argument('--port', type=int,
                        default=int(os.environ.get('TOPSAILAI_AGENT_DAEMON_PORT', '7373')),
                        help='Server port (default: 7373)')
    parser.add_argument('--wait-interval', type=int, default=2,
                        help='Polling interval in seconds (default: 2)')
    parser.add_argument('--max-wait-time', type=int, default=300,
                        help='Maximum wait time in seconds (default: 300)')
    parser.add_argument('--verbose', action='store_true',
                        help='Print verbose output')

    args = parser.parse_args()

    # Update host/port from args if not already set
    if args.host == 'localhost' and 'TOPSAILAI_AGENT_DAEMON_HOST' in os.environ:
        args.host = os.environ['TOPSAILAI_AGENT_DAEMON_HOST']
    if args.port == 7373 and 'TOPSAILAI_AGENT_DAEMON_PORT' in os.environ:
        args.port = int(os.environ['TOPSAILAI_AGENT_DAEMON_PORT'])

    # Send message and wait for result
    result = send_and_wait(
        session_id=args.session_id,
        message=args.message,
        role=args.role,
        host=args.host,
        port=args.port,
        wait_interval=args.wait_interval,
        max_wait_time=args.max_wait_time,
        verbose=args.verbose
    )

    if result:
        print("\n" + "=" * 60)
        print("RESULT:")
        print("=" * 60)
        for msg in result:
            print(f"\n[{msg.get('create_time')}] [{msg.get('msg_id')}] [{msg.get('role')}]")
            print(msg.get('message', ''))
            if msg.get('task_id'):
                print(f">>> task_id: {msg.get('task_id')}")
            if msg.get('task_result'):
                print(f">>> task_result:")
                print(msg.get('task_result'))
        print("\n" + "=" * 60)
        sys.exit(0)
    else:
        print("\nNo result received (timeout or error)")
        sys.exit(1)


if __name__ == '__main__':
    main()
