"""
Pytest configuration for unit tests.

This conftest.py ensures test isolation by cleaning up environment variables
that may be set by the application initialization (e.g., from .env files).
"""

import os
import pytest


# Environment variables that should be cleaned up for test isolation
ENV_VARS_TO_CLEAN = [
    "MODEL_SETTINGS",
    "TOPSAILAI_SESSION_ID",
    "SESSION_ID",
    "TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP",
    "TOPSAILAI_CONTEXT_SUMMARY_PROMPT_MAP",
    "TOPSAILAI_CONTEXT_SUMMARY_PROMPT_EXTRA_MAP",
    "TOPSAILAI_LOCK_DIR",
    "TOPSAILAI_TASK_ID",
    "TOPSAILAI_TASK_DIR",
    "TOPSAILAI_AGENT_NAME",
    "TOPSAILAI_ANSWER_DIR",
    "TOPSAILAI_STORY_DIR",
    "TOPSAILAI_STORY_PROMPT",
    "TOPSAILAI_PROMPT_WHEN_NO_TOOL_CALL",
    "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD",
    "TOPSAILAI_LOAD_OVERVIEW_INTO_PROMPT_SKILLS",
    "TOPSAILAI_SUMMARIZE_INTO_SESSION",
    "TOPSAILAI_USE_TOOL_CALLS",
    "USE_TOOL_CALLS",
    "TOPSAILAI_CHAT_MULTI_LINE",
    "CHAT_MULTI_LINE",
    "TOPSAILAI_INTERACTIVE_MODE",
    "TOPSAILAI_CHAT_INTERACTIVE_MODE",
    "TOPSAILAI_FILE_WHITE_LIST_NO_TRUNCATE_EXT",
    "TOPSAILAI_TEAM_MANAGER_ONLY_AGENT",
    "TOPSAILAI_TEAM_MANAGER_NAME",
    "TOPSAILAI_TEAM_ENV_KEYS",
    "DISABLED_TOOLS",
    "SANDBOX_SETTINGS",
    "EXTRA_TOOLS",
    "CONTEXT_HISTORY_MANAGERS",
    "CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH",
    "CONTEXT_MESSAGES_SLIM_THRESHOLD_TOKENS",
    "DEBUG",
    "MAX_TOKENS",
    "TEMPERATURE",
    "TOP_P",
    "FREQUENCY_PENALTY",
    "LLM_RESPONSE_STREAM",
    "OPENAI_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "GOPATH",
    "GOCACHE",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Clean up environment variables before each test."""
    # Store original values
    original_values = {}
    for key in ENV_VARS_TO_CLEAN:
        original_values[key] = os.environ.get(key)
    
    # Remove all env vars that might pollute tests
    for key in ENV_VARS_TO_CLEAN:
        monkeypatch.delenv(key, raising=False)
    
    yield
    
    # Restore original values after test (optional, for safety)
    # Note: pytest fixtures automatically restore monkeypatch changes


@pytest.fixture(autouse=True)
def clean_temp_files():
    """Clean up temporary files/directories after each test."""
    import shutil
    import tempfile
    
    temp_dirs = []
    
    # Store reference to tempfile.mkdtemp
    original_mkdtemp = tempfile.mkdtemp
    
    def tracked_mkdtemp(*args, **kwargs):
        dir_path = original_mkdtemp(*args, **kwargs)
        temp_dirs.append(dir_path)
        return dir_path
    
    # Monkey-patch tempfile.mkdtemp to track created directories
    tempfile.mkdtemp = tracked_mkdtemp
    
    yield
    
    # Restore original function
    tempfile.mkdtemp = original_mkdtemp
    
    # Clean up any temp directories created during the test
    for temp_dir in temp_dirs:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
