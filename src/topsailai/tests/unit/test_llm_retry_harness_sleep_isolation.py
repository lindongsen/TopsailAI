"""Author: DawsonLin. Regression checks for retry-only sleep isolation."""

import ast
import inspect
import threading
import time

import pytest

from topsailai.ai_base import llm_base
from tests.bdd import llm_retry_exhaustion_harness as harness


@pytest.mark.parametrize("raise_inside", [False, True])
def test_retry_clock_preserves_shared_sleep_and_restores_consumer(raise_inside):
    """Other threads keep real sleep and both exit paths restore the clock."""
    original_clock = llm_base.time
    original_sleep = time.sleep
    observed = []
    try:
        with harness._skip_retry_backoff() as clock:
            assert llm_base.time is clock
            llm_base.time.sleep(85)
            clock.sleep.assert_called_once_with(85)
            assert time.sleep is original_sleep
            assert clock.monotonic._mock_wraps is time.monotonic
            assert isinstance(clock.monotonic(), float)
            worker = threading.Thread(target=lambda: observed.append(time.sleep))
            worker.start()
            worker.join(timeout=5)
            assert not worker.is_alive()
            assert observed == [original_sleep]
            if raise_inside:
                raise RuntimeError("exercise exceptional restoration")
    except RuntimeError:
        if not raise_inside:
            raise
    assert llm_base.time is original_clock
    assert time.sleep is original_sleep


def test_all_retry_harness_paths_use_the_isolated_clock():
    """Guard all four paths against reintroducing shared module mutation."""
    source = inspect.getsource(harness)
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert sum(isinstance(node.func, ast.Name) and node.func.id == "_skip_retry_backoff"
               for node in calls) == 4
    assert "llm_base.time.sleep" not in source
