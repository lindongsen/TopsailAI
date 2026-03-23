#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
List Sessions CLI - List all sessions from the session database

This module provides command-line functionality to list all sessions
stored in the database, displaying session ID, name, creation time,
and task information.

Usage:
    list_sessions.py [database_connection_string]

Arguments:
    database_connection_string: Optional database connection string.
                                Defaults to 'sqlite:///sessions.db'

Examples:
    list_sessions.py
    list_sessions.py sqlite:///custom.db

Author: DawsonLin
Email: lin_dongsen@126.com
"""

import sys
import os
from datetime import datetime

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.context.ctx_manager import get_session_manager


def format_sessions(sessions):
    """
    Format session data for display in a human-readable table format.
    
    This function takes a list of session objects and formats them into
    a readable string with headers, columns, and proper alignment.
    
    Args:
        sessions (list): List of session objects with attributes:
                        - session_id: Unique identifier for the session
                        - session_name: Optional name of the session
                        - create_time: datetime object representing creation time
                        - task: Task description string
        
    Returns:
        str: Formatted string containing all sessions in table format.
             Returns "No sessions found." if sessions list is empty.
    
    Example:
        >>> sessions = [Session(session_id="abc", session_name="test", 
        ...                     create_time=datetime.now(), task="Test task")]
        >>> print(format_sessions(sessions))
        Sessions:
        --------------------------------------------------------------------------------
        SESSION_ID                         NAME                      CREATED
        --------------------------------------------------------------------------------
        abc                                test                      2026-03-24 00:34:23
          Task: Test task
        --------------------------------------------------------------------------------
        Total: 1 sessions
    """
    if not sessions:
        return "No sessions found."

    # Header
    output = []
    output.append("Sessions:")
    output.append("-" * 80)
    output.append("SESSION_ID".ljust(35) + "NAME".ljust(25) + "CREATED")
    output.append("-" * 80)

    # Sessions
    for session in sessions:
        session_id = str(session.session_id)[:34]
        name = (str(session.session_name) if session.session_name else '')[:24]
        created = session.create_time.strftime("%Y-%m-%d %H:%M:%S") if session.create_time else ''
        output.append(f"{session_id.ljust(35)}{name.ljust(25)}{created}")
        output.append(f"  Task: {session.task[:65]}{'...' if len(session.task) > 65 else ''}")

    output.append("-" * 80)
    output.append(f"Total: {len(sessions)} sessions")

    return '\n'.join(output)


def main():
    """
    Main entry point for listing sessions.
    
    This function:
    1. Parses command-line arguments for database connection
    2. Creates a session manager with the specified database connection
    3. Retrieves all sessions from the database
    4. Displays the sessions in a formatted table
    
    Default Behavior:
        - If no database_connection_string provided, uses 'sqlite:///sessions.db'
    
    Returns:
        None
        
    Raises:
        SystemExit: Exits with code 1 if error occurs during retrieval
    
    Example:
        $ python ai_list_sessions.py
        Sessions:
        --------------------------------------------------------------------------------
        SESSION_ID                         NAME                      CREATED
        --------------------------------------------------------------------------------
        abc123                             Test Session             2026-03-24 00:34:23
          Task: This is a test task...
        --------------------------------------------------------------------------------
        Total: 1 sessions
    """
    # Get database connection from command line or use default
    db_conn = None
    if len(sys.argv) > 2:
        db_conn = sys.argv[2]

    try:
        # Create manager
        manager = get_session_manager(db_conn)

        # List sessions
        sessions = manager.list_sessions()

        # Display results
        formatted_output = format_sessions(sessions)
        print(formatted_output)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
