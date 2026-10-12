"""Unit 5 isolated process lifecycle acceptance. Author: DawsonLin."""

from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import psutil
import pytest

from cli_topsailai import core
from cli_topsailai.session_driver import (
    ProcessEvidence, metadata_path, observe_driver, probe_driver_process,
)
from cli_topsailai.session_driver_launcher import DriverAuthority, launch_driver


@pytest.fixture
def fixture_owner(tmp_path):
    """Copy the harmless script under basetemp; never execute production entry."""
    entry = tmp_path / "fixture owner.py"
    shutil.copyfile(Path(__file__).with_name("session_driver_fixture.py"), entry)
    authority = DriverAuthority(entry, Path(sys.executable))
    authority.validate()
    return tmp_path, authority


def rows():
    """Use the pytest process as a harmless live target-session identity."""
    pid = os.getpid()
    return [dict(session_id="fixture", pid=pid, session_pid=pid,
                 filename=f"fixture.{pid}.session.stdout")]


def observation(home, authority):
    """Verify actual PID/command evidence with explicitly supplied fixture entry."""
    return observe_driver(home, "fixture", process_probe=partial(
        probe_driver_process, driver_entry=authority.entry))


def release(home, children):
    """Release fixtures normally; signal only exact test handles on cleanup failure."""
    (home / "release").touch()
    for child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print(f"Cleanup exact fixture PID {child.pid}")
            child.terminate()
            child.wait(timeout=5)


def test_competing_publication_and_clean_exit(fixture_owner, capsys):
    """Two candidates yield one verified owner; clean exit restores table/JSON -."""
    home, authority = fixture_owner
    barrier = threading.Barrier(2)
    children = []

    def spawn(argv, **kwargs):
        """Force both preflights to finish before either candidate starts."""
        barrier.wait(timeout=5)
        child = subprocess.Popen(argv, **kwargs)
        children.append(child)
        return child

    def start():
        """Exercise actual launch confirmation without observer/probe substitutes."""
        return launch_driver(rows(), 1, topsailai_home=home, authority=authority,
                             environment=dict(os.environ), discover=rows,
                             spawn=spawn, timeout=5)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: start(), range(2)))
        assert sorted(result.outcome for result in results) == ["already_running", "launched"]
        owner = observation(home, authority)
        assert owner.state == "ON" and owner.verification is ProcessEvidence.VERIFIED
        assert len([child for child in children if child.poll() is None]) == 1
        assert owner.driver_pid in [child.pid for child in children]
        enriched = rows()
        core._enrich_driver_rows(enriched, home, authority)
        assert core._workspace_json_item(enriched[0], 1)["driver"]["state"] == "ON"
        assert enriched[0]["workspace_status"] == "running"
        metadata = metadata_path(home, "fixture")
        before = metadata.read_bytes(), metadata.stat().st_mtime_ns
        core._handle_driver_action("driver_status", 1, rows(), home, authority,
                                   dict(os.environ), rows)
        assert "state=ON" in capsys.readouterr().out
        assert before == (metadata.read_bytes(), metadata.stat().st_mtime_ns)
    finally:
        release(home, children)
    assert all(child.poll() is not None for child in children)
    assert observation(home, authority).state == "-"
    assert not metadata_path(home, "fixture").with_suffix(".log").exists()
    core._enrich_driver_rows(enriched, home, authority)
    assert core._workspace_json_item(enriched[0], 1)["driver"]["state"] == "-"


@pytest.mark.parametrize("status,state", [("running", "STALE"),
                                         ("stopped", "EXIT"), ("failed", "FAIL")])
def test_residual_record_only(fixture_owner, status, state):
    """A known exited fixture PID supports residual states only while meta exists."""
    home, authority = fixture_owner
    child = subprocess.Popen([str(authority.interpreter), "-c", "pass"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    child.wait(timeout=5)
    path = metadata_path(home, "fixture")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(version=1, session_id="fixture", pid=child.pid,
                                   run_id="a" * 32, status=status)))
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert observation(home, authority).state == state
    assert before == (path.read_bytes(), path.stat().st_mtime_ns)
    path.unlink()
    print(f"Fixture removed {path}")
    assert observation(home, authority).state == "-"


def test_live_owner_survives_cli_process_exit(fixture_owner):
    """An actual launcher harness exits without terminating its resident fixture."""
    home, authority = fixture_owner
    environment = dict(os.environ, TOPSAILAI_HOME=str(home))
    package_root = str(Path(core.__file__).resolve().parent.parent)
    existing_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        [package_root, existing_path] if existing_path else [package_root])
    error_path = home / "harness-stderr.log"
    with error_path.open("wb") as error_log:
        harness = subprocess.Popen([str(authority.interpreter), str(authority.entry),
                                    "--session", "fixture", "--cli"], env=environment,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=error_log)
    owner = None
    try:
        assert harness.wait(timeout=10) == 0, error_path.read_text()
        result = json.loads((home / "cli-result.json").read_text())
        assert result["outcome"] == "launched" and result["retained"] == 1
        owner = psutil.Process(result["pid"])
        assert observation(home, authority).state == "ON"
        assert owner.is_running()
    finally:
        release(home, [harness])
        if owner is not None:
            try:
                owner.wait(timeout=5)
            except psutil.TimeoutExpired:
                print(f"Cleanup exact fixture PID {owner.pid}")
                owner.terminate()
                owner.wait(timeout=5)
    assert observation(home, authority).state == "-"
