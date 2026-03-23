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

import sys
import os

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.context.ctx_manager import get_session_manager
from topsailai.utils import json_tool
from topsailai.workspace.print_tool import print_context_messages


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
        Message #1:
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

    # Header
    output = []
    output.append("Messages:")
    output.append("-" * 120)

    # Messages
    for i, message in enumerate(messages, 1):
        output.append(f"Message #{i}:")
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


def main():
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
    # Check for required session_id argument
    if len(sys.argv) < 2:
        print("Error: session_id is required")
        print("Usage: retrieve_messages.py <session_id>")
        sys.exit(1)

    session_id = sys.argv[1]

    db_conn = None
    if len(sys.argv) > 2:
        db_conn = sys.argv[2]

    try:
        # Create manager
        manager = get_session_manager(db_conn)

        # Retrieve messages
        messages = manager.retrieve_messages(session_id)

        # Display results
        print_context_messages(messages)
        #formatted_output = format_messages(messages)
        #print(formatted_output)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
