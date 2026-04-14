#!/usr/bin/env python3
"""
Mock session state checker script for integration testing.
Simulates the TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER behavior.
"""

import os
import sys


def main():
    """Main entry point for the mock session state checker."""
    # Read required environment variable
    session_id = os.environ.get('TOPSAILAI_SESSION_ID', '')
    
    # For testing purposes, always return "idle"
    # In a real scenario, this would check if a session is being processed
    print("idle")
    return 0


if __name__ == '__main__':
    sys.exit(main())
