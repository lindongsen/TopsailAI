"""Verify the ``workspace list --local`` hostname filter.

Author: DawsonLin
"""

import json
from argparse import Namespace
from unittest.mock import Mock

import pytest

from cli_topsailai import core, paths
from cli_topsailai.workspace_hostname import filter_workspace_rows_by_hostname


def row(hostname, sid="sample"):
    """Build an enriched row carrying only the field the filter reads."""
    return {"session_id": sid, "pid": 1, "hostname": hostname}


def test_local_hostname_is_kept():
    """A row produced on this host must survive the filter."""
    rows = [row("host-a")]

    assert filter_workspace_rows_by_hostname(rows, "host-a") == rows


def test_foreign_hostname_is_dropped():
    """A row produced on another host must be removed."""
    rows = [row("host-b")]

    assert filter_workspace_rows_by_hostname(rows, "host-a") == []


def test_empty_hostname_is_kept():
    """An unknown origin must be kept so a local session is never hidden."""
    rows = [row("")]

    assert filter_workspace_rows_by_hostname(rows, "host-a") == rows


@pytest.mark.parametrize("value", [None, 42, ["host-a"], {"host": "host-a"}])
def test_non_string_hostname_is_kept(value):
    """A non-string value is an unresolved origin, not a foreign host."""
    rows = [row(value)]

    assert filter_workspace_rows_by_hostname(rows, "host-a") == rows


def test_missing_hostname_key_is_kept():
    """A row without the key has no resolved origin and must be kept."""
    rows = [{"session_id": "sample", "pid": 1}]

    assert filter_workspace_rows_by_hostname(rows, "host-a") == rows


def test_comparison_is_case_sensitive():
    """A hostname is an OS identifier, so case must not be normalized."""
    rows = [row("HOST-A")]

    assert filter_workspace_rows_by_hostname(rows, "host-a") == []


def test_original_order_is_preserved():
    """Retained rows must keep their discovery order."""
    rows = [row("host-a", "one"), row("host-b", "two"), row("", "three"),
            row("host-a", "four")]

    kept = filter_workspace_rows_by_hostname(rows, "host-a")

    assert [item["session_id"] for item in kept] == ["one", "three", "four"]


@pytest.mark.parametrize("local_hostname", [None, 42, ["host-a"]])
def test_non_string_local_hostname_disables_the_filter(local_hostname):
    """An unusable local hostname must not silently drop every row."""
    rows = [row("host-a"), row("host-b")]

    assert filter_workspace_rows_by_hostname(rows, local_hostname) == rows


def test_input_rows_are_not_mutated():
    """The filter must return rows without altering the caller's list."""
    rows = [row("host-a"), row("host-b")]

    filter_workspace_rows_by_hostname(rows, "host-a")

    assert len(rows) == 2


@pytest.fixture
def task_dir(tmp_path):
    """Create two local sessions and one session from another host."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    records = (("alpha", 111, "host-a"), ("beta", 222, "host-b"),
               ("gamma", 333, ""))
    for session_id, pid, hostname in records:
        (directory / f"{session_id}.{pid}.session.stdout").touch()
        (directory / f"{session_id}.{pid}.session.meta").write_text(json.dumps({
            "session_id": session_id, "pid": pid, "status": "running",
            "session_name": f"{session_id} name", "hostname": hostname,
            "project_workspace": f"/work/{session_id}",
        }))
    return directory


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point the one-shot printers at the isolated task directory."""
    monkeypatch.setattr(paths, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(core, "_driver_authority", Mock(return_value=None))
    monkeypatch.setattr(core.socket, "gethostname", lambda: "host-a")
    return tmp_path


def test_json_keeps_local_and_unknown_rows(task_dir, capsys):
    """The JSON document must describe the filtered subset only."""
    core._print_workspace_json(local_only=True)

    payload = json.loads(capsys.readouterr().out)

    assert {item["session_id"] for item in payload["items"]} == {"alpha", "gamma"}
    assert payload["total"] == len(payload["items"]) == 2


def test_json_without_the_flag_keeps_every_row(task_dir, capsys):
    """The default must remain unfiltered so shared folders stay visible."""
    core._print_workspace_json()

    payload = json.loads(capsys.readouterr().out)

    assert payload["total"] == 3


def test_table_keeps_local_and_unknown_rows(task_dir, capsys):
    """The table must render the same filtered subset as the JSON document."""
    core._print_workspace_table(local_only=True)

    out = capsys.readouterr().out

    assert "alpha name" in out
    assert "gamma name" in out
    assert "beta name" not in out
    assert "(Total: 2)" in out


def test_table_warns_with_the_host_when_nothing_matches(tmp_path, monkeypatch, capsys):
    """A directory holding only foreign rows must name the host, not claim empty."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    (directory / "beta.222.session.stdout").touch()
    (directory / "beta.222.session.meta").write_text(json.dumps({
        "session_id": "beta", "pid": 222, "status": "running",
        "session_name": "beta name", "hostname": "host-b",
        "project_workspace": "/work/beta",
    }))
    monkeypatch.setattr(paths, "get_topsailai_home", lambda: str(tmp_path))

    core._print_workspace_table(local_only=True)

    out = capsys.readouterr().out

    assert "No log files found for this host: host-a" in out
    assert "No .stdout log files found in:" not in out


def test_handler_forwards_the_flag_to_the_table(monkeypatch):
    """The non-interactive handler must pass ``--local`` to the table."""
    table = Mock()
    monkeypatch.setattr(core, "_print_workspace_table", table)

    code = core._handle_workspace_subcommand(
        Namespace(workspace_command="list", format=None, local=True),
    )

    assert code == 0
    table.assert_called_once_with(
        include_completed=False, session_ids=None, local_only=True,
    )


def test_handler_forwards_the_flag_to_json(monkeypatch):
    """The JSON path must receive the same flag."""
    printer = Mock()
    monkeypatch.setattr(core, "_print_workspace_json", printer)

    code = core._handle_workspace_subcommand(
        Namespace(workspace_command="list", format=None, json=True, local=True),
    )

    assert code == 0
    printer.assert_called_once_with(
        include_completed=False, session_ids=None, local_only=True,
    )


def test_handler_defaults_to_no_filter_without_the_attribute(monkeypatch):
    """The deprecated ``-w`` path passes no ``local`` attribute and must not filter."""
    table = Mock()
    monkeypatch.setattr(core, "_print_workspace_table", table)

    core._handle_workspace_subcommand(Namespace(workspace_command="list", format=None))

    table.assert_called_once_with(
        include_completed=False, session_ids=None, local_only=False,
    )


def test_cli_registers_the_option(monkeypatch):
    """``--local`` must reach the handler through the real parser."""
    table = Mock()
    monkeypatch.setattr(core, "_print_workspace_table", table)

    with pytest.raises(SystemExit) as raised:
        core.main(["workspace", "list", "--local"])

    assert raised.value.code == 0
    table.assert_called_once_with(
        include_completed=False, session_ids=None, local_only=True,
    )


def test_cli_composes_local_with_all_and_session(monkeypatch):
    """``--local`` must compose with ``-a`` and ``-s`` instead of overriding them."""
    table = Mock()
    monkeypatch.setattr(core, "_print_workspace_table", table)

    with pytest.raises(SystemExit):
        core.main(["workspace", "-a", "list", "--local", "-s", "alpha"])

    table.assert_called_once_with(
        include_completed=True, session_ids=["alpha"], local_only=True,
    )
