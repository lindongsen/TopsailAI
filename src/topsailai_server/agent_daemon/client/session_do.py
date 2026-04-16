"""
Session Do Functions

This module provides the do_xxx functions for session-related CLI operations.
These functions are used by the topsailai_agent_client CLI.

Functions:
    - do_client_health: Check server health
    - do_client_list_sessions: List sessions
    - do_client_get_session: Get a single session by ID
    - do_client_delete_sessions: Delete sessions
    - do_client_process_session: Process pending messages for a session
"""

import argparse
import socket

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.client.session import SessionClient


# Default values - support environment variable overrides
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 7373
DEFAULT_SESSION_ID = socket.gethostname()


def do_client_health(args):
    """Check server health"""
    client = SessionClient(base_url=f"http://{args.host}:{args.port}")
    
    try:
        if client.health_check():
            print(f"Server is healthy at http://{args.host}:{args.port}")
            return True
        else:
            print(f"Server health check failed at http://{args.host}:{args.port}")
            return False
    except Exception as e:
        print(f"Error: Cannot connect to server at http://{args.host}:{args.port}")
        logger.exception("Health check failed: %s", e)
        return False


def do_client_list_sessions(args):
    """List sessions"""
    client = SessionClient(base_url=f"http://{args.host}:{args.port}")
    
    try:
        logger.info("Listing sessions")
        
        # Parse session_ids if provided
        session_ids = None
        if args.session_ids:
            session_ids = [s.strip() for s in args.session_ids.split(',') if s.strip()]
        
        sessions = client.list_sessions(
            session_ids=session_ids,
            start_time=args.start_time,
            end_time=args.end_time,
            offset=args.offset or 0,
            limit=args.limit or 1000,
            sort_key=args.sort_key or "create_time",
            order_by=args.order_by or "desc",
            verbose=args.verbose
        )
        
        return True
    except Exception as e:
        logger.exception("Failed to list sessions: %s", e)
        print(f"Error: {e}")
        return False


def do_client_get_session(args):
    """Get a single session by ID"""
    client = SessionClient(base_url=f"http://{args.host}:{args.port}")
    
    try:
        logger.info("Getting session %s", args.session_id)
        client.get_session(args.session_id, verbose=args.verbose)
        return True
    except Exception as e:
        logger.exception("Failed to get session: %s", e)
        print(f"Error: {e}")
        return False


def do_client_delete_sessions(args):
    """Delete sessions"""
    client = SessionClient(base_url=f"http://{args.host}:{args.port}")
    
    # Get session IDs from positional args or --session-ids option
    session_ids = []
    if hasattr(args, 'session_ids') and args.session_ids:
        # Handle positional args
        session_ids = list(args.session_ids)
    elif hasattr(args, 'session_ids_str') and args.session_ids_str:
        # Handle --session-ids option (comma-separated string)
        session_ids = [s.strip() for s in args.session_ids_str.split(',') if s.strip()]
    
    if not session_ids:
        print("Error: At least one session ID is required")
        return False
    
    try:
        logger.info("Deleting %d session(s)", len(session_ids))
        client.delete_sessions(session_ids, verbose=args.verbose)
        return True
    except Exception as e:
        logger.exception("Failed to delete sessions: %s", e)
        print(f"Error: {e}")
        return False


def do_client_process_session(args):
    """Process pending messages for a session"""
    client = SessionClient(base_url=f"http://{args.host}:{args.port}")
    
    try:
        logger.info("Processing session %s", args.session_id)
        client.process_session(args.session_id, verbose=args.verbose)
        return True
    except Exception as e:
        logger.exception("Failed to process session: %s", e)
        print(f"Error: {e}")
        return False


def add_session_parsers(subparsers):
    """Add session-related subparsers to the argument parser
    
    Args:
        subparsers: The subparsers object from argparse
    """
    # Health check
    health_parser = subparsers.add_parser('health', help='Check server health')
    health_parser.set_defaults(func=do_client_health)
    
    # List sessions
    list_sessions_parser = subparsers.add_parser('list-sessions', help='List all sessions')
    list_sessions_parser.add_argument('--session-ids', type=str, help='Comma-separated session IDs to filter')
    list_sessions_parser.add_argument('--start-time', type=str, help='Start time filter')
    list_sessions_parser.add_argument('--end-time', type=str, help='End time filter')
    list_sessions_parser.add_argument('--offset', type=int, default=0, help='Offset (default: 0)')
    list_sessions_parser.add_argument('--limit', type=int, default=1000, help='Limit (default: 1000)')
    list_sessions_parser.add_argument('--sort-key', type=str, default='create_time', help='Sort key (default: create_time)')
    list_sessions_parser.add_argument('--order-by', type=str, default='desc', choices=['asc', 'desc'], help='Order by (default: desc)')
    list_sessions_parser.set_defaults(func=do_client_list_sessions)
    
    # Get session
    get_session_parser = subparsers.add_parser('get-session', help='Get a single session by ID')
    get_session_parser.add_argument('--session-id', type=str, required=True, help='Session ID (required)')
    get_session_parser.set_defaults(func=do_client_get_session)
    
    # Process session
    process_session_parser = subparsers.add_parser('process-session', help='Process pending messages for a session')
    process_session_parser.add_argument('--session-id', type=str, default=DEFAULT_SESSION_ID, help=f'Session ID (default: {DEFAULT_SESSION_ID})')
    process_session_parser.set_defaults(func=do_client_process_session)
    
    # Delete sessions
    delete_sessions_parser = subparsers.add_parser('delete-sessions', help='Delete sessions')
    delete_sessions_parser.add_argument('session_ids', nargs='*', help='Session IDs to delete (positional args)')
    delete_sessions_parser.add_argument('--session-ids', dest='session_ids_str', type=str, help='Comma-separated session IDs to delete')
    delete_sessions_parser.set_defaults(func=do_client_delete_sessions)
