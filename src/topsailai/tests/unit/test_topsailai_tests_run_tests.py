'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-08-27
  Purpose: Unit tests for tests/run_tests.py child-process environment building
'''

import importlib.util
import os
import json
import subprocess
import threading
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import xml.etree.ElementTree as ET


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

    def test_run_test_forwards_env(self, runner, monkeypatch, tmp_path):
        """The pytest subprocess must receive the environment with the source root."""
        captured = {}

        class FakeCompleted:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured.update(kwargs)
            _write_junit(cmd)
            return FakeCompleted()

        monkeypatch.setattr(runner, "RUN_TEMP_ROOT", tmp_path / "runner")
        monkeypatch.setattr(runner.subprocess, "run", fake_run)
        status, details, _ = runner.run_test("test_topsailai_tests_run_tests.py", 5)

        assert status == "PASS"
        assert "All tests passed" in details
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
            _write_junit(cmd)
            return FakeCompleted()

        monkeypatch.setattr(runner, "RUN_TEMP_ROOT", tmp_path / "unit-runner")
        monkeypatch.setattr(runner.subprocess, "run", fake_run)
        status, _, _ = runner.run_test("nested/test_example.py", 5)

        assert status == "PASS"
        basetemp_arg = next(
            value for value in captured["cmd"] if value.startswith("--basetemp=")
        )
        basetemp = Path(basetemp_arg.split("=", 1)[1])
        assert basetemp.is_relative_to(runner.RUN_TEMP_ROOT)
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
            output_file=tmp_path / "test_results.txt",
            temp_root=tmp_path / "runner",
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


def _junit_document(body):
    """Build a pytest-shaped suite with truthful declared record/outcome counters."""
    suite = ET.fromstring(f"<testsuite>{body}</testsuite>")
    suite.set("tests", str(len(suite.findall("testcase"))))
    for tag, attribute in (("failure", "failures"), ("error", "errors"), ("skipped", "skipped")):
        suite.set(attribute, str(len(list(suite.iter(tag)))))
    return "<testsuites>" + ET.tostring(suite, encoding="unicode") + "</testsuites>"


def _write_junit(cmd, body='<testcase name="ok"/>'):
    """Create controlled case evidence for a mocked child invocation."""
    option = next((arg for arg in cmd if arg.startswith("--junitxml=")), None)
    if option:
        Path(option.split("=", 1)[1]).write_text(_junit_document(body))


class TestScopedEvidence:
    """Exercise task-scoped, complete and truthful runner evidence."""

    def test_options(self, runner, tmp_path):
        """Explicit paths override defaults without creating default directories."""
        defaults = runner.parse_args([])
        assert defaults.output_file == runner.OUTPUT_FILE
        assert defaults.temp_root == runner.RUN_TEMP_ROOT
        args = runner.parse_args(["--output-file", str(tmp_path / "report"), "--temp-root", str(tmp_path)])
        assert args.output_file == tmp_path / "report"
        assert args.temp_root == tmp_path

    @pytest.mark.parametrize("kind", ["pass", "fail", "timeout-bytes", "timeout-text", "error", "missing", "malformed"])
    def test_attempt_evidence(self, runner, monkeypatch, tmp_path, kind):
        """Every outcome retains full logs and missing case evidence cannot pass."""
        output = "start\n" + "x" * 9000 + "\nend"

        def fake_run(cmd, **kwargs):
            assert kwargs["stdin"] == subprocess.DEVNULL
            assert "-rA" in cmd
            if kind.startswith("timeout"):
                value = output.encode() if kind.endswith("bytes") else output
                raise subprocess.TimeoutExpired(cmd, 5, output=value, stderr=value)
            if kind == "error":
                raise OSError("controlled failure")
            if kind not in {"missing", "malformed"}:
                _write_junit(cmd)
            if kind == "malformed":
                Path(next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--junitxml="))).write_text("<broken")
            return SimpleNamespace(returncode=1 if kind == "fail" else 0, stdout=output, stderr=output)

        monkeypatch.setattr(runner.subprocess, "run", fake_run)
        status, details, _ = runner.run_test("nested/test_example.py", 5, temp_root=tmp_path)
        expected = {"pass": "PASS", "fail": "FAIL", "timeout-bytes": "TIMEOUT", "timeout-text": "TIMEOUT"}.get(kind, "ERROR")
        assert status == expected
        metadata = list(tmp_path.rglob("metadata.json"))
        assert len(metadata) == 1
        record = json.loads(metadata[0].read_text())
        assert record["status"] == expected
        assert str(metadata[0].parent) in details
        if kind != "error":
            assert (metadata[0].parent / "stdout.txt").read_text() == output
            assert (metadata[0].parent / "stderr.txt").read_text() == output
        assert record["cases"]["evidence"] == ("valid" if kind in {"pass", "fail"} else "missing" if kind != "malformed" else "malformed")

    def test_unique_paths_and_retained_attempts(self, runner, monkeypatch, tmp_path):
        """Colliding flattened names, retries and repeated calls never overwrite evidence."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            _write_junit(cmd)
            return SimpleNamespace(returncode=1 if len(calls) == 1 else 0, stdout="retained", stderr="")

        monkeypatch.setattr(runner.subprocess, "run", fake_run)
        runner.run_test("a/test_b.py", 5, retries=1, temp_root=tmp_path)
        runner.run_test("a-test_b.py", 5, temp_root=tmp_path)
        runner.run_test("a/test_b.py", 5, temp_root=tmp_path)
        paths = [arg for cmd in calls for arg in cmd if arg.startswith("--basetemp=")]
        assert len(paths) == len(set(paths)) == 4
        assert len(list(tmp_path.rglob("metadata.json"))) == 4

    @pytest.mark.parametrize("body,counts", [
        ('<testcase name="ok"/>', (1, 1, 0, 0, 0)),
        ('<testcase name="skip"><skipped type="pytest.xfail"/></testcase>', (1, 0, 0, 0, 1)),
        ('<testcase name="fail"><failure/></testcase>', (1, 0, 1, 0, 0)),
        ('<testcase name="collection"><error/></testcase>', (1, 0, 0, 1, 0)),
    ])
    def test_case_counts(self, runner, tmp_path, body, counts):
        """Count testcase records once, including collection errors and xfail skips."""
        path = tmp_path / "junit.xml"
        path.write_text(_junit_document(body))
        result = runner.read_case_counts(path)
        assert tuple(result[key] for key in ("records", "passed", "failures", "errors", "skipped")) == counts
        assert result["evidence"] == "valid"

    @pytest.mark.parametrize("sequential", [False, True])
    def test_path_threading(self, runner, monkeypatch, tmp_path, sequential):
        """Both executors forward explicit roots and retain input order."""
        roots = []

        def fake_test(name, timeout, retries, *, temp_root):
            roots.append(temp_root)
            return "PASS", "controlled", 0.1

        monkeypatch.setattr(runner, "run_test", fake_test)
        files = ["b.py", "a.py"]
        lock = threading.Lock()
        if sequential:
            results = runner.execute_sequentially(files, 5, 10, lock, temp_root=tmp_path)
        else:
            results = runner.execute_concurrently(files, 2, 5, 10, lock, temp_root=tmp_path)
        assert [item["file"] for item in results] == files
        assert roots == [tmp_path, tmp_path]

    @pytest.mark.parametrize("xml,evidence", [
        ("<testsuites/>", "incomplete"),
        ("<unexpected/>", "malformed"),
        ('<testsuite><testcase><failure/><error/><skipped/></testcase></testsuite>', "malformed"),
        (_junit_document('<testcase name="one"/><testcase name="two"/>'), "valid"),
    ])
    def test_xml_boundaries(self, runner, tmp_path, xml, evidence):
        """Empty and conflicting XML cannot masquerade as valid successful cases."""
        path = tmp_path / "junit.xml"
        path.write_text(xml)
        assert runner.read_case_counts(path)["evidence"] == evidence

    def test_skips_and_xpass_log_retention(self, runner, monkeypatch, tmp_path):
        """Preserve supplementary categories that XML alone cannot distinguish."""
        output = "XFAIL expected\nXPASS unexpected\n2 deselected\n"

        def fake_run(cmd, **kwargs):
            _write_junit(cmd, '<testcase name="xfail"><skipped type="pytest.xfail"/></testcase><testcase name="xpass"/>')
            return SimpleNamespace(returncode=0, stdout=output, stderr="")

        monkeypatch.setattr(runner.subprocess, "run", fake_run)
        assert runner.run_test("example.py", 5, temp_root=tmp_path)[0] == "PASS"
        metadata = next(tmp_path.rglob("metadata.json"))
        cases = json.loads(metadata.read_text())["cases"]
        assert cases["skipped"] == 1 and cases["passed"] == 1
        assert (metadata.parent / "stdout.txt").read_text() == output

    @pytest.mark.parametrize("sequential", [False, True])
    def test_main_case_evidence(self, runner, monkeypatch, tmp_path, sequential, capsys):
        """Main reports file and case dimensions separately using final-attempt evidence."""
        args = runner.parse_args(["example.py", "--retries", "0", "--workers", "1",
                                  "--output-file", str(tmp_path / "report"),
                                  "--temp-root", str(tmp_path / "runs")]
                                 + (["--sequential"] if sequential else []))
        monkeypatch.setattr(runner, "parse_args", lambda: args)
        monkeypatch.setattr(runner, "get_test_files", lambda selected=None: ["example.py"])

        def fake_run(cmd, **kwargs):
            _write_junit(cmd, '<testcase name="one"/><testcase name="two"/>')
            return SimpleNamespace(returncode=0, stdout="2 passed", stderr="")

        monkeypatch.setattr(runner.subprocess, "run", fake_run)
        assert runner.main() == 0
        summary = json.loads(next((tmp_path / "runs").rglob("cases.json")).read_text())
        assert summary["records"] == summary["passed"] == 2
        assert summary["incomplete_files"] == 0
        assert "COMPLETE: Total=1, Passed=1, Failed=0" in capsys.readouterr().out


class TestJUnitReconciliation:
    """Reject partial evidence through parsing, file execution and aggregation."""

    @pytest.mark.parametrize("xml", [
        '<testsuite tests="45" failures="0" errors="0" skipped="0"><testcase name="one"/></testsuite>',
        '<testsuite tests="3" failures="1" errors="1" skipped="0"><testcase name="bad"><failure/><error/></testcase><testcase name="ok"/><testcase name="other"/></testsuite>',
    ])
    def test_inconsistent_zero_exit_is_error(self, runner, monkeypatch, tmp_path, xml):
        """An exit-zero child cannot qualify incomplete or contradictory XML as PASS."""
        args = runner.parse_args(["example.py", "--workers", "1", "--retries", "0",
                                  "--temp-root", str(tmp_path / "runs"),
                                  "--output-file", str(tmp_path / "report")])
        monkeypatch.setattr(runner, "parse_args", lambda: args)
        monkeypatch.setattr(runner, "get_test_files", lambda selected=None: ["example.py"])

        def fake_run(cmd, **kwargs):
            """Supply inconsistent case evidence despite child success."""
            path = Path(next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--junitxml=")))
            path.write_text(xml)
            return SimpleNamespace(returncode=0, stdout="claimed success", stderr="")

        monkeypatch.setattr(runner.subprocess, "run", fake_run)
        assert runner.main() == 1
        metadata = json.loads(next((tmp_path / "runs").rglob("metadata.json")).read_text())
        assert metadata["returncode"] == 0
        assert metadata["status"] == "ERROR"
        assert metadata["cases"]["evidence"] != "valid"
        assert json.loads(next((tmp_path / "runs").rglob("cases.json")).read_text())["incomplete_files"] == 1


    @pytest.mark.parametrize("body,counts", [
        ('<testcase name="setup"><error message="failed on setup with X"/><error message="failed on teardown with Y"/></testcase>', (1, 0, 0, 2, 0)),
        ('<testcase name="call"><failure/></testcase><testcase name="call"><error message="failed on teardown with X"/></testcase>', (2, 0, 1, 1, 0)),
        ('<testcase name="collection"><error message="collection failure"/></testcase>', (1, 0, 0, 1, 0)),
        ('<testcase name="skip"><skipped/><error message="failed on teardown with X"/></testcase>', (1, 0, 0, 1, 1)),
    ])
    def test_valid_phase_records(self, runner, tmp_path, body, counts):
        """Count phase errors independently without inventing negative passing counts."""
        path = tmp_path / "junit.xml"
        path.write_text(_junit_document(body))
        result = runner.read_case_counts(path)
        assert result["evidence"] == "valid"
        assert tuple(result[key] for key in ("records", "passed", "failures", "errors", "skipped")) == counts

    def test_multiple_suites(self, runner, tmp_path):
        """Aggregate leaf suites once without counting the enclosing container."""
        path = tmp_path / "junit.xml"
        leaf = _junit_document('<testcase name="ok"/>').removeprefix("<testsuites>").removesuffix("</testsuites>")
        path.write_text('<testsuites tests="999">' + leaf * 2 + '</testsuites>')
        assert runner.read_case_counts(path) == dict(records=2, passed=2, failures=0, errors=0, skipped=0, evidence="valid")

    @pytest.mark.parametrize("xml", [
        '<testsuite><testcase/></testsuite>',
        '<testsuite tests="-1" failures="0" errors="0" skipped="0"><testcase/></testsuite>',
        '<testsuite tests="1" failures="1" errors="0" skipped="0"><testcase/></testsuite>',
        '<testsuite tests="1" failures="0" errors="0" skipped="0"><testsuite/></testsuite>',
        '<testsuites><testcase/></testsuites>',
        _junit_document('<testcase><error/><error/></testcase><testcase/>'),
        _junit_document('<testcase><skipped/><error/></testcase><testcase/>'),
        _junit_document('<testcase><failure/><failure/></testcase><testcase/>'),
    ])
    def test_unsupported_or_inconsistent_structure(self, runner, tmp_path, xml):
        """Reject missing counters, unsupported nesting and contradictory case outcomes."""
        path = tmp_path / "junit.xml"
        path.write_text(xml)
        assert runner.read_case_counts(path)["evidence"] == "malformed"
