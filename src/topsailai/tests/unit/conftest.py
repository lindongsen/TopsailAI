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
