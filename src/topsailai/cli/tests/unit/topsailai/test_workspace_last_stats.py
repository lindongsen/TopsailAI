"""Verify the workspace JSON item publishes the last per-agent stats record.

Author: DawsonLin

``{session_id}.{pid}.session.stats.jsonl`` is an append-only log of cumulative
snapshots, so only its last complete line describes the current state. These
tests pin the reader's boundaries and the item's contract: the record is the
row's own, it is ``null`` rather than an empty object when absent, and the
table renderer never pays for it.
"""

import json
from unittest.mock import Mock

import pytest

from cli_topsailai import core, formatting, log_files, session_driver, session_info
from cli_topsailai.process_liveness import ProcessState
from cli_topsailai.session_stats import read_last_stats_record, row_last_stats


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    """Keep liveness, driver, cache and workspace lookup state isolated."""
    monkeypatch.setattr(formatting, "pid_state", Mock(return_value=ProcessState.ALIVE))
    monkeypatch.setattr(formatting, "is_session_pipe_open", Mock(return_value=False))
    monkeypatch.setattr(session_driver, "observe_driver", Mock(return_value=None))
    monkeypatch.setattr(session_info, "_SESSION_INFO_CACHE", session_info._SessionInfoCache())
    monkeypatch.setattr(session_info, "_SESSION_RECORD_CACHE", {})
    monkeypatch.setattr(session_info, "load_project_workspace_lookup", Mock(return_value={}))


def stats_record(session_id, pid, *, attempt_seq=1, prompt_tokens=100,
                 total_requests=1, retained_calls=1, role="worker"):
    """Build one version-1 record shaped like the writer's own output."""
    return {
        "schema_version": 1,
        "record_id": f"{session_id}:{pid}:{attempt_seq}",
        "session_id": session_id,
        "pid": pid,
        "attempt_seq": attempt_seq,
        "outcome": "success",
        "agent_role": role,
        "token_stat": {"total_prompt_tokens": prompt_tokens},
        "llm_request_stat": {"total_requests": total_requests},
        "tool_stat": {"retained_calls": retained_calls},
    }


def write_stats(directory, session_id, pid, records, *, backup=None):
    """Append the given records as complete lines to one stats file.

    ``backup`` selects a rotation backup, whose name is
    ``{stem}.{index}.jsonl`` rather than a suffix appended after ``.jsonl``.
    """
    stem = f"{session_id}.{pid}.session.stats"
    name = f"{stem}.jsonl" if backup is None else f"{stem}.{backup}.jsonl"
    path = directory / name
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


def build_rows(tmp_path, names, records):
    """Create a test-owned task directory and return enriched rows."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).touch()
    for (session_id, pid), record in records.items():
        (directory / f"{session_id}.{pid}.session.meta").write_text(
            json.dumps(dict(session_id=session_id, pid=pid) | record)
        )
    rows = log_files.discover_workspace_log_files(str(directory), include_completed=True)
    session_info.enrich_files_with_session_names(rows)
    formatting.enrich_workspace_rows(rows, str(tmp_path))
    return rows


def test_reader_returns_the_last_complete_record(tmp_path):
    """Cumulative snapshots mean the last line is the current state."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    write_stats(directory, "sample", 123, [
        stats_record("sample", 123, attempt_seq=1, prompt_tokens=100),
        stats_record("sample", 123, attempt_seq=2, prompt_tokens=250),
        stats_record("sample", 123, attempt_seq=3, prompt_tokens=400),
    ])

    record = read_last_stats_record(directory, "sample", 123)

    assert record["attempt_seq"] == 3
    assert record["token_stat"]["total_prompt_tokens"] == 400


def test_reader_ignores_an_incomplete_final_line(tmp_path):
    """A mid-append fragment is not a record, so the previous line wins."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    path = write_stats(directory, "sample", 123, [
        stats_record("sample", 123, attempt_seq=1, prompt_tokens=100),
        stats_record("sample", 123, attempt_seq=2, prompt_tokens=250),
    ])
    with path.open("a") as stream:
        stream.write('{"schema_version": 1, "session_id": "sample", "pid": 12')

    record = read_last_stats_record(directory, "sample", 123)

    assert record["attempt_seq"] == 2


def test_reader_falls_back_to_a_rotation_backup(tmp_path):
    """A just-rotated active file is empty, so the newest record is a backup."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    (directory / "sample.123.session.stats.jsonl").write_text("")
    write_stats(directory, "sample", 123, [
        stats_record("sample", 123, attempt_seq=7, prompt_tokens=900),
    ], backup=1)

    record = read_last_stats_record(directory, "sample", 123)

    assert record["attempt_seq"] == 7


def test_reader_rejects_a_record_written_by_another_process(tmp_path):
    """A record naming another PID is not this row's evidence."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    write_stats(directory, "sample", 123, [stats_record("sample", 999)])

    assert read_last_stats_record(directory, "sample", 123) is None


def test_reader_reports_none_for_an_absent_file(tmp_path):
    """No file means no record, not an empty record."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)

    assert read_last_stats_record(directory, "sample", 123) is None


def test_reader_reports_none_for_an_unsupported_schema(tmp_path):
    """A record from another schema version is not published as current."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    record = stats_record("sample", 123)
    record["schema_version"] = 2
    write_stats(directory, "sample", 123, [record])

    assert read_last_stats_record(directory, "sample", 123) is None


def test_reader_reads_a_bounded_tail_not_the_whole_file(tmp_path, monkeypatch):
    """The read must not grow with the file, so it seeks from the end."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    write_stats(directory, "sample", 123, [
        stats_record("sample", 123, attempt_seq=index, prompt_tokens=index)
        for index in range(1, 200)
    ])
    reads = []

    import cli_topsailai.session_stats as module

    real_open = module.Path.open

    def tracking_open(self, *args, **kwargs):
        stream = real_open(self, *args, **kwargs)
        original_read = stream.read

        def tracking_read(size=-1):
            reads.append(size)
            return original_read(size)

        stream.read = tracking_read
        return stream

    monkeypatch.setattr(module.Path, "open", tracking_open)

    record = read_last_stats_record(directory, "sample", 123)

    assert record["attempt_seq"] == 199
    # Every read is bounded by the fixed window, never by the file size.
    assert reads and all(0 < size <= 2 * 4096 for size in reads)


def test_item_publishes_the_rows_own_record(tmp_path):
    """A worker row carries the worker's counters, not the manager's."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    write_stats(directory, "sample", 123, [
        stats_record("sample", 123, prompt_tokens=5000, role="manager"),
    ])
    write_stats(directory, "sample", 456, [
        stats_record("sample", 456, prompt_tokens=70, role="worker"),
    ])
    rows = build_rows(tmp_path, ["sample.123.session.stdout",
                                 "sample.456.task.stdout"], {})

    items = {row["pid"]: core._workspace_json_item(row, index)
             for index, row in enumerate(rows, start=1)}

    assert items[123]["last_stats"]["agent_role"] == "manager"
    assert items[123]["last_stats"]["token_stat"]["total_prompt_tokens"] == 5000
    assert items[456]["last_stats"]["agent_role"] == "worker"
    assert items[456]["last_stats"]["token_stat"]["total_prompt_tokens"] == 70


def test_item_reports_null_when_no_record_exists(tmp_path):
    """The key is always present, so the schema never changes shape."""
    rows = build_rows(tmp_path, ["sample.123.session.stdout"], {})

    item = core._workspace_json_item(rows[0], 1)

    assert "last_stats" in item
    assert item["last_stats"] is None


def test_item_does_not_borrow_a_parent_record_for_a_task_row(tmp_path):
    """A worker without its own file must not publish the manager's numbers."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    write_stats(directory, "sample", 123, [
        stats_record("sample", 123, prompt_tokens=5000, role="manager"),
    ])
    rows = build_rows(tmp_path, ["sample.123.session.stdout",
                                 "sample.456.task.stdout"], {})

    task_row = next(row for row in rows if row["is_task"])

    assert core._workspace_json_item(task_row, 1)["last_stats"] is None


def test_row_last_stats_requires_filename_ownership(tmp_path):
    """A row whose filename does not carry its PID has no record of its own."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    write_stats(directory, "sample", 123, [stats_record("sample", 123)])

    assert row_last_stats({
        "session_id": "sample", "pid": 123, "is_task": False,
        "filename": "sample.999.session.stdout",
        "path": str(directory / "sample.999.session.stdout"),
    }) is None


def test_table_renderer_never_reads_the_stats_file(tmp_path, monkeypatch):
    """The table does not publish the record, so it must not pay for it."""
    import cli_topsailai.session_stats as module

    calls = []
    monkeypatch.setattr(
        module, "read_last_stats_record",
        lambda *args, **kwargs: calls.append(args) or None,
    )
    rows = build_rows(tmp_path, ["sample.123.session.stdout"], {})

    formatting.print_table(rows)

    assert calls == []


def test_reader_failure_keeps_the_document(tmp_path, monkeypatch):
    """A stats read that raises must cost the field, never the document."""
    import cli_topsailai.session_stats as module

    monkeypatch.setattr(
        module, "read_last_stats_record",
        Mock(side_effect=RuntimeError("stats exploded")),
    )
    rows = build_rows(tmp_path, ["sample.123.session.stdout"], {})

    item = core._workspace_json_item(rows[0], 1)

    assert item["last_stats"] is None
    assert item["session_id"] == "sample"


def test_missing_identity_mapper_keeps_the_document(tmp_path, monkeypatch):
    """An unimportable identity mapper must degrade to null, not raise."""
    import builtins

    import cli_topsailai.session_stats as module

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "cli_topsailai.workspace_runtime":
            raise ImportError("module unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    write_stats(directory, "sample", 123, [stats_record("sample", 123)])

    assert module.read_last_stats_record(directory, "sample", 123) is None
