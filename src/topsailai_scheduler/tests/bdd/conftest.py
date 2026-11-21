"""Fixtures shared by every BDD module.

The session fixture is the only place a daemon is started, so every scenario
gets exactly one daemon in its own temporary workspace and cannot influence
another scenario through a shared task tree, lock file or provider state folder.

The step definitions are imported here so they are registered once for every
feature module. pytest-bdd rejects a duplicate definition, so defining a step
beside each feature is how two features silently drift apart.
"""

import os
import subprocess

import pytest

from support import BINARY, PROJECT_ROOT, Session

# steps is loaded as a plugin so pytest registers the fixtures its decorators
# create. Importing it as a plain module would leave those fixtures in the
# module namespace, where pytest never looks for them.
pytest_plugins = ["steps"]


class TaskRef:
    """The task a scenario is currently talking about.

    A scenario names its task once and later steps refer to "that task", so the
    identity has to survive between steps. A mutable holder is used instead of a
    string fixture because some steps name a task without a Given step.
    """

    def __init__(self):
        """Start with no task selected and no recorded result."""
        self.id = None
        # second holds a second task id when a scenario needs two tasks.
        self.second = None
        # last holds the CLI result of the action under test, copied out
        # immediately because any later CLI call overwrites the session's own.
        self.last = {"code": 0, "out": "", "err": ""}
        # recorded holds the lock record read before the daemon was killed.
        self.recorded = {}
        # elapsed holds a measured duration, for a behaviour that is only
        # observable as time such as waiting for a concurrency slot.
        self.elapsed = 0.0
        # baseline holds a count taken before an action, so a later step can
        # assert that the count grew rather than assert an exact total that
        # depends on timing.
        self.baseline = 0


@pytest.fixture
def task():
    """Provide the scenario's task holder."""
    return TaskRef()


@pytest.fixture
def session():
    """Provide one daemon per scenario and clean it up afterwards."""
    if not os.access(BINARY, os.X_OK):
        pytest.fail("the scheduler binary is missing; run make build first")

    # A suite run against a stale binary proves nothing about the current
    # source, so a stale binary is a failure rather than a skip.
    freshness = subprocess.run(
        [os.path.join(PROJECT_ROOT, "tests", "binary_fresh.sh")],
        capture_output=True,
        text=True,
    )
    if freshness.returncode != 0:
        pytest.fail(freshness.stderr.strip() or "the scheduler binary is stale")

    active = Session()
    try:
        yield active
    finally:
        active.stop()
