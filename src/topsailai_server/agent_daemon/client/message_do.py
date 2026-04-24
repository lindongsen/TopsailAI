"""
Message Do Functions

This module provides the do_xxx functions for message-related CLI operations.
These functions are used by the topsailai_agent_client CLI.

Functions:
    - do_client_send_message: Send a message to a session
    - do_client_get_messages: Retrieve messages from a session
"""

import socket

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.client.message import MessageClient


# Default values - support environment variable overrides
DEFAULT_SESSION_ID = socket.gethostname()


def do_client_send_message(args):
    """Send a message to a session"""
    client = MessageClient(base_url=f"http://{args.host}:{args.port}")
    
    try:
        logger.info("Sending message to session %s", args.session_id)
        client.send_message(
            session_id=args.session_id,
            message=args.message,
            role=args.role or "user",
            processed_msg_id=args.processed_msg_id,
            verbose=args.verbose
        )
        return True
    except Exception as e:
        logger.exception("Failed to send message: %s", e)
        print(f"Error: {e}")
        return False


def do_client_get_messages(args):
    """Retrieve messages from a session"""
    client = MessageClient(base_url=f"http://{args.host}:{args.port}")
    
    try:
        logger.info("Retrieving messages for session %s", args.session_id)
        client.list_messages(
            session_id=args.session_id,
            start_time=args.start_time,
            end_time=args.end_time,
            offset=args.offset or 0,
            limit=args.limit or 1000,
            sort_key=args.sort_key or "create_time",
            order_by=args.order_by or "desc",
            processed_msg_id=args.processed_msg_id,
            verbose=args.verbose
        )
        return True
    except Exception as e:
        logger.exception("Failed to retrieve messages: %s", e)
        print(f"Error: {e}")
        return False


def add_message_parsers(subparsers):
    """Add message-related subparsers to the argument parser
    
    Args:
        subparsers: The subparsers object from argparse
    """
    # Send message
    send_msg_parser = subparsers.add_parser('send-message', help='Send a message to a session')
    send_msg_parser.add_argument('--message', type=str, required=True, help='Message content')
    send_msg_parser.add_argument('--session-id', type=str, default=DEFAULT_SESSION_ID, help=f'Session ID (default: {DEFAULT_SESSION_ID})')
    send_msg_parser.add_argument('--role', type=str, default='user', choices=['user', 'assistant'], help='Message role (default: user)')
    send_msg_parser.add_argument('--processed-msg-id', type=str, help='Processed message ID')
    send_msg_parser.set_defaults(func=do_client_send_message)
    
    # Get messages (also available as list-messages)
    get_msgs_parser = subparsers.add_parser('get-messages', help='Retrieve messages from a session')
    get_msgs_parser.add_argument('--session-id', type=str, default=DEFAULT_SESSION_ID, help=f'Session ID (default: {DEFAULT_SESSION_ID})')
    get_msgs_parser.add_argument('--start-time', type=str, help='Start time filter')
    get_msgs_parser.add_argument('--end-time', type=str, help='End time filter')
    get_msgs_parser.add_argument('--offset', type=int, default=0, help='Offset (default: 0)')
    get_msgs_parser.add_argument('--limit', type=int, default=1000, help='Limit (default: 1000)')
    get_msgs_parser.add_argument('--sort-key', type=str, default='create_time', help='Sort key (default: create_time)')
    get_msgs_parser.add_argument('--order-by', type=str, default='desc', choices=['asc', 'desc'], help='Order by (default: desc)')
    get_msgs_parser.add_argument('--processed-msg-id', type=str, help='Filter messages by processed_msg_id')
    get_msgs_parser.set_defaults(func=do_client_get_messages)
    
    # List messages (alias for get-messages)
    list_msgs_parser = subparsers.add_parser('list-messages', help='Retrieve messages from a session (alias for get-messages)')
    list_msgs_parser.add_argument('--session-id', type=str, default=DEFAULT_SESSION_ID, help=f'Session ID (default: {DEFAULT_SESSION_ID})')
    list_msgs_parser.add_argument('--start-time', type=str, help='Start time filter')
    list_msgs_parser.add_argument('--end-time', type=str, help='End time filter')
    list_msgs_parser.add_argument('--offset', type=int, default=0, help='Offset (default: 0)')
    list_msgs_parser.add_argument('--limit', type=int, default=1000, help='Limit (default: 1000)')
    list_msgs_parser.add_argument('--sort-key', type=str, default='create_time', help='Sort key (default: create_time)')
    list_msgs_parser.add_argument('--order-by', type=str, default='desc', choices=['asc', 'desc'], help='Order by (default: desc)')
    list_msgs_parser.add_argument('--processed-msg-id', type=str, help='Filter messages by processed_msg_id')
    list_msgs_parser.set_defaults(func=do_client_get_messages)
