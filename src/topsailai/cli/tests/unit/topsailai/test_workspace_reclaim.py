"""Tests for the read-only ``workspace reclaim`` inspection command.

Author: DawsonLin
"""

import json
import os
import socket
import time
from pathlib import Path

import pytest

from cli_topsailai.workspace_reclaim_cli import run_workspace_reclaim_cli

from topsailai.context.session_activity import ActivityObservation, ActivityState

#: Age used by every fixture so a record is unambiguously expired.
_OLD_AGE = 10 * 86400
#: Age used by every fixture so a record is unambiguously fresh.
_FRESH_AGE = 60


class _FakeProbe:
    """Return a fixed observation per session without touching the host."""

    def __init__(self, states):
        self.states = states
        self.calls = []

    def observe_many(self, session_ids):
        """Record the requested batch and answer from the fixed mapping."""
        self.calls.append(tuple(session_ids))
        return {
            session_id: self.states.get(
                session_id,
                ActivityObservation(ActivityState.UNKNOWN, "no evidence"),
            )
            for session_id in session_ids
        }


def _stopped(reason="all verified local owners absent"):
    """Build a stopped observation with the production reason text."""
    return ActivityObservation(ActivityState.STOPPED, reason)


def _make_task_dir(tmp_path: Path) -> Path:
    """Create the ``{home}/workspace/task`` layout the command expects."""
    task_dir = tmp_path / "workspace" / "task"
    task_dir.mkdir(parents=True)
    return task_dir


def _make_file(task_dir: Path, name: str, *, age: float = _OLD_AGE) -> Path:
    """Create one regular file with an explicit modification age in seconds."""
    path = task_dir / name
    path.write_text("record")
    mtime = time.time() - age
    os.utime(path, (mtime, mtime))
    return path


def _make_socket(task_dir: Path, name: str) -> Path:
    """Create one real unix socket endpoint with the given name."""
    path = task_dir / name
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        endpoint.bind(str(path))
    finally:
        endpoint.close()
    return path


def _invoke(tmp_path, states, argv, *, probe=None):
    """Run the command with an isolated home and a fixed activity probe."""
    fake = _FakeProbe(states) if probe is None else probe
    code = run_workspace_reclaim_cli(
        argv,
        home_resolver=lambda: str(tmp_path),
        probe_factory=lambda _task_dir: fake,
    )
    return code, fake


def _receipt(capsys):
    """Parse the single JSON document the command wrote to stdout."""
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected one receipt line, got {len(lines)}"
    return json.loads(lines[0])


def _by_session(receipt):
    """Index the reported sessions by their identifier."""
    return {item["session_id"]: item for item in receipt["response"]["sessions"]}


def test_expired_orphan_records_are_reclaimable(tmp_path, capsys):
    """A stopped session without metadata reclaims its expired records."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-a.111.session.stats.jsonl")
    _make_file(task_dir, "sess-a.111.session.stdout")

    code, _probe = _invoke(tmp_path, {"sess-a": _stopped()}, ["--json"])

    assert code == 0
    receipt = _receipt(capsys)
    session = _by_session(receipt)["sess-a"]
    assert session["decision"] == "reclaimable"
    assert session["reason"] == "expired owner records without metadata"
    assert session["has_metadata"] is False
    assert session["record_count"] == 2
    assert session["expired_count"] == 2
    assert receipt["response"]["reclaimable_sessions"] == ["sess-a"]


def test_expired_metadata_is_reclaimable_with_its_artifacts(tmp_path, capsys):
    """A stopped session that still owns expired metadata is reclaimable."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-c.333.session.meta")
    _make_file(task_dir, "sess-c.333.session.stdout")

    code, _probe = _invoke(tmp_path, {"sess-c": _stopped()}, ["--json"])

    assert code == 0
    session = _by_session(_receipt(capsys))["sess-c"]
    assert session["decision"] == "reclaimable"
    assert session["reason"] == "expired metadata and its artifacts"
    assert session["has_metadata"] is True


def test_running_owner_blocks_reclaim(tmp_path, capsys):
    """A live owner protects its records even when they are expired."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-b.222.session.stats.jsonl")

    states = {"sess-b": ActivityObservation(ActivityState.RUNNING, "live associated owner")}
    code, _probe = _invoke(tmp_path, states, ["--json"])

    assert code == 0
    session = _by_session(_receipt(capsys))["sess-b"]
    assert session["decision"] == "blocked"
    assert session["reason"] == "owning session is still alive"
    assert session["expired_count"] == 1


def test_unknown_owner_blocks_reclaim(tmp_path, capsys):
    """An unverifiable owner blocks reclaim instead of guessing."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-u.777.session.stats.jsonl")

    states = {"sess-u": ActivityObservation(ActivityState.UNKNOWN, "inventory changed")}
    code, _probe = _invoke(tmp_path, states, ["--json"])

    assert code == 0
    session = _by_session(_receipt(capsys))["sess-u"]
    assert session["decision"] == "blocked"
    assert session["reason"] == "inventory changed"


def test_fresh_metadata_blocks_reclaim(tmp_path, capsys):
    """Metadata inside the retention window is not reclaimable."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-d.444.session.meta", age=_FRESH_AGE)

    code, _probe = _invoke(tmp_path, {"sess-d": _stopped()}, ["--json"])

    assert code == 0
    session = _by_session(_receipt(capsys))["sess-d"]
    assert session["decision"] == "blocked"
    assert session["reason"] == "metadata is still within the retention window"
    assert session["expired_count"] == 0


def test_fresh_orphan_records_block_reclaim(tmp_path, capsys):
    """A fresh orphan record is the startup window, not a residue."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-e.555.session.stats.jsonl", age=_FRESH_AGE)

    code, _probe = _invoke(tmp_path, {"sess-e": _stopped()}, ["--json"])

    assert code == 0
    session = _by_session(_receipt(capsys))["sess-e"]
    assert session["decision"] == "blocked"
    assert session["reason"] == "owner records are still within the retention window"


def test_socket_endpoint_is_not_reported_as_a_record(tmp_path, capsys):
    """A socket is owned by its channel, so it is never a reclaimable record."""
    task_dir = _make_task_dir(tmp_path)
    _make_socket(task_dir, "sess-f.666.session.sock")

    code, _probe = _invoke(tmp_path, {"sess-f": _stopped()}, ["--json"])

    assert code == 0
    session = _by_session(_receipt(capsys))["sess-f"]
    assert session["record_count"] == 0
    assert session["socket_count"] == 1
    assert session["records"] == []
    assert session["decision"] == "blocked"
    assert session["reason"] == "only a socket endpoint remains"


def test_session_selector_narrows_the_inventory(tmp_path, capsys):
    """``-s`` reports only the selected session."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-a.111.session.stats.jsonl")
    _make_file(task_dir, "sess-b.222.session.stats.jsonl")

    states = {"sess-a": _stopped(), "sess-b": _stopped()}
    code, probe = _invoke(tmp_path, states, ["-s", "sess-a", "--json"])

    assert code == 0
    receipt = _receipt(capsys)
    assert [item["session_id"] for item in receipt["response"]["sessions"]] == ["sess-a"]
    assert probe.calls == [("sess-a",)]
    assert receipt["response"]["selectors"] == {"session_ids": ["sess-a"]}


def test_temporary_session_display_spelling_selects_on_disk_identity(tmp_path, capsys):
    """``(temp)`` selects the records whose on-disk prefix is ``topsailai``."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "topsailai.999.session.stats.jsonl")

    code, _probe = _invoke(tmp_path, {"topsailai": _stopped()}, ["-s", "(temp)", "--json"])

    assert code == 0
    receipt = _receipt(capsys)
    assert [item["session_id"] for item in receipt["response"]["sessions"]] == ["topsailai"]
    assert receipt["response"]["selectors"] == {"session_ids": ["topsailai"]}


def test_json_receipt_carries_the_complete_contract(tmp_path, capsys):
    """The receipt exposes every documented field and one stdout document."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-a.111.session.stats.jsonl")

    code, _probe = _invoke(tmp_path, {"sess-a": _stopped()}, ["--json"])

    assert code == 0
    receipt = _receipt(capsys)
    assert receipt["ok"] is True
    assert receipt["exit_code"] == 0
    assert receipt["action"] == "reclaim"
    assert receipt["delivery_state"] == "inspected"
    response = receipt["response"]
    for field in (
        "retention_days", "meta_max_count", "selectors", "sessions",
        "session_count", "reclaimable_sessions", "reclaimable_session_count",
        "blocked_session_count", "reclaimable_record_count", "reclaimable_bytes",
    ):
        assert field in response, field
    assert response["session_count"] == 1
    assert response["reclaimable_session_count"] == 1
    assert response["blocked_session_count"] == 0
    assert response["reclaimable_record_count"] == 1


def test_human_output_lists_every_session_with_its_reason(tmp_path, capsys):
    """The default mode prints one row per session and never deletes."""
    task_dir = _make_task_dir(tmp_path)
    orphan = _make_file(task_dir, "sess-a.111.session.stats.jsonl")
    _make_file(task_dir, "sess-b.222.session.stats.jsonl")

    states = {
        "sess-a": _stopped(),
        "sess-b": ActivityObservation(ActivityState.RUNNING, "live associated owner"),
    }
    code, _probe = _invoke(tmp_path, states, [])

    assert code == 0
    out = capsys.readouterr().out
    assert "sess-a" in out
    assert "sess-b" in out
    assert "reclaimable" in out
    assert "owning session is still alive" in out
    assert "never deletes" in out
    assert orphan.exists(), "the inspection must not delete anything"


def test_dry_run_flag_is_accepted_and_changes_nothing(tmp_path, capsys):
    """``--dry-run`` is an explicit alias for the default behaviour."""
    task_dir = _make_task_dir(tmp_path)
    record = _make_file(task_dir, "sess-a.111.session.stats.jsonl")

    code, _probe = _invoke(tmp_path, {"sess-a": _stopped()}, ["--dry-run"])

    assert code == 0
    assert "sess-a" in capsys.readouterr().out
    assert record.exists()


def test_verbose_lists_each_record_with_its_verdict(tmp_path, capsys):
    """``--verbose`` adds one line per owner record."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-a.111.session.stats.jsonl")
    _make_file(task_dir, "sess-a.111.session.stdout", age=_FRESH_AGE)

    code, _probe = _invoke(tmp_path, {"sess-a": _stopped()}, ["--verbose"])

    assert code == 0
    out = capsys.readouterr().out
    assert "sess-a.111.session.stats.jsonl" in out
    assert "sess-a.111.session.stdout" in out
    assert "yes" in out
    assert "no" in out


def test_zero_retention_disables_reclaim(tmp_path, capsys, monkeypatch):
    """A non-positive retention disables both production paths."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-a.111.session.stats.jsonl")
    monkeypatch.setenv("TOPSAILAI_SESSION_META_RETENTION_DAYS", "0")

    code, _probe = _invoke(tmp_path, {"sess-a": _stopped()}, ["--json"])

    assert code == 0
    receipt = _receipt(capsys)
    assert receipt["delivery_state"] == "nothing_to_inspect"
    assert receipt["response"]["sessions"] == []
    assert "Retention is disabled" in receipt["message"]


def test_retention_days_override_is_reported(tmp_path, capsys, monkeypatch):
    """The configured retention is echoed and applied to the verdict."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-a.111.session.stats.jsonl", age=2 * 86400)
    monkeypatch.setenv("TOPSAILAI_SESSION_META_RETENTION_DAYS", "1")

    code, _probe = _invoke(tmp_path, {"sess-a": _stopped()}, ["--json"])

    assert code == 0
    receipt = _receipt(capsys)
    assert receipt["response"]["retention_days"] == 1
    assert _by_session(receipt)["sess-a"]["decision"] == "reclaimable"


def test_metadata_count_limit_marks_excess_metadata(tmp_path, capsys, monkeypatch):
    """Metadata beyond the configured count is reclaimable oldest first."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-a.111.session.meta", age=_FRESH_AGE)
    _make_file(task_dir, "sess-a.222.session.meta", age=_FRESH_AGE)
    monkeypatch.setenv("TOPSAILAI_SESSION_META_MAX_COUNT", "1")

    code, _probe = _invoke(tmp_path, {"sess-a": _stopped()}, ["--json"])

    assert code == 0
    receipt = _receipt(capsys)
    assert receipt["response"]["meta_max_count"] == 1
    session = _by_session(receipt)["sess-a"]
    assert session["decision"] == "reclaimable"
    assert session["reason"] == "metadata beyond the retention count"


def test_missing_task_directory_reports_nothing_to_inspect(tmp_path, capsys):
    """A home that never ran an agent owns no record."""
    code, _probe = _invoke(tmp_path, {}, ["--json"])

    assert code == 0
    receipt = _receipt(capsys)
    assert receipt["delivery_state"] == "nothing_to_inspect"
    assert receipt["response"]["session_count"] == 0


def test_unreadable_task_directory_fails_the_inspection(tmp_path, capsys, monkeypatch):
    """An unreadable directory is a failure, not an empty inventory.

    The permission is injected instead of set with ``chmod``, because the test
    process may run as root, where a mode of ``0o000`` still permits listing and
    the failure would never be exercised.
    """
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-a.111.session.stats.jsonl")

    def _deny(_path):
        raise PermissionError(13, "Permission denied", str(task_dir))

    monkeypatch.setattr(
        "cli_topsailai.workspace_reclaim_cli.os.listdir", _deny,
    )

    code, _probe = _invoke(tmp_path, {"sess-a": _stopped()}, ["--json"])

    assert code == 1
    receipt = _receipt(capsys)
    assert receipt["ok"] is False
    assert receipt["error_code"] == "inspection_failed"


def test_conflicting_session_selectors_are_a_usage_error(tmp_path, capsys):
    """Two different ``-s`` values are rejected instead of silently merged."""
    _make_task_dir(tmp_path)

    code, _probe = _invoke(tmp_path, {}, ["-s", "a", "-s", "b", "--json"])

    assert code == 2
    receipt = _receipt(capsys)
    assert receipt["error_code"] == "usage_error"


def test_empty_session_selector_is_a_usage_error(tmp_path, capsys):
    """An empty selector must never be read as "select everything"."""
    _make_task_dir(tmp_path)

    code, _probe = _invoke(tmp_path, {}, ["-s", " , ", "--json"])

    assert code == 2
    receipt = _receipt(capsys)
    assert receipt["error_code"] == "usage_error"


def test_one_batch_observation_covers_every_session(tmp_path, capsys):
    """A directory with many sessions is inventoried once, not once per session."""
    task_dir = _make_task_dir(tmp_path)
    states = {}
    for index in range(12):
        session_id = f"sess-{index:02d}"
        _make_file(task_dir, f"{session_id}.{100 + index}.session.stats.jsonl")
        states[session_id] = _stopped()

    code, probe = _invoke(tmp_path, states, ["--json"])

    assert code == 0
    assert len(probe.calls) == 1
    assert len(probe.calls[0]) == 12
    assert _receipt(capsys)["response"]["session_count"] == 12


def test_non_owner_files_are_ignored(tmp_path, capsys):
    """A name the framework pattern rejects is not an owner record."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "notes.txt")
    _make_file(task_dir, "sess-a.111.session.unknown_suffix")
    _make_file(task_dir, "sess-a.111.session.stats.jsonl")

    code, _probe = _invoke(tmp_path, {"sess-a": _stopped()}, ["--json"])

    assert code == 0
    receipt = _receipt(capsys)
    assert receipt["response"]["session_count"] == 1
    assert _by_session(receipt)["sess-a"]["record_count"] == 1


def test_rotation_backup_is_reported_as_an_owner_record(tmp_path, capsys):
    """A rotated ``stats.N.jsonl`` backup is inventoried like its primary."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-a.111.session.stats.1.jsonl")

    code, _probe = _invoke(tmp_path, {"sess-a": _stopped()}, ["--json"])

    assert code == 0
    session = _by_session(_receipt(capsys))["sess-a"]
    assert session["record_count"] == 1
    assert session["decision"] == "reclaimable"


def test_reclaimable_sessions_sort_before_blocked_ones(tmp_path, capsys):
    """The table puts actionable sessions first."""
    task_dir = _make_task_dir(tmp_path)
    _make_file(task_dir, "sess-z.111.session.stats.jsonl")
    _make_file(task_dir, "sess-a.222.session.stats.jsonl")

    states = {
        "sess-z": _stopped(),
        "sess-a": ActivityObservation(ActivityState.RUNNING, "live associated owner"),
    }
    code, _probe = _invoke(tmp_path, states, ["--json"])

    assert code == 0
    order = [item["session_id"] for item in _receipt(capsys)["response"]["sessions"]]
    assert order == ["sess-z", "sess-a"]


def test_help_is_rendered_without_inspecting(tmp_path, capsys):
    """``--help`` documents the read-only contract and exits successfully."""
    _make_task_dir(tmp_path)

    code, probe = _invoke(tmp_path, {}, ["--help"])

    assert code == 0
    out = capsys.readouterr().out
    assert "never deletes" in out
    assert "--dry-run" in out
    assert probe.calls == []
