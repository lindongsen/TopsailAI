#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Retrieve Messages CLI - Retrieve messages for a specific session ID

This module provides command-line functionality to retrieve all messages
associated with a given session from the database.

Usage:
    retrieve_messages.py <session_id> [database_connection_string]

Arguments:
    session_id: Required session identifier
    database_connection_string: Optional database connection string.
                                Defaults to 'sqlite:///memory.db'

Examples:
    retrieve_messages.py abc123
    retrieve_messages.py abc123 sqlite:///custom.db

Author: DawsonLin
Email: lin_dongsen@126.com
"""

import argparse
import copy
import sys
import os

import _import_topsailai

os.chdir(_import_topsailai.PROJECT_FOLDER_BASE)
from topsailai.context.ctx_manager import get_session_manager
from topsailai.utils import json_tool
from topsailai.workspace.print_tool import print_context_messages


def truncate_message_content(messages, max_chars):
    """
    Truncate message content to a maximum character count.

    Each message's ``content`` field is limited to ``max_chars`` characters.
    When truncation occurs, an ellipsis (``...``) is appended to indicate that
    the content was shortened. Messages whose content is already within the
    limit are returned unchanged.

    Args:
        messages (list): List of message dictionaries containing a 'content' field.
        max_chars (int): Maximum number of characters to keep for each content.

    Returns:
        list: New list of message dictionaries with truncated content.
    """
    if max_chars is None or max_chars <= 0:
        return messages

    truncated = []
    for message in messages:
        msg = copy.deepcopy(message) if isinstance(message, dict) else message
        if isinstance(msg, dict) and "content" in msg:
            content = msg["content"]
            text = content if isinstance(content, str) else str(content)
            if len(text) > max_chars:
                msg["content"] = text[:max_chars] + "..."
            else:
                msg["content"] = text
        truncated.append(msg)
    return truncated


def format_messages(messages):
    """
    Format messages for display in a human-readable format.
    
    This function takes a list of message dictionaries and formats them
    into a readable string with headers, separators, and proper JSON
    pretty-printing.
    
    Args:
        messages (list): List of message dictionaries containing 'role' and 'content' fields.
        
    Returns:
        str: Formatted string containing all messages with headers and separators.
             Returns "No messages found for this session." if messages list is empty.
    
    Example:
        >>> msgs = [{"role": "user", "content": "Hello"}]
        >>> print(format_messages(msgs))
        Messages:
        ------------------------------------------------------------------------------------------------------------------------
        Message #1 (chars: 5):
        {
          "role": "user",
          "content": "Hello"
        }
        ------------------------------------------------------------
        ------------------------------------------------------------
        Total: 1 messages
    """
    if not messages:
        return "No messages found for this session."

    def _content_chars(message):
        """Return the character length of the message content field."""
        if not isinstance(message, dict):
            return len(str(message))
        content = message.get("content")
        if content is None:
            return 0
        return len(content) if isinstance(content, str) else len(str(content))

    # Header
    output = []
    output.append("Messages:")
    output.append("-" * 120)

    # Messages
    for i, message in enumerate(messages, 1):
        output.append(f"Message #{i} (chars: {_content_chars(message)}):")
        if isinstance(message, dict):
            # Pretty print the JSON
            output.append(json_tool.json_dump(message, indent=2))
        else:
            # Fallback for non-dict messages
            output.append(str(message))
        output.append("-" * 60)

    output.append("-" * 120)
    output.append(f"Total: {len(messages)} messages")

    return '\n'.join(output)


def parse_args(argv=None):
    """
    Parse command-line arguments.

    Args:
        argv: Optional argument list. Defaults to sys.argv[1:].

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="Retrieve messages for a specific session ID."
    )
    parser.add_argument(
        "session_id",
        help="Required session identifier.",
    )
    parser.add_argument(
        "db_conn",
        nargs="?",
        default=None,
        help="Optional database connection string. Defaults to 'sqlite:///memory.db'.",
    )
    parser.add_argument(
        "--max-chars",
        "-c",
        type=int,
        default=None,
        metavar="N",
        help="Truncate each message's displayed content to at most N characters. "
             "Truncation is applied by the shared formatter and does not affect counts.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """
    Main entry point for retrieving messages.

    This function:
    1. Validates command-line arguments (requires session_id)
    2. Creates a session manager with optional database connection
    3. Retrieves all messages for the specified session
    4. Displays the messages using print_context_messages

    Returns:
        None

    Raises:
        SystemExit: Exits with code 1 if session_id is missing or error occurs
    """
    args = parse_args(argv)

    try:
        # Create manager
        manager = get_session_manager(args.db_conn)

        # Retrieve messages
        messages = manager.retrieve_messages(args.session_id)

        # Display results using the shared formatter, passing through the
        # truncation limit so counts remain based on the original content.
        print_context_messages(messages, content_max_length=args.max_chars)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
