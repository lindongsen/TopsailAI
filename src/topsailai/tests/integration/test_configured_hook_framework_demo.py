"""Integration test for the complete configured Hook framework demonstration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO = PROJECT_ROOT / "tests" / "demo" / "hooks" / "demo_configured_framework_readiness.py"


def test_manifest_pinned_demo_runs_real_worker_and_cleans_up() -> None:
    """The public bootstrap-to-Executor path must run and close without debt."""
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        [sys.executable, str(DEMO)],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Registration mode: startup" in result.stdout
    assert "Outcome: success" in result.stdout
    assert "Cleanup debts: 0" in result.stdout
    assert "Deleted demo temporary directory:" in result.stdout
