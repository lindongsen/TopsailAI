"""Unit 1 execution checklist (Author: DawsonLin).

Verify all six states, malformed/oversized/unsafe/disappearing records,
conservative process identity, immutable models, and read-only filesystem use.
Run fixtures, caches, bytecode and coverage only under the workspace .tmp.
No real driver, model calls, signals, locks or external log operations.
"""

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli_topsailai import session_driver as sd


@pytest.fixture
def record(tmp_path):
    """Create only test-owned metadata under the configured pytest base."""
    path = sd.metadata_path(tmp_path, "team.123")
    path.parent.mkdir(parents=True)
    value = dict(version=1, session_id="team.123", pid=123,
                 run_id="a" * 32, status="running")
    path.write_text(json.dumps(value))
    return tmp_path, path, value


def observe(record, evidence=sd.ProcessEvidence.ABSENT):
    """Inject process evidence without querying a real driver."""
    return sd.observe_driver(record[0], "team.123", process_probe=lambda _: evidence)


@pytest.mark.parametrize("status,evidence,state", [
    ("running", sd.ProcessEvidence.VERIFIED, "ON"),
    ("running", sd.ProcessEvidence.ABSENT, "STALE"),
    ("running", sd.ProcessEvidence.UNKNOWN, "?"),
    ("stopped", sd.ProcessEvidence.ABSENT, "EXIT"),
    ("failed", sd.ProcessEvidence.ABSENT, "FAIL"),
    ("stopped", sd.ProcessEvidence.VERIFIED, "?"),
    ("failed", sd.ProcessEvidence.UNKNOWN, "?"),
    ("running", "alive", "?"),
])
def test_states_read_only(record, status, evidence, state):
    """Assert exact states without changing metadata, lock or log evidence."""
    home, path, value = record
    value["status"] = status
    path.write_text(json.dumps(value))
    for suffix in (".lock", ".log"):
        path.with_suffix(suffix).write_bytes(b"unchanged")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.parent.iterdir()}
    result = observe(record, evidence)
    assert result.state == state
    assert result.driver_pid == 123 and result.run_id == "a" * 32
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.parent.iterdir()}
    with pytest.raises(FrozenInstanceError):
        result.metadata.pid = 9


def test_absence(tmp_path):
    """Missing directories and missing files mean absence without creation."""
    assert sd.observe_driver(tmp_path, "team").state == "-"
    assert not list(tmp_path.iterdir())
    path = sd.metadata_path(tmp_path, "team")
    path.parent.mkdir(parents=True)
    assert sd.observe_driver(tmp_path, "team").state == "-"


@pytest.mark.parametrize("session", ["", "(temp)", "topsailai", "..", "a..b", "a/b",
                                      "a\\b", "a\n", "a\0", "a" * 201, True])
def test_unsafe_ids(tmp_path, session):
    """Reject unsafe identifiers before performing any dependent I/O."""
    assert sd.observe_driver(tmp_path, session).state == "?"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("field,value", [("version", 2), ("version", True),
    ("session_id", "other"), ("pid", 0), ("pid", True), ("pid", "1"),
    ("run_id", "bad"), ("run_id", []), ("status", []), ("status", "unknown")])
def test_invalid_fields(record, field, value):
    """Validate types and contract values before exposing a model."""
    record[2][field] = value
    record[1].write_text(json.dumps(record[2]))
    assert observe(record).state == "?"


@pytest.mark.parametrize("data", [b"{", b"\xff", b"[]", b"{}", b" " * 65537])
def test_invalid_bytes(record, data):
    """Reject corrupt encodings, shapes and oversized metadata."""
    record[1].write_bytes(data)
    assert observe(record).state == "?"


def test_symlink_and_nonregular(record):
    """Never follow metadata symlinks or read special files."""
    path = record[1]
    other = path.with_name("alias.meta")
    other.symlink_to(path)
    assert sd.observe_driver(record[0], "alias").state == "?"
    directory = path.with_name("directory.meta")
    directory.mkdir()
    assert sd.observe_driver(record[0], "directory").state == "?"


def test_parent_symlink(tmp_path):
    """Reject symlink substitution of a metadata ancestor."""
    target = tmp_path / "real"
    target.mkdir()
    (tmp_path / "workspace").symlink_to(target, target_is_directory=True)
    assert sd.observe_driver(tmp_path, "team").state == "?"


@pytest.mark.parametrize("error", [PermissionError, FileNotFoundError, OSError])
def test_read_failure(record, monkeypatch, error):
    """Classify access and post-discovery disappearance conservatively."""
    def fail(_path):
        """Inject a fallible read without touching shared OS singletons."""
        raise error("sensitive detail")
    monkeypatch.setattr(sd, "_read_metadata", fail)
    result = observe(record)
    assert result.state == "?" and "sensitive" not in result.reason


def test_invalid_home(record):
    """Require explicit absolute storage roots."""
    assert sd.observe_driver(Path("relative"), "team").state == "?"
    assert sd.observe_driver(None, "team").state == "?"


@pytest.mark.parametrize("command,expected", [
    (["python3", "/driver/session_agent_driver.py", "--session", "team.123"], True),
    (["/driver/session_agent_driver", "-s", "team.123"], False),
    (["python3", "session_agent_driver.py", "--session=team.123"], True),
    (["python3", "/driver/session_agent_driver.py", "--session", "other"], False),
    (["python3", "/driver/session_agent_driver.py", "--session"], False),
    (["python3", "/driver/session_agent_driver.py", "-s", "team.123", "-s", "team.123"], False),
    (["sh", "-c", "session_agent_driver.py --session team.123"], False),
    ([], False), (["python3"], False),
])
def test_command_identity(command, expected):
    """Only exact entry/session evidence can verify a driver."""
    meta = sd.DriverMetadata(1, "team.123", 123, "a" * 32, "running")
    assert sd._matches_command(command, meta, Path("/driver/session_agent_driver.py"), "/driver") is expected


@pytest.mark.parametrize("mode,expected", [
    ("valid", sd.ProcessEvidence.VERIFIED), ("mismatch", sd.ProcessEvidence.UNKNOWN),
    ("denied", sd.ProcessEvidence.UNKNOWN), ("absent", sd.ProcessEvidence.ABSENT),
    ("zombie", sd.ProcessEvidence.ABSENT), ("unstable", sd.ProcessEvidence.UNKNOWN),
    ("reused", sd.ProcessEvidence.UNKNOWN),
])
def test_process_probe(record, monkeypatch, mode, expected):
    """Use isolated process doubles, never send signals or start a driver."""
    times = iter([1, 2 if mode == "reused" else 1])
    def process(_pid):
        """Return a controlled read-only process or a classified failure."""
        if mode == "denied":
            raise sd.psutil.AccessDenied(123)
        if mode == "absent":
            raise sd.psutil.NoSuchProcess(123)
        return SimpleNamespace(create_time=lambda: next(times),
            cmdline=lambda: ["python3", "/driver/session_agent_driver.py", "-s",
                             "other" if mode == "mismatch" else "team.123"],
            cwd=lambda: "/driver", is_running=lambda: mode != "unstable",
            status=lambda: sd.psutil.STATUS_ZOMBIE if mode == "zombie" else "running")
    monkeypatch.setattr(sd, "psutil", SimpleNamespace(Process=process,
        NoSuchProcess=sd.psutil.NoSuchProcess, AccessDenied=sd.psutil.AccessDenied,
        Error=sd.psutil.Error,
        STATUS_ZOMBIE=sd.psutil.STATUS_ZOMBIE, STATUS_DEAD=sd.psutil.STATUS_DEAD))
    meta = sd._parse_metadata(record[1].read_bytes(), "team.123")
    assert sd.probe_driver_process(meta, driver_entry=Path("/driver/session_agent_driver.py")) is expected


def test_unsupported_safe_read(record, monkeypatch):
    """Fail closed when platform no-follow directory reads are unavailable."""
    monkeypatch.setattr(sd, "os", SimpleNamespace())
    assert observe(record).reason == "safe_read_unsupported"


def test_file_replaced_during_open(record, monkeypatch):
    """Reject a changed inode between inspection and opened-file custody."""
    actual = sd.os
    def different(_fd):
        """Return an isolated mismatching identity without changing files."""
        return SimpleNamespace(st_mode=sd.stat.S_IFREG, st_dev=-1, st_ino=-1)
    replacement = SimpleNamespace(**vars(actual))
    replacement.fstat = different
    monkeypatch.setattr(sd, "os", replacement)
    assert observe(record).reason == "metadata_changed"


def test_missing_entry_authority(record, monkeypatch):
    """Never guess a checkout entry or query processes without entry authority."""
    def unexpected_process(_pid):
        """Fail if missing entry authority still triggers process inspection."""
        pytest.fail("process inspection requires explicit driver entry authority")
    monkeypatch.setattr(sd, "psutil", SimpleNamespace(Process=unexpected_process))
    meta = sd._parse_metadata(record[1].read_bytes(), "team.123")
    assert sd.probe_driver_process(meta) is sd.ProcessEvidence.UNKNOWN
    result = sd.observe_driver(record[0], "team.123")
    assert result.state == "?"
    assert result.reason == "process_unverified"
    assert result.verification is sd.ProcessEvidence.UNKNOWN


# Unit 2 checklist: shared snapshots, all display states, eligibility, refresh,
# JSON parity, preserved session status/order and no driver-owned mutations.
@pytest.mark.parametrize("state", ["ON", "STALE", "-", "?", "EXIT", "FAIL"])
def test_workspace_snapshot_table_json_parity(tmp_path, monkeypatch, state, capsys):
    """Both renderers consume the same observation without additional probes."""
    from cli_topsailai import formatting as fmt
    from cli_topsailai.core import _workspace_json_item

    row = dict(filename="team.123.456.session.stdout", session_id="team.123",
               pid=456, session_pid=456, ctime=1)
    metadata = sd.DriverMetadata(1, "team.123", 123, "a" * 32, "running")
    observation = sd.DriverObservation(state, "fixture", metadata)
    calls = []
    monkeypatch.setattr(fmt, "os", SimpleNamespace(kill=lambda *_: None))
    monkeypatch.setattr(fmt, "is_session_pipe_open", lambda _: True)
    monkeypatch.setattr(sd, "observe_driver", lambda *args: calls.append(args) or observation)
    fmt.enrich_workspace_rows([row], str(tmp_path))
    monkeypatch.setattr(sd, "observe_driver", lambda *_: pytest.fail("renderer reobserved"))
    monkeypatch.setattr(fmt, "is_session_pipe_open", lambda _: pytest.fail("renderer probed"))
    fmt.print_table([row])
    lines = capsys.readouterr().out.splitlines()
    assert [cell.strip() for cell in lines[0].split("|")][4:6] == ["Status", "Driver"]
    assert [cell.strip() for cell in lines[2].split("|")][4:6] == ["INPUT", state]
    item = _workspace_json_item(row, 1)
    assert item["status"] == "input" and item["pid"] == 456
    assert item["driver"] == dict(state=state, reason="fixture", driver_pid=123,
        run_id="a" * 32, metadata_status="running", verification="unknown")
    assert len(calls) == 1 and row["driver_observation"] is observation


@pytest.mark.parametrize("changes", [
    dict(is_task=True), dict(session_id="topsailai"), dict(session_id="(temp)"),
    dict(session_id=None), dict(session_id="a/b"), dict(filename="team.123.456.stdout"),
    dict(filename="malformed.session.stdout"), dict(session_pid=999),
    dict(session_pid=True),
])
def test_workspace_ineligible_rows(tmp_path, monkeypatch, changes):
    """Task, temp, malformed and legacy rows never trigger driver observation."""
    from cli_topsailai import formatting as fmt
    from cli_topsailai.core import _workspace_json_item

    row = dict(filename="team.123.456.session.stdout", session_id="team.123",
               pid=456, session_pid=456, ctime=1)
    row.update(changes)
    monkeypatch.setattr(fmt, "os", SimpleNamespace(kill=lambda *_: None))
    monkeypatch.setattr(fmt, "is_session_pipe_open", lambda _: False)
    monkeypatch.setattr(sd, "observe_driver", lambda *_: pytest.fail("ineligible observed"))
    fmt.enrich_workspace_rows([row], str(tmp_path))
    assert row["driver_observation"] is None
    assert _workspace_json_item(row, 1)["driver"] is None


@pytest.mark.parametrize("legacy", [False, True])
def test_workspace_ambiguous_live_identity(tmp_path, monkeypatch, legacy):
    """Multiple live session PIDs suppress observation even with a legacy row."""
    from cli_topsailai import formatting as fmt

    rows = [dict(filename=f"team.{pid}.session.stdout", session_id="team",
                 pid=pid, session_pid=pid, ctime=pid) for pid in (1, 2)]
    if legacy:
        rows[1]["filename"] = "team.2.stdout"
    monkeypatch.setattr(fmt, "os", SimpleNamespace(kill=lambda *_: None))
    monkeypatch.setattr(fmt, "is_session_pipe_open", lambda _: False)
    monkeypatch.setattr(sd, "observe_driver", lambda *_: pytest.fail("ambiguous observed"))
    fmt.enrich_workspace_rows(rows, str(tmp_path))
    assert all(row["driver_observation"] is None for row in rows)
    assert [row["ctime"] for row in rows] == [1, 2]


def test_workspace_refresh_read_only(record, monkeypatch):
    """Each refresh replaces its snapshot without mutating metadata, lock or log."""
    from cli_topsailai import formatting as fmt

    home, path, _ = record
    for suffix in (".lock", ".log"):
        path.with_suffix(suffix).write_bytes(b"unchanged")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.parent.iterdir()}
    rows = [dict(filename="team.123.456.session.stdout", session_id="team.123",
                 pid=456, session_pid=456, ctime=1)]
    monkeypatch.setattr(fmt, "os", SimpleNamespace(kill=lambda *_: None))
    monkeypatch.setattr(fmt, "is_session_pipe_open", lambda _: False)
    fmt.enrich_workspace_rows(rows, str(home))
    first = rows[0]["driver_observation"]
    assert first.state == "?" and first.reason == "process_unverified"
    fmt.enrich_workspace_rows(rows, str(home))
    assert rows[0]["driver_observation"] is not first
    assert rows[0]["workspace_status"] == "running"
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.parent.iterdir()}


def test_workspace_duplicate_rows_share_snapshot(tmp_path, monkeypatch):
    """Repeated rows for one PID share a single observation, preserving order."""
    from cli_topsailai import formatting as fmt

    rows = [dict(filename="team.456.session.stdout", session_id="team",
                 pid=456, session_pid=456, ctime=n) for n in (1, 2)]
    calls = []
    monkeypatch.setattr(fmt, "os", SimpleNamespace(kill=lambda *_: None))
    monkeypatch.setattr(fmt, "is_session_pipe_open", lambda _: False)
    monkeypatch.setattr(sd, "observe_driver", lambda *args: calls.append(args)
                        or sd.DriverObservation("-", "metadata_missing"))
    fmt.enrich_workspace_rows(rows, str(tmp_path))
    assert len(calls) == 1
    assert rows[0]["driver_observation"] is rows[1]["driver_observation"]
    assert [row["ctime"] for row in rows] == [1, 2]


def test_workspace_dead_session_retains_driver_snapshot(tmp_path, monkeypatch):
    """An explicit exited session remains eligible for independent driver status."""
    from cli_topsailai import formatting as fmt

    row = dict(filename="team.456.session.stdout", session_id="team", pid=456, ctime=1)
    def absent(*args):
        """Represent a confirmed absent target session without a real signal."""
        raise ProcessLookupError()
    monkeypatch.setattr(fmt, "os", SimpleNamespace(kill=absent))
    fmt.enrich_workspace_rows([row], str(tmp_path))
    assert row["workspace_status"] == "idle" and row["workspace_pid"] is None
    assert row["pid"] == 456
    assert row["driver_observation"].state == "-"


# Repair checklist: reject string/bool/zero/negative raw PIDs before probing;
# preserve idle table/JSON parity and fixture metadata/lock/log bytes and mtimes.
@pytest.mark.parametrize("pid", ["456", True, 0, -1],
                         ids=["string", "boolean", "zero", "negative"])
def test_workspace_invalid_raw_pid_read_only(record, monkeypatch, capsys, pid):
    """Invalid raw PIDs stay idle without probing or observing driver artifacts."""
    from cli_topsailai import formatting as fmt
    from cli_topsailai.core import _workspace_json_item

    home, path, _ = record
    for suffix in (".lock", ".log"):
        path.with_suffix(suffix).write_bytes(b"unchanged")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.parent.iterdir()}
    row = dict(filename="team.123.456.session.stdout", session_id="team.123",
               pid=pid, session_pid=456, ctime=1)
    monkeypatch.setattr(fmt, "os", SimpleNamespace(
        kill=lambda *_: pytest.fail("invalid PID probed")))
    monkeypatch.setattr(fmt, "is_session_pipe_open",
                        lambda _: pytest.fail("invalid PID pipe probed"))
    monkeypatch.setattr(sd, "observe_driver",
                        lambda *_: pytest.fail("invalid PID driver observed"))
    fmt.enrich_workspace_rows([row], str(home))
    assert row["pid"] is pid
    assert row["workspace_pid"] is None
    assert row["workspace_status"] == "idle"
    assert row["driver_observation"] is None
    item = _workspace_json_item(row, 1)
    assert item["pid"] is None and item["status"] == "idle"
    assert item["driver"] is None
    fmt.print_table([row])
    cells = [cell.strip() for cell in capsys.readouterr().out.splitlines()[2].split("|")]
    assert cells[3:6] == ["-", "-", "-"]
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.parent.iterdir()}
