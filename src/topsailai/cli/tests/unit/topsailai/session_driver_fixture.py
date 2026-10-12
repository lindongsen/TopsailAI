"""Harmless fixture owner and CLI-exit harness. Author: DawsonLin.

This is not the production driver. All paths derive from the test-owned HOME.
The directory mutex models fixture-owned admission, not production OS locking.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid


def owner(home, session):
    """Publish one owner, wait for harness release, then remove owned records."""
    root = home / "workspace/task/session_agent_driver"
    root.mkdir(parents=True, exist_ok=True)
    mutex = root / "fixture-owner"
    try:
        mutex.mkdir()
    except FileExistsError:
        return 7
    meta = root / f"{session}.meta"
    log = root / f"{session}.log"
    try:
        log.write_text("fixture only\n")
        meta.write_text(json.dumps(dict(version=1, session_id=session,
            pid=os.getpid(), run_id=uuid.uuid4().hex, status="running")))
        deadline = time.monotonic() + 15
        while not (home / "release").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        for path in (meta, log):
            path.unlink(missing_ok=True)
            print(f"Fixture removed {path}", flush=True)
        mutex.rmdir()
        print(f"Fixture removed {mutex}", flush=True)
    return 0


def cli_exit(home, session):
    """Launch via the real service and exit after real CLI reap leaves it live."""
    from cli_topsailai.core import _reap_driver_children
    from cli_topsailai.session_driver_launcher import DriverAuthority, launch_driver

    pid = os.getpid()
    rows = [dict(session_id=session, pid=pid, session_pid=pid,
                 filename=f"{session}.{pid}.session.stdout")]
    authority = DriverAuthority(Path(sys.argv[0]).resolve(), Path(sys.executable))
    result = launch_driver(rows, 1, topsailai_home=home, authority=authority,
                           environment=dict(os.environ), discover=lambda: rows)
    children = [result.child] if result.child is not None else []
    _reap_driver_children(children)
    (home / "cli-result.json").write_text(json.dumps(dict(
        outcome=result.outcome, pid=result.child.pid if result.child else None,
        retained=len(children))))
    return 0 if result.outcome == "launched" and len(children) == 1 else 8


def main():
    """Choose only the harmless owner or test CLI-exit mode."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--cli", action="store_true")
    args = parser.parse_args()
    home = Path(os.environ["TOPSAILAI_HOME"])
    return cli_exit(home, args.session) if args.cli else owner(home, args.session)


if __name__ == "__main__":
    raise SystemExit(main())
