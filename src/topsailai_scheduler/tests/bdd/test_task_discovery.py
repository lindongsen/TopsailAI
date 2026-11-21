"""Bind the task discovery feature to its scenarios.

The step definitions live in steps.py and are registered once by conftest.py, so
this module only names the feature file it collects.
"""

from pytest_bdd import scenarios

scenarios("features/task_discovery.feature")
