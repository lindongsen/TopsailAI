#!/usr/bin/env python3
"""Prove watch renders immediately on start and honours a terminal resize.

Two behaviours are checked against a real terminal, because neither is observable
from a unit test that injects a tick channel:

1. Immediate collection. The interval is set far longer than the observation
   window, so any table visible inside that window can only come from the
   immediate collection. A loop that still waits for its first tick cannot
   produce a table here.
2. Live layout. The interval is short, the pane is widened between ticks, and the
   next render must use the new width. A layout sampled once at startup keeps the
   old width forever.

The two checks need different intervals, so they run as two separate sessions.
Width is measured without `-J`, because joining wrapped lines would report a
wrapped table as one very wide line and hide the real width.

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


def run(arguments: list[str]) -> str:
    """Run one command and return its standard output."""
    completed = subprocess.run(
        arguments, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return completed.stdout


def capture(target: str) -> str:
    """Capture the visible pane without joining wrapped lines."""
    return run(["tmux", "capture-pane", "-p", "-S", "-", "-t", target])


def widest_line(value: str) -> int:
    """Return the widest visible line, measured in characters."""
    return max((len(line.rstrip()) for line in value.splitlines()), default=0)


def wait_for(predicate, deadline_seconds: float, interval: float = 0.1) -> bool:
    """Poll a predicate until it holds or the deadline expires."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def start_session(target: str, binary: Path, width: int) -> None:
    """Start one detached interactive session at a fixed width."""
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


def check_immediate(binary: Path, evidence: Path, interval: str, window: float) -> dict:
    """Prove a table appears before the first tick can arrive."""
    target = f"watch-immediate-{int(time.time())}"
    try:
        start_session(target, binary, 100)
        if not wait_for(lambda: PROMPT_PATTERN.search(capture(target)), 20.0):
            return {"check": "immediate-collection", "status": "FAIL",
                    "reason": "the interactive prompt never appeared"}
        send(target, f"watch {interval}")
        appeared = wait_for(lambda: TABLE_HEADER in capture(target), window)
        (evidence / "watch-immediate.txt").write_text(capture(target), encoding="utf-8")
        return {
            "check": "immediate-collection",
            "interval": interval,
            "observation_seconds": window,
            "table_visible_before_first_tick": appeared,
            "status": "PASS" if appeared else "FAIL",
        }
    finally:
        stop_session(target)


def check_resize(binary: Path, evidence: Path, narrow: int, wide: int, window: float) -> dict:
    """Prove a resize between ticks reaches the next render."""
    target = f"watch-resize-{int(time.time())}"
    try:
        start_session(target, binary, narrow)
        if not wait_for(lambda: PROMPT_PATTERN.search(capture(target)), 20.0):
            return {"check": "resize-honoured", "status": "FAIL",
                    "reason": "the interactive prompt never appeared"}
        # A short interval is required: the resize can only be observed on a
        # render, and a long interval would place the next render outside the
        # observation window.
        send(target, "watch 2s")
        if not wait_for(lambda: TABLE_HEADER in capture(target), window):
            return {"check": "resize-honoured", "status": "FAIL",
                    "reason": "no table appeared before the resize"}
        before = capture(target)
        narrow_widest = widest_line(before)
        (evidence / "watch-narrow.txt").write_text(before, encoding="utf-8")
        run(["tmux", "resize-window", "-t", target, "-x", str(wide)])
        widened = wait_for(
            lambda: widest_line(capture(target)) > narrow_widest, window
        )
        after = capture(target)
        (evidence / "watch-wide.txt").write_text(after, encoding="utf-8")
        return {
            "check": "resize-honoured",
            "narrow_width": narrow,
            "wide_width": wide,
            "widest_before": narrow_widest,
            "widest_after": widest_line(after),
            "status": "PASS" if widened else "FAIL",
        }
    finally:
        stop_session(target)


def check_stop_key(binary: Path, evidence: Path, window: float) -> dict:
    """Prove one keypress stops the loop and returns a usable prompt."""
    target = f"watch-stop-{int(time.time())}"
    try:
        start_session(target, binary, 100)
        if not wait_for(lambda: PROMPT_PATTERN.search(capture(target)), 20.0):
            return {"check": "keypress-stops-loop", "status": "FAIL",
                    "reason": "the interactive prompt never appeared"}
        send(target, "watch 2s")
        if not wait_for(lambda: TABLE_HEADER in capture(target), window):
            return {"check": "keypress-stops-loop", "status": "FAIL",
                    "reason": "no table appeared before the keypress"}
        # A space is a harmless key: it stops the loop and is then applied to the
        # prompt, where a backspace erases it. Escape is avoided because it can
        # leave the REPL and destroy the evidence before it is captured.
        run(["tmux", "send-keys", "-t", target, "-l", " "])
        stopped = wait_for(
            lambda: "auto-refresh stopped" in capture(target), window
        )
        run(["tmux", "send-keys", "-t", target, "BSpace"])
        final = capture(target)
        (evidence / "watch-stopped.txt").write_text(final, encoding="utf-8")
        return {
            "check": "keypress-stops-loop",
            "stopped_message": stopped,
            "prompt_usable": bool(PROMPT_PATTERN.search(final)),
            "status": "PASS" if stopped and PROMPT_PATTERN.search(final) else "FAIL",
        }
    finally:
        stop_session(target)


def main() -> int:
    """Run every watch check and report each as PASS or FAIL."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--long-interval", default="60s")
    parser.add_argument("--narrow-width", type=int, default=60)
    parser.add_argument("--wide-width", type=int, default=200)
    parser.add_argument("--observation-seconds", type=float, default=8.0)
    args = parser.parse_args()
    if not args.binary.is_file():
        parser.error("binary does not exist")
    if not args.evidence_dir.is_absolute():
        parser.error("evidence directory must be absolute")
    args.evidence_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).isoformat()
    checks = [
        check_immediate(
            args.binary, args.evidence_dir, args.long_interval, args.observation_seconds
        ),
        check_resize(
            args.binary,
            args.evidence_dir,
            args.narrow_width,
            args.wide_width,
            args.observation_seconds,
        ),
        check_stop_key(args.binary, args.evidence_dir, args.observation_seconds),
    ]
    record = {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "status": "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL",
    }
    (args.evidence_dir / "watch-checks.json").write_text(
        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
