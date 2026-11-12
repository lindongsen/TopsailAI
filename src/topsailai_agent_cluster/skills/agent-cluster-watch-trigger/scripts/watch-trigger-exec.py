#!/usr/bin/env python3
"""Run the behaviour scripts bound to one watched-session state transition.

This file is the generic executor. It decides *when* something runs; a behaviour
script decides *what* runs. The binding is a directory name, so adding a reaction
to a transition is a new file in a transition directory rather than an edit here.

The Agent Cluster `watch --trigger` runner executes this file directly, with no
shell, in its own process group, with a five second lifetime. It captures and
discards stdout and stderr, so a behaviour must use an external channel such as
the system audio service, the desktop notification service or a file.

The runner builds the child environment from a whitelist, so this executor cannot
be configured through an environment variable in normal operation. Behaviour
discovery is therefore path-based, and `AGENT_CLUSTER_TRIGGER_BEHAVIOURS` exists
only so a human can point the executor at another tree when running it by hand.

Layout, relative to a behaviour root:

    <root>/<previous>_to_<state>/<behaviour>

For example `running_to_waiting_input/bell.py`. The separator is `_to_` rather
than `->`, because a directory name is also a shell word and `->` would be read as
a redirection by every shell that touched it.
"""

import os
import signal
import subprocess
import sys
import time

TRANSITION_SEPARATOR = "_to_"
# The runner kills the whole process group after five seconds, so every behaviour
# in one dispatch draws from one budget below that bound. A behaviour that spends
# the budget leaves nothing for the next one, which is the intended trade: a
# bounded total matters more than every behaviour getting a turn.
BUDGET_SECONDS = 4.0
# A behaviour root is a directory of transition directories. The per-user root is
# searched first so an operator can add or override one behaviour without editing
# the shipped tree, and the shipped root is searched second so the default
# reactions keep working after that.
USER_ROOT = os.path.join(
    os.path.expanduser("~"), ".topsailai", "topsailai-agent-cluster.triggers"
)
SHIPPED_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "behaviours")


def transition_key(previous_state, state):
    """Return the directory name that binds behaviours to one transition."""
    return "{}{}{}".format(
        previous_state or "unknown", TRANSITION_SEPARATOR, state or "unknown"
    )


def behaviour_roots():
    """Return the behaviour roots to search, highest precedence first."""
    roots = []
    explicit = os.environ.get("AGENT_CLUSTER_TRIGGER_BEHAVIOURS", "")
    if explicit:
        roots.append(explicit)
    roots.append(USER_ROOT)
    roots.append(SHIPPED_ROOT)
    return [root for root in roots if os.path.isdir(root)]


def behaviour_files(key):
    """Return the behaviour files for one transition, highest precedence first.

    A file name is the behaviour identity, so a user file shadows a shipped file
    of the same name instead of running beside it. Without that rule an override
    would double-fire, which is the one failure a user cannot see in the code.
    """
    selected = {}
    for root in behaviour_roots():
        directory = os.path.join(root, key)
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if name.startswith(".") or name.startswith("_"):
                continue
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            selected.setdefault(name, path)
    return [selected[name] for name in sorted(selected)]


def behaviour_argv(path):
    """Return the argv array that runs one behaviour file.

    An executable file is run directly, so the kernel honours its own shebang and
    the behaviour may be written in any language. A Python file without the
    executable bit is run through this interpreter instead of being skipped,
    because a missing mode bit is a packaging mistake rather than an intent.
    """
    if os.access(path, os.X_OK):
        return [path]
    if path.endswith(".py"):
        return [sys.executable, path]
    return []


def run_behaviour(path, deadline):
    """Run one behaviour under the shared deadline and report whether it ran."""
    argv = behaviour_argv(path)
    if not argv:
        return False
    timeout = max(0.0, deadline - time.monotonic())
    if timeout <= 0:
        return False
    try:
        child = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    try:
        child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_group(child)
    return True


def terminate_group(child):
    """Kill one behaviour and every process it started, then reap it.

    The behaviour runs in its own session, so the group id equals its pid. Killing
    the group is what stops a behaviour that spawned a helper, because killing only
    the direct child would leave that helper running past the runner's bound.
    """
    try:
        os.killpg(os.getpgid(child.pid), signal.SIGKILL)
    except OSError:
        pass
    try:
        child.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


def main():
    """Dispatch the behaviours bound to the observed transition and exit 0."""
    previous_state = os.environ.get("AGENT_CLUSTER_PREVIOUS_STATE", "")
    state = os.environ.get("AGENT_CLUSTER_STATE", "")
    if not previous_state and not state:
        return 0
    deadline = time.monotonic() + BUDGET_SECONDS
    for path in behaviour_files(transition_key(previous_state, state)):
        run_behaviour(path, deadline)
    return 0


if __name__ == "__main__":
    sys.exit(main())
