"""
Test Client Module

This package contains unit tests for the agent_daemon client module.
The client module provides REST API clients for interacting with the agent_daemon service.

Test Files:
    - test_base.py: Tests for client/base.py (BaseClient)
    - test_session.py: Tests for client/session.py (SessionClient)
    - test_message.py: Tests for client/message.py (MessageClient)
    - test_task.py: Tests for client/task.py (TaskClient)
    - test_cli.py: Tests for client/cli.py (CLI argument parsing)
    - test_client_main.py: Tests for client/__init__.py (main client exports)

Usage:
    Run all client tests:
        pytest tests/unit/test_client/ -v

    Run specific test file:
        pytest tests/unit/test_client/test_base.py -v
"""
