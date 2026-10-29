"""Pytest fixture for the bounded U1 raw resume handoff test."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from resume_raw_handoff_helpers import Custody


@pytest.fixture
def raw_custody():
    """Provide one workspace-owned custody root and retain failed evidence."""
    workspace = Path(__file__).resolve().parents[3]
    base = workspace / ".tmp" / "c2-reduced" / "u1-runtime"
    base.mkdir(parents=True, exist_ok=True)
    root = base / f"run-{__import__('os').getpid()}-{__import__('uuid').uuid4().hex}"
    custody = Custody(root)
    try:
        yield custody
    finally:
        if not custody.finished:
            try:
                custody.finish()
            except Exception as error:
                custody.events.append(f"teardown failure: {error}")
                teardown = custody.root / "teardown-failure.json"
                teardown.write_text(json.dumps({
                    "error": str(error),
                    "root_retained": True,
                }, indent=2, sort_keys=True), encoding="utf-8")
                print(f"retaining fixture root after teardown failure {custody.root}")
                raise
        archive = workspace / ".tmp" / "c2-reduced" / "u1-reports"
        archive.mkdir(parents=True, exist_ok=True)
        report = custody.root / "custody-report.json"
        if report.exists():
            archived = archive / f"{custody.root.name}-{custody.root.stat().st_mtime_ns}.json"
            archived.write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
            custody.events.append(f"archived custody report {archived}")
            report.write_text(json.dumps({"events": custody.events}, indent=2), encoding="utf-8")
        for marker in (custody.u2_marker, custody.u3_marker, custody.u4_marker):
            if marker.exists():
                marker.unlink()
                custody.events.append(f"deleted run-scoped marker {marker}")
                print(f"deleted run-scoped marker {marker}")
        if custody.finished:
            custody.events.append(f"deleting fixture root {custody.root}")
            shutil.rmtree(custody.root)
            print(f"deleted owned fixture root {custody.root}")
