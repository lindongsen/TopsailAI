#!/usr/bin/env python3
'''
  Author: Dawsonlin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Client CLI for agent_daemon API
'''

import argparse
import json
import sys
import socket
import os
import requests

# Add the parent directory to the path for imports
CWD = __file__
CWD = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(CWD))

from topsailai_server.agent_daemon import logger

# Default values - support environment variable overrides
DEFAULT_HOST = os.environ.get("TOPSAILAI_AGENT_DAEMON_HOST", "localhost")
DEFAULT_PORT = int(os.environ.get("TOPSAILAI_AGENT_DAEMON_PORT", "7373"))
DEFAULT_SESSION_ID = socket.gethostname()

SPLIT_LINE = "\n" + "="*77


def format_time(time_str):
    """Format time string to YYYY-MM-DD HH:MM:SS"""
    if not time_str:
        return 'N/A'
    # Handle ISO format: 2026-04-13T23:27:53.123456
    if 'T' in time_str:
        date_part, time_part = time_str.split('T')
        time_part = time_part.split('.')[0]
        return f"{date_part} {time_part}"
    return time_str


def do_client_health(args):
    """Check server health"""
    base_url = f"http://{args.host}:{args.port}"
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            print(f"Server is healthy at {base_url}")
            if args.verbose:
                print(f"Response: {response.json()}")
            return True
        else:
            print(f"Server returned status code: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"Error: Cannot connect to server at {base_url}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


def do_client_list_sessions(args):
    """List sessions"""
    base_url = f"http://{args.host}:{args.port}"
    url = f"{base_url}/api/v1/session"

    params = {}

    if args.session_ids:
        params["session_ids"] = args.session_ids
    if args.start_time:
        params["start_time"] = args.start_time
    if args.end_time:
        params["end_time"] = args.end_time
    if args.offset is not None:
        params["offset"] = args.offset
    if args.limit is not None:
        params["limit"] = args.limit
    if args.sort_key:
        params["sort_key"] = args.sort_key
    if args.order_by:
        params["order_by"] = args.order_by

    try:
        logger.info("Listing sessions")
        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                sessions = result.get("data", [])
                print(f"Retrieved {len(sessions)} session(s)")
                if args.verbose:
                    print(f"Response: {json.dumps(result, indent=2)}")
                else:
                    for session in sessions:
                        create_time = format_time(session.get('create_time'))
                        session_id = session.get('session_id')
                        session_name = session.get('session_name', 'N/A')
                        task = session.get('task', 'N/A')
                        processed_msg_id = session.get('processed_msg_id', 'N/A')

                        # Only show one when session_id == session_name
                        if session_id == session_name:
                            session_display = session_id
                        else:
                            session_display = f"{session_id}: {session_name}"

                        print(SPLIT_LINE)
                        print(f"[{create_time}] {session_display}")
                        print(f"Task: {task}")
                        print(f">>> Processed: {processed_msg_id}")
                return True
            else:
                print(f"Error: {result.get('message', 'Unknown error')}")
                return False
        else:
            print(f"Error: HTTP {response.status_code} - {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"Error: Cannot connect to server at {base_url}")
        return False
    except Exception as e:
        logger.exception("Failed to list sessions: %s", e)
        print(f"Error: {e}")
        return False


def do_client_send_message(args):
    """Send a message to a session"""
    base_url = f"http://{args.host}:{args.port}"
    url = f"{base_url}/api/v1/message"

    data = {
        "message": args.message,
        "session_id": args.session_id,
    }

    if args.role:
        data["role"] = args.role

    if args.processed_msg_id:
        data["processed_msg_id"] = args.processed_msg_id

    try:
        logger.info("Sending message to session %s", args.session_id)
        response = requests.post(url, json=data, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                print(f"Message sent successfully")
                if args.verbose:
                    print(f"Response: {json.dumps(result, indent=2)}")
                return True
            else:
                print(f"Error: {result.get('message', 'Unknown error')}")
                return False
        else:
            print(f"Error: HTTP {response.status_code} - {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"Error: Cannot connect to server at {base_url}")
        return False
    except Exception as e:
        logger.exception("Failed to send message: %s", e)
        print(f"Error: {e}")
        return False


def do_client_get_messages(args):
    """Retrieve messages from a session"""
    base_url = f"http://{args.host}:{args.port}"
    url = f"{base_url}/api/v1/message"

    params = {
        "session_id": args.session_id,
    }

    if args.start_time:
        params["start_time"] = args.start_time
    if args.end_time:
        params["end_time"] = args.end_time
    if args.offset is not None:
        params["offset"] = args.offset
    if args.limit is not None:
        params["limit"] = args.limit
    if args.sort_key:
        params["sort_key"] = args.sort_key
    if args.order_by:
        params["order_by"] = args.order_by

    try:
        logger.info("Retrieving messages for session %s", args.session_id)
        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                messages = result.get("data", [])
                # First line shows count and session_id
                if messages:
                    session_id = messages[0].get('session_id')
                    print(f"Retrieved {len(messages)} message(s), Session: {session_id}")
                if args.verbose:
                    print(f"Response: {json.dumps(result, indent=2)}")
                else:
                    for msg in messages:
                        create_time = format_time(msg.get('create_time'))
                        update_time = format_time(msg.get('update_time'))
                        msg_id = msg.get('msg_id')
                        role = msg.get('role')
                        message = msg.get('message')
                        task_id = msg.get('task_id')
                        task_result = msg.get('task_result')

                        print(SPLIT_LINE)
                        # Show time and msg_id on first line
                        print(f"[{create_time}] [{msg_id}] [{role}]")
                        # Show role and full message on second line
                        print(message)
                        # If task_id exists, show it
                        if task_id:
                            print("")
                            print(f">>> update_time: [{update_time}]")
                            print(f">>> task_id: {task_id}")
                        # If task_result exists, show it
                        if task_result:
                            print(f">>> task_result: \n{task_result}")
                return True
            else:
                print(f"Error: {result.get('message', 'Unknown error')}")
                return False
        else:
            print(f"Error: HTTP {response.status_code} - {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"Error: Cannot connect to server at {base_url}")
        return False
    except Exception as e:
        logger.exception("Failed to retrieve messages: %s", e)
        print(f"Error: {e}")
        return False


def do_client_set_task_result(args):
    """Set a task result"""
    base_url = f"http://{args.host}:{args.port}"
    url = f"{base_url}/api/v1/task"

    data = {
        "session_id": args.session_id,
        "processed_msg_id": args.processed_msg_id,
        "task_id": args.task_id,
        "task_result": args.task_result,
    }

    try:
        logger.info("Setting task result for session %s, task %s", args.session_id, args.task_id)
        response = requests.post(url, json=data, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                print(f"Task result set successfully")
                if args.verbose:
                    print(f"Response: {json.dumps(result, indent=2)}")
                return True
            else:
                print(f"Error: {result.get('message', 'Unknown error')}")
                return False
        else:
            print(f"Error: HTTP {response.status_code} - {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"Error: Cannot connect to server at {base_url}")
        return False
    except Exception as e:
        logger.exception("Failed to set task result: %s", e)
        print(f"Error: {e}")
        return False


def do_client_get_tasks(args):
    """Retrieve tasks"""
    base_url = f"http://{args.host}:{args.port}"
    url = f"{base_url}/api/v1/task"

    params = {
        "session_id": args.session_id,
    }

    if args.task_ids:
        params["task_ids"] = args.task_ids
    if args.start_time:
        params["start_time"] = args.start_time
    if args.end_time:
        params["end_time"] = args.end_time
    if args.offset is not None:
        params["offset"] = args.offset
    if args.limit is not None:
        params["limit"] = args.limit
    if args.sort_key:
        params["sort_key"] = args.sort_key
    if args.order_by:
        params["order_by"] = args.order_by

    try:
        logger.info("Retrieving tasks for session %s", args.session_id)
        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                tasks = result.get("data", [])
                print(f"Retrieved {len(tasks)} task(s)")
                if args.verbose:
                    print(f"Response: {json.dumps(result, indent=2)}")
                else:
                    for task in tasks:
                        create_time = format_time(task.get('create_time'))
                        session_id = task.get('session_id')
                        task_id = task.get('task_id')
                        msg_id = task.get('msg_id', 'N/A')
                        message = task.get('message', '')
                        task_result = task.get('task_result')

                        # Format according to document specification:
                        # [2026-04-14 13:31:36] task=[{TASK_ID}] session=[{SESSION_ID}] msg=[{MSG_ID}]
                        # task content
                        # ---
                        # task result
                        print(SPLIT_LINE)
                        print(f"[{create_time}] task=[{task_id}] session=[{session_id}] msg=[{msg_id}]")
                        print("Task: " + message)
                        if task_result:
                            print("---")
                            print(task_result)
                return True
            else:
                print(f"Error: {result.get('message', 'Unknown error')}")
                return False
        else:
            print(f"Error: HTTP {response.status_code} - {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"Error: Cannot connect to server at {base_url}")
        return False
    except Exception as e:
        logger.exception("Failed to retrieve tasks: %s", e)
        print(f"Error: {e}")
        return False


def do_client_process_session(args):
    """Process pending messages for a session"""
    base_url = f"http://{args.host}:{args.port}"
    url = f"{base_url}/api/v1/session/process"

    data = {
        "session_id": args.session_id,
    }

    try:
        logger.info("Processing session %s", args.session_id)
        response = requests.post(url, json=data, timeout=30)

        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                data = result.get("data", {})
                processed = data.get("processed", False)
                message = data.get("message", "")
                print(f"Session processed: {processed}")
                print(f"Message: {message}")
                if args.verbose:
                    print(f"Response: {json.dumps(result, indent=2)}")
                return True
            else:
                print(f"Error: {result.get('message', 'Unknown error')}")
                return False
        else:
            print(f"Error: HTTP {response.status_code} - {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"Error: Cannot connect to server at {base_url}")
        return False
    except Exception as e:
        logger.exception("Failed to process session: %s", e)
        print(f"Error: {e}")
        return False


def do_client_delete_sessions(args):
    """Delete sessions"""
    base_url = f"http://{args.host}:{args.port}"
    url = f"{base_url}/api/v1/session/delete"

    # Get session IDs from positional args or --session-ids option
    session_ids = []
    if args.session_ids:
        # Handle comma-separated string
        if isinstance(args.session_ids, str):
            session_ids = [s.strip() for s in args.session_ids.split(',') if s.strip()]
        else:
            session_ids = list(args.session_ids)

    if not session_ids:
        print("Error: At least one session ID is required")
        return False

    data = {
        "session_ids": session_ids,
    }

    try:
        logger.info("Deleting %d session(s)", len(session_ids))
        response = requests.post(url, json=data, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                data = result.get("data", {})
                deleted_sessions = data.get("deleted_sessions", 0)
                deleted_messages = data.get("deleted_messages", 0)
                deleted_ids = data.get("session_ids", [])

                print(f"Deleted {deleted_sessions} session(s)")
                print(f"Deleted {deleted_messages} message(s)")
                print(f"Session IDs: {', '.join(deleted_ids)}")

                if args.verbose:
                    print(f"Response: {json.dumps(result, indent=2)}")
                return True
            else:
                print(f"Error: {result.get('message', 'Unknown error')}")
                return False
        else:
            print(f"Error: HTTP {response.status_code} - {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"Error: Cannot connect to server at {base_url}")
        return False
    except Exception as e:
        logger.exception("Failed to delete sessions: %s", e)
        print(f"Error: {e}")
        return False


def cli():
    """Client CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Agent Daemon Client - CLI to interact with agent_daemon API',
        prog='topsailai_agent_daemon client'
    )
    parser.add_argument(
        '--host',
        type=str,
        default=DEFAULT_HOST,
        help=f'Server host (default: {DEFAULT_HOST}, env: TOPSAILAI_AGENT_DAEMON_HOST)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=DEFAULT_PORT,
        help=f'Server port (default: {DEFAULT_PORT}, env: TOPSAILAI_AGENT_DAEMON_PORT)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output'
    )

    # Client subcommands
    subparsers = parser.add_subparsers(dest='operation', help='Client operations')

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
    list_msgs_parser.set_defaults(func=do_client_get_messages)

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

    # Process session
    process_session_parser = subparsers.add_parser('process-session', help='Process pending messages for a session')
    process_session_parser.add_argument('--session-id', type=str, default=DEFAULT_SESSION_ID, help=f'Session ID (default: {DEFAULT_SESSION_ID})')
    process_session_parser.set_defaults(func=do_client_process_session)

    # Delete sessions
    delete_sessions_parser = subparsers.add_parser('delete-sessions', help='Delete sessions')
    delete_sessions_parser.add_argument('session_ids', nargs='*', help='Session IDs to delete (positional args)')
    delete_sessions_parser.add_argument('--session-ids', type=str, help='Comma-separated session IDs to delete')
    delete_sessions_parser.set_defaults(func=do_client_delete_sessions)

    # Parse arguments
    args = parser.parse_args()

    # Require operation
    if not args.operation:
        parser.print_help()
        sys.exit(1)

    # Execute the operation
    args.func(args)


if __name__ == '__main__':
    cli()
