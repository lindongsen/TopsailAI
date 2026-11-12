#!/usr/bin/env python3
"""Raise one desktop notification popup.

This is a behaviour script, not an executor. The watch trigger executor decides
when a behaviour runs, so this file never inspects the transition: it is bound to
a transition by the directory it is installed in, not by a condition in its code.
That is what lets the same file serve any transition without an edit.

The wording is derived from the payload states rather than hardcoded, so the same
file reads correctly under any transition directory. A state the script does not
recognise falls back to naming the transition itself instead of inventing a
sentence that would be wrong.

It exits 0 when no session bus is reachable, because a headless run has no
operator to alert and a non-zero exit would only add a diagnostic row to the table.
"""

import os
import pwd
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _desktop import (  # noqa: E402
    desktop_accounts,
    privilege_dropper,
    remaining,
    session_buses,
)

NOTIFICATION_APP = "agent-cluster"
NOTIFICATION_EXPIRE_MS = "15000"
# The executor kills the whole process group after five seconds, so every
# behaviour draws from one budget below that bound instead of taking its own.
BUDGET_SECONDS = 4.0

# A state is described by what it means to the operator, not by its wire name.
STATE_PHRASES = {
    "waiting_input": "is waiting for input",
    "running": "is running",
    "idle": "is idle",
    "unknown": "has an unverified state",
}
STATE_TITLES = {
    "waiting_input": "agent needs input",
}


def notification_title(state):
    """Return the popup title for one state."""
    return STATE_TITLES.get(state, "agent state changed")


def notification_body(previous_state, state):
    """Describe the session and the transition, using only payload values."""
    name = os.environ.get("AGENT_CLUSTER_SESSION_NAME", "")
    endpoint = os.environ.get("AGENT_CLUSTER_ENDPOINT_ID", "")
    subject = name or "a watched session"
    if name and endpoint:
        subject = "{} on {}".format(name, endpoint)
    elif endpoint:
        subject = "a session on {}".format(endpoint)
    phrase = STATE_PHRASES.get(state)
    if phrase is not None:
        return "{} {}".format(subject, phrase)
    return "{} changed from {} to {}".format(subject, previous_state or "unknown", state)


def notify(sender, address, uid, deadline):
    """Raise one desktop notification through one session bus."""
    timeout = remaining(deadline)
    if timeout <= 0:
        return False
    state = os.environ.get("AGENT_CLUSTER_STATE", "")
    previous_state = os.environ.get("AGENT_CLUSTER_PREVIOUS_STATE", "")
    environment = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "DBUS_SESSION_BUS_ADDRESS": address,
        "TERM": "dumb",
    }
    options = {}
    if uid != os.geteuid():
        account = pwd.getpwuid(uid)
        environment["HOME"] = account.pw_dir
        options["preexec_fn"] = privilege_dropper(uid, account.pw_gid)
    try:
        result = subprocess.run(
            [
                sender,
                "--app-name", NOTIFICATION_APP,
                "--expire-time", NOTIFICATION_EXPIRE_MS,
                notification_title(state),
                notification_body(previous_state, state),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout,
            env=environment,
            **options,
        )
    except (OSError, KeyError, RuntimeError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def main():
    """Raise one popup through an available session bus and always exit 0."""
    sender = shutil.which("notify-send")
    if sender is None:
        return 0
    deadline = time.monotonic() + BUDGET_SECONDS
    for uid in desktop_accounts():
        for address in session_buses(uid):
            if notify(sender, address, uid, deadline):
                return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
