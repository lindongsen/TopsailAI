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

from topsailai.context.ctx_manager import get_session_manager
from topsailai.utils import json_tool, format_tool


# Global flag for graceful exit
running = True


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    global running
    print("\n\nReceived interrupt signal. Shutting down...")
    running = False


def format_message_content(msg) -> str:
    """
    Format message content for better readability.

    Handles:
    1. JSON array format: [{"step_name": "xxx", "raw_text": "yyy"}]
    2. Nested JSON with step_name and raw_text structure
    3. Plain text content

    Args:
        msg: The message object.

    Returns:
        str: Formatted message content.
    """
    try:
        content = json_tool.json_load(msg.message)
    except Exception:
        # If not JSON, return as-is
        return msg.message

    # Handle JSON array format: [{"step_name": "xxx", "raw_text": "yyy"}]
    if isinstance(content, list):
        lines = []
        for idx, item in enumerate(content):
            if isinstance(item, dict):
                step_name = item.get('step_name', '')
                raw_text = item.get('raw_text', '')
                
                if step_name and raw_text:
                    if idx > 0:
                        lines.append("")  # Add blank line between items
                    lines.append(f"[{step_name}]")
                    lines.append(str(raw_text))
                elif item:  # Non-empty dict without step_name/raw_text
                    if idx > 0:
                        lines.append("")
                    lines.append(json_tool.json_dump(item, indent=2))
            elif item:  # Non-empty non-dict item
                if idx > 0:
                    lines.append("")
                lines.append(str(item))
        
        if lines:
            return "\n".join(lines)
        return str(content)

    # Handle JSON dict format
    if isinstance(content, dict):
        # Check for step_name and raw_text structure
        step_name = content.get('step_name')
        raw_text = content.get('raw_text')

        if step_name and raw_text:
            # This is a nested AI message, try to parse raw_text
            lines = []
            lines.append(f"[{step_name}]")

            # Try to parse raw_text as JSON
            try:
                raw_data = json_tool.json_load(raw_text)
                if isinstance(raw_data, dict):
                    # Extract the actual message content
                    inner_step = raw_data.get('step_name', '')
                    inner_raw = raw_data.get('raw_text', raw_text)
                    if inner_step:
                        lines.append(f"[{inner_step}]")
                    lines.append(str(inner_raw))
                elif isinstance(raw_data, list):
                    # Handle list inside raw_text
                    for idx, item in enumerate(raw_data):
                        if isinstance(item, dict):
                            inner_step = item.get('step_name', '')
                            inner_raw = item.get('raw_text', '')
                            if inner_step and inner_raw:
                                if idx > 0:
                                    lines.append("")
                                lines.append(f"[{inner_step}]")
                                lines.append(str(inner_raw))
                        elif item:
                            if idx > 0:
                                lines.append("")
                            lines.append(str(item))
                else:
                    # raw_text is a plain string
                    lines.append(str(raw_text))
            except Exception:
                # raw_text is a plain string
                lines.append(str(raw_text))

            return "\n".join(lines)

        # Check for role field
        role = content.get('role', '')
        if role:
            lines = [f"Role: {role}"]

            # Check for content field
            content_text = content.get('content', '')
            if content_text:
                # Try to parse content if it's a JSON string
                try:
                    inner_content = json_tool.json_load(content_text)
                    if isinstance(inner_content, dict):
                        inner_step = inner_content.get('step_name', '')
                        inner_raw = inner_content.get('raw_text', content_text)
                        if inner_step:
                            lines.append(f"[{inner_step}]")
                        lines.append(str(inner_raw))
                    elif isinstance(inner_content, list):
                        # Handle list in content
                        for idx, item in enumerate(inner_content):
                            if isinstance(item, dict):
                                inner_step = item.get('step_name', '')
                                inner_raw = item.get('raw_text', '')
                                if inner_step and inner_raw:
                                    if idx > 0:
                                        lines.append("")
                                    lines.append(f"[{inner_step}]")
                                    lines.append(str(inner_raw))
                            elif item:
                                if idx > 0:
                                    lines.append("")
                                lines.append(str(item))
                    else:
                        lines.append(str(content_text))
                except Exception:
                    lines.append(str(content_text))

            return "\n".join(lines)

        # If no special structure, just dump as formatted JSON
        return json_tool.json_dump(content, indent=2)

    # If not a dict or list, return as-is
    return str(content)


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
                        formatted_content = format_message_content(msg)

                        print(f"\n[{msg.create_time.strftime('%Y-%m-%d %H:%M:%S') if msg.create_time else 'N/A'}] "
                              f"msg_id={msg.msg_id}")
                        print(formatted_content)
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
                                formatted_content = format_message_content(msg)

                                print(f"\n[{msg.create_time.strftime('%Y-%m-%d %H:%M:%S') if msg.create_time else 'N/A'}] "
                                      f"Session: {session_id} ({session_name})")
                                print(f"msg_id={msg.msg_id}")
                                print(formatted_content)
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
