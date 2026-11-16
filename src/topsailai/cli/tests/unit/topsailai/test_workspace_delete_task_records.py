"""Tests for the ``workspace delete-task-records`` reclaim command.

The command previews by default and deletes only with ``--yes``. A task record
carries ``session_messages``, so a content-bearing record is kept unless the
operator opts in, and a truncated record is refused even though it no longer
parses, because the raw bytes still hold conversation text.

Every fixture builds an isolated ``{home}/workspace/task`` layout and passes it
through ``home_resolver``, so no test can reach the real agent home.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from cli_topsailai import workspace_delete_task_records_cli as cli

#: Age comfortably beyond the default 7-day retention window.
OLD_AGE_SECONDS = 30 * 24 * 60 * 60


@pytest.fixture
def home(tmp_path):
    """Create an isolated home whose task folder exists."""
    (tmp_path / "workspace" / "task").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def task_dir(home):
    """Return the isolated task folder."""
    return home / "workspace" / "task"


def _run(home, argv, **kwargs):
    """Run the command against *home* with an empty held-open set."""
    kwargs.setdefault("open_paths", lambda: set())
    return cli.run_workspace_delete_task_records_cli(
        argv, home_resolver=lambda: str(home), **kwargs
    )


def _receipt(capsys):
    """Parse the single JSON receipt the command wrote to stdout."""
    return json.loads(capsys.readouterr().out)


def _by_name(receipt):
    """Index record rows by filename."""
    return {row["filename"]: row for row in receipt["response"]["records"]}


def _age(path: Path, seconds: float = OLD_AGE_SECONDS) -> Path:
    """Backdate *path* by *seconds*."""
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))
    return path


def _task(task_dir: Path, name: str, *, messages=None, content="", age=OLD_AGE_SECONDS):
    """Write a task record and backdate it."""
    payload = {
        "create_time": "2026-01-01T00:00:00",
        "session_id": "wa-test",
        "session_messages": messages if messages is not None else [],
        "task_content": content,
        "task_id": name,
    }
    path = task_dir / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return _age(path, age)


def _pidfile(task_dir: Path, name: str, pid: int, *, age=OLD_AGE_SECONDS):
    """Write a driver pidfile and backdate it."""
    path = task_dir / name
    path.write_text(str(pid), encoding="utf-8")
    return _age(path, age)


# --------------------------------------------------------------------------
# Task records
# --------------------------------------------------------------------------


def test_zero_byte_task_is_reclaimable(home, task_dir, capsys):
    """A truly empty file holds nothing and is reclaimable."""
    path = task_dir / "zero.task"
    path.write_text("", encoding="utf-8")
    _age(path)

    assert _run(home, ["--json"]) == 0
    row = _by_name(_receipt(capsys))["zero.task"]

    assert row["deletable"] is True
    assert row["reason"] == "empty file, holds no content"


def test_parsed_task_without_messages_is_reclaimable(home, task_dir, capsys):
    """A record that parses but carries no message is reclaimable."""
    _task(task_dir, "blank.task")

    assert _run(home, ["--json"]) == 0
    row = _by_name(_receipt(capsys))["blank.task"]

    assert row["deletable"] is True
    assert row["reason"] == "parsed but holds no content"


def test_content_bearing_task_is_kept_without_opt_in(home, task_dir, capsys):
    """A record holding conversation messages is kept by default."""
    _task(task_dir, "chatty.task", messages=[{"role": "user", "content": "hi"}])

    assert _run(home, ["--json"]) == 0
    row = _by_name(_receipt(capsys))["chatty.task"]

    assert row["deletable"] is False
    assert "pass --allow-content" in row["reason"]
    assert row["message_count"] == 1


def test_content_bearing_task_is_removed_and_archived_when_opted_in(home, task_dir):
    """Opting in removes the record only after an archive copy exists."""
    _task(task_dir, "chatty.task", messages=[{"role": "user", "content": "hi"}])

    assert _run(home, ["--yes", "--allow-content"]) == 0

    assert not (task_dir / "chatty.task").exists()
    archived = task_dir / cli.DEFAULT_ARCHIVE_DIRNAME / "chatty.task"
    assert archived.is_file()
    assert json.loads(archived.read_text(encoding="utf-8"))["session_messages"]


def test_truncated_task_is_refused(home, task_dir, capsys):
    """A truncated record no longer parses but still holds conversation text."""
    path = task_dir / "cut.task"
    path.write_text(
        '{"session_messages": [{"role": "user", "content": "real words',
        encoding="utf-8",
    )
    _age(path)

    assert _run(home, ["--json"]) == 0
    row = _by_name(_receipt(capsys))["cut.task"]

    assert row["deletable"] is False
    assert "truncated or corrupt" in row["reason"]


def test_truncated_task_is_refused_even_when_content_is_allowed(home, task_dir):
    """``--allow-content`` must not override the truncation refusal."""
    path = task_dir / "cut.task"
    path.write_text('{"session_messages": [{"content": "real words', encoding="utf-8")
    _age(path)

    assert _run(home, ["--yes", "--allow-content"]) == 0

    assert path.exists()


def test_young_task_is_kept(home, task_dir, capsys):
    """A record inside the retention window is kept."""
    _task(task_dir, "fresh.task", age=60)

    assert _run(home, ["--json"]) == 0
    row = _by_name(_receipt(capsys))["fresh.task"]

    assert row["deletable"] is False
    assert "within the retention window" in row["reason"]


def test_held_open_task_is_kept(home, task_dir, capsys):
    """A record held open by a live process is kept."""
    path = _task(task_dir, "busy.task")

    assert _run(home, ["--json"], open_paths=lambda: {str(path)}) == 0
    row = _by_name(_receipt(capsys))["busy.task"]

    assert row["deletable"] is False
    assert row["reason"] == "held open by a live process"


def test_unreadable_process_table_fails_closed(home, task_dir, capsys):
    """An unanswerable process table must not authorize a deletion."""
    _task(task_dir, "empty.task")

    assert _run(home, ["--json"], open_paths=lambda: None) == 0
    row = _by_name(_receipt(capsys))["empty.task"]

    assert row["deletable"] is False
    assert "process table is unreadable" in row["reason"]


# --------------------------------------------------------------------------
# Driver pidfiles
# --------------------------------------------------------------------------


def test_dead_pidfile_is_reclaimable(home, task_dir, capsys):
    """A pidfile whose recorded process is gone is reclaimable."""
    _pidfile(task_dir, "gone.driver.pid", 999999)

    assert _run(home, ["--json"]) == 0
    row = _by_name(_receipt(capsys))["gone.driver.pid"]

    assert row["deletable"] is True
    assert "is gone" in row["reason"]


def test_live_pidfile_is_kept(home, task_dir, capsys):
    """A pidfile naming a live process is kept."""
    _pidfile(task_dir, "alive.driver.pid", os.getpid())

    assert _run(home, ["--json"]) == 0
    row = _by_name(_receipt(capsys))["alive.driver.pid"]

    assert row["deletable"] is False
    assert "is still alive" in row["reason"]


def test_unreadable_pidfile_has_no_owner_to_protect(home, task_dir, capsys):
    """A pidfile with no readable pid protects nothing."""
    path = task_dir / "junk.driver.pid"
    path.write_text("not-a-pid", encoding="utf-8")
    _age(path)

    assert _run(home, ["--json"]) == 0
    row = _by_name(_receipt(capsys))["junk.driver.pid"]

    assert row["deletable"] is True
    assert row["reason"] == "unreadable pid, no owner to protect"


# --------------------------------------------------------------------------
# Deletion mechanics
# --------------------------------------------------------------------------


def test_dry_run_deletes_nothing(home, task_dir):
    """The default run is a preview and must not touch the filesystem."""
    path = _task(task_dir, "empty.task")

    assert _run(home, []) == 0

    assert path.exists()


def test_explicit_dry_run_wins_over_yes(home, task_dir):
    """An explicit ``--dry-run`` must not be overridden by ``--yes``."""
    path = _task(task_dir, "empty.task")

    assert _run(home, ["--yes", "--dry-run"]) == 0

    assert path.exists()


def test_deletion_is_logged(home, task_dir, capsys):
    """Every removal prints a ``DELETED:`` line."""
    path = _task(task_dir, "empty.task")

    assert _run(home, ["--yes"]) == 0

    captured = capsys.readouterr()
    assert f"DELETED: {path}" in captured.err
    assert "Removed 1 record(s)" in captured.out


def test_changed_identity_skips_deletion(home, task_dir, monkeypatch):
    """A record that changed after inspection must not be removed."""
    path = _task(task_dir, "empty.task")
    calls = {"count": 0}

    def fake_identity(target):
        calls["count"] += 1
        return (1, 2, 3, 4, calls["count"])

    monkeypatch.setattr(cli, "_file_identity", fake_identity)

    assert _run(home, ["--yes"]) == 1

    assert path.exists()


def test_removal_failure_is_reported(home, task_dir, monkeypatch):
    """A failing unlink reports a non-zero exit instead of claiming success."""
    _task(task_dir, "empty.task")

    def failing_unlink(target):
        raise OSError("disk is read-only")

    monkeypatch.setattr(cli.os, "unlink", failing_unlink)

    assert _run(home, ["--yes"]) == 1


def test_missing_task_folder_is_reported(tmp_path):
    """A missing task folder is an inspection failure, not a crash."""
    assert _run(tmp_path, []) == cli._INSPECTION_FAILED


def test_negative_min_age_is_a_usage_error(home):
    """A negative retention window is rejected."""
    assert _run(home, ["--min-age-days", "-1"]) == cli._USAGE_ERROR


def test_kind_filter_selects_one_record_family(home, task_dir, capsys):
    """``--kind`` restricts the inventory to one record family."""
    _task(task_dir, "empty.task")
    _pidfile(task_dir, "gone.driver.pid", 999999)

    assert _run(home, ["--json", "--kind", "pidfile"]) == 0
    names = set(_by_name(_receipt(capsys)))

    assert names == {"gone.driver.pid"}


def test_symlink_is_ignored(home, task_dir, capsys):
    """A symlink is never treated as a record."""
    target = _task(task_dir, "real.task")
    (task_dir / "link.task").symlink_to(target)

    assert _run(home, ["--json"]) == 0
    names = set(_by_name(_receipt(capsys)))

    assert "link.task" not in names


# --------------------------------------------------------------------------
# Receipt contract
# --------------------------------------------------------------------------


def test_json_receipt_keeps_stdout_machine_readable(home, task_dir, capsys):
    """JSON mode emits one receipt on stdout and human text on stderr."""
    _task(task_dir, "empty.task")

    assert _run(home, ["--json"]) == 0

    captured = capsys.readouterr()
    receipt = json.loads(captured.out)
    assert receipt["action"] == "delete-task-records"
    assert receipt["ok"] is True
    assert receipt["delivery_state"] == "inspected"
    assert receipt["response"]["record_count"] == 1
    assert receipt["response"]["reclaimable_record_count"] == 1
    assert captured.err == ""


def test_json_receipt_reports_applied_state(home, task_dir, capsys):
    """A real deletion reports ``applied`` and the removed count."""
    _task(task_dir, "empty.task")

    assert _run(home, ["--yes", "--json"]) == 0

    receipt = json.loads(capsys.readouterr().out)
    assert receipt["delivery_state"] == "applied"
    assert receipt["response"]["applied"] is True
    assert "Removed 1 record(s)" in receipt["message"]
