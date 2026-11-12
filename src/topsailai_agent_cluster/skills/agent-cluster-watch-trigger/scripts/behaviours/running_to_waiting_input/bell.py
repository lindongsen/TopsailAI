#!/usr/bin/env python3
"""Play the system bell sound once.

This is a behaviour script, not an executor. The watch trigger executor decides
when a behaviour runs, so this file never inspects the transition: it is bound to
a transition by the directory it is installed in, not by a condition in its code.
That is what lets the same file serve any transition without an edit.

It reads no configuration from the environment beyond the inherited basics, and it
exits 0 when no audio service is reachable, because a headless run has no operator
to alert and a non-zero exit would only add a diagnostic row to the table.
"""

import os
import pwd
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _desktop import privilege_dropper, pulse_sockets, remaining  # noqa: E402

SOUND_FILE = "/usr/share/sounds/freedesktop/stereo/bell.oga"
# The executor kills the whole process group after five seconds, so every
# behaviour draws from one budget below that bound instead of taking its own.
BUDGET_SECONDS = 4.0


def play(player, socket_path, uid, deadline):
    """Play the bell through one PulseAudio socket and report success."""
    timeout = remaining(deadline)
    if timeout <= 0:
        return False
    environment = os.environ.copy()
    environment["PULSE_SERVER"] = "unix:" + socket_path
    options = {}
    if uid != os.geteuid():
        account = pwd.getpwuid(uid)
        options["preexec_fn"] = privilege_dropper(uid, account.pw_gid)
    try:
        result = subprocess.run(
            [player, SOUND_FILE],
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
    """Play the bell once and always exit successfully."""
    player = shutil.which("paplay")
    if player is None or not os.path.isfile(SOUND_FILE):
        return 0
    deadline = time.monotonic() + BUDGET_SECONDS
    for socket_path, uid in pulse_sockets():
        if play(player, socket_path, uid, deadline):
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
