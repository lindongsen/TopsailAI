"""Integration test for the complete configured Hook framework demonstration."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from topsailai.utils.env_tool import resolve_python_interpreter


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO = PROJECT_ROOT / "tests" / "demo" / "hooks" / "demo_configured_framework_readiness.py"


def test_manifest_pinned_demo_runs_real_worker_and_cleans_up() -> None:
    """The public bootstrap-to-Executor path must run and close without debt."""
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        [resolve_python_interpreter(), str(DEMO)],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Registration mode: startup" in result.stdout
    assert "Outcome: success" in result.stdout
    assert "Cleanup debts: 0" in result.stdout
    assert "Deleted demo temporary directory:" in result.stdout

    assert "Unified status: success; default Hooks: 1; Script children: 1" in result.stdout
    assert "Script process exit: 0" in result.stdout
    assert "Scope closed: True" in result.stdout
    assert "Worker exited: True" in result.stdout
    assert "Capture converged: True" in result.stdout
    assert "Demo temporary directory removed: True" in result.stdout
    lines = result.stdout.splitlines()
    demo_pid = int(next(line.removeprefix("Demo PID: ") for line in lines if line.startswith("Demo PID: ")))
    worker_pid = int(next(line.removeprefix("Worker PID: ") for line in lines if line.startswith("Worker PID: ")))
    assert len({demo_pid, worker_pid, os.getpid()}) == 3
    for pid in (demo_pid, worker_pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        raise AssertionError(f"owned demo process still exists: {pid}")
    removed = Path(next(line.removeprefix("Deleted demo temporary directory: ") for line in lines if line.startswith("Deleted demo temporary directory: ")))
    assert removed.parent == PROJECT_ROOT / ".tmp" / "u11" / "final"
    assert not removed.exists()
