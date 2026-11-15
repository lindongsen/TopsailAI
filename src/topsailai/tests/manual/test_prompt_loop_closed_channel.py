"""Manual verification: a closed input channel must not spin the prompt loop.

Run this script directly. It starts child processes whose stdin is
``/dev/null``, so every read raises ``EOFError`` immediately and forever. That
is the exact condition that produced unbounded tee-log growth in production.

Two modes are measured:

``bounded``
    The current implementation. ``input_message`` must propagate ``EOFError``
    so the caller can end the session. The child reports the outcome and the
    number of bytes it wrote.

``unbounded``
    A deliberate reproduction of the previous behaviour, where the prompt loop
    swallowed ``EOFError`` and reprompted. The child is killed after a short
    budget and the bytes it managed to write are reported, which demonstrates
    that the measurement is meaningful rather than trivially zero.

Usage:
    python tests/manual/test_prompt_loop_closed_channel.py
"""

import os
import subprocess
import sys
import tempfile

# The child runs with stdin at /dev/null, so the prompt is written to a file
# instead of a terminal. The byte count is the evidence.
CHILD_SOURCE = r'''
import sys

mode = sys.argv[1]
from topsailai.workspace.input_tool import input_message

if mode == "bounded":
    try:
        input_message("PROMPT> ")
    except EOFError:
        print("RESULT: EOFError propagated")
        sys.exit(0)
    print("RESULT: no EOFError")
    sys.exit(2)

# Reproduction of the previous behaviour: swallow EOFError and reprompt.
while True:
    try:
        input_message("PROMPT> ")
    except EOFError:
        continue
'''

BOUNDED_TIMEOUT_SECONDS = 30
UNBOUNDED_BUDGET_SECONDS = 5


def _child_env() -> dict:
    """Return an environment where the child can import this package.

    The child runs with ``-c``, so the package root is not on ``sys.path``
    automatically. Both the project root (for ``tests.*``) and the package
    folder (for ``topsailai``) are added explicitly.
    """
    package_folder = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)
    )))
    project_root = os.path.dirname(package_folder)
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    roots = [project_root, package_folder]
    if existing:
        roots.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(roots)
    # The measurement is about a closed stdin, so the named-pipe channel must
    # be off. With a pipe the read blocks waiting for a writer instead of
    # raising EOFError, which would measure the wrong condition.
    env["TOPSAILAI_INPUT_PIPE_ENABLED"] = "0"
    env["TOPSAILAI_CHAT_MULTI_LINE"] = "0"
    env["TOPSAILAI_INTERACTIVE_MODE"] = "1"
    return env


def _run_child(mode: str, timeout: int) -> tuple:
    """Run one child with stdin at /dev/null and return its outcome."""
    handle = tempfile.NamedTemporaryFile(mode="w+", suffix=".stdout", delete=False)
    output_path = handle.name
    handle.close()

    try:
        with open(os.devnull, "rb") as devnull, open(output_path, "wb") as output_file:
            process = subprocess.Popen(
                [sys.executable, "-c", CHILD_SOURCE, mode],
                stdin=devnull,
                stdout=output_file,
                stderr=subprocess.PIPE,
                env=_child_env(),
            )
            try:
                _, stderr = process.communicate(timeout=timeout)
                timed_out = False
            except subprocess.TimeoutExpired:
                process.kill()
                _, stderr = process.communicate()
                timed_out = True

        with open(output_path, "rb") as reader:
            written = reader.read()

        return {
            "mode": mode,
            "returncode": process.returncode,
            "timed_out": timed_out,
            "bytes": len(written),
            "text": written.decode("utf-8", "replace"),
            "stderr": stderr.decode("utf-8", "replace"),
        }
    finally:
        os.unlink(output_path)


def main() -> int:
    """Measure both modes and report whether the bounded mode holds."""
    bounded = _run_child("bounded", BOUNDED_TIMEOUT_SECONDS)
    unbounded = _run_child("unbounded", UNBOUNDED_BUDGET_SECONDS)

    print("=== bounded (current implementation) ===")
    print(f"returncode : {bounded['returncode']}")
    print(f"timed_out  : {bounded['timed_out']}")
    print(f"bytes      : {bounded['bytes']}")
    print(f"result     : {bounded['text'].strip()}")
    if bounded["stderr"].strip():
        print(f"stderr     : {bounded['stderr'].strip()[:400]}")

    print()
    print("=== unbounded (previous behaviour, killed after budget) ===")
    print(f"returncode : {unbounded['returncode']}")
    print(f"timed_out  : {unbounded['timed_out']}")
    print(f"bytes      : {unbounded['bytes']}")

    print()
    failures = []
    if bounded["timed_out"]:
        failures.append("bounded mode did not finish: the prompt loop still spins")
    if bounded["returncode"] != 0:
        failures.append(f"bounded mode exited with {bounded['returncode']}")
    if "EOFError propagated" not in bounded["text"]:
        failures.append("bounded mode did not propagate EOFError")
    if not unbounded["timed_out"]:
        failures.append("unbounded mode finished, so the measurement is not meaningful")
    if unbounded["bytes"] <= bounded["bytes"]:
        failures.append(
            "unbounded mode wrote no more than bounded mode, so the measurement "
            "does not demonstrate growth"
        )

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print(
        f"PASS: bounded mode wrote {bounded['bytes']} bytes and ended; "
        f"unbounded mode wrote {unbounded['bytes']} bytes in "
        f"{UNBOUNDED_BUDGET_SECONDS}s before being killed"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
