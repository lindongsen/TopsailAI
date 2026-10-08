"""Tests for root-BDD owned temporary-directory management."""

import os
import subprocess
from pathlib import Path

import pytest

from tests.bdd.temp_storage import (
    BDD_TEMP_ROOT,
    WORKSPACE,
    BDDTempCleanupError,
    BDDTempStorage,
)
from topsailai.utils.env_tool import resolve_python_interpreter


def test_default_root_is_workspace_tmp_bdd() -> None:
    """The default storage root is the fixed BDD folder below workspace .tmp."""
    assert BDD_TEMP_ROOT == WORKSPACE / ".tmp" / "bdd"
    assert BDD_TEMP_ROOT == Path(__file__).resolve().parents[2] / ".tmp" / "bdd"


def test_created_directory_stays_below_explicit_workspace_root(tmp_path: Path) -> None:
    """Creation always passes the configured workspace root to tempfile."""
    root = tmp_path / ".tmp" / "bdd"
    storage = BDDTempStorage(root)

    directory = storage.create_directory("scenario-")

    assert directory.parent == root.resolve()
    storage.cleanup()
    assert not directory.exists()


def test_root_creation_failure_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unavailable workspace root fails rather than using the system temp root."""
    attempted: list[Path] = []

    def reject_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        attempted.append(self)
        raise PermissionError("workspace temp root unavailable")

    monkeypatch.setattr(Path, "mkdir", reject_mkdir)

    with pytest.raises(PermissionError, match="workspace temp root unavailable"):
        BDDTempStorage(tmp_path / ".tmp" / "bdd")

    assert attempted == [(tmp_path / ".tmp" / "bdd").resolve()]


def test_cleanup_removes_only_owned_directories(tmp_path: Path) -> None:
    """Cleanup leaves sibling files and directories not created by the storage intact."""
    root = tmp_path / ".tmp" / "bdd"
    storage = BDDTempStorage(root)
    owned = storage.create_directory("owned-")
    unrelated = root / "unrelated"
    unrelated.mkdir()
    marker = unrelated / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    storage.cleanup()

    assert not owned.exists()
    assert marker.read_text(encoding="utf-8") == "keep"


def test_missing_owned_root_is_treated_as_already_cleaned(tmp_path: Path) -> None:
    """A missing-path error is successful only when the owned root is absent."""
    storage = BDDTempStorage(tmp_path / ".tmp" / "bdd")
    owned = storage.create_directory("owned-")
    owned.rmdir()

    def report_missing(_path: Path) -> None:
        raise FileNotFoundError("owned root disappeared")

    storage.cleanup(report_missing)
    storage.cleanup(report_missing)


def test_nested_missing_path_retains_existing_owned_root(tmp_path: Path) -> None:
    """A child-path failure does not discard ownership of an existing root."""
    storage = BDDTempStorage(tmp_path / ".tmp" / "bdd")
    owned = storage.create_directory("owned-")
    marker = owned / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    def report_nested_missing(_path: Path) -> None:
        raise FileNotFoundError("nested entry disappeared")

    with pytest.raises(BDDTempCleanupError) as raised:
        storage.cleanup(report_nested_missing)

    assert raised.value.failures[0][0] == owned
    assert marker.exists()
    storage.cleanup()
    assert not owned.exists()


def test_cleanup_continues_and_retries_only_retained_failure(tmp_path: Path) -> None:
    """A failed root is retained while successfully removed roots are forgotten."""
    storage = BDDTempStorage(tmp_path / ".tmp" / "bdd")
    removable = storage.create_directory("removable-")
    blocked = storage.create_directory("blocked-")
    attempts: list[Path] = []

    def remove_tree(path: Path) -> None:
        attempts.append(path)
        if path == blocked:
            raise OSError("injected cleanup failure")
        path.rmdir()

    with pytest.raises(BDDTempCleanupError) as raised:
        storage.cleanup(remove_tree)

    assert attempts == [blocked, removable]
    assert raised.value.failures[0][0] == blocked
    assert blocked.exists()
    assert not removable.exists()

    attempts.clear()
    storage.cleanup(lambda path: (attempts.append(path), path.rmdir())[-1])
    assert attempts == [blocked]


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(3)])
def test_cleanup_propagates_host_interrupts(
    tmp_path: Path, interrupt: BaseException
) -> None:
    """Cleanup never converts a host interruption into an aggregate failure."""
    storage = BDDTempStorage(tmp_path / ".tmp" / "bdd")
    owned = storage.create_directory("owned-")

    def interrupt_cleanup(_path: Path) -> None:
        raise interrupt

    with pytest.raises(type(interrupt)) as raised:
        storage.cleanup(interrupt_cleanup)

    assert raised.value is interrupt
    storage.cleanup()
    assert not owned.exists()


def _run_fixture_teardown_child(
    tmp_path: Path,
    close_error: bool,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run the real BDD fixture graph in an isolated pytest process."""
    child_root = tmp_path / ("close-error" if close_error else "normal")
    child_root.mkdir()
    evidence_path = child_root / "owned-path.txt"
    test_path = child_root / "test_fixture_teardown.py"
    test_path.write_text(
        """from pathlib import Path

class Scenario:
    def __init__(self, directory, evidence_path, close_error):
        self.directory = directory
        self.evidence_path = evidence_path
        self.close_error = close_error

    def close(self):
        assert self.directory.exists()
        self.evidence_path.write_text(str(self.directory), encoding="utf-8")
        if self.close_error:
            raise RuntimeError("injected close failure")


def test_real_fixture_teardown(team_values_prompt_ctx, bdd_tmp_path, request):
    evidence_path = Path(request.config.getoption("--lifecycle-evidence"))
    close_error = request.config.getoption("--scenario-close-error")
    team_values_prompt_ctx["scenario"] = Scenario(
        bdd_tmp_path, evidence_path, close_error
    )
    assert bdd_tmp_path.exists()
""",
        encoding="utf-8",
    )
    plugin_path = child_root / "lifecycle_plugin.py"
    plugin_path.write_text(
        """def pytest_addoption(parser):
    parser.addoption("--lifecycle-evidence")
    parser.addoption("--scenario-close-error", action="store_true")
""",
        encoding="utf-8",
    )
    command = [
        resolve_python_interpreter(),
        "-m",
        "pytest",
        "-q",
        "--color=no",
        "--tb=line",
        "-p",
        "tests.bdd.conftest",
        "-p",
        "tests.bdd.steps.team_values_prompt_steps",
        "-p",
        "lifecycle_plugin",
        f"--lifecycle-evidence={evidence_path}",
        f"--basetemp={child_root / 'basetemp'}",
        "-o",
        f"cache_dir={child_root / 'cache'}",
    ]
    if close_error:
        command.append("--scenario-close-error")
    command.append(str(test_path))
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["TMPDIR"] = str(child_root)
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(child_root), environment.get("PYTHONPATH", "")))
    )
    result = subprocess.run(
        command,
        cwd=WORKSPACE,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, evidence_path


def test_real_team_fixture_closes_before_storage_finalizer(tmp_path: Path) -> None:
    """Real pytest teardown closes the scenario before deleting its directory."""
    result, evidence_path = _run_fixture_teardown_child(tmp_path, close_error=False)

    assert result.returncode == 0, result.stdout + result.stderr
    owned_path = Path(evidence_path.read_text(encoding="utf-8"))
    assert not owned_path.exists()


def test_real_storage_finalizer_runs_after_visible_close_error(tmp_path: Path) -> None:
    """Real pytest reports the close error and still deletes owned storage."""
    result, evidence_path = _run_fixture_teardown_child(tmp_path, close_error=True)

    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "RuntimeError: injected close failure" in output
    owned_path = Path(evidence_path.read_text(encoding="utf-8"))
    assert not owned_path.exists()
