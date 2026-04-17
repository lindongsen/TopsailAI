"""
Test API Module

This package contains unit tests for the agent_daemon API module.
The API module provides RESTful endpoints for managing sessions, messages, and tasks.

Test Files:
    - test_utils.py: Tests for api/utils.py (ApiResponse, success_response, error_response)
    - test_app.py: Tests for api/app.py (create_app, health check)
    - test_session.py: Tests for api/routes/session.py (SessionClient)
    - test_message.py: Tests for api/routes/message.py (MessageClient)
    - test_task.py: Tests for api/routes/task.py (TaskClient)

Usage:
    Run all API tests:
        pytest tests/unit/test_api/ -v

    Run specific test file:
        pytest tests/unit/test_api/test_utils.py -v
"""
