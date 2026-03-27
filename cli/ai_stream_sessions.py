#!/usr/bin/env python3
'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-29
  Purpose: Stream session messages in real-time, similar to tail -f behavior.
           Continuously polls for new messages and outputs them immediately.
'''

import os
import argparse
import signal
import sys
import time
from datetime import datetime

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.context.ctx_manager import get_session_manager
from topsailai.utils import json_tool


# Global flag for graceful exit
running = True


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    global running
    print("\n\nReceived interrupt signal. Shutting down...")
    running = False


def get_latest_message_time(session_manager, session_id: str) -> datetime:
    """
    Get the creation time of the latest message for a session.

    Args:
        session_manager: The session manager instance.
        session_id: The session ID to check.

    Returns:
        datetime: The creation time of the latest message, or None if no messages exist.
    """
    messages = session_manager.get_messages_by_session(session_id)
    if messages:
        # Messages are ordered by create_time ascending, so get the last one
        return messages[-1].create_time
    return None


def stream_session_messages(session_manager, session_id: str, session_name: str, poll_interval: float = 1.0):
    """
    Stream messages for a specific session.

    Args:
        session_manager: The session manager instance.
        session_id: The session ID to stream messages from.
        session_name: The session name for display purposes.
        poll_interval: Interval in seconds between polls.
    """
    global running

    # Track the last seen message to detect new ones
    last_msg_id = None

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting stream for session: {session_id} ({session_name})")
    print("-" * 80)

    while running:
        try:
            messages = session_manager.get_messages_by_session(session_id)

            if messages:
                # Get the latest message
                latest_msg = messages[-1]

                # Check if there's a new message
                if latest_msg.msg_id != last_msg_id:
                    # Find new messages (from last_msg_id onwards)
                    new_messages = []
                    for msg in messages:
                        if msg.msg_id == last_msg_id:
                            break
                        new_messages.append(msg)

                    # If this is the first check, show all messages
                    if last_msg_id is None:
                        new_messages = messages

                    # Output new messages
                    for msg in new_messages:
                        try:
                            content = json_tool.json_load(msg.message)
                        except Exception:
                            content = msg.message

                        print(f"\n[{msg.create_time.strftime('%Y-%m-%d %H:%M:%S') if msg.create_time else 'N/A'}] "
                              f"msg_id={msg.msg_id}")
                        print(f"Content: {json_tool.json_dump(content, indent=2)}")
                        print("-" * 80)

                    # Update last seen message
                    last_msg_id = latest_msg.msg_id

            # Poll for new messages
            time.sleep(poll_interval)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error streaming session {session_id}: {e}")
            time.sleep(poll_interval)

    print(f"\nStopped streaming session: {session_id}")


def stream_all_sessions(session_manager, poll_interval: float = 1.0):
    """
    Stream messages from all active sessions.

    Args:
        session_manager: The session manager instance.
        poll_interval: Interval in seconds between polls.
    """
    global running

    # Track last seen message for each session
    last_messages = {}  # session_id -> last_msg_id

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting stream for all sessions")
    print("-" * 80)

    while running:
        try:
            # Get all sessions
            sessions = session_manager.list_sessions()

            for session in sessions:
                session_id = session.session_id
                session_name = session.session_name or "Unnamed"

                try:
                    messages = session_manager.get_messages_by_session(session_id)

                    if messages:
                        # Get the latest message for this session
                        latest_msg = messages[-1]
                        last_msg_id = last_messages.get(session_id)

                        # Check if there's a new message
                        if latest_msg.msg_id != last_msg_id:
                            # Find new messages
                            new_messages = []
                            for msg in messages:
                                if msg.msg_id == last_msg_id:
                                    break
                                new_messages.append(msg)

                            # If this is the first check, show all messages
                            if last_msg_id is None:
                                new_messages = messages

                            # Output new messages
                            for msg in new_messages:
                                try:
                                    content = json_tool.json_load(msg.message)
                                except Exception:
                                    content = msg.message

                                print(f"\n[{msg.create_time.strftime('%Y-%m-%d %H:%M:%S') if msg.create_time else 'N/A'}] "
                                      f"Session: {session_id} ({session_name})")
                                print(f"msg_id={msg.msg_id}")
                                print(f"Content: {json_tool.json_dump(content, indent=2)}")
                                print("-" * 80)

                            # Update last seen message
                            last_messages[session_id] = latest_msg.msg_id

                    # Handle case where session was removed from tracking
                    elif session_id in last_messages:
                        del last_messages[session_id]

                except Exception as e:
                    print(f"Error processing session {session_id}: {e}")

            # Poll for new messages
            time.sleep(poll_interval)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error in stream loop: {e}")
            time.sleep(poll_interval)

    print("\nStopped streaming all sessions")


def main():
    """Main entry point for the stream sessions CLI."""
    global running

    # Set up signal handler for graceful exit
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    parser = argparse.ArgumentParser(
        description='Stream session messages in real-time. '
                    'Continuously polls for new messages and outputs them immediately.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Stream all sessions
  python ai_stream_sessions.py

  # Stream a specific session
  python ai_stream_sessions.py --session-id abc123

  # Stream with custom poll interval (0.5 seconds)
  python ai_stream_sessions.py --poll-interval 0.5

  # Stream specific session with custom interval
  python ai_stream_sessions.py --session-id abc123 --poll-interval 0.5
        '''
    )

    parser.add_argument(
        '--db-conn',
        type=str,
        default=None,
        help='Database connection string. If not provided, uses default from session manager.'
    )

    parser.add_argument(
        '--session-id',
        type=str,
        default=None,
        help='Specific session ID to stream. If not provided, streams all sessions.'
    )

    parser.add_argument(
        '--poll-interval',
        type=float,
        default=1.0,
        help='Interval in seconds between polls for new messages. Default: 1.0'
    )

    args = parser.parse_args()

    # Validate poll interval
    if args.poll_interval <= 0:
        print("Error: poll-interval must be positive")
        sys.exit(1)

    # Get session manager
    session_manager = get_session_manager(args.db_conn)

    if args.session_id:
        # Stream specific session
        sessions = session_manager.list_sessions()
        session = None
        for s in sessions:
            if s.session_id == args.session_id:
                session = s
                break

        if session is None:
            print(f"Error: Session not found: {args.session_id}")
            sys.exit(1)

        stream_session_messages(
            session_manager,
            args.session_id,
            session.session_name or "Unnamed",
            args.poll_interval
        )
    else:
        # Stream all sessions
        stream_all_sessions(session_manager, args.poll_interval)


if __name__ == '__main__':
    main()
