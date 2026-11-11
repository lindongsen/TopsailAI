#!/usr/bin/env python3
"""Play an audible notification when a watched session needs input.

The Agent Cluster `watch --trigger` runner executes this file directly, with no
shell, in its own process group, with a five second lifetime. It captures and
discards stdout and stderr, so the notification is played through the desktop
audio service rather than written to a stream or terminal BEL.
"""

import glob
import os
import pwd
import shutil
import stat
import subprocess
import sys

PREVIOUS_STATE = "running"
STATE = "waiting_input"
SOUND_FILE = "/usr/share/sounds/freedesktop/stereo/bell.oga"
PULSE_SOCKET_PATTERN = "/tmp/pulse-*/native"


def should_ring(previous_state, state):
    """Return True only for the running -> waiting_input transition."""
    return previous_state == PREVIOUS_STATE and state == STATE


def pulse_sockets():
    """Return accessible PulseAudio sockets, preferring the current user."""
    current_uid = os.geteuid()
    sockets = []
    for path in glob.glob(PULSE_SOCKET_PATTERN):
        try:
            metadata = os.stat(path)
        except OSError:
            continue
        if not stat.S_ISSOCK(metadata.st_mode):
            continue
        if metadata.st_uid != current_uid and current_uid != 0:
            continue
        sockets.append((metadata.st_uid != current_uid, path, metadata.st_uid))
    return [(path, uid) for _, path, uid in sorted(sockets)]


def privilege_dropper(uid, gid):
    """Return a preexec hook that switches to the desktop audio account.

    Python 3.8 does not accept `user`/`group` in subprocess.run, so the
    account switch is performed inside the child before exec.
    """
    def drop():
        os.setgid(gid)
        os.setuid(uid)
    return drop


def play(player, socket_path, uid):
    """Play the bell through one PulseAudio socket and report success."""
    environment = os.environ.copy()
    environment["PULSE_SERVER"] = f"unix:{socket_path}"
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
            timeout=3,
            env=environment,
            **options,
        )
    except (OSError, KeyError, RuntimeError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def ring():
    """Play the system bell through an available desktop audio service."""
    player = shutil.which("paplay")
    if player is None or not os.path.isfile(SOUND_FILE):
        return False
    return any(play(player, socket_path, uid) for socket_path, uid in pulse_sockets())


def main():
    """Play once for the documented transition and always exit successfully."""
    previous_state = os.environ.get("AGENT_CLUSTER_PREVIOUS_STATE", "")
    state = os.environ.get("AGENT_CLUSTER_STATE", "")
    if should_ring(previous_state, state):
        ring()
    return 0


if __name__ == "__main__":
    sys.exit(main())
