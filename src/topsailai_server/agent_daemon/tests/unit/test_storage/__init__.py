"""
Test Storage Module

This package contains unit tests for the agent_daemon storage module.
The storage module provides SQLAlchemy-based persistence for sessions and messages.

Test Files:
    - test_base.py: Tests for SessionData, SessionStorageBase, MessageData, MessageStorageBase
    - test_session_manager.py: Tests for SessionSQLAlchemy (session storage operations)
    - test_message_manager.py: Tests for MessageSQLAlchemy (message storage operations)
    - test_processor_helper.py: Tests for processor_helper (message formatting and processing)

Usage:
    Run all storage tests:
        pytest tests/unit/test_storage/ -v

    Run specific test file:
        pytest tests/unit/test_storage/test_session_manager.py -v

Dependencies:
    - pytest
    - pytest-mock
    - sqlalchemy (in-memory SQLite for testing)
"""

import sys
import os

# Add the project root to the path for imports
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
