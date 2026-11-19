#!/usr/bin/env python3
"""Prove `watch --bell` rings the terminal bell on a state change, and only then.

The bell is a single byte (BEL, 0x07) written into the terminal stream. It is not
a printable cell, so `capture-pane` cannot see it: that command reports the
rendered grid, and a control byte leaves no cell behind. Evidence therefore comes
from `pipe-pane`, which copies the raw bytes the pane received to a file. Counting
BEL bytes in that file is the only direct proof that the bell reached the
terminal, and it is the same channel an SSH client forwards to the operator.

Four checks are deterministic and always run:

1. The banner names the scope. `watch -b` prints `bell: on any state change`, so
   an operator who expected one specific transition is not misled.
2. Arming is silent. The first collection describes what was already there, so a
   bell at arm time would fire for the whole fleet at once.
3. An unchanged tick is silent. This is the regression that matters most: the
   suppression compares the next payload against the last one, so a BEL stored in
   that baseline would make every following tick differ and reprint the table
   forever, ringing on each one. A live loop that stays silent across many ticks
   proves the baseline holds no BEL.
4. The flag is opt-in. A plain `watch` must produce no BEL at all, even while the
   table reprints because a `DATA_STATUS` timestamp moved.

One check is not deterministic and is reported honestly:

5. A real state change rings once. The state of a session is owned by the
   provider, so this script cannot cause one without mutating the fleet, which is
   outside a read-only acceptance run. It watches for a natural transition inside
   a bounded window and reports BLOCKED when none occurred. BLOCKED is not PASS.

The script starts its own tmux sessions, drives the real interactive CLI, captures
evidence under the workspace temporary directory and removes only the sessions it
created.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time

PROMPT_PATTERN = re.compile(
    r"(?:workspace|endpoint\[[^\]]+\]|session\[[^\]]+\]|start\.[a-z]+|answer)>"
)
# A table header is the only reliable marker that a rendered table reached the
# terminal, and it is independent of which endpoints happen to be registered.
TABLE_HEADER = "ENDPOINT"
BELL = b"\a"
BELL_BANNER = "bell: on any state change"


def run(arguments: list[str]) -> str:
    """Run one command and return its standard output."""
    completed = subprocess.run(
        arguments, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return completed.stdout


def capture(target: str) -> str:
    """Capture the visible pane without joining wrapped lines."""
    return run(["tmux", "capture-pane", "-p", "-S", "-", "-t", target])


def capture_visible(target: str) -> str:
    """Capture only the rows currently on screen.

    Scrollback must be excluded when comparing successive renders. A watch loop
    appends a new table on every tick, so a capture that includes history grows
    with each render and differs from the previous one for that reason alone. That
    would report a change on every tick and make the comparison meaningless.
    """
    return run(["tmux", "capture-pane", "-p", "-t", target])


def wait_for(predicate, deadline_seconds: float, interval: float = 0.1) -> bool:
    """Poll a predicate until it holds or the deadline expires."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def start_session(target: str, binary: Path, width: int) -> None:
    """Start one detached interactive session at a fixed width.

    Colour is disabled so `SESSION_STATUS` is rendered as text. With colour the
    state is carried by the row colour and the column is absent, which would make
    a state change invisible to a text comparison.
    """
    run(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            target,
            "-x",
            str(width),
            "-y",
            "50",
            str(binary),
            "-no-color",
            "-i",
        ]
    )


def stop_session(target: str) -> None:
    """Remove only the session this script created."""
    subprocess.run(
        ["tmux", "kill-session", "-t", target],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def send(target: str, text: str) -> None:
    """Send literal text followed by Enter."""
    run(["tmux", "send-keys", "-t", target, "-l", text])
    run(["tmux", "send-keys", "-t", target, "Enter"])


def attach_pipe(target: str, raw_log: Path) -> None:
    """Copy the pane's raw bytes to a file so a control byte becomes evidence.

    `-O` routes the pipe to a shell command, and the append form keeps the file
    across the whole session. This must be attached before the command under test
    runs, because `pipe-pane` only captures output produced after it is attached.
    """
    run(["tmux", "pipe-pane", "-O", "-t", target, f"cat >> {raw_log}"])


def raw_size(raw_log: Path) -> int:
    """Return how many bytes the pane has delivered so far."""
    if not raw_log.is_file():
        return 0
    return raw_log.stat().st_size


def count_bells(raw_log: Path, offset: int = 0) -> int:
    """Count BEL bytes the pane received after a byte offset.

    The offset matters because the pipe is attached before the command runs, so
    the file also holds the prompt and the banner. Counting from zero would let a
    bell from an earlier phase be attributed to the phase under test.
    """
    if not raw_log.is_file():
        return 0
    return raw_log.read_bytes()[offset:].count(BELL)


# The state vocabulary the table can print. A cell is only treated as a state
# when it is one of these words, because a narrow pane truncates the header to
# `SESSION_S...` and that cell would otherwise be read as a state.
KNOWN_STATES = {
    "running",
    "waiting_input",
    "idle",
    "stopped",
    "completed",
    "failed",
    "error",
    "offline",
    "unknown",
    "ready",
    "no sessions",
}


def state_column(pane: str) -> list[str]:
    """Extract the SESSION_STATUS cell of the most recent table.

    Only the state column is compared, because the rest of the table moves for
    reasons that are not a state change: `DATA_STATUS` carries an observation
    timestamp, and the prompt changes when the loop arms. Comparing the whole pane
    would report both as a state change and make the check meaningless.

    Only the last table is read, because a watch loop appends a new table on every
    tick and a tall pane holds several of them. Reading every table would make the
    row count grow with each render, so the comparison would report a change on
    every tick for that reason alone.

    A cell is accepted only when it is a known state word. A truncated header
    (`SESSION_S...`) and a truncated state (`waiting_i...`) both appear on a narrow
    pane, and the header must not be counted as a row.
    """
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in pane.splitlines():
        cells = [cell.strip() for cell in line.split("│")] if "│" in line else []
        if len(cells) >= 2 and cells[1] in KNOWN_STATES:
            current.append(cells[1])
            continue
        # A line that is not a state row ends the current table. The header and
        # the rule lines fall here, so each table becomes one block.
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks[-1] if blocks else []


def arm(target: str, binary: Path, raw_log: Path, command: str, window: float) -> dict:
    """Start one interactive session, attach the raw pipe and run one command.

    The pane is wide so the state column is rendered in full. A narrow pane
    truncates `waiting_input` to `waiting_i...`, and a truncated cell cannot be
    compared against the state vocabulary.
    """
    start_session(target, binary, 200)
    if not wait_for(lambda: PROMPT_PATTERN.search(capture(target)), 20.0):
        return {"armed": False, "reason": "the interactive prompt never appeared"}
    attach_pipe(target, raw_log)
    send(target, command)
    if not wait_for(lambda: TABLE_HEADER in capture(target), window):
        return {"armed": False, "reason": "no table appeared after the command"}
    return {"armed": True}


def check_banner(binary: Path, evidence: Path, window: float) -> dict:
    """Prove the banner names the bell scope."""
    target = f"bell-banner-{int(time.time())}"
    raw_log = evidence / "bell-banner.raw"
    try:
        armed = arm(target, binary, raw_log, "watch 2s -b", window)
        if not armed["armed"]:
            return {"check": "banner-names-scope", "status": "FAIL",
                    "reason": armed["reason"]}
        shown = wait_for(lambda: BELL_BANNER in capture(target), window)
        (evidence / "bell-banner.txt").write_text(capture(target), encoding="utf-8")
        return {
            "check": "banner-names-scope",
            "banner": BELL_BANNER,
            "banner_visible": shown,
            "status": "PASS" if shown else "FAIL",
        }
    finally:
        stop_session(target)


def check_arming_silent(binary: Path, evidence: Path, window: float) -> dict:
    """Prove the first collection rings nothing.

    The bell is counted from the moment the pipe is attached, so a bell emitted
    while the first table was being rendered is included. A loop that rang on its
    baseline would fire once for every session already in the fleet.
    """
    target = f"bell-arm-{int(time.time())}"
    raw_log = evidence / "bell-arming.raw"
    try:
        armed = arm(target, binary, raw_log, "watch 60s -b", window)
        if not armed["armed"]:
            return {"check": "arming-is-silent", "status": "FAIL",
                    "reason": armed["reason"]}
        # The interval is far longer than the window, so no tick can arrive and
        # any bell counted here can only come from the immediate collection.
        bells = count_bells(raw_log)
        (evidence / "bell-arming.txt").write_text(capture(target), encoding="utf-8")
        return {
            "check": "arming-is-silent",
            "interval": "60s",
            "observation_seconds": window,
            "bell_count": bells,
            "status": "PASS" if bells == 0 else "FAIL",
        }
    finally:
        stop_session(target)


def check_unchanged_ticks_silent(binary: Path, evidence: Path, window: float) -> dict:
    """Prove a loop that observes no state change stays silent.

    This is the regression guard for the baseline. A BEL stored in the payload
    baseline makes every following tick differ, so the table reprints and rings on
    every tick. Several ticks inside the window must therefore produce zero bells,
    while the table itself is allowed to reprint because a `DATA_STATUS`
    timestamp moved.
    """
    target = f"bell-steady-{int(time.time())}"
    raw_log = evidence / "bell-steady.raw"
    try:
        armed = arm(target, binary, raw_log, "watch 2s -b", window)
        if not armed["armed"]:
            return {"check": "unchanged-ticks-are-silent", "status": "FAIL",
                    "reason": armed["reason"]}
        # Let several ticks pass. The window is a multiple of the interval, so a
        # silent result cannot be explained by "no tick happened yet".
        time.sleep(window)
        bells = count_bells(raw_log)
        (evidence / "bell-steady.txt").write_text(capture(target), encoding="utf-8")
        return {
            "check": "unchanged-ticks-are-silent",
            "interval": "2s",
            "observation_seconds": window,
            "bell_count": bells,
            "status": "PASS" if bells == 0 else "FAIL",
        }
    finally:
        stop_session(target)


def check_opt_in(binary: Path, evidence: Path, window: float) -> dict:
    """Prove a plain `watch` never rings, even while the table reprints."""
    target = f"bell-optin-{int(time.time())}"
    raw_log = evidence / "bell-optin.raw"
    try:
        armed = arm(target, binary, raw_log, "watch 2s", window)
        if not armed["armed"]:
            return {"check": "flag-is-opt-in", "status": "FAIL",
                    "reason": armed["reason"]}
        time.sleep(window)
        bells = count_bells(raw_log)
        banner_absent = BELL_BANNER not in capture(target)
        (evidence / "bell-optin.txt").write_text(capture(target), encoding="utf-8")
        return {
            "check": "flag-is-opt-in",
            "interval": "2s",
            "observation_seconds": window,
            "bell_count": bells,
            "banner_absent": banner_absent,
            "status": "PASS" if bells == 0 and banner_absent else "FAIL",
        }
    finally:
        stop_session(target)


def check_state_change_rings(binary: Path, evidence: Path, window: float) -> dict:
    """Ring once on a real state change, or report BLOCKED honestly.

    The state of a session belongs to the provider, so this read-only run cannot
    cause a transition without mutating the fleet. It watches for a natural one
    inside the window. No transition means the check could not be exercised, which
    is BLOCKED rather than PASS: an untested positive path must never be recorded
    as verified.

    Only the state column is compared, and bells are counted from the byte offset
    taken at that same moment. Comparing the whole pane would treat the arming
    prompt and the moving `DATA_STATUS` timestamp as a state change, and counting
    from zero would attribute an earlier phase's bell to this one.
    """
    target = f"bell-change-{int(time.time())}"
    raw_log = evidence / "bell-change.raw"
    try:
        armed = arm(target, binary, raw_log, "watch 2s -b", window)
        if not armed["armed"]:
            return {"check": "state-change-rings", "status": "FAIL",
                    "reason": armed["reason"]}
        baseline = state_column(capture_visible(target))
        offset = raw_size(raw_log)
        (evidence / "bell-change-before.txt").write_text(
            capture_visible(target), encoding="utf-8"
        )
        if not baseline:
            return {"check": "state-change-rings", "status": "FAIL",
                    "reason": "the state column could not be read from the table"}
        changed = wait_for(
            lambda: state_column(capture_visible(target)) != baseline, window
        )
        # One extra tick after the change, so a bell emitted on the tick that
        # rendered the new state has reached the pipe before it is counted.
        time.sleep(2.5)
        bells = count_bells(raw_log, offset)
        final = state_column(capture_visible(target))
        (evidence / "bell-change-after.txt").write_text(
            capture_visible(target), encoding="utf-8"
        )
        if not changed:
            return {
                "check": "state-change-rings",
                "observation_seconds": window,
                "baseline_states": baseline,
                "bell_count": bells,
                "status": "BLOCKED",
                "reason": "no state change occurred in the window; the positive path was not exercised",
            }
        return {
            "check": "state-change-rings",
            "observation_seconds": window,
            "baseline_states": baseline,
            "final_states": final,
            "bell_count": bells,
            "status": "PASS" if bells >= 1 else "FAIL",
        }
    finally:
        stop_session(target)


def main() -> int:
    """Run every bell check and report each as PASS, FAIL or BLOCKED."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--observation-seconds", type=float, default=8.0)
    parser.add_argument("--change-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if not args.binary.is_file():
        parser.error("binary does not exist")
    if not args.evidence_dir.is_absolute():
        parser.error("evidence directory must be absolute")
    args.evidence_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).isoformat()
    checks = [
        check_banner(args.binary, args.evidence_dir, args.observation_seconds),
        check_arming_silent(args.binary, args.evidence_dir, args.observation_seconds),
        check_unchanged_ticks_silent(
            args.binary, args.evidence_dir, args.observation_seconds
        ),
        check_opt_in(args.binary, args.evidence_dir, args.observation_seconds),
        check_state_change_rings(args.binary, args.evidence_dir, args.change_seconds),
    ]
    failed = [c for c in checks if c["status"] == "FAIL"]
    blocked = [c for c in checks if c["status"] == "BLOCKED"]
    record = {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "status": "FAIL" if failed else ("BLOCKED" if blocked else "PASS"),
    }
    (args.evidence_dir / "watch-bell.json").write_text(
        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(record, indent=2, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
