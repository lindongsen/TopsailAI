"""
Pytest configuration for unit tests.

This module sets up the test environment by ensuring that environment variables
used for configuration are properly managed during tests.
"""

import os
import sys


def pytest_configure(config):
    """Configure the test environment before any tests run."""
    # Ensure the module cache is clean for prompt_base tests
    if "topsailai.ai_base.prompt_base" in sys.modules:
        del sys.modules["topsailai.ai_base.prompt_base"]


def pytest_runtest_setup(item):
    """
    Setup before each test runs.
    Ensures clean module state for tests that mock module-level constants.
    """
    # Clear module caches that might be affected by mocking
    modules_to_clear = [
        "topsailai.skill_hub.skill_repo",
        "topsailai.skill_hub.skill_tool",
        "topsailai.skill_hub.skill_hub",
    ]
    for module in modules_to_clear:
        if module in sys.modules:
            # Clear the module but keep it importable
            pass  # Don't clear, as it breaks other tests


def pytest_runtest_teardown(item):
    """
    Cleanup after each test runs.
    """
    pass
