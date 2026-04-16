"""
Task Do Functions

This module provides the do_xxx functions for task-related CLI operations.
These functions are used by the topsailai_agent_client CLI.

Functions:
    - do_client_set_task_result: Set a task result
    - do_client_get_tasks: Retrieve tasks
"""

import socket

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.client.task import TaskClient


# Default values - support environment variable overrides
DEFAULT_SESSION_ID = socket.gethostname()


def do_client_set_task_result(args):
    """Set a task result"""
    client = TaskClient(base_url=f"http://{args.host}:{args.port}")
    
    try:
        logger.info("Setting task result for session %s, task %s", args.session_id, args.task_id)
        client.set_task_result(
            session_id=args.session_id,
            processed_msg_id=args.processed_msg_id,
            task_id=args.task_id,
            task_result=args.task_result,
            verbose=args.verbose
        )
        return True
    except Exception as e:
        logger.exception("Failed to set task result: %s", e)
        print(f"Error: {e}")
        return False


def do_client_get_tasks(args):
    """Retrieve tasks"""
    client = TaskClient(base_url=f"http://{args.host}:{args.port}")
    
    try:
        logger.info("Retrieving tasks for session %s", args.session_id)
        
        # Parse task_ids if provided
        task_ids = None
        if args.task_ids:
            task_ids = [t.strip() for t in args.task_ids.split(',') if t.strip()]
        
        client.list_tasks(
            session_id=args.session_id,
            task_ids=task_ids,
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
        logger.exception("Failed to retrieve tasks: %s", e)
        print(f"Error: {e}")
        return False


def add_task_parsers(subparsers):
    """Add task-related subparsers to the argument parser
    
    Args:
        subparsers: The subparsers object from argparse
    """
    # Set task result
    set_task_parser = subparsers.add_parser('set-task-result', help='Set a task result')
    set_task_parser.add_argument('--session-id', type=str, default=DEFAULT_SESSION_ID, help=f'Session ID (default: {DEFAULT_SESSION_ID})')
    set_task_parser.add_argument('--processed-msg-id', type=str, required=True, help='Processed message ID')
    set_task_parser.add_argument('--task-id', type=str, required=True, help='Task ID')
    set_task_parser.add_argument('--task-result', type=str, required=True, help='Task result')
    set_task_parser.set_defaults(func=do_client_set_task_result)
    
    # Get tasks (also available as list-tasks)
    get_tasks_parser = subparsers.add_parser('get-tasks', help='Retrieve tasks')
    get_tasks_parser.add_argument('--session-id', type=str, default=DEFAULT_SESSION_ID, help=f'Session ID (default: {DEFAULT_SESSION_ID})')
    get_tasks_parser.add_argument('--task-ids', type=str, help='Comma-separated task IDs')
    get_tasks_parser.add_argument('--start-time', type=str, help='Start time filter')
    get_tasks_parser.add_argument('--end-time', type=str, help='End time filter')
    get_tasks_parser.add_argument('--offset', type=int, default=0, help='Offset (default: 0)')
    get_tasks_parser.add_argument('--limit', type=int, default=1000, help='Limit (default: 1000)')
    get_tasks_parser.add_argument('--sort-key', type=str, default='create_time', help='Sort key (default: create_time)')
    get_tasks_parser.add_argument('--order-by', type=str, default='desc', choices=['asc', 'desc'], help='Order by (default: desc)')
    get_tasks_parser.set_defaults(func=do_client_get_tasks)
    
    # List tasks (alias for get-tasks)
    list_tasks_parser = subparsers.add_parser('list-tasks', help='Retrieve tasks (alias for get-tasks)')
    list_tasks_parser.add_argument('--session-id', type=str, default=DEFAULT_SESSION_ID, help=f'Session ID (default: {DEFAULT_SESSION_ID})')
    list_tasks_parser.add_argument('--task-ids', type=str, help='Comma-separated task IDs')
    list_tasks_parser.add_argument('--start-time', type=str, help='Start time filter')
    list_tasks_parser.add_argument('--end-time', type=str, help='End time filter')
    list_tasks_parser.add_argument('--offset', type=int, default=0, help='Offset (default: 0)')
    list_tasks_parser.add_argument('--limit', type=int, default=1000, help='Limit (default: 1000)')
    list_tasks_parser.add_argument('--sort-key', type=str, default='create_time', help='Sort key (default: create_time)')
    list_tasks_parser.add_argument('--order-by', type=str, default='desc', choices=['asc', 'desc'], help='Order by (default: desc)')
    list_tasks_parser.set_defaults(func=do_client_get_tasks)
