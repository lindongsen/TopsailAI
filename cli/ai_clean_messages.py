#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clean Messages CLI - Clean old messages from chat history

This module provides command-line functionality to clean up old messages
from the chat history database based on a time threshold. Messages older
than the specified number of seconds will be deleted.

This is useful for:
- Freeing up database storage space
- Removing outdated conversation history
- Maintaining privacy by deleting old messages

Usage:
    ai_clean_messages.py [before_seconds] [database_connection_string]

Arguments:
    before_seconds: Optional number of seconds before current time.
                   Messages with access_time less than (current time - before_seconds) will be deleted.
                   Defaults to 2592000 (30 days).
    database_connection_string: Optional database connection string.
                               Defaults to 'sqlite:///memory.db'

Examples:
    ai_clean_messages.py
    ai_clean_messages.py 86400
    ai_clean_messages.py 604800 sqlite:///custom.db

Author: DawsonLin
Email: lin_dongsen@126.com
"""

import sys
import os
from datetime import datetime, timedelta

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.context.ctx_manager import get_session_manager


def main():
    """
    Main entry point for cleaning old messages.
    
    This function:
    1. Parses command-line arguments for time threshold and database connection
    2. Creates a session manager with the specified database connection
    3. Deletes all messages older than the specified number of seconds
    4. Displays the number of deleted messages and cutoff time
    
    Default Behavior:
        - If no before_seconds provided, defaults to 30 days (2592000 seconds)
        - If no database_connection_string provided, uses in-memory SQLite
    
    Returns:
        None
        
    Raises:
        SystemExit: Exits with code 1 if before_seconds is invalid or error occurs
    
    Example:
        Running with 86400 seconds (1 day):
        $ ai_clean_messages.py 86400
        Successfully cleaned 150 messages
        Cutoff time: 2026-03-23 00:34:07
        Messages older than 86400 seconds (1 days) have been deleted
    """
    # Default values
    default_before_seconds = 30 * 24 * 60 * 60  # 30 days in seconds

    # Parse command line arguments
    before_seconds = default_before_seconds

    if len(sys.argv) > 1:
        try:
            before_seconds = int(sys.argv[1])
            if before_seconds <= 0:
                print("Error: before_seconds must be a positive integer")
                sys.exit(1)
        except ValueError:
            print("Error: before_seconds must be a valid integer")
            sys.exit(1)

    db_conn = None
    if len(sys.argv) > 2:
        db_conn = sys.argv[2]

    try:
        # Create manager
        session_manager = get_session_manager(db_conn)
        manager = session_manager.chat_history

        # Clean messages
        deleted_count = manager.clean_messages(before_seconds)

        # Calculate cutoff time for display
        cutoff_time = datetime.now() - timedelta(seconds=before_seconds)

        print(f"Successfully cleaned {deleted_count} messages")
        print(f"Cutoff time: {cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Messages older than {before_seconds} seconds ({before_seconds // 86400} days) have been deleted")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
