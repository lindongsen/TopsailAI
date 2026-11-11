#!/usr/bin/env python3
"""Ring one terminal bell when a watched session becomes blocked on input.

The Agent Cluster `watch --trigger` runner executes this file directly, with no
shell, in its own process group, with a five second lifetime. It captures and
discards both stdout and stderr, so a bell written to a stream would never reach
the operator. The bell is therefore written to the controlling terminal device,
which is the only channel the operator can actually see.
"""

import os
import signal
import sys

# The transition this script reacts to. `watch` already fires only on this
# transition, so the check is a guard that keeps the script correct when it is
# invoked by hand or by a future caller, not a second detection path.
PREVIOUS_STATE = "running"
STATE = "waiting_input"

# BEL is the ASCII bell: one byte, no escape sequence, so a dumb terminal and a
# full-screen editor both handle it without corrupting the rendered table.
BELL = b"\a"

# The controlling terminal is the only visible channel, because the runner
# discards the script's own streams.
TERMINAL_DEVICE = "/dev/tty"


def should_ring(previous_state, state):
    """Return True only for the running -> waiting_input transition."""
    return previous_state == PREVIOUS_STATE and state == STATE


def ring():
    """Write one bell to the controlling terminal.

    Returns True when the bell was written. A missing terminal is not an error:
    the runner reports a non-zero exit as a script failure, and a bell that
    cannot be delivered is not worth a diagnostic in the table.
    """
    # A process group that is not the foreground group can be stopped by SIGTTOU
    # when the terminal has TOSTOP set, so the signal is ignored rather than
    # handled. The runner puts the script in its own process group, which makes
    # this the normal case rather than an exotic one.
    try:
        signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    except (AttributeError, ValueError, OSError):
        # A platform without SIGTTOU, or a non-main thread, needs no handling.
        pass
    try:
        with open(TERMINAL_DEVICE, "wb", buffering=0) as terminal:
            terminal.write(BELL)
        return True
    except OSError:
        # No controlling terminal, for example a detached or headless run.
        return False


def main():
    """Ring once for the documented transition and always exit successfully."""
    previous_state = os.environ.get("AGENT_CLUSTER_PREVIOUS_STATE", "")
    state = os.environ.get("AGENT_CLUSTER_STATE", "")
    if not should_ring(previous_state, state):
        return 0
    ring()
    return 0


if __name__ == "__main__":
    sys.exit(main())
