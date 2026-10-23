"""Probe newline-containing FIFO messages without changing production input logic.

Author: DawsonLin
Run with the project interpreter; all artifacts live in the required --artifacts folder.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


def receive(args):
    """Call the real workspace input entry with only endpoint/history isolation."""
    from topsailai.workspace import input_tool

    try:
        with patch.object(input_tool, "_build_pipe_path", return_value=args.pipe), \
                patch.object(input_tool, "_append_input_history_jsonl"):
            result = input_tool.input_message("PROBE> ")
        record = {"received": result}
    except Exception as exc:
        record = {"error": type(exc).__name__, "detail": str(exc)}
    Path(args.result).write_text(json.dumps(record, ensure_ascii=False))


def probe(args, mode, name, message, fragmented):
    """Deliver one frame to a bounded independent real receiver process."""
    from topsailai.cli.cli_topsailai.runtime_pipe import format_pipe_payload, send_to_pipe

    root = Path(args.artifacts) / f"{mode}-{name}"
    root.mkdir(parents=True, exist_ok=True)
    fifo = root / "input.pipe"
    result = root / "result.json"
    os.mkfifo(fifo)
    env = os.environ.copy()
    env.update(TOPSAILAI_HOME=str(root), TOPSAILAI_WORK_FOLDER=str(root),
               TOPSAILAI_CHAT_MULTI_LINE=str(mode), TOPSAILAI_INPUT_PIPE_ENABLED="1",
               TOPSAILAI_INPUT_PIPE_TIMEOUT="2", TOPSAILAI_EVENTS_ENABLED="0",
               TOPSAILAI_HOOK_POINTS="{}", PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, str(Path(__file__).resolve()), "--receive",
               "--pipe", str(fifo), "--result", str(result)]
    child = subprocess.Popen(command, env=env, cwd=root, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    delivery = "OK"
    try:
        if fragmented:
            deadline = time.monotonic() + 5
            fd = None
            while fd is None:
                try:
                    fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("FIFO reader did not open")
                    time.sleep(0.01)
            try:
                frame = format_pipe_payload(message)
                split = frame.index(b"\n") + 1
                os.write(fd, frame[:split])
                time.sleep(0.15)
                os.write(fd, frame[split:])
            finally:
                os.close(fd)
        else:
            from topsailai.cli.cli_topsailai import runtime_pipe

            staging = SimpleNamespace(mkstemp=lambda **kw: tempfile.mkstemp(
                **(kw | {"dir": str(root)})))
            with patch.object(runtime_pipe, "tempfile", staging):
                delivery = repr(send_to_pipe(fifo, message, timeout=5))
        try:
            stdout, stderr = child.communicate(timeout=7)
        except subprocess.TimeoutExpired:
            child.kill()
            stdout, stderr = child.communicate()
            delivery += " HANG"
    except Exception as exc:
        delivery = f"{type(exc).__name__}: {exc}"
        try:
            stdout, stderr = child.communicate(timeout=4)
        except subprocess.TimeoutExpired:
            child.kill()
            stdout, stderr = child.communicate()
            delivery += " HANG"
    finally:
        fifo.unlink(missing_ok=True)
        print(f"DELETED owned FIFO: {fifo}")
    record = json.loads(result.read_text()) if result.exists() else {"error": "NO_RESULT"}
    record.update(mode=mode, case=name, sent=message,
                  equal=record.get("received") == message, delivery=delivery,
                  stdout=stdout, stderr=stderr, returncode=child.returncode)
    print(json.dumps(record, ensure_ascii=False))
    return record


def main():
    """Run a small observable matrix without starting an agent or external LLM."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts")
    parser.add_argument("--receive", action="store_true")
    parser.add_argument("--pipe")
    parser.add_argument("--result")
    args = parser.parse_args()
    if args.receive:
        receive(args)
        return
    if not args.artifacts or not Path(args.artifacts).is_absolute():
        parser.error("--artifacts must be an absolute task temporary folder")
    cases = [("single", "hello", False),
             ("three-lines", "first\nsecond\n第三行", False),
             ("blank-line", "first\n\nlast", False),
             ("split-write", "first\nsecond\nlast", True)]
    records = [probe(args, mode, *case) for mode in (0, 1) for case in cases]
    (Path(args.artifacts) / "report.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2))
    print("SUMMARY", json.dumps({"equal": sum(r["equal"] for r in records),
                                 "total": len(records)}))


if __name__ == "__main__":
    main()
