'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-08-27
  Purpose: Unit tests for tests/run_tests.py child-process environment building
'''

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


RUNNER_PATH = Path(__file__).resolve().parents[1] / "run_tests.py"


def _load_runner():
    """Load tests/run_tests.py as a module without executing its main()."""
    spec = importlib.util.spec_from_file_location("topsailai_run_tests_under_test", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    """Return the loaded run_tests.py module for this test module."""
    return _load_runner()


class TestResolveSrcRoot:
    """Tests for source-root discovery used to build the child PYTHONPATH."""

    def test_default_src_root_contains_package(self, runner):
        """The resolved source root must contain the importable topsailai package."""
        assert (runner.SRC_ROOT / "topsailai" / "__init__.py").is_file()

    def test_src_root_is_not_hardcoded(self, runner):
        """Discovery must work for an arbitrary layout, not a fixed absolute path."""
        fake_root = runner.SRC_ROOT / "fake" / "layout"
        assert runner.resolve_src_root(fake_root, "topsailai") == runner.SRC_ROOT

    def test_fallback_when_package_missing(self, runner, tmp_path):
        """A layout without the package falls back to the parent of the start dir."""
        start = tmp_path / "pkg" / "tests"
        start.mkdir(parents=True)
        assert runner.resolve_src_root(start, "not_exist_pkg") == tmp_path / "pkg"


class TestBuildChildEnv:
    """Tests for build_child_env() PYTHONPATH construction."""

    def test_prepends_project_and_source_roots(self, runner):
        """Children import both the tests package and the project package deterministically."""
        env = runner.build_child_env({"PYTHONPATH": f"/foo{os.pathsep}/bar"})
        entries = env["PYTHONPATH"].split(os.pathsep)
        assert entries[:2] == [
            os.path.normpath(str(runner.PROJECT_ROOT)),
            os.path.normpath(str(runner.SRC_ROOT)),
        ]
        assert entries[2:] == ["/foo", "/bar"]

    def test_keeps_existing_pythonpath_entries(self, runner):
        """Inherited entries are preserved instead of being replaced or cleared."""
        env = runner.build_child_env(
            {"PYTHONPATH": os.pathsep.join(["/keep/first", "/keep/second"])}
        )
        assert "/keep/first" in env["PYTHONPATH"]
        assert "/keep/second" in env["PYTHONPATH"]

    def test_removes_duplicated_required_roots(self, runner):
        """Already present project and source roots are not duplicated."""
        source = str(runner.SRC_ROOT)
        project = str(runner.PROJECT_ROOT)
        env = runner.build_child_env(
            {"PYTHONPATH": os.pathsep.join(["/foo", source, project])}
        )
        assert env["PYTHONPATH"].split(os.pathsep) == [
            os.path.normpath(project),
            os.path.normpath(source),
            "/foo",
        ]

    def test_missing_pythonpath(self, runner):
        """An unset PYTHONPATH still yields both required import roots."""
        env = runner.build_child_env({})
        assert env["PYTHONPATH"].split(os.pathsep) == [
            os.path.normpath(str(runner.PROJECT_ROOT)),
            os.path.normpath(str(runner.SRC_ROOT)),
        ]

    def test_empty_pythonpath(self, runner):
        """An empty PYTHONPATH yields required roots without blank entries."""
        env = runner.build_child_env({"PYTHONPATH": ""})
        assert env["PYTHONPATH"].split(os.pathsep) == [
            os.path.normpath(str(runner.PROJECT_ROOT)),
            os.path.normpath(str(runner.SRC_ROOT)),
        ]

    def test_other_variables_preserved(self, runner):
        """Unrelated environment variables must survive untouched."""
        env = runner.build_child_env({"PATH": "/usr/bin", "TOPSAILAI_HOME": "/tmp/home"})
        assert env["PATH"] == "/usr/bin"
        assert env["TOPSAILAI_HOME"] == "/tmp/home"

    def test_base_env_not_mutated(self, runner):
        """The caller mapping must not be modified in place."""
        base = {"PYTHONPATH": "/foo"}
        runner.build_child_env(base)
        assert base == {"PYTHONPATH": "/foo"}

    def test_process_environment_not_mutated(self, runner):
        """Falling back to os.environ must not write PYTHONPATH back to it."""
        original = os.environ.pop("PYTHONPATH", None)
        try:
            env = runner.build_child_env()
            assert "PYTHONPATH" not in os.environ
            assert env["PYTHONPATH"].split(os.pathsep)[:2] == [
                os.path.normpath(str(runner.PROJECT_ROOT)),
                os.path.normpath(str(runner.SRC_ROOT)),
            ]
        finally:
            if original is not None:
                os.environ["PYTHONPATH"] = original

    def test_defaults_to_os_environ(self, runner):
        """Without a base mapping the current process environment is the baseline."""
        os.environ["TOPSAILAI_RUNNER_PROBE"] = "probe-value"
        try:
            env = runner.build_child_env()
            assert env["TOPSAILAI_RUNNER_PROBE"] == "probe-value"
        finally:
            os.environ.pop("TOPSAILAI_RUNNER_PROBE", None)

    def test_explicit_src_root_override(self, runner):
        """An explicit source root argument takes precedence over the resolved one."""
        env = runner.build_child_env({"PYTHONPATH": ""}, src_root="/custom/root")
        assert env["PYTHONPATH"].split(os.pathsep) == [
            os.path.normpath(str(runner.PROJECT_ROOT)),
            os.path.normpath("/custom/root"),
        ]

    def test_empty_src_root_keeps_project_root(self, runner):
        """An empty source override still keeps the tests package importable."""
        env = runner.build_child_env({"PYTHONPATH": "/foo"}, src_root="")
        assert env["PYTHONPATH"].split(os.pathsep) == [
            os.path.normpath(str(runner.PROJECT_ROOT)),
            "/foo",
        ]


class TestRunTestPassesEnv:
    """Tests that run_test() actually forwards the built environment."""

    def test_run_test_forwards_env(self, runner, monkeypatch):
        """The pytest subprocess must receive the environment with the source root."""
        captured = {}

        class FakeCompleted:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured.update(kwargs)
            return FakeCompleted()

        monkeypatch.setattr(runner.subprocess, "run", fake_run)
        status, details, _ = runner.run_test("test_topsailai_tests_run_tests.py", 5)

        assert status == "PASS"
        assert details == "All tests passed"
        env = captured["env"]
        assert env["PYTHONPATH"].split(os.pathsep)[:2] == [
            os.path.normpath(str(runner.PROJECT_ROOT)),
            os.path.normpath(str(runner.SRC_ROOT)),
        ]
        assert captured["cwd"] == runner.TEST_DIR

    def test_run_test_uses_isolated_workspace_basetemp(self, runner, monkeypatch, tmp_path):
        """Each file receives a distinct pytest basetemp below the workspace temp root."""
        captured = {}

        class FakeCompleted:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured.update(kwargs)
            return FakeCompleted()

        monkeypatch.setattr(runner, "RUN_TEMP_ROOT", tmp_path / "unit-runner")
        monkeypatch.setattr(runner.subprocess, "run", fake_run)
        status, _, _ = runner.run_test("nested/test_example.py", 5)

        assert status == "PASS"
        basetemp_arg = next(
            value for value in captured["cmd"] if value.startswith("--basetemp=")
        )
        basetemp = Path(basetemp_arg.split("=", 1)[1])
        assert basetemp.parent == runner.RUN_TEMP_ROOT
        assert runner.RUN_TEMP_ROOT.stat().st_mode & 0o777 == 0o755
        assert "-p" in captured["cmd"] and "no:cacheprovider" in captured["cmd"]


class TestMainExitCode:
    """Tests for main() result aggregation and process exit semantics."""

    @staticmethod
    def _run_main(runner, monkeypatch, tmp_path, results):
        """Run main() with controlled execution results and a temporary report."""
        args = SimpleNamespace(
            files=[],
            threshold=10.0,
            timeout=120,
            workers=1,
            retries=0,
            sequential=False,
            sequential_yes_do_it=False,
        )
        test_files = [result["file"] for result in results]
        monkeypatch.setattr(runner, "OUTPUT_FILE", tmp_path / "test_results.txt")
        monkeypatch.setattr(runner, "parse_args", lambda: args)
        monkeypatch.setattr(runner, "get_test_files", lambda selected=None: test_files)
        monkeypatch.setattr(
            runner,
            "execute_concurrently",
            lambda *unused_args, **unused_kwargs: results,
        )
        return runner.main()

    @staticmethod
    def _result(status, name="test_example.py"):
        """Build one controlled runner result."""
        return {
            "file": name,
            "status": status,
            "details": f"{status} details",
            "elapsed": 0.1,
        }

    def test_all_pass_returns_zero(self, runner, monkeypatch, tmp_path):
        """An all-PASS result set must return success."""
        result = self._run_main(
            runner, monkeypatch, tmp_path, [self._result("PASS")]
        )
        assert result == 0

    @pytest.mark.parametrize("status", ["FAIL", "TIMEOUT", "ERROR"])
    def test_non_pass_status_returns_nonzero(
        self, runner, monkeypatch, tmp_path, status
    ):
        """FAIL, TIMEOUT, and ERROR classifications must return failure."""
        result = self._run_main(
            runner, monkeypatch, tmp_path, [self._result(status)]
        )
        assert result == 1

    def test_zero_collected_files_returns_nonzero(
        self, runner, monkeypatch, tmp_path
    ):
        """An empty collection must not be reported as a successful run."""
        result = self._run_main(runner, monkeypatch, tmp_path, [])
        assert result == 1

    def test_complete_line_format_is_stable(
        self, runner, monkeypatch, tmp_path, capsys
    ):
        """The machine-consumed COMPLETE line must retain its exact format."""
        result = self._run_main(
            runner, monkeypatch, tmp_path, [self._result("PASS")]
        )
        assert result == 0
        assert "COMPLETE: Total=1, Passed=1, Failed=0" in capsys.readouterr().out.splitlines()

    def test_mixed_results_report_counts_and_return_nonzero(
        self, runner, monkeypatch, tmp_path, capsys
    ):
        """Mixed PASS and FAIL results must report exact counts and fail."""
        results = [
            self._result("PASS", "test_pass.py"),
            self._result("FAIL", "test_fail.py"),
        ]
        result = self._run_main(runner, monkeypatch, tmp_path, results)
        assert result == 1
        assert "COMPLETE: Total=2, Passed=1, Failed=1" in capsys.readouterr().out.splitlines()
