"""Shared fixtures for CLI unit tests.

Author: DawsonLin
"""

import pytest


@pytest.fixture(autouse=True)
def clean_thread_local():
    """Clear thread-local storage before and after each test."""
    from topsailai.utils import thread_local_tool

    thread_local_tool.rid_all_thread_vars()
    yield
    thread_local_tool.rid_all_thread_vars()


@pytest.fixture(autouse=True)
def set_test_logger_identity(clean_thread_local):
    """Set the thread-local agent name to ``unit-test`` during each test."""
    from topsailai.utils.thread_local_tool import ctxm_give_agent_name

    with ctxm_give_agent_name("unit-test"):
        yield
