"""Shared configuration for tool parameter-coercion behavior tests.

This suite is independent from ``cli/tests/bdd``: it calls tool functions in-process
instead of driving the CLI, and it registers its own step modules so that the two
suites never share step definitions.
"""

import pytest


def pytest_configure(config):
    """Register markers used by the tool parameter-coercion feature set."""
    config.addinivalue_line("markers", "bdd: Gherkin behavior test")
    config.addinivalue_line(
        "markers",
        "wip: scenario pinned to a known source defect, expected to fail",
    )


pytest_plugins = [
    "tests.bdd.steps.tool_param_cmd_git_file_steps",
    "tests.bdd.steps.tool_param_remote_steps",
    "tests.bdd.steps.tool_param_human_guard_steps",
    "tests.bdd.steps.tool_calls_normalization_steps",
]


def pytest_collection_modifyitems(config, items):
    """Turn the ``wip`` tag into a non-strict xfail so defects stay visible."""
    for item in items:
        if item.get_closest_marker("wip") is not None:
            item.add_marker(pytest.mark.xfail(reason="known tool parameter defect", strict=False))
