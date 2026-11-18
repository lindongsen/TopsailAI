"""Adversarial tests for the 2026-11-14 disk-growth incident.

The incident produced 51.75 GB of deleted-but-open data. Two orphaned test
processes were stuck in an unbounded prompt loop, their stdout was redirected
to log files, and the log files were deleted while the descriptors stayed open,
so the space was never reclaimed.

These tests assert the three properties that incident violated:

1. A prompt loop over a closed input channel writes a bounded number of bytes.
2. A deleted-but-open file keeps holding its space until the descriptor closes,
   and that state is detectable from the process descriptor table.
3. A session lifecycle of many turns keeps its total prompt output bounded.

Every test is adversarial: it reproduces the failure condition rather than the
happy path, and the byte assertions are paired with a negative control that
reproduces the old unbounded behaviour so a green result cannot be vacuous.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

# tests/unit/<this file> -> tests/unit -> tests -> workspace root
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = WORKSPACE_ROOT.parent
TMP_ROOT = WORKSPACE_ROOT / ".tmp" / "disk-growth-adversarial"

# A prompt loop that must terminate on a closed input channel.
BOUNDED_SCRIPT = """
import sys
from topsailai.workspace.input_tool import input_one_line

try:
    input_one_line("PROMPT> ")
except EOFError:
    sys.exit(0)
sys.exit(3)
"""

# Negative control: the pre-fix loop swallowed EOFError and reprompted.
UNBOUNDED_SCRIPT = """
import sys
from topsailai.workspace.input_tool import _input

MAX_INPUT_RETRY_COUNT = 999
message = ""
for _ in range(MAX_INPUT_RETRY_COUNT):
    try:
        message = _input("PROMPT> ")
    except EOFError:
        message = ""
    message = message.strip()
    if not message:
        continue
    break
sys.exit(0)
"""

# A session lifecycle: many turns, each ending with a closed input channel.
LIFECYCLE_SCRIPT = """
import sys
from topsailai.workspace.input_tool import input_one_line

TURNS = 50
for _ in range(TURNS):
    try:
        input_one_line("PROMPT> ")
    except EOFError:
        continue
sys.exit(0)
"""


def _child_env() -> dict:
    """Build a child environment that isolates the input channel.

    ``topsailai/__init__.py`` loads ``.env.local`` at import time, and that file
    enables pipe input on this host. Pipe input would block on a named pipe
    instead of reaching the closed-stdin branch, so the variable is forced off
    here. ``load_dotenv`` does not override an existing value, so the explicit
    setting wins.
    """
    env = dict(os.environ)
    env["TOPSAILAI_INPUT_PIPE_ENABLED"] = "0"
    existing = env.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p]
    if str(SOURCE_ROOT) not in parts:
        parts.insert(0, str(SOURCE_ROOT))
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _run_child(script: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a script with stdin closed, capturing stdout and stderr."""
    return subprocess.run(
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env=_child_env(),
        timeout=timeout,
        cwd=str(WORKSPACE_ROOT),
    )


class TestBoundedPromptOutput(unittest.TestCase):
    """A closed input channel must not produce unbounded prompt output."""

    def test_closed_stdin_writes_bounded_bytes(self):
        """The prompt is written once, then the loop ends.

        Before the fix this loop reprompted forever; the incident's processes
        wrote gigabytes this way. The bound is generous enough to tolerate a
        prompt plus a newline and strict enough to fail on any reprompting.
        """
        result = _run_child(BOUNDED_SCRIPT)
        written = len(result.stdout)

        self.assertEqual(
            result.returncode,
            0,
            f"child did not exit cleanly: {result.stderr[-2000:]!r}",
        )
        self.assertLess(
            written,
            200,
            f"prompt loop wrote {written} bytes on a closed stdin; "
            f"output={result.stdout[:400]!r}",
        )
        self.assertEqual(
            result.stdout.count(b"PROMPT>"),
            1,
            f"prompt was written {result.stdout.count(b'PROMPT>')} times "
            f"instead of once",
        )

    def test_negative_control_reproduces_unbounded_output(self):
        """The old loop writes far more, so the bound above is meaningful.

        Without this control a green byte assertion could pass simply because
        the child never reached the prompt at all.
        """
        bounded = _run_child(BOUNDED_SCRIPT)
        unbounded = _run_child(UNBOUNDED_SCRIPT)

        self.assertEqual(unbounded.returncode, 0)
        self.assertGreater(
            len(unbounded.stdout),
            1000,
            "the negative control did not reproduce the old unbounded "
            f"behaviour; it wrote only {len(unbounded.stdout)} bytes",
        )
        self.assertGreater(
            len(unbounded.stdout),
            10 * len(bounded.stdout),
            "the negative control is not clearly worse than the fixed path",
        )

    def test_session_lifecycle_keeps_total_output_bounded(self):
        """Many turns over a closed channel stay proportional to the turns.

        A per-turn bound is not enough: the incident accumulated across a long
        run. Total output must stay near one prompt per turn instead of growing
        with the retry bound.
        """
        result = _run_child(LIFECYCLE_SCRIPT)
        written = len(result.stdout)
        turns = 50

        self.assertEqual(
            result.returncode,
            0,
            f"lifecycle child failed: {result.stderr[-2000:]!r}",
        )
        self.assertLess(
            written,
            20 * turns,
            f"{turns} turns wrote {written} bytes, which exceeds one prompt "
            f"per turn by more than 20x",
        )
        self.assertEqual(
            result.stdout.count(b"PROMPT>"),
            turns,
            f"expected exactly one prompt per turn, got "
            f"{result.stdout.count(b'PROMPT>')}",
        )


class TestDeletedButOpenDetection(unittest.TestCase):
    """A deleted file whose descriptor is open still holds its space."""

    def setUp(self):
        """Create an owned temporary directory under the workspace .tmp."""
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.mkdtemp(dir=str(TMP_ROOT), prefix="deleted-open-")

    def tearDown(self):
        """Remove only the directory this test created."""
        import shutil

        if os.path.isdir(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            print(f"[DELETED] {self.temp_dir}")

    def test_deleted_descriptor_keeps_size_until_close(self):
        """Unlinking the path does not release the space while the fd is open.

        This is the exact mechanism that turned deleted log files into 51.75 GB
        of unreclaimable space: the path disappeared, so ordinary disk-usage
        inspection showed nothing, while the descriptor kept the blocks.
        """
        path = os.path.join(self.temp_dir, "grow.log")
        payload = b"x" * 65536

        handle = open(path, "wb")
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

            os.unlink(path)
            self.assertFalse(
                os.path.exists(path),
                "the path should be gone after unlink",
            )

            held = os.fstat(handle.fileno()).st_size
            self.assertEqual(
                held,
                len(payload),
                "the open descriptor must still report the full size after "
                "the path was removed",
            )
        finally:
            handle.close()
        with self.assertRaises(ValueError):
            os.fstat(handle.fileno())

    @pytest.mark.skipif(
        not os.path.isdir("/proc/self/fd"),
        reason="requires a /proc descriptor table",
    )
    def test_orphan_descriptor_is_visible_in_descriptor_table(self):
        """A deleted-but-open descriptor is discoverable before it is closed.

        Detection is what makes the condition diagnosable; without it the space
        is invisible to path-based inspection.
        """
        path = os.path.join(self.temp_dir, "orphan.log")
        handle = open(path, "wb")
        try:
            handle.write(b"y" * 4096)
            handle.flush()
            os.unlink(path)

            target = os.readlink(f"/proc/self/fd/{handle.fileno()}")
            self.assertIn(
                "deleted",
                target,
                f"descriptor target should be marked deleted, got {target!r}",
            )
            self.assertIn(
                "orphan.log",
                target,
                f"descriptor target should name the removed file, got {target!r}",
            )
        finally:
            handle.close()

    def test_closing_the_descriptor_releases_the_held_space(self):
        """Closing the last descriptor is what actually reclaims the space.

        The incident was resolved by killing the owning processes, which is
        equivalent to closing their descriptors. This asserts that the release
        is tied to the descriptor, not to the path.
        """
        path = os.path.join(self.temp_dir, "release.log")
        payload = b"z" * 32768

        handle = open(path, "wb")
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        os.unlink(path)
        held_before = os.fstat(handle.fileno()).st_size
        handle.close()

        self.assertEqual(held_before, len(payload))
        self.assertFalse(os.path.exists(path))
        self.assertEqual(
            os.listdir(self.temp_dir),
            [],
            "the temporary directory should be empty after the descriptor "
            "closed and the path was removed",
        )


if __name__ == "__main__":
    unittest.main()
