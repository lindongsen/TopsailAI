"""Verify source and packaged acceptance boundaries. Author: DawsonLin."""

from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


def dry_run(target):
    """Resolve a real Makefile target without running its test commands."""
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", "-f", str(ROOT / "Makefile"), target],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return result.stdout


def test_source_gate_excludes_only_packaged_and_slow_scenarios():
    """Keep source scenarios in the default directory-wide BDD selection."""
    output = dry_run("core-bdd-test")
    assert '-m "not slow and not packaged" tests/bdd' in output
    assert "--ignore" not in output
    assert "uv run python" in output
    assert "PYTHONPATH=" in output


def test_packaged_gate_is_explicit():
    """Select packaged acceptance rather than silently omitting it everywhere."""
    output = dry_run("test-bdd-packaged")
    assert '-m "packaged" tests/bdd' in output
    assert output.index("dev-tools deb-build-cython-py3") < output.index('-m "packaged"')
    assert f'TOPSAILAI_PACKAGED_ROOT="{ROOT.parents[1]}/build/output/.deb/topsailai/TopsailAI/src"' in output
    assert "--basetemp=" in output
    assert "cache_dir=" in output


def test_release_gate_requires_source_slow_and_packaged_verification():
    """Require all core BDD categories in release acceptance."""
    output = dry_run("test-release")
    for selector in ("not slow and not packaged", "slow", "packaged"):
        assert f'-m "{selector}" tests/bdd' in output
    assert "tests/run_tests.py" in output


def test_missing_control_handler_artifacts_fail_packaged_acceptance(tmp_path):
    """Do not report missing packaging prerequisites as skipped verification."""
    from tests.bdd.steps.compiled_module_discovery_steps import (
        CompiledDiscoveryContext, given_compiled_control_handlers,
    )
    context = CompiledDiscoveryContext(packaged_root=tmp_path)
    with pytest.raises(pytest.fail.Exception, match="prerequisite absent or stale"):
        given_compiled_control_handlers(context)
