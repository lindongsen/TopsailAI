"""
Pytest fixtures for integration tests
"""

import pytest
import os
import sys
import uuid
from datetime import datetime

# Add the parent directory to the path for imports
sys.path.insert(0, '/root/ai/TopsailAI/src')


@pytest.fixture
def session_id():
    """Generate a unique session ID for testing"""
    return f"test-session-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def message():
    """Default test message"""
    return "This is a test message for integration testing"


@pytest.fixture
def role():
    """Default role for message"""
    return "user"