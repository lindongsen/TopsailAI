#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Delete Session CLI - Delete a session by session ID

This module provides command-line functionality to delete a specific session
from the database. It checks if the session exists before attempting deletion
and provides appropriate error messages.

Usage:
    delete_session.py <session_id> [database_connection_string]

Arguments:
    session_id: Required session identifier to delete
    database_connection_string: Optional database connection string.
                                Defaults to 'sqlite:///memory.db'

Examples:
    delete_session.py abc123
    delete_session.py abc123 sqlite:///custom.db

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


def main():
    """
    Main entry point for deleting a session.
    
    This function:
    1. Validates command-line arguments (requires session_id)
    2. Creates a session manager with optional database connection
    3. Checks if the session exists before deletion
    4. Deletes the session and displays success message
    
    Returns:
        None
        
    Raises:
        SystemExit: Exits with code 1 if session_id is missing, session doesn't exist, or error occurs
    
    Example:
        $ python ai_delete_session.py abc123
        Session 'abc123' has been successfully deleted
        
        $ python ai_delete_session.py nonexistent
        Error: Session 'nonexistent' does not exist
    """
    # Check for required session_id argument
    if len(sys.argv) < 2:
        print("Error: session_id is required")
        print("Usage: delete_session.py <session_id> [database_connection_string]")
        sys.exit(1)

    session_id = sys.argv[1]

    db_conn = None
    if len(sys.argv) > 2:
        db_conn = sys.argv[2]

    try:
        # Create manager
        manager = get_session_manager(db_conn)

        # Check if session exists
        if not manager.exists_session(session_id):
            print(f"Error: Session '{session_id}' does not exist")
            sys.exit(1)

        # Delete session
        manager.delete_session(session_id)

        print(f"Session '{session_id}' has been successfully deleted")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
