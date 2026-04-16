#!/usr/bin/env python3
"""
Agent Daemon Client CLI

Author: Dawsonlin
Email: lin_dongsen@126.com
Created: 2026-04-12
Purpose: Client CLI for agent_daemon API

This module provides a command-line interface for interacting with the
agent_daemon API. It uses the client modules from topsailai_server.agent_daemon.client
for all API operations.

Usage:
    from topsailai_server.agent_daemon.topsailai_agent_client import cli
    cli()
"""

import argparse
import os
import sys

# Add the parent directory to the path for imports
CWD = __file__
CWD = os.path.dirname(os.path.abspath(__file__))
CWD = os.path.dirname(CWD)
sys.path.insert(0, os.path.dirname(CWD))

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.client import (
    add_session_parsers,
    add_message_parsers,
    add_task_parsers,
)


# Default values - support environment variable overrides
DEFAULT_HOST = os.environ.get("TOPSAILAI_AGENT_DAEMON_HOST", "localhost")
DEFAULT_PORT = int(os.environ.get("TOPSAILAI_AGENT_DAEMON_PORT", "7373"))


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
    
    # Add session parsers
    add_session_parsers(subparsers)
    
    # Add message parsers
    add_message_parsers(subparsers)
    
    # Add task parsers
    add_task_parsers(subparsers)
    
    # Parse arguments
    args = parser.parse_args()
    
    # Require operation
    if not args.operation:
        parser.print_help()
        sys.exit(1)
    
    # Execute the operation
    success = args.func(args)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    cli()
