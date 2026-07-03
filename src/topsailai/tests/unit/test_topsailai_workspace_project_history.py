"""
Top-level proxy for workspace/project_history tests.

This file allows tests/run_tests.py to discover and execute the project_history
unit tests located in tests/unit/workspace/project_history/.
"""

# Re-export all test classes from the subdirectory test module so that
# tests/run_tests.py (which only scans tests/unit/) can collect them.
from topsailai.tests.unit.workspace.project_history.test_history import (
    TestProjectWorkspaceFallback,
    TestRecordProjectHistory,
    TestRotation,
)

__all__ = [
    "TestRecordProjectHistory",
    "TestProjectWorkspaceFallback",
    "TestRotation",
]
