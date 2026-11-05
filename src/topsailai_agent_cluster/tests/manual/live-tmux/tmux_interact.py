#!/usr/bin/env python3
"""Drive one reproducible Agent Cluster CLI interaction through tmux."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time

PROMPT_PATTERN = re.compile(
    r"(?:workspace|endpoint\[[^\]]+\]|session\[[^\]]+\]|start\.[a-z]+|answer)>\s*$"
)
CASE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_LEDGER_BYTES = 1024 * 1024


def capture(target: str, ansi: bool) -> str:
    """Capture the complete visible pane plus retained history."""
    arguments = ["tmux", "capture-pane", "-pJ", "-S", "-"]
    if ansi:
        arguments.insert(2, "-e")
    arguments.extend(["-t", target])
    return subprocess.run(arguments, check=True, text=True, stdout=subprocess.PIPE).stdout


def last_nonempty_line(value: str) -> str:
    """Return the last nonempty terminal line."""
    for line in reversed(value.splitlines()):
        if line.strip():
            return line
    return ""


def new_output(before: str, after: str) -> str:
    """Return only terminal content newly rendered after the interaction."""
    common_length = 0
    for before_character, after_character in zip(before, after):
        if before_character != after_character:
            break
        common_length += 1
    return after[common_length:]


def append_bounded(path: Path, record: dict[str, object]) -> None:
    """Append one JSON record while retaining a bounded current-run ledger."""
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    combined = existing + line
    encoded = combined.encode("utf-8")
    if len(encoded) > MAX_LEDGER_BYTES:
        combined = encoded[-MAX_LEDGER_BYTES:].decode("utf-8", errors="ignore")
        first_newline = combined.find("\n")
        combined = combined[first_newline + 1 :] if first_newline >= 0 else line
    path.write_text(combined, encoding="utf-8")


def main() -> int:
    """Send one command, wait for a newly rendered prompt and preserve evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    if not CASE_PATTERN.fullmatch(args.case):
        parser.error("case must use lowercase kebab-case")
    if not args.evidence_dir.is_absolute():
        parser.error("evidence directory must be absolute")
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    before_plain = capture(args.target, ansi=False)
    before_ansi = capture(args.target, ansi=True)
    prefix = args.evidence_dir / args.case
    (prefix.with_suffix(".before.txt")).write_text(before_plain, encoding="utf-8")
    (prefix.with_suffix(".before.ansi")).write_text(before_ansi, encoding="utf-8")
    started = time.monotonic()
    subprocess.run(["tmux", "send-keys", "-t", args.target, "-l", args.command], check=True)
    subprocess.run(["tmux", "send-keys", "-t", args.target, "Enter"], check=True)
    deadline = started + args.timeout
    after_plain = before_plain
    status = "TIMEOUT"
    while time.monotonic() < deadline:
        time.sleep(0.1)
        after_plain = capture(args.target, ansi=False)
        if after_plain != before_plain and PROMPT_PATTERN.search(last_nonempty_line(after_plain)):
            status = "CAPTURED"
            break
    after_ansi = capture(args.target, ansi=True)
    elapsed = round(time.monotonic() - started, 3)
    delta_plain = new_output(before_plain, after_plain)
    delta_ansi = new_output(before_ansi, after_ansi)
    (prefix.with_suffix(".after.txt")).write_text(after_plain, encoding="utf-8")
    (prefix.with_suffix(".after.ansi")).write_text(after_ansi, encoding="utf-8")
    (prefix.with_suffix(".delta.txt")).write_text(delta_plain, encoding="utf-8")
    (prefix.with_suffix(".delta.ansi")).write_text(delta_ansi, encoding="utf-8")
    record = {
        "case": args.case,
        "command": args.command,
        "elapsed_seconds": elapsed,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "prompt": last_nonempty_line(after_plain),
        "status": status,
        "target": args.target,
    }
    append_bounded(args.evidence_dir / "run-ledger.jsonl", record)
    print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    return 0 if status == "CAPTURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
