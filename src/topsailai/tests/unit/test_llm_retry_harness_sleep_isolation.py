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


def _iter_functions(node, prefix=""):
    """Yield every function in the module with its qualified name."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from _iter_functions(child, f"{prefix}{child.name}.")
        elif isinstance(child, ast.FunctionDef):
            yield f"{prefix}{child.name}", child
            yield from _iter_functions(child, f"{prefix}{child.name}.")


def _drives_retry_loop(function):
    """Return whether this function starts a real retry-driving request."""
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"_run", "chat"}:
                return True
    return False


def _uses_isolated_clock(function):
    """Return whether this function enters the retry-only clock isolation."""
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_skip_retry_backoff"
        for node in ast.walk(function)
    )


def test_every_retry_entry_uses_the_isolated_clock():
    """Guard every retry entry against reintroducing shared module mutation.

    The previous version asserted a hardcoded total call count, which broke as
    soon as a legitimate retry path was added and never proved that the paths
    which actually drive a retry were covered. This version derives the entry
    set from the code itself: any function that starts a retry-driving request
    must enter the isolated clock, so adding a path without isolation fails
    here while adding a correctly isolated path keeps passing.
    """
    source = inspect.getsource(harness)
    tree = ast.parse(source)
    entries = {
        name: function
        for name, function in _iter_functions(tree)
        if _drives_retry_loop(function)
    }
    # The transport delegate is the single sanctioned exception: it performs the
    # real request and is only ever called from inside a caller's isolated
    # clock, so it must not open a second isolation scope of its own.
    transport_delegate = "RealTransportAgent.run"
    assert transport_delegate in entries
    unisolated = sorted(
        name for name, function in entries.items()
        if name != transport_delegate and not _uses_isolated_clock(function)
    )
    assert unisolated == [], f"retry entries without clock isolation: {unisolated}"
    # A vacuous pass is impossible only while real entries are still discovered.
    assert len(entries) >= 2
    assert "llm_base.time.sleep" not in source
