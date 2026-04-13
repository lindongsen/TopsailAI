#!/usr/bin/env python3
'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: CLI entry point for agent_daemon
'''

import sys
import argparse
import os
import signal
import time

# Add the parent directory to the path for imports
CWD = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(CWD))

from topsailai import WORK_FOLDER
from topsailai_server.agent_daemon import logger

# Default values
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = "7373"
DEFAULT_DB_URL = "sqlite:///topsailai_agent_daemon.db"

DEFAULT_PROCESSOR = CWD + "/scripts/processor.sh"
DEFAULT_SUMMARIZER = CWD + "/scripts/summarizer.sh"
DEFAULT_SESSION_STATE_CHECKER = CWD + "/scripts/session_state_checker.py"

# PID file location
PID_FILE = os.path.join(WORK_FOLDER, "topsailai_agent_daemon.pid")


def init_env():
    """ Init Environ """
    for k, v in dict(
        TOPSAILAI_AGENT_DAEMON_HOST=DEFAULT_HOST,
        TOPSAILAI_AGENT_DAEMON_PORT=DEFAULT_PORT,
        TOPSAILAI_AGENT_DAEMON_DB_URL=DEFAULT_DB_URL,
        TOPSAILAI_AGENT_DAEMON_PROCESSOR=DEFAULT_PROCESSOR,
        TOPSAILAI_AGENT_DAEMON_SUMMARIZER=DEFAULT_SUMMARIZER,
        TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER=DEFAULT_SESSION_STATE_CHECKER,
    ).items():
        if not os.getenv(k):
            os.environ[k] = v
    return

def write_pid(pid):
    """Write PID to file"""
    try:
        with open(PID_FILE, 'w') as f:
            f.write(str(pid))
    except Exception as e:
        logger.warning("Failed to write PID file: %s", e)


def read_pid():
    """Read PID from file"""
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r') as f:
                return int(f.read().strip())
    except Exception:
        pass
    return None


def remove_pid():
    """Remove PID file"""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass


def is_process_running(pid):
    """Check if process is running"""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def do_start(args):
    """Start the agent_daemon server"""
    init_env()

    # Check if already running
    existing_pid = read_pid()
    if existing_pid and is_process_running(existing_pid):
        logger.error("Agent daemon is already running with PID %d", existing_pid)
        print(f"Error: Agent daemon is already running with PID {existing_pid}")
        sys.exit(1)

    # Set environment variables from CLI arguments (override existing)
    if args.host:
        os.environ['TOPSAILAI_AGENT_DAEMON_HOST'] = args.host
    if args.port:
        os.environ['TOPSAILAI_AGENT_DAEMON_PORT'] = str(args.port)
    if args.db_url:
        os.environ['TOPSAILAI_AGENT_DAEMON_DB_URL'] = args.db_url
    if args.processor:
        os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = args.processor
    if args.summarizer:
        os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = args.summarizer
    if args.session_state_checker:
        os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = args.session_state_checker

    # Log the configuration using os.getenv to reflect actual values being used
    logger.info("Starting agent_daemon with configuration:")
    logger.info("  host: %s", os.getenv('TOPSAILAI_AGENT_DAEMON_HOST', DEFAULT_HOST))
    logger.info("  port: %s", os.getenv('TOPSAILAI_AGENT_DAEMON_PORT', DEFAULT_PORT))
    logger.info("  db_url: %s", os.getenv('TOPSAILAI_AGENT_DAEMON_DB_URL', DEFAULT_DB_URL))
    logger.info("  processor: %s", os.getenv('TOPSAILAI_AGENT_DAEMON_PROCESSOR') or "not set")
    logger.info("  session_state_checker: %s", os.getenv('TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER') or "not set")

    required_vars = [
        "TOPSAILAI_AGENT_DAEMON_PROCESSOR",
        "TOPSAILAI_AGENT_DAEMON_SUMMARIZER",
        "TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER"
    ]
    for var in required_vars:
        if not os.getenv(var):
            logger.error("Required environment variable %s is not set", var)
            sys.exit(1)

    # Import main after setting environment variables
    from topsailai_server.agent_daemon.main import main

    # Write PID
    pid = os.getpid()
    write_pid(pid)

    try:
        # Run the main application
        main()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down")
    except Exception as e:
        logger.exception("Error starting agent_daemon: %s", e)
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        remove_pid()


def do_stop(args):
    """Stop the agent_daemon server"""
    pid = read_pid()
    if not pid:
        print("Error: PID file not found. Is the agent daemon running?")
        sys.exit(1)

    if not is_process_running(pid):
        print(f"Warning: Process {pid} is not running. Cleaning up PID file.")
        remove_pid()
        sys.exit(1)

    try:
        logger.info("Stopping agent_daemon (PID: %d)", pid)
        os.kill(pid, signal.SIGTERM)

        # Wait for process to stop
        for _ in range(10):
            if not is_process_running(pid):
                break
            time.sleep(0.5)

        # Force kill if still running
        if is_process_running(pid):
            logger.warning("Process did not stop gracefully, forcing...")
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)

        remove_pid()
        print(f"Agent daemon (PID: {pid}) stopped successfully")

    except OSError as e:
        logger.error("Failed to stop agent_daemon: %s", e)
        print(f"Error: Failed to stop agent daemon: {e}")
        sys.exit(1)


def cli():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Agent Daemon - AI Agent orchestration service',
        prog='topsailai_agent_daemon'
    )
    parser.add_argument(
        '--version',
        action='version',
        version='1.0.0'
    )

    # Create subparsers for start/stop commands
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Start command
    start_parser = subparsers.add_parser('start', help='Start the agent daemon')
    start_parser.add_argument(
        '--host',
        type=str,
        default=DEFAULT_HOST,
        help=f'Listen IP (default: {DEFAULT_HOST})'
    )
    start_parser.add_argument(
        '--port',
        type=int,
        default=int(DEFAULT_PORT),
        help=f'Listen port (default: {DEFAULT_PORT})'
    )
    start_parser.add_argument(
        '--db_url',
        type=str,
        default=DEFAULT_DB_URL,
        help=f'Database URL (default: {DEFAULT_DB_URL})'
    )
    start_parser.add_argument(
        '--processor',
        type=str,
        help='Script file path for TOPSAILAI_AGENT_DAEMON_PROCESSOR'
    )
    start_parser.add_argument(
        '--summarizer',
        type=str,
        help='Script file path for TOPSAILAI_AGENT_DAEMON_SUMMARIZER'
    )
    start_parser.add_argument(
        '--session_state_checker',
        type=str,
        help='Script file path for TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'
    )
    start_parser.set_defaults(func=do_start)

    # Stop command
    stop_parser = subparsers.add_parser('stop', help='Stop the agent daemon')
    stop_parser.set_defaults(func=do_stop)

    # Parse arguments
    args = parser.parse_args()

    # If no command provided, show help
    if not args.command:
        parser.print_help()
        sys.exit(1)

    logger.info("work folder: [%s]", WORK_FOLDER)

    # Execute the command
    args.func(args)


if __name__ == '__main__':
    cli()