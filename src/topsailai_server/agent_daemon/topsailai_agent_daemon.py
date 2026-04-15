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
import atexit

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
    """Initialize environment variables with default values if not set."""
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


def write_pid(pid):
    """Write PID to file for process tracking."""
    try:
        with open(PID_FILE, 'w') as f:
            f.write(str(pid))
    except Exception as e:
        logger.warning("Failed to write PID file: %s", e)


def read_pid():
    """Read PID from file for process management."""
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r') as f:
                return int(f.read().strip())
    except Exception:
        pass
    return None


def remove_pid():
    """Remove PID file during cleanup."""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass


def is_process_running(pid):
    """Check if a process with given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cleanup():
    """Cleanup handler registered with atexit."""
    remove_pid()


def daemonize():
    """
    Fork the current process into a daemon.
    
    This function performs the classic Unix double-fork to create a daemon process.
    The daemon will run in the background, detached from the terminal.
    
    Returns:
        bool: True if this is the parent process (should exit), False if child process (continue)
    """
    try:
        # First fork - detach from parent process
        pid = os.fork()
        if pid > 0:
            # Parent process - wait briefly then exit
            time.sleep(0.5)
            sys.exit(0)
    except OSError as e:
        logger.error("First fork failed: %s", e)
        sys.exit(1)

    # Decouple from parent environment
    os.chdir(WORK_FOLDER)
    os.setsid()  # Create new session, become session leader
    os.umask(0o022)

    # Second fork - prevent acquiring a controlling terminal
    try:
        pid = os.fork()
        if pid > 0:
            # First child - exit
            sys.exit(0)
    except OSError as e:
        logger.error("Second fork failed: %s", e)
        sys.exit(1)

    # Redirect standard file descriptors to /dev/null
    sys.stdout.flush()
    sys.stderr.flush()
    with open('/dev/null', 'r') as devnull:
        os.dup2(devnull.fileno(), sys.stdin.fileno())
    with open('/dev/null', 'a+') as devnull:
        os.dup2(devnull.fileno(), sys.stdout.fileno())
        os.dup2(devnull.fileno(), sys.stderr.fileno())

    # Register cleanup handler
    atexit.register(cleanup)

    return False


def do_start(args):
    """
    Start the agent_daemon server in background mode.
    
    This function:
    1. Checks if daemon is already running
    2. Validates required environment variables
    3. Daemonizes the process
    4. Starts the main application
    
    Args:
        args: Parsed command-line arguments
    """
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

    # Validate required environment variables
    required_vars = [
        "TOPSAILAI_AGENT_DAEMON_PROCESSOR",
        "TOPSAILAI_AGENT_DAEMON_SUMMARIZER",
        "TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER"
    ]
    for var in required_vars:
        if not os.getenv(var):
            logger.error("Required environment variable %s is not set", var)
            sys.exit(1)

    # Daemonize the process (runs in background)
    is_parent = daemonize()

    if is_parent:
        # Parent process - print success message and exit
        print(f"Agent daemon started successfully")
        print(f"PID file: {PID_FILE}")
        sys.exit(0)

    # Child process (daemon) - write PID and start main application
    pid = os.getpid()
    write_pid(pid)
    logger.info("Daemon started with PID: %d", pid)

    try:
        # Import main after setting environment variables
        from topsailai_server.agent_daemon.main import main

        # Run the main application
        main()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down")
    except Exception as e:
        logger.exception("Error in daemon process: %s", e)
        sys.exit(1)
    finally:
        remove_pid()


def do_stop(args):
    """
    Stop the agent_daemon server gracefully.
    
    This function:
    1. Reads the PID from file
    2. Sends SIGTERM for graceful shutdown
    3. Waits for process to terminate
    4. Force kills with SIGKILL if necessary
    5. Removes the PID file
    
    Args:
        args: Parsed command-line arguments
    """
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
        print(f"Stopping agent daemon (PID: {pid})...")

        # Send SIGTERM for graceful shutdown
        os.kill(pid, signal.SIGTERM)

        # Wait for process to stop gracefully
        for i in range(10):
            if not is_process_running(pid):
                break
            time.sleep(0.5)

        # Force kill if still running
        if is_process_running(pid):
            logger.warning("Process did not stop gracefully, forcing SIGKILL...")
            print("Process did not stop gracefully, forcing...")
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)

        remove_pid()
        print(f"Agent daemon (PID: {pid}) stopped successfully")
        logger.info("Agent daemon stopped successfully")

    except OSError as e:
        logger.error("Failed to stop agent_daemon: %s", e)
        print(f"Error: Failed to stop agent daemon: {e}")
        sys.exit(1)


def do_status(args):
    """
    Check and display the status of the agent_daemon server.
    
    Args:
        args: Parsed command-line arguments
    """
    pid = read_pid()
    if not pid:
        print("Agent daemon is NOT running (no PID file)")
        return

    if is_process_running(pid):
        print(f"Agent daemon is RUNNING (PID: {pid})")
    else:
        print(f"Agent daemon is NOT running (stale PID file: {pid})")
        print("Cleaning up stale PID file...")
        remove_pid()


def do_restart(args):
    """
    Restart the agent_daemon server.
    
    This function stops the running daemon (if any) and starts a new one.
    
    Args:
        args: Parsed command-line arguments
    """
    print("Restarting agent daemon...")

    # Try to stop existing daemon
    pid = read_pid()
    if pid and is_process_running(pid):
        do_stop(args)
        # Wait for process to fully terminate
        time.sleep(1)

    # Start new daemon
    print("Starting agent daemon...")
    do_start(args)


def cli():
    """
    CLI entry point with argument parsing and command dispatch.
    
    Supports the following commands:
    - start: Start the daemon in background mode
    - stop: Stop the running daemon
    - restart: Restart the daemon
    - status: Check if daemon is running
    """
    parser = argparse.ArgumentParser(
        description='Agent Daemon - AI Agent orchestration service',
        prog='topsailai_agent_daemon'
    )
    parser.add_argument(
        '--version',
        action='version',
        version='1.0.0'
    )

    # Create subparsers for commands
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Start command
    start_parser = subparsers.add_parser('start', help='Start the agent daemon in background')
    start_parser.add_argument(
        '--host',
        type=str,
        default=None,
        help=f'Listen IP (default: {DEFAULT_HOST})'
    )
    start_parser.add_argument(
        '--port',
        type=int,
        default=None,
        help=f'Listen port (default: {DEFAULT_PORT})'
    )
    start_parser.add_argument(
        '--db_url',
        type=str,
        default=None,
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

    # Status command
    status_parser = subparsers.add_parser('status', help='Check if agent daemon is running')
    status_parser.set_defaults(func=do_status)

    # Restart command
    restart_parser = subparsers.add_parser('restart', help='Restart the agent daemon')
    restart_parser.add_argument(
        '--host',
        type=str,
        default=None,
        help=f'Listen IP (default: {DEFAULT_HOST})'
    )
    restart_parser.add_argument(
        '--port',
        type=int,
        default=None,
        help=f'Listen port (default: {DEFAULT_PORT})'
    )
    restart_parser.add_argument(
        '--db_url',
        type=str,
        default=None,
        help=f'Database URL (default: {DEFAULT_DB_URL})'
    )
    restart_parser.add_argument(
        '--processor',
        type=str,
        help='Script file path for TOPSAILAI_AGENT_DAEMON_PROCESSOR'
    )
    restart_parser.add_argument(
        '--summarizer',
        type=str,
        help='Script file path for TOPSAILAI_AGENT_DAEMON_SUMMARIZER'
    )
    restart_parser.add_argument(
        '--session_state_checker',
        type=str,
        help='Script file path for TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'
    )
    restart_parser.set_defaults(func=do_restart)

    # Parse arguments
    args = parser.parse_args()

    # If no command provided, show help
    if not args.command:
        parser.print_help()
        sys.exit(1)

    logger.info("Work folder: [%s]", WORK_FOLDER)

    # Execute the command
    args.func(args)


if __name__ == '__main__':
    cli()
