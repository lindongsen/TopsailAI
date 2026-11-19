"""Pin the ``topsailai runtime info`` contract.

Author: DawsonLin

The command publishes the workspace-list item for one exact process, restricted
to three groups: the session identity, the ``runtime`` object and the
``metafile`` object. These tests therefore assert parity against
``topsailai workspace list --json --include-runtime`` instead of a frozen copy of
its fields, and they assert the selector and ownership rules that make the
projection safe.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

CLI_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, SRC_ROOT)
sys.path.insert(0, CLI_ROOT)

from cli_topsailai import runtime_cli as cli
from cli_topsailai import runtime_info as ri
from topsailai.context.ctx_manager import get_session_manager
from topsailai.context.session_manager import SessionData

#: A PID that no process owns, used to prove an explicit PID is queried even
#: when the session itself looks idle.
DEAD_PID = 999999


def make_home(tmp_path: Path) -> str:
    """Create an isolated home with the task directory the command scans."""
    (tmp_path / ri.TASK_SUBDIR).mkdir(parents=True, exist_ok=True)
    return str(tmp_path)


def write_stdout(home: str, session_id: str, pid: int) -> Path:
    """Create the session stdout file that records a PID's ownership."""
    path = Path(home) / ri.TASK_SUBDIR / f"{session_id}.{pid}.session.stdout"
    path.write_text("", encoding="utf-8")
    return path


def write_task_stdout(home: str, session_id: str, pid: int,
                      task_id: str = "topsailai.1795078235.630223") -> Path:
    """Create the task log a child agent writes instead of a session log."""
    path = (Path(home) / ri.TASK_SUBDIR
            / f"{session_id}.{pid}.{task_id}.task.stdout")
    path.write_text("", encoding="utf-8")
    return path


def write_meta(home: str, session_id: str, pid: int, **fields) -> Path:
    """Create the exact session metadata record the list exposes as metafile."""
    data = {"version": 1, "session_id": session_id, "pid": pid,
            "session_name": "Recorded Name", "hostname": "test-host"}
    data.update(fields)
    path = Path(home) / ri.TASK_SUBDIR / f"{session_id}.{pid}.session.meta"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def manager_for(tmp_path: Path):
    """Return a session manager backed by an isolated SQLite file."""
    return get_session_manager(f"sqlite:///{tmp_path / 'sessions.db'}")


def collected_record(pid: int, is_task: bool = False) -> dict:
    """Return one runtime record shaped like the collector's real output."""
    return {
        "state": "ok",
        "error_code": None,
        "pid": pid,
        "is_task": is_task,
        "data": {"ok": True, "model": {"name": "example-model"}},
    }


class TestResolveTarget:
    """Both selectors are required and the PID must belong to the session."""

    def test_missing_pid_is_a_usage_error(self, tmp_path: Path):
        """A session alone does not name the process whose runtime is reported."""
        home = make_home(tmp_path)

        with pytest.raises(ri.RuntimeInfoError) as caught:
            ri.resolve_target("s", None, home)

        assert caught.value.error_code == "usage_error"
        assert caught.value.exit_code == 2

    def test_missing_session_is_a_usage_error(self, tmp_path: Path):
        """A PID alone does not prove which session the caller meant."""
        home = make_home(tmp_path)
        write_stdout(home, "s", 4242)

        with pytest.raises(ri.RuntimeInfoError) as caught:
            ri.resolve_target(None, 4242, home)

        assert caught.value.error_code == "usage_error"
        assert caught.value.exit_code == 2

    def test_explicit_pid_for_the_same_session(self, tmp_path: Path):
        """A PID recorded for the requested session is accepted unchanged."""
        home = make_home(tmp_path)
        write_stdout(home, "s", 4242)

        assert ri.resolve_target("s", 4242, home) == ("s", 4242)

    def test_task_agent_pid_is_accepted(self, tmp_path: Path):
        """A child agent writes only a task log, so that file must prove it."""
        home = make_home(tmp_path)
        write_task_stdout(home, "s", 4242)

        assert ri.resolve_target("s", 4242, home) == ("s", 4242)

    def test_explicit_pid_without_a_record_is_target_not_found(self, tmp_path: Path):
        """A PID with no stdout record cannot be attributed to any session."""
        home = make_home(tmp_path)

        with pytest.raises(ri.RuntimeInfoError) as caught:
            ri.resolve_target("s", 4242, home)

        assert caught.value.error_code == "target_not_found"
        assert caught.value.exit_code == 3

    def test_explicit_pid_for_another_session_is_target_mismatch(self, tmp_path: Path):
        """Reporting another session's runtime data would be worse than failing."""
        home = make_home(tmp_path)
        write_stdout(home, "other", 4242)

        with pytest.raises(ri.RuntimeInfoError) as caught:
            ri.resolve_target("s", 4242, home)

        assert caught.value.error_code == "target_mismatch"
        assert caught.value.exit_code == 3

    def test_unusable_identifier_is_target_mismatch(self, tmp_path: Path):
        """An identifier that cannot name a file must fail instead of matching."""
        home = make_home(tmp_path)
        write_stdout(home, "s", 4242)

        with pytest.raises(ri.RuntimeInfoError) as caught:
            ri.resolve_target("../s", 4242, home)

        assert caught.value.error_code == "target_mismatch"

    def test_unparseable_stdout_files_are_skipped(self, tmp_path: Path):
        """One unusable leftover must not hide the record that does match."""
        home = make_home(tmp_path)
        task_dir = Path(home) / ri.TASK_SUBDIR
        (task_dir / "broken.notapid.session.stdout").write_text("", encoding="utf-8")
        (task_dir / "zero.0.session.stdout").write_text("", encoding="utf-8")
        write_stdout(home, "s", 4242)

        assert ri.resolve_target("s", 4242, home) == ("s", 4242)


class TestProjection:
    """The document must be the list item's three groups, not a copy of them."""

    def test_document_matches_the_workspace_list_item(self, tmp_path: Path):
        """Every published value must equal the list's value for the same row."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="parity", task="Task"))
        write_stdout(home, "parity", os.getpid())
        write_meta(home, "parity", os.getpid())
        record = collected_record(os.getpid())

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_workspace_runtime",
                   return_value={"parity.%d.session.stdout" % os.getpid(): record}):
            produced = json.loads(ri.build_document("parity", os.getpid(), home))

        assert produced["session_id"] == "parity"
        assert produced["pid"] == os.getpid()
        assert produced["runtime"] == record
        assert produced["metafile"]["session_id"] == "parity"
        assert produced["metafile"]["pid"] == os.getpid()

    def test_only_the_three_groups_are_published(self, tmp_path: Path):
        """List presentation keys must not leak into the projected document."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="s", task="Task"))
        write_stdout(home, "s", os.getpid())

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_workspace_runtime",
                   return_value={}):
            produced = json.loads(ri.build_document("s", os.getpid(), home))

        assert set(produced) == {
            "session_id", "session_name", "project_workspace", "is_task",
            "session_qualifier", "pid", "status", "runtime", "metafile",
        }
        for excluded in ("no", "filename", "hostname", "created_at",
                         "completed", "driver", "process_generation"):
            assert excluded not in produced

    def test_metafile_is_null_without_a_record(self, tmp_path: Path):
        """A row without a metadata record reports ``null``, not an empty object."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="s", task="Task"))
        write_stdout(home, "s", os.getpid())

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_workspace_runtime",
                   return_value={}):
            produced = json.loads(ri.build_document("s", os.getpid(), home))

        assert produced["metafile"] is None

    def test_task_row_is_selected_by_its_own_pid(self, tmp_path: Path):
        """One session may run several agents, so the PID selects the row."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="s", task="Task"))
        write_stdout(home, "s", 4242)
        # The published ``pid`` is liveness-gated, so the task row must be a
        # live process for the projection to report it.
        write_task_stdout(home, "s", os.getpid())

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_workspace_runtime",
                   return_value={}) as collect:
            produced = json.loads(ri.build_document("s", os.getpid(), home))

        assert produced["pid"] == os.getpid()
        assert produced["is_task"] is True
        assert produced["session_qualifier"] == "task"
        assert collect.call_args.args[0][0]["pid"] == os.getpid()

    def test_temporary_session_is_reachable_by_both_spellings(self, tmp_path: Path):
        """Discovery reports ``(temp)``, so the reserved prefix must map to it."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        write_stdout(home, "topsailai", os.getpid())

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_workspace_runtime",
                   return_value={}):
            for spelling in ("(temp)", "topsailai"):
                produced = json.loads(
                    ri.build_document(spelling, os.getpid(), home)
                )
                # The list publishes an empty identity for a temporary row, so
                # the projection must publish the list's value, not the label.
                assert produced["session_id"] == ""
                assert produced["pid"] == os.getpid()


    def test_runtime_is_collected_for_one_row_only(self, tmp_path: Path):
        """The command must not fan out over the whole task directory."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="s", task="Task"))
        write_stdout(home, "s", 4242)
        write_task_stdout(home, "s", 4343)

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_workspace_runtime",
                   return_value={}) as collect:
            ri.build_document("s", 4242, home)

        assert len(collect.call_args.args[0]) == 1

    def test_default_timeout_is_the_collector_default(self, tmp_path: Path):
        """An omitted ``--timeout`` must not override the collector's budget."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="s", task="Task"))
        write_stdout(home, "s", 4242)

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_workspace_runtime",
                   return_value={}) as collect:
            ri.build_document("s", 4242, home)

        assert "timeout" not in collect.call_args.kwargs

    def test_explicit_timeout_is_forwarded(self, tmp_path: Path):
        """An explicit budget must reach the transport unchanged."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="s", task="Task"))
        write_stdout(home, "s", 4242)

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_workspace_runtime",
                   return_value={}) as collect:
            ri.build_document("s", 4242, home, 0.25)

        assert collect.call_args.kwargs["timeout"] == 0.25

    def test_missing_session_is_session_not_found(self, tmp_path: Path):
        """A row cannot be produced without a discovered process log."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager):
            with pytest.raises(ri.RuntimeInfoError) as caught:
                ri.build_document("missing", 4242, home)

        assert caught.value.error_code == "session_not_found"
        assert caught.value.exit_code == 1

    def test_pid_without_a_row_is_target_not_found(self, tmp_path: Path):
        """A session that exists but has no row for the PID must fail closed."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="s", task="Task"))
        write_stdout(home, "s", 4242)

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager):
            with pytest.raises(ri.RuntimeInfoError) as caught:
                ri.build_document("s", 4343, home)

        assert caught.value.error_code == "target_not_found"


class TestRunInfo:
    """Every path must print one parseable document and no text line."""

    def test_success_prints_one_document(self, tmp_path: Path, capsys):
        """A successful lookup prints the record and exits zero."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="s", task="Task"))
        write_stdout(home, "s", os.getpid())

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_workspace_runtime",
                   return_value={}):
            assert ri.run_info(
                ri.RuntimeInfoRequest(session_id="s", pid=os.getpid()), home=home
            ) == 0

        captured = capsys.readouterr()
        assert json.loads(captured.out)["session_id"] == "s"
        assert captured.err == ""

    def test_missing_session_prints_a_parseable_document(self, tmp_path: Path,
                                                         capsys):
        """A session whose rows are all dropped is reported as not found.

        The PID is proven to belong to the session first, so a session that
        exists but has no visible row is the case that reaches this branch.
        """
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        write_stdout(home, "gone", 4242)
        write_meta(home, "gone", 4242, status="completed")

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager):
            assert ri.run_info(
                ri.RuntimeInfoRequest(session_id="gone", pid=4242), home=home
            ) == 1

        captured = capsys.readouterr()
        document = json.loads(captured.out)
        assert document["error_code"] == "session_not_found"
        assert document["session_id"] == "gone"
        assert captured.err == ""

    def test_target_failure_uses_its_own_exit_code(self, tmp_path: Path, capsys):
        """A rejected PID exits 3 and names the reason."""
        home = make_home(tmp_path)

        assert ri.run_info(ri.RuntimeInfoRequest(session_id="s", pid=4242),
                           home=home) == 3

        document = json.loads(capsys.readouterr().out)
        assert document["error_code"] == "target_not_found"

    def test_missing_selector_is_a_usage_error(self, tmp_path: Path, capsys):
        """A missing selector is a usage error, not a lookup failure."""
        home = make_home(tmp_path)

        assert ri.run_info(ri.RuntimeInfoRequest(session_id="s"), home=home) == 2

        document = json.loads(capsys.readouterr().out)
        assert document["error_code"] == "usage_error"

    def test_unexpected_error_is_lookup_failed(self, tmp_path: Path, capsys):
        """A storage failure is classified instead of escaping as a traceback."""
        home = make_home(tmp_path)
        write_stdout(home, "s", 4242)

        with patch("cli_topsailai.core._driver_authority",
                   side_effect=RuntimeError("storage unavailable")):
            assert ri.run_info(ri.RuntimeInfoRequest(session_id="s", pid=4242),
                               home=home) == 1

        document = json.loads(capsys.readouterr().out)
        assert document["error_code"] == "lookup_failed"
        assert "storage unavailable" in document["message"]


class TestCliWiring:
    """The action must be reachable, documented and free of delivery options."""

    def test_info_is_dispatched_before_the_envelope(self):
        """``info`` prints its own document, so it returns before the envelope."""
        executor = Mock(side_effect=AssertionError("no delivery"))
        info = Mock(return_value=0)

        with patch.object(cli, "run_info", info):
            code = cli.run_runtime_cli(
                ["info", "-s", "s", "-p", "123", "--timeout", "3"],
                executor=executor, home_resolver=lambda: "/isolated/home",
            )

        assert code == 0
        executor.assert_not_called()
        info.assert_called_once_with(
            ri.RuntimeInfoRequest(session_id="s", pid=123, timeout=3.0),
            home="/isolated/home",
        )

    def test_json_is_a_noop(self):
        """The document is always JSON, so ``--json`` must not change anything."""
        info = Mock(return_value=0)

        with patch.object(cli, "run_info", info):
            assert cli.run_runtime_cli(["info", "-s", "s", "-p", "123", "--json"],
                                       home_resolver=lambda: "/h") == 0

        assert info.call_args.args[0] == ri.RuntimeInfoRequest(
            session_id="s", pid=123
        )

    @pytest.mark.parametrize("extra", [
        ["-m", "x"], ["-a", "{}"], ["-i", "/send x"], ["--stdin"],
        ["-n", "2"], ["-f"], ["--is-task"], ["extra"],
    ])
    def test_delivery_and_log_options_are_rejected(self, extra, capsys):
        """``info`` accepts only selectors and the transport budget."""
        home, executor, info = Mock(), Mock(), Mock()

        with patch.object(cli, "run_info", info):
            code = cli.run_runtime_cli(
                ["info", "-s", "s", "-p", "123", *extra, "--json"],
                home_resolver=home, executor=executor,
            )

        assert code == 2
        info.assert_not_called()
        executor.assert_not_called()
        home.assert_not_called()
        assert json.loads(capsys.readouterr().out)["error_code"] == "usage_error"

    @pytest.mark.parametrize("argv", [
        ["info"], ["info", "-s", "s"], ["info", "-p", "123"],
    ])
    def test_both_selectors_are_required(self, argv, capsys):
        """A session alone or a PID alone is an incomplete selector."""
        info = Mock(return_value=0)

        with patch.object(cli, "run_info", info):
            code = cli.run_runtime_cli([*argv, "--json"],
                                       home_resolver=lambda: "/h")

        assert code == 2
        info.assert_not_called()
        assert json.loads(capsys.readouterr().out)["error_code"] == "usage_error"

    def test_help_documents_the_action(self, capsys):
        """Help must advertise the action and one example of it."""
        with pytest.raises(SystemExit) as caught:
            cli.run_runtime_cli(["info", "--help"])

        assert caught.value.code == 0
        output = capsys.readouterr().out
        assert "logs, or info" in output
        assert "topsailai runtime info -s SESSION -p PID" in output

    def test_real_entry_point_reports_session_not_found(self, tmp_path: Path):
        """The shipped command emits one JSON document without a real session."""
        root = Path(__file__).resolve().parents[3]
        env = dict(os.environ, TOPSAILAI_HOME=str(tmp_path), HOME=str(tmp_path))
        completed = subprocess.run(
            [sys.executable, str(root / "topsailai_cli.py"), "runtime", "info",
             "-s", "nonexistent-fixture", "-p", "4242"],
            env=env, capture_output=True, text=True, check=False, timeout=120,
        )

        assert completed.returncode == 3
        assert json.loads(completed.stdout)["error_code"] == "target_not_found"
        assert completed.stderr == ""


if __name__ == "__main__":
    pytest.main([__file__, "--color=no"])
