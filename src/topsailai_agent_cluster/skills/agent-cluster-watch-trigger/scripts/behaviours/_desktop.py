#!/usr/bin/env python3
"""Desktop session helpers shared by the watch trigger behaviour scripts.

The Agent Cluster trigger runner builds the child environment from a whitelist, so
neither DBUS_SESSION_BUS_ADDRESS nor DISPLAY reaches a behaviour script, and
PULSE_SERVER is absent as well. These helpers discover the real audio socket and
the real session bus, and they switch to the account that owns the desktop
session, because both services refuse a connection from another account.

This module is not a behaviour. It sits beside the transition directories so a
behaviour can import it, and the executor never runs it because it is not inside
a transition directory.
"""

import glob
import os
import pwd
import stat
import time

PULSE_SOCKET_PATTERN = "/tmp/pulse-*/native"
USER_RUNTIME_BUS_PATTERN = "/run/user/*/bus"


def remaining(deadline):
    """Return the seconds left before the shared deadline, never negative."""
    return max(0.0, deadline - time.monotonic())


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


def proc_environ(uid):
    """Yield the environment entries of every process owned by one account."""
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        path = os.path.join("/proc", name, "environ")
        try:
            if os.stat(path).st_uid != uid:
                continue
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            continue
        for entry in data.split(b"\0"):
            if entry:
                yield entry.decode("utf-8", "replace")


def session_buses(uid):
    """Return the session bus addresses reachable for one account.

    The runtime directory is the documented location, but a desktop session
    started by a display manager publishes an abstract socket instead, so the
    address is also read from the account's own processes. Both forms are
    returned because only the bus itself can say which one is live.
    """
    addresses = []
    runtime = "/run/user/{}/bus".format(uid)
    if os.path.exists(runtime):
        addresses.append("unix:path=" + runtime)
    for entry in proc_environ(uid):
        if not entry.startswith("DBUS_SESSION_BUS_ADDRESS="):
            continue
        address = entry.split("=", 1)[1]
        if address and address not in addresses:
            addresses.append(address)
    return addresses


def desktop_accounts():
    """Return the accounts that own a desktop session, audio owner first."""
    current_uid = os.geteuid()
    accounts = []
    for _, uid in pulse_sockets():
        if uid not in accounts:
            accounts.append(uid)
    for path in glob.glob(USER_RUNTIME_BUS_PATTERN):
        try:
            uid = os.stat(path).st_uid
        except OSError:
            continue
        if uid not in accounts:
            accounts.append(uid)
    if current_uid not in accounts:
        accounts.append(current_uid)
    return accounts


def privilege_dropper(uid, gid):
    """Return a preexec hook that switches to the desktop account.

    Python 3.8 does not accept `user`/`group` in subprocess.run, so the account
    switch is performed inside the child before exec.
    """
    def drop():
        os.setgid(gid)
        os.setuid(uid)
    return drop
