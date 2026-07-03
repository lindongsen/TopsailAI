'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-15
  Purpose: Pytest configuration and fixtures for unit tests

  Features:
  - Test isolation with environment variable cleanup
  - Temporary directory management
  - Mock environment reader
'''

import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture(autouse=True)
def clean_env():
    """
    Automatically clean up environment variables before and after each test.
    
    This fixture ensures test isolation by:
    1. Saving original environment variables before the test
    2. Clearing non-preserved variables before the test runs
    3. Restoring them after the test completes
    4. Cleaning up any test-specific environment changes
    """
    original_env = os.environ.copy()
    
    # List of environment variables to always preserve
    preserved_vars = {
        'PATH', 'HOME', 'USER', 'SHELL', 'LANG', 'LC_ALL',
        'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV',
        'PYTEST_CURRENT_TEST',  # Required by pytest during teardown
    }
    
    # Clear non-preserved environment variables BEFORE the test
    for key in list(os.environ.keys()):
        if key not in preserved_vars:
            os.environ.pop(key, None)
    
    yield
    
    # Restore preserved variables
    for key in list(os.environ.keys()):
        if key not in preserved_vars:
            os.environ.pop(key, None)
    
    # Restore original values for preserved variables
    for key, value in original_env.items():
        if key in preserved_vars:
            os.environ[key] = value


@pytest.fixture(autouse=True)
def fast_tool_approval_timeout():
    """
    Set a short default timeout for tool approval tests.

    The production default timeout is intentionally long (human-in-the-loop),
    but unit tests must complete quickly. This fixture runs after ``clean_env``
    and sets a small default so deny/ask_again timeout paths execute fast.
    """
    os.environ['TOPSAILAI_TOOL_APPROVAL_DEFAULT_TIMEOUT'] = '0.05'
    yield


@pytest.fixture(autouse=True)
def clear_approval_state():
    """
    Automatically clear tool approval state before and after each test.

    This fixture prevents state leaks between tool_approval tests by:
    1. Clearing cached approval rules.
    2. Clearing pending approval instances from the registry.
    3. Resetting the singleton LocalApprovalTransport instance.
    """
    from topsailai.ai_base.tool_approval import matcher, registry
    from topsailai.ai_base.tool_approval.transport import LocalApprovalTransport

    matcher.clear_approval_rules_cache()
    registry.clear_pending_approvals()
    LocalApprovalTransport.reset_instance()

    yield

    matcher.clear_approval_rules_cache()
    registry.clear_pending_approvals()
    LocalApprovalTransport.reset_instance()

@pytest.fixture
def temp_workspace():
    """
    Create a temporary workspace directory for tests.
    
    Yields:
        Path: Path to the temporary workspace directory
        
    The directory is automatically cleaned up after the test.
    """
    temp_dir = tempfile.mkdtemp(prefix="test_workspace_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_env_reader():
    """
    Provide a mock environment reader for tests.
    
    Returns:
        MagicMock: A mock EnvReader instance with common methods mocked
    """
    mock_reader = MagicMock()
    mock_reader.get.return_value = None
    mock_reader.get_int.return_value = 0
    mock_reader.get_bool.return_value = False
    mock_reader.get_float.return_value = 0.0
    return mock_reader


@pytest.fixture
def sample_messages():
    """
    Provide sample chat messages for testing.
    
    Returns:
        list: A list of sample message dictionaries
    """
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, how are you?"},
        {"role": "assistant", "content": "I'm doing well, thank you!"},
    ]


@pytest.fixture
def sample_tool_calls():
    """
    Provide sample tool call data for testing.
    
    Returns:
        list: A list of sample tool call dictionaries
    """
    return [
        {
            "tool_call": "curl",
            "tool_args": {"url": "https://example.com"},
            "error": None,
            "result": {"status": 200, "data": "Success"}
        },
        {
            "tool_call": "file_read",
            "tool_args": {"path": "/tmp/test.txt"},
            "error": "File not found",
            "result": None
        }
    ]


@pytest.fixture
def mock_time():
    """
    Provide a mock time function for consistent testing.
    
    Returns:
        MagicMock: A mock time function that returns a fixed timestamp
    """
    import time
    fixed_time = 1700000000.0  # 2023-11-14 22:13:20 UTC
    
    with patch('time.time', return_value=fixed_time):
        yield fixed_time


@pytest.fixture
def mock_datetime():
    """
    Provide a mock datetime for consistent testing.
    
    Returns:
        MagicMock: A mock datetime that returns fixed values
    """
    from datetime import datetime
    fixed_dt = datetime(2023, 11, 14, 22, 13, 20)
    
    with patch('datetime.datetime') as mock_dt:
        mock_dt.now.return_value = fixed_dt
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def sample_skill_info():
    """
    Provide sample skill information for testing.
    
    Returns:
        dict: A sample skill information dictionary
    """
    return {
        "name": "test_skill",
        "version": "1.0.0",
        "description": "A test skill for unit testing",
        "author": "Test Author",
        "tags": ["test", "example"],
        "enabled": True
    }


@pytest.fixture
def sample_prompt():
    """
    Provide a sample prompt template for testing.
    
    Returns:
        str: A sample prompt template string
    """
    return """You are a helpful AI assistant.

Context:
{context}

User Question:
{question}

Please provide a helpful response."""


@pytest.fixture
def sample_config():
    """
    Provide a sample configuration dictionary for testing.
    
    Returns:
        dict: A sample configuration dictionary
    """
    return {
        "model": "gpt-4",
        "temperature": 0.7,
        "max_tokens": 2000,
        "top_p": 0.9,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0
    }


@pytest.fixture(autouse=True)
def clean_thread_local():
    """
    Automatically clean up thread-local storage before and after each test.
    
    This fixture ensures test isolation by clearing thread-local variables
    that might persist between tests, particularly the agent object.
    """
    # Import here to avoid circular imports
    from topsailai.utils import thread_local_tool
    
    # Clear thread-local storage before test
    thread_local_tool.rid_all_thread_vars()
    
    yield
    
    # Clear thread-local storage after test
    thread_local_tool.rid_all_thread_vars()


@pytest.fixture(autouse=True)
def set_test_logger_identity(clean_thread_local):
    """
    Set a distinctive logger identifier for unit tests.

    This fixture runs after ``clean_thread_local`` and temporarily sets the
    thread-local agent name to ``unit-test``. The logger formatter combines
    this with the thread name to produce a message_id such as
    ``(unit-test:<thread_name>)``, making it easy to distinguish unit-test
    logs from production logs.
    """
    from topsailai.utils.thread_local_tool import ctxm_give_agent_name
    with ctxm_give_agent_name("unit-test"):
        yield


@pytest.fixture
def temp_history_path(tmp_path):
    """
    Provide a temporary path for project-history JSONL files.

    Yields:
        Path: A temporary file path that will be cleaned up automatically.
    """
    from topsailai.workspace.project_history import history

    history_file = tmp_path / ".project_history.jsonl"
    with patch.object(history, "FILE_PROJECT_HISTORY", str(history_file)):
        yield history_file
