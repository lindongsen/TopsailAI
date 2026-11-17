"""Verify the workspace JSON item exposes the metadata file and lookup record.

Author: DawsonLin
"""

import json
from unittest.mock import Mock

import pytest

from cli_topsailai import core, formatting, log_files, session_driver, session_info
from cli_topsailai.process_liveness import ProcessState


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    """Keep liveness, driver, cache and workspace lookup state isolated."""
    monkeypatch.setattr(formatting, "pid_state", Mock(return_value=ProcessState.ALIVE))
    monkeypatch.setattr(formatting, "is_session_pipe_open", Mock(return_value=False))
    monkeypatch.setattr(session_driver, "observe_driver", Mock(return_value=None))
    monkeypatch.setattr(session_info, "_SESSION_INFO_CACHE", session_info._SessionInfoCache())
    monkeypatch.setattr(session_info, "_SESSION_RECORD_CACHE", {})
    monkeypatch.setattr(session_info, "load_project_workspace_lookup", Mock(return_value={}))


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


def test_item_exposes_the_complete_metafile_record(tmp_path):
    """The full stored record reaches the consumer, not only name and workspace."""
    record = {
        "status": "running",
        "session_name": "Detailed Session",
        "hostname": "origin-host",
        "project_workspace": "/work/project",
        "pwd": "/work/project",
        "category": "agent",
        "agent_name": "TopsailAI",
        "agent_type": "AgentReAct",
        "agent_role": "manager",
        "model_name": "example-model",
        "start_ts": "2026-11-17T13:21:48.244830",
        "end_ts": None,
        "task_id": "",
        "files": {"stdout": "sample.123.session.stdout"},
        "feature_flags": {"TOPSAILAI_INPUT_PIPE_ENABLED": True},
    }
    rows = build_rows(tmp_path, ["sample.123.session.stdout"], {("sample", 123): record})

    item = core._workspace_json_item(rows[0], 1)

    assert item["metafile"] == dict(session_id="sample", pid=123) | record
    # The projected fields keep their own resolution and are not replaced by
    # the raw record, so existing consumers see no behavior change.
    assert item["session_name"] == "Detailed Session"
    assert item["project_workspace"] == "/work/project"
    assert item["hostname"] == "origin-host"


def test_item_reports_null_when_the_metafile_is_absent(tmp_path):
    """A row without a usable record reports null, never an empty object."""
    rows = build_rows(tmp_path, ["sample.123.session.stdout"], {})

    item = core._workspace_json_item(rows[0], 1)

    assert "metafile" in item
    assert item["metafile"] is None


def test_item_reports_null_when_the_metafile_is_not_an_object(tmp_path):
    """A non-object record is unusable evidence, so it is not forwarded."""
    rows = build_rows(tmp_path, ["sample.123.session.stdout"], {})
    rows[0]["_workspace_session_meta_data"] = ["not", "an", "object"]

    assert core._workspace_json_item(rows[0], 1)["metafile"] is None


def test_task_and_session_rows_share_the_item_schema(tmp_path):
    """Both row kinds carry the key, so the schema never changes shape."""
    record = {"status": "running", "session_name": "Parent Session",
              "hostname": "origin-host", "project_workspace": "/work/project"}
    rows = build_rows(
        tmp_path,
        ["sample.123.session.stdout", "sample.456.child.task.stdout"],
        {("sample", 123): record},
    )
    task = next(row for row in rows if row["is_task"])
    session = next(row for row in rows if not row["is_task"])

    task_item = core._workspace_json_item(task, 1)
    session_item = core._workspace_json_item(session, 2)

    assert set(task_item) == set(session_item)
    assert task_item["metafile"] == session_item["metafile"]


def test_metafile_grants_no_signal_authority(tmp_path):
    """Exposing the record must not turn a stored PID into kill authority."""
    record = {"status": "running", "session_name": "Exited Session",
              "hostname": "origin-host", "project_workspace": "/work/project"}
    rows = build_rows(tmp_path, ["sample.123.session.stdout"], {("sample", 123): record})
    formatting.pid_state.return_value = ProcessState.DEAD
    formatting.enrich_workspace_rows(rows, str(tmp_path))

    item = core._workspace_json_item(rows[0], 1)

    assert item["metafile"]["pid"] == 123
    assert item["process_generation"] is None


def test_metafile_costs_no_extra_lookup(tmp_path, monkeypatch):
    """The value comes from the enrichment that already ran, not a new query."""
    query = Mock(return_value={})
    monkeypatch.setattr(session_info, "_get_sessions_info", query)
    record = {"status": "running", "session_name": "Detailed Session",
              "hostname": "origin-host", "project_workspace": "/work/project"}
    rows = build_rows(tmp_path, ["sample.123.session.stdout"], {("sample", 123): record})
    calls_after_enrichment = query.call_count

    core._workspace_json_item(rows[0], 1)

    assert query.call_count == calls_after_enrichment


def test_lookup_record_fields_are_merged_into_the_item_body(tmp_path):
    """The lookup record is flattened into the body instead of being nested."""
    rows = build_rows(tmp_path, ["sample.123.session.stdout"], {})
    rows[0]["_workspace_session_record"] = {
        "session_id": "sample",
        "session_name": "Lookup Session",
        "project_workspace": "/work/project",
        "status": "Running",
        "task": "investigate the failure",
        "is_running": True,
        "total_prompt_tokens": 1234,
        "tool_call_count": 7,
        "topsailai_home": "/root/.topsailai",
    }

    item = core._workspace_json_item(rows[0], 1)

    assert item["task"] == "investigate the failure"
    assert item["is_running"] is True
    assert item["total_prompt_tokens"] == 1234
    assert item["tool_call_count"] == 7
    assert item["topsailai_home"] == "/root/.topsailai"
    # The record is flattened, so no nested copy is left behind.
    assert "record" not in item


def test_lookup_status_is_exposed_as_status_raw_without_overwriting_status(tmp_path):
    """The coarser lookup status never replaces the finer-grained body value."""
    rows = build_rows(tmp_path, ["sample.123.session.stdout"], {})
    rows[0]["workspace_status"] = "input"
    rows[0]["_workspace_session_record"] = {"status": "Running"}

    item = core._workspace_json_item(rows[0], 1)

    assert item["status"] == "input"
    assert item["status_raw"] == "Running"


def test_body_values_win_over_colliding_lookup_fields(tmp_path):
    """A colliding key keeps the body value, so no existing field changes."""
    rows = build_rows(tmp_path, ["sample.123.session.stdout"], {})
    rows[0]["session_name"] = "Body Session"
    rows[0]["project_workspace"] = "/work/body"
    rows[0]["_workspace_session_record"] = {
        "session_id": "sample",
        "session_name": "Lookup Session",
        "project_workspace": "/work/lookup",
    }

    item = core._workspace_json_item(rows[0], 1)

    assert item["session_name"] == "Body Session"
    assert item["project_workspace"] == "/work/body"


def test_lookup_fields_are_absent_when_the_lookup_failed(tmp_path):
    """A failed lookup leaves the fields absent rather than reporting null."""
    rows = build_rows(tmp_path, ["sample.123.session.stdout"], {})

    item = core._workspace_json_item(rows[0], 1)

    assert "task" not in item
    assert "status_raw" not in item
    assert "total_prompt_tokens" not in item
    # The metadata file is a separate source, so it keeps its own null contract.
    assert "metafile" in item


def test_merged_fields_come_from_the_real_enrichment_path(tmp_path):
    """The cache populated by the lookup is what reaches the item body."""
    session_info._SESSION_RECORD_CACHE["sample"] = {
        "session_id": "sample",
        "session_name": "Cached Session",
        "status": "Idle",
        "task": "cached task",
        "turn_total_count": 3,
    }
    rows = build_rows(tmp_path, ["sample.123.session.stdout"], {})

    item = core._workspace_json_item(rows[0], 1)

    assert item["task"] == "cached task"
    assert item["turn_total_count"] == 3
    assert item["status_raw"] == "Idle"
