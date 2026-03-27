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
import logging
import re
from datetime import datetime
from typing import List, Optional

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

from topsailai.context.ctx_manager import get_session_manager
from topsailai.utils import json_tool, format_tool


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Global flag for graceful exit
running = True

# Default constants
DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_MAX_MESSAGES = 50
SEPARATOR_WIDTH = 80


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    global running
    print("\n\nReceived interrupt signal. Shutting down...")
    running = False


# ============================================================================
# Helper functions for message content formatting
# ============================================================================

def _format_json_array(content: list) -> str:
    """Format a JSON array message."""
    lines = []
    for idx, item in enumerate(content):
        if isinstance(item, dict):
            step_name = item.get('step_name', '')
            raw_text = item.get('raw_text', '')
            
            if step_name and raw_text:
                if idx > 0:
                    lines.append("")
                lines.append(f"[{step_name}]")
                lines.append(str(raw_text))
            elif item:
                if idx > 0:
                    lines.append("")
                lines.append(json_tool.json_dump(item, indent=2))
        elif item:
            if idx > 0:
                lines.append("")
            lines.append(str(item))
    
    return "\n".join(lines) if lines else str(content)


def _format_nested_message(content: dict) -> Optional[str]:
    """Format a nested message with step_name and raw_text."""
    step_name = content.get('step_name')
    raw_text = content.get('raw_text')

    if not (step_name and raw_text):
        return None

    lines = [f"[{step_name}]"]

    try:
        raw_data = json_tool.json_load(raw_text)
        if isinstance(raw_data, dict):
            inner_step = raw_data.get('step_name', '')
            inner_raw = raw_data.get('raw_text', raw_text)
            if inner_step:
                lines.append(f"[{inner_step}]")
            lines.append(str(inner_raw))
        elif isinstance(raw_data, list):
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
            lines.append(str(raw_text))
    except Exception:
        lines.append(str(raw_text))

    return "\n".join(lines)


def _format_role_message(content: dict) -> Optional[str]:
    """Format a message with role field."""
    role = content.get('role', '')
    if not role:
        return None

    lines = [f"Role: {role}"]
    content_text = content.get('content', '')

    if content_text:
        try:
            inner_content = json_tool.json_load(content_text)
            if isinstance(inner_content, dict):
                inner_step = inner_content.get('step_name', '')
                inner_raw = inner_content.get('raw_text', content_text)
                if inner_step:
                    lines.append(f"[{inner_step}]")
                lines.append(str(inner_raw))
            elif isinstance(inner_content, list):
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
        return msg.message

    # Handle JSON array format
    if isinstance(content, list):
        return _format_json_array(content)

    # Handle JSON dict format
    if isinstance(content, dict):
        # Try nested message format first
        formatted = _format_nested_message(content)
        if formatted:
            return formatted

        # Try role-based format
        formatted = _format_role_message(content)
        if formatted:
            return formatted

        # Fallback to formatted JSON dump
        return json_tool.json_dump(content, indent=2)

    return str(content)


# ============================================================================
# Helper functions for message tracking
# ============================================================================

def get_new_messages(messages: list, last_msg_id: Optional[str], max_messages: Optional[int] = None) -> list:
    """
    Get new messages after last_msg_id in correct chronological order.
    
    Args:
        messages: List of message objects (assumed to be in chronological order)
        last_msg_id: The last seen message ID (None for first run)
        max_messages: Maximum number of messages to return on first run
        
    Returns:
        List of new message objects in chronological order
    """
    if not messages:
        return []
    
    if last_msg_id is None:
        # First run - return messages up to max_messages limit
        if max_messages and len(messages) > max_messages:
            return messages[-max_messages:]
        return messages
    
    # Find the index of last_msg_id
    last_idx = -1
    for idx, msg in enumerate(messages):
        if msg.msg_id == last_msg_id:
            last_idx = idx
            break
    
    # Get messages after last_msg_id
    if last_idx >= 0:
        new_messages = messages[last_idx + 1:]
    else:
        # last_msg_id not found, return all messages (edge case)
        logger.warning(f"Last message ID {last_msg_id} not found in message list")
        new_messages = messages
    
    return new_messages


def output_messages(messages: list, session_id: str = None, session_name: str = None, 
                    show_session: bool = False):
    """
    Output formatted messages to stdout.
    
    Args:
        messages: List of message objects to output
        session_id: Session ID for display
        session_name: Session name for display
        show_session: Whether to show session info in output
    """
    for msg in messages:
        formatted_content = format_message_content(msg)
        
        timestamp = msg.create_time.strftime('%Y-%m-%d %H:%M:%S') if msg.create_time else 'N/A'
        
        if show_session and session_id:
            print(f"\n[{timestamp}] Session: {session_id} ({session_name or 'Unnamed'})")
            print(f"msg_id={msg.msg_id}")
        else:
            print(f"\n[{timestamp}] msg_id={msg.msg_id}")
        
        print(formatted_content)
        print("-" * SEPARATOR_WIDTH)


# ============================================================================
# Streaming functions
# ============================================================================

def stream_session_messages(session_manager, session_id: str, session_name: str, 
                            poll_interval: float = 1.0, max_messages: int = DEFAULT_MAX_MESSAGES):
    """
    Stream messages for a specific session.

    Args:
        session_manager: The session manager instance.
        session_id: The session ID to stream messages from.
        session_name: The session name for display purposes.
        poll_interval: Interval in seconds between polls.
        max_messages: Maximum number of historical messages to show on first run.
    """
    global running

    last_msg_id = None

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting stream for session: {session_id} ({session_name})")
    print("-" * SEPARATOR_WIDTH)

    while running:
        try:
            messages = session_manager.get_messages_by_session(session_id)

            if messages:
                latest_msg = messages[-1]

                if latest_msg.msg_id != last_msg_id:
                    new_messages = get_new_messages(messages, last_msg_id, max_messages)
                    
                    output_messages(new_messages, session_id, session_name, show_session=False)
                    
                    last_msg_id = latest_msg.msg_id
                    logger.debug(f"Updated last_msg_id to {last_msg_id}")

            time.sleep(poll_interval)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error streaming session {session_id}: {e}")
            time.sleep(poll_interval)

    print(f"\nStopped streaming session: {session_id}")


def stream_all_sessions(session_manager, poll_interval: float = 1.0, 
                        max_messages: int = DEFAULT_MAX_MESSAGES):
    """
    Stream messages from all active sessions.

    Args:
        session_manager: The session manager instance.
        poll_interval: Interval in seconds between polls.
        max_messages: Maximum number of historical messages to show on first run.
    """
    global running

    last_messages = {}  # session_id -> last_msg_id

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting stream for all sessions")
    print("-" * SEPARATOR_WIDTH)

    while running:
        try:
            sessions = session_manager.list_sessions()

            for session in sessions:
                session_id = session.session_id
                session_name = session.session_name or "Unnamed"

                try:
                    messages = session_manager.get_messages_by_session(session_id)

                    if messages:
                        latest_msg = messages[-1]
                        last_msg_id = last_messages.get(session_id)

                        if latest_msg.msg_id != last_msg_id:
                            new_messages = get_new_messages(messages, last_msg_id, max_messages)
                            
                            output_messages(new_messages, session_id, session_name, show_session=True)
                            
                            last_messages[session_id] = latest_msg.msg_id

                    elif session_id in last_messages:
                        del last_messages[session_id]

                except Exception as e:
                    logger.error(f"Error processing session {session_id}: {e}")

            time.sleep(poll_interval)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error in stream loop: {e}")
            time.sleep(poll_interval)

    print("\nStopped streaming all sessions")


# ============================================================================
# Validation functions
# ============================================================================

def validate_db_conn(db_conn: str) -> bool:
    """
    Validate database connection string format.
    
    Args:
        db_conn: Database connection string to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not db_conn:
        return True  # Empty is valid (will use default)
    
    # Basic validation - check for common database URL patterns
    # Supported formats: sqlite:///path, postgresql://user:pass@host/db, etc.
    valid_schemes = ('sqlite:///', 'postgresql://', 'mysql://', 'mongodb://')
    
    if not any(db_conn.startswith(scheme) for scheme in valid_schemes):
        # Check if it might be a file path (for SQLite)
        if not os.path.exists(db_conn) and not db_conn.startswith('/'):
            logger.warning(f"Database connection string format may be invalid: {db_conn}")
            return False
    
    return True


# ============================================================================
# Main entry point
# ============================================================================

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

  # Limit initial message history to 20 messages
  python ai_stream_sessions.py --max-messages 20

  # Enable debug logging
  python ai_stream_sessions.py --log-level DEBUG
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
        default=DEFAULT_POLL_INTERVAL,
        help=f'Interval in seconds between polls for new messages. Default: {DEFAULT_POLL_INTERVAL}'
    )

    parser.add_argument(
        '--max-messages',
        type=int,
        default=DEFAULT_MAX_MESSAGES,
        help=f'Maximum number of historical messages to show on first run. Default: {DEFAULT_MAX_MESSAGES}'
    )

    parser.add_argument(
        '--log-level',
        type=str,
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Set logging level. Default: INFO'
    )

    args = parser.parse_args()

    # Configure logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Validate poll interval
    if args.poll_interval <= 0:
        print("Error: poll-interval must be positive")
        sys.exit(1)

    # Validate max messages
    if args.max_messages <= 0:
        print("Error: max-messages must be positive")
        sys.exit(1)

    # Validate database connection string
    if not validate_db_conn(args.db_conn):
        print(f"Warning: Database connection string format may be invalid: {args.db_conn}")
        print("Proceeding anyway (will use default if connection fails)...")

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
            args.poll_interval,
            args.max_messages
        )
    else:
        # Stream all sessions
        stream_all_sessions(session_manager, args.poll_interval, args.max_messages)


if __name__ == '__main__':
    main()
