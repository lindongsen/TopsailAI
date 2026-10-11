"""Pytest configuration for the session agent driver BDD suite.

This suite is self-contained under ``scripts/session_agent_driver/tests/bdd``.
Step definitions are registered by importing the step module from the test
entry file (``test_session_agent_driver_bdd.py``), so no ``pytest_plugins``
declaration is needed here (that would require a top-level conftest).
"""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def pytest_configure(config):
    """Register markers used by this suite."""
    config.addinivalue_line("markers", "bdd: Gherkin behavior test")
