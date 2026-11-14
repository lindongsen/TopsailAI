"""R08 workspace validation and late-race evidence."""

from __future__ import annotations

import json
import os
import pathlib
import pwd
import subprocess
import sys
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from cli_topsailai import project_scope

SESSION = "r08-session"


def _record(workspace: pathlib.Path | str, **extra: object) -> dict[str, object]:
    """Build an authoritative persisted-session record."""
    record: dict[str, object] = {"session_id": SESSION, "project_workspace": str(workspace)}
    record.update(extra)
    return record


def _resume(record: dict[str, object], **kwargs: object) -> int:
    """Invoke the real persisted-session resume boundary."""
    with patch.object(project_scope, "session_liveness", return_value="idle"):
        return project_scope.resume_session_result(
            SESSION, query=lambda _sid: [record], emit_status=False,
            driver="topsailai_agent_plan_tasks", **kwargs,
        )


def _owned_fixture_root() -> pathlib.Path:
    """Create a unique fixture root directly under the workspace .tmp directory."""
    workspace = pathlib.Path(__file__).parents[3].resolve()
    tmp_root = workspace / ".tmp"
    tmp_root.mkdir(exist_ok=True)
    while True:
        candidate = tmp_root / f"c1-r08-{uuid.uuid4().hex}"
        try:
            candidate.mkdir(mode=0o755)
            assert candidate.stat().st_uid == os.geteuid()
            return candidate
        except FileExistsError:
            continue
        except BaseException:
            if candidate.exists():
                _cleanup_owned_root(candidate)
            raise


@contextmanager
def _owned_fixture():
    """Own and clean a fixture for its complete initialization and test lifetime."""
    fixture_root = None
    try:
        fixture_root = _owned_fixture_root()
        _verify_read_only_traversability(fixture_root)
        yield fixture_root
    finally:
        if fixture_root is not None and fixture_root.exists():
            _cleanup_owned_root(fixture_root)


def _verify_read_only_traversability(fixture_root: pathlib.Path) -> None:
    """Verify ancestor search permission without changing any ancestor mode."""
    current = fixture_root.resolve()
    while True:
        mode = current.stat().st_mode & 0o777
        assert mode & 0o001, (
            f"fixture ancestor is not traversable by de-privileged users: "
            f"{current} mode={mode:o}; refusing permission mutation"
        )
        if current == pathlib.Path(current.anchor):
            return
        current = current.parent


def _assert_owned(path: pathlib.Path, fixture_root: pathlib.Path) -> pathlib.Path:
    """Verify an operation target is an owned descendant of the fixture root."""
    target = path.resolve()
    root = fixture_root.resolve()
    assert target == root or root in target.parents
    assert root.stat().st_uid == os.geteuid()
    assert target.stat().st_uid in {os.geteuid(), pwd.getpwnam("nobody").pw_uid}
    return target


def _owned_chmod(path: pathlib.Path, mode: int, fixture_root: pathlib.Path) -> None:
    """Change permissions only inside this test-owned fixture root."""
    _assert_owned(path, fixture_root)
    path.chmod(mode)


def _owned_chown(path: pathlib.Path, uid: int, gid: int, fixture_root: pathlib.Path) -> None:
    """Change ownership only on an existing fixture-root descendant."""
    _assert_owned(path, fixture_root)
    os.chown(path, uid, gid)


def _log_delete(path: pathlib.Path) -> None:
    """Record an intentional test-owned deletion."""
    print(f"[C1 cleanup] deleting {path}")


def _cleanup_owned_root(fixture_root: pathlib.Path) -> None:
    """Delete only the exclusively owned fixture tree with per-path logging."""
    root = fixture_root.resolve()
    expected_parent = pathlib.Path(__file__).parents[3].resolve() / ".tmp"
    assert root.parent == expected_parent.resolve()
    assert root.exists() and root.stat().st_uid == os.geteuid()
    for entry in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        _log_delete(entry)
        if entry.is_dir():
            entry.rmdir()
        else:
            entry.unlink()
    _log_delete(root)
    root.rmdir()


def _configure_selected_model(home: pathlib.Path, workspace: pathlib.Path) -> None:
    """Install an isolated selected model whose environment visibly changes."""
    home.mkdir(parents=True, exist_ok=True)
    (home / ".models.jsonl").write_text(
        json.dumps({"id": "r08", "name": "R08", "provider": "test",
                    "protocol": "openai-compatible", "model": "r08-model",
                    "environment": {"R08_MODEL_MARKER": "selected"}}) + "\n",
        encoding="utf-8",
    )
    (home / ".model_selection.json").write_text(
        json.dumps({"workspace": None, "projects": {str(workspace.resolve()): "r08"}}),
        encoding="utf-8",
    )

def test_missing_workspace_field_fails_closed(tmp_path):
    """A persisted record without a workspace has no caller-cwd fallback."""
    before_cwd, before_env = os.getcwd(), os.environ.copy()
    submitted: list[object] = []
    result = _resume({"session_id": SESSION}, background=True,
                     spawn=lambda *args, **kwargs: submitted.append(args))
    assert result == 4
    assert submitted == []
    assert os.getcwd() == before_cwd
    assert os.environ.copy() == before_env


@pytest.mark.parametrize("kind", ["missing", "file", "relative"])
def test_missing_file_and_relative_workspace_fail_before_submission(tmp_path, kind):
    """Missing, regular-file and relative paths are rejected without creation."""
    if kind == "missing":
        workspace = tmp_path / "missing"
    elif kind == "file":
        workspace = tmp_path / "workspace-file"
        workspace.write_text("not a directory", encoding="utf-8")
    else:
        workspace = pathlib.Path("r08-relative-workspace")
    submitted: list[object] = []
    result = _resume(_record(workspace), background=True,
                     spawn=lambda *args, **kwargs: submitted.append(args))
    assert result == 4
    assert submitted == []
    if kind == "missing":
        assert not workspace.exists()


def test_inaccessible_ancestor_fails_closed():
    """A lower-privileged resume cannot bypass an inaccessible owned ancestor."""
    if os.geteuid() != 0:
        pytest.fail("R08 requires root to drop the controlled child to nobody; environment cannot satisfy this case")
    with _owned_fixture() as fixture_root:
        ancestor = fixture_root / "private-parent"
        workspace = ancestor / "workspace"
        ancestor.mkdir()
        workspace.mkdir()
        nobody = pwd.getpwnam("nobody")
        _owned_chown(workspace, nobody.pw_uid, nobody.pw_gid, fixture_root)
        _owned_chmod(ancestor, 0o700, fixture_root)
        result = _run_unprivileged_resume(workspace, fixture_root)
        assert result.returncode == 0, result.stderr
        assert '"status": 4' in result.stdout
        assert '"submitted": 0' in result.stdout


@pytest.mark.parametrize(
    ("background", "agent_mode"),
    [(False, "raw"), (True, "raw"), (True, "tmux"), (True, "dtach")],
)
def test_disappearance_matrix_is_rejected_by_late_check(
    tmp_path, background, agent_mode, monkeypatch
):
    """Every supported resume mode rejects removal after real preparation."""
    workspace = tmp_path / f"workspace-{agent_mode}-{background}"
    workspace.mkdir()
    submitted: list[object] = []
    helper_calls: list[object] = []
    home = tmp_path / "home"
    _configure_selected_model(home, workspace)
    monkeypatch.setenv("TOPSAILAI_HOME", str(home))
    before_cwd, before_env = os.getcwd(), os.environ.copy()
    assert "R08_MODEL_MARKER" not in os.environ
    model_observed = []
    original_project_prepare = project_scope._apply_selected_model_environment

    def prepare_then_remove(folder: str):
        """Run real model preparation, then remove the prepared directory."""
        result = original_project_prepare(folder)
        model_observed.append(os.environ.get("R08_MODEL_MARKER"))
        _log_delete(workspace)
        workspace.rmdir()
        return result

    with patch.object(project_scope, "_apply_selected_model_environment", side_effect=prepare_then_remove):
        if background:
            import cli_topsailai.agent_launch as agent_module
            import cli_topsailai.agent_launch_background as background_module
            import cli_topsailai.agent_launch_terminal as terminal_module
            monkeypatch.setattr(agent_module, "_apply_selected_model_environment", prepare_then_remove)
            def record_background(*args, **kwargs):
                helper_calls.append((args, kwargs))
                return {"outcome": "submitted", "launcher_pid": 1, "log_path": "owned.log"}
            monkeypatch.setattr(background_module, "launch_background", record_background)
            monkeypatch.setattr(terminal_module, "resolve_mechanism", lambda mode: mode)
            def record_terminal(*args, **kwargs):
                helper_calls.append((args, kwargs))
                return {"outcome": "submitted", "launcher_pid": 1, "log_path": "owned.log"}
            monkeypatch.setattr(terminal_module, "submit_terminal", record_terminal)
        result = _resume(_record(workspace), background=background,
                         agent_mode=agent_mode, spawn=lambda *a, **k: submitted.append(a))
    assert result == 4
    assert submitted == []
    assert len(helper_calls) == 0
    assert model_observed == ["selected"]
    assert not workspace.exists()
    assert os.getcwd() == before_cwd
    assert os.environ.copy() == before_env
    assert "R08_MODEL_MARKER" not in os.environ


def test_disappearance_counterfactual_without_late_check_would_submit(tmp_path):
    """The same real mutation reaches spawn when late revalidation is disabled."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    submitted: list[object] = []
    original_prepare = project_scope._apply_selected_model_environment

    def prepare_then_remove(folder: str):
        """Remove the real prepared directory before the spawn boundary."""
        result = original_prepare(folder)
        _log_delete(workspace)
        workspace.rmdir()
        return result

    def capture_spawn(*args, **kwargs):
        """Record the unsafe counterfactual submission."""
        submitted.append((args, kwargs))

        class Child:
            """Minimal child for the counterfactual only."""
            def wait(self):
                """Return a completed status."""
                return 0

        return Child()

    with patch.object(project_scope, "_apply_selected_model_environment", side_effect=prepare_then_remove):
        result = project_scope.launch_agent_driver(
            str(workspace), "topsailai_agent_plan_tasks", SESSION,
            agent_mode="raw", spawn=capture_spawn, emit_status=False,
            prelaunch_check=None,
        )
    assert result == 0
    assert submitted
    assert not workspace.exists()


@pytest.mark.parametrize("mode", ["raw", "dtach"])
def test_real_child_cwd_failure_returns_five(tmp_path, mode):
    """A real Popen cwd failure after late validation maps to status five."""
    workspace = tmp_path / f"workspace-{mode}"
    workspace.mkdir()
    submitted: list[object] = []

    def remove_then_spawn(argv, **kwargs):
        """Remove the validated directory before the OS cwd operation."""
        _log_delete(workspace)
        workspace.rmdir()
        submitted.append((argv, kwargs))
        return subprocess.Popen(argv, **kwargs)

    result = _resume(_record(workspace), background=False, agent_mode=mode,
                     spawn=remove_then_spawn)
    assert result == 5
    assert submitted
    assert not workspace.exists()


def test_real_child_cwd_eacces_is_observed():
    """A nobody child receives real EACCES from Popen cwd establishment."""
    if os.geteuid() != 0:
        pytest.fail("R08 requires root to drop the controlled child to nobody; environment cannot satisfy this case")
    with _owned_fixture() as fixture_root:
        workspace = fixture_root / "workspace"
        workspace.mkdir(mode=0o700)
        script = """
import errno, os, subprocess, sys
os.setgroups([])
os.setgid(65534)
os.setuid(65534)
try:
    subprocess.Popen([sys.executable, '-c', 'pass'], cwd=sys.argv[1])
except OSError as error:
    print(error.errno)
    raise SystemExit(0 if error.errno == errno.EACCES else 2)
raise SystemExit(3)
"""
        result = subprocess.run([sys.executable, "-c", script, str(workspace)],
                                cwd=str(fixture_root), capture_output=True, text=True,
                                check=False, env={"PATH": os.environ["PATH"]})
    assert result.returncode == 0
    assert result.stdout.strip() == "13"
def _run_unprivileged_resume(
    workspace: pathlib.Path, fixture_root: pathlib.Path, *, cwd_eacces: bool = False
):
    """Run the real resume path as nobody with an owned fixture root."""
    nobody = pwd.getpwnam("nobody")
    cli_root = pathlib.Path(__file__).parents[3]
    source_root = pathlib.Path(__file__).parents[5]
    home = fixture_root / "home"
    task_dir = home / "workspace" / "task"
    task_dir.mkdir(parents=True, mode=0o755)
    _configure_selected_model(home, workspace)
    for path in (home, home / "workspace", task_dir):
        _owned_chown(path, nobody.pw_uid, nobody.pw_gid, fixture_root)
        _owned_chmod(path, 0o755, fixture_root)
    script = r'''
import json, os, pathlib, subprocess, sys
from cli_topsailai import project_scope
from cli_topsailai.project_scope import _apply_selected_model_environment
workspace = sys.argv[1]
fixture_root = pathlib.Path(sys.argv[2]).resolve()
target = pathlib.Path(workspace).resolve()
assert target == fixture_root or fixture_root in target.parents
record = {"session_id": "r08-session", "project_workspace": workspace}
submitted = []
before_cwd = os.getcwd()
before_environment = os.environ.copy()
def revoke(folder):
    result = _apply_selected_model_environment(folder)
    changed_model = os.environ.get("R08_MODEL_MARKER") == "selected"
    target = pathlib.Path(folder).resolve()
    assert target == fixture_root or fixture_root in target.parents
    if not os.environ.get("R08_CWD_EACCES"):
        assert target.stat().st_uid == os.getuid()
        os.chmod(target, 0o000)
        try:
            os.listdir(target)
        except PermissionError as error:
            print(json.dumps({"denied_errno": error.errno, "denied_type": type(error).__name__,
                              "model_changed": changed_model}))
    return result
def spawn(argv, **kwargs):
    target = pathlib.Path(workspace).resolve()
    assert target == fixture_root or fixture_root in target.parents
    if os.environ.get("R08_CWD_EACCES"):
        assert target.stat().st_uid == os.getuid()
        os.chmod(target, 0o000)
    submitted.append((argv, kwargs))
    return subprocess.Popen(argv, **kwargs)
project_scope.session_liveness = lambda *a, **k: "idle"
project_scope._apply_selected_model_environment = revoke
result = project_scope.resume_session_result(
    "r08-session", query=lambda _sid: [record], emit_status=False,
    driver="topsailai_agent_plan_tasks", spawn=spawn,
)
print(json.dumps({"uid": os.getuid(), "euid": os.geteuid(), "gid": os.getgid(),
                  "groups": os.getgroups(), "status": result, "submitted": len(submitted),
                  "cwd_restored": os.getcwd() == before_cwd,
                  "environment_restored": os.environ.copy() == before_environment,
                  "model_restored": "R08_MODEL_MARKER" not in os.environ}))
'''
    environment = os.environ.copy()
    environment["TOPSAILAI_HOME"] = str(home)
    environment["PYTHONPATH"] = os.pathsep.join((str(cli_root), str(source_root)))
    if cwd_eacces:
        environment["R08_CWD_EACCES"] = "1"
    return subprocess.run(
        [sys.executable, "-c", script, str(workspace), str(fixture_root)],
        cwd=str(cli_root), env=environment, capture_output=True, text=True,
        check=False,
        preexec_fn=lambda: (os.setgroups([]), os.setgid(nobody.pw_gid),
                            os.setuid(nobody.pw_uid)),
    )


def test_real_unprivileged_cwd_eacces_uses_resume_boundary():
    """A late cwd permission loss maps through production resume to status five."""
    if os.geteuid() != 0:
        pytest.fail("R08 requires root to drop the controlled child to nobody; environment cannot satisfy this case")
    with _owned_fixture() as fixture_root:
        workspace = fixture_root / "workspace"
        workspace.mkdir(mode=0o755)
        nobody = pwd.getpwnam("nobody")
        _owned_chown(workspace, nobody.pw_uid, nobody.pw_gid, fixture_root)
        result = _run_unprivileged_resume(workspace, fixture_root, cwd_eacces=True)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["uid"] == nobody.pw_uid
        assert payload["euid"] == nobody.pw_uid
        assert payload["gid"] == nobody.pw_gid
        assert payload["groups"] == []
        assert payload["status"] == 5
        assert payload["submitted"] == 1
        assert payload["cwd_restored"] is True
        assert payload["environment_restored"] is True
        assert payload["model_restored"] is True


def test_real_unprivileged_permission_loss_is_eacces():
    """A nobody child loses real access after real preparation and fails closed."""
    if os.geteuid() != 0:
        pytest.fail(
            "R08 requires root to drop the controlled child to nobody; "
            "environment cannot satisfy this case"
        )
    with _owned_fixture() as fixture_root:
        workspace = fixture_root / "workspace"
        workspace.mkdir(mode=0o755)
        nobody = pwd.getpwnam("nobody")
        _owned_chown(workspace, nobody.pw_uid, nobody.pw_gid, fixture_root)
        result = _run_unprivileged_resume(workspace, fixture_root)
        assert result.returncode == 0, result.stderr
        lines = result.stdout.strip().splitlines()
        payload = json.loads(lines[-1])
        assert payload["uid"] == nobody.pw_uid
        assert payload["euid"] == nobody.pw_uid
        assert payload["gid"] == nobody.pw_gid
        assert payload["groups"] == []
        assert payload["status"] == 4
        assert payload["submitted"] == 0
        assert payload["cwd_restored"] is True
        assert payload["environment_restored"] is True
        assert payload["model_restored"] is True
        denied = [json.loads(line) for line in lines[:-1] if line.startswith("{")]
        assert denied
        assert denied[-1]["denied_errno"] == 13
        assert denied[-1]["denied_type"] == "PermissionError"
        assert denied[-1]["model_changed"] is True
