#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clean Sessions CLI - Clean old sessions from session storage

This module provides command-line functionality to clean up old sessions
from the database based on a time threshold. Sessions older than the
specified number of seconds will be deleted.

Usage:
    ai_clean_sessions.py [before_seconds] [database_connection_string]

Arguments:
    before_seconds: Optional number of seconds before current time.
                   Sessions with create_time less than (current time - before_seconds) will be deleted.
                   Defaults to 2592000 (30 days).
    database_connection_string: Optional database connection string.
                               Defaults to 'sqlite:///memory.db'

Examples:
    ai_clean_sessions.py
    ai_clean_sessions.py 86400
    ai_clean_sessions.py 604800 sqlite:///custom.db

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
from cli_topsailai.session_cleanup import (
    clean_orphaned_session_files,
    delete_session_disk_files,
    get_task_dir,
)


def main():
    """
    Main entry point for cleaning old sessions.

    This function:
    1. Parses command-line arguments for time threshold and database connection
    2. Creates a session manager with the specified database connection
    3. Deletes all sessions older than the specified number of seconds
    4. Cleans up disk files associated with each deleted session
    5. Removes orphaned .pipe/.jsonl files whose .stdout is gone

    Default Behavior:
        - If no before_seconds provided, defaults to 30 days (2592000 seconds)
        - If no database_connection_string provided, uses in-memory SQLite

    Returns:
        None

    Raises:
        SystemExit: Exits with code 1 if before_seconds is invalid or error occurs

    Example:
        Running with 86400 seconds (1 day):
        $ ai_clean_sessions.py 86400
        Successfully cleaned 15 sessions
        Cutoff time: 2026-03-23 00:34:07
        Sessions older than 86400 seconds (1 days) have been deleted
    """
    # Default values
    default_before_seconds = 30 * 24 * 60 * 60  # 30 days in seconds (1 month)

    # Parse command line arguments
    before_seconds = default_before_seconds

    if len(sys.argv) > 1:
        try:
            before_seconds = int(sys.argv[1])
            if before_seconds < 0:
                print("Error: before_seconds must be a non-negative integer")
                sys.exit(1)
        except ValueError:
            print("Error: before_seconds must be a valid integer")
            sys.exit(1)

    db_conn = None
    if len(sys.argv) > 2:
        db_conn = sys.argv[2]

    try:
        # Create manager
        manager = get_session_manager(db_conn)

        # Calculate cutoff time
        cutoff_time = datetime.now() - timedelta(seconds=before_seconds)

        # Find sessions to delete
        sessions = manager.list_sessions()
        sessions_to_delete = [
            session for session in sessions
            if session.create_time is not None and session.create_time < cutoff_time
        ]

        deleted_count = 0
        failed_disk_files = 0
        task_dir = get_task_dir()

        for session in sessions_to_delete:
            # Delete session and its chat history from the database
            manager.delete_session(session.session_id)
            deleted_count += 1

            # Clean up disk files associated with the session
            _deleted, _failed = delete_session_disk_files(task_dir, session.session_id)
            failed_disk_files += len(_failed)

        # Remove orphaned .pipe/.jsonl files whose .stdout counterpart is gone
        _orphan_deleted, _orphan_failed = clean_orphaned_session_files(task_dir)
        failed_disk_files += len(_orphan_failed)

        print(f"Successfully cleaned {deleted_count} sessions")
        print(f"Cutoff time: {cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Sessions older than {before_seconds} seconds ({before_seconds // 86400} days) have been deleted")
        if failed_disk_files:
            print(f"[WARN] Failed to remove {failed_disk_files} disk file(s)")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
